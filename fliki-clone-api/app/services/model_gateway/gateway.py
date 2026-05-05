"""Gateway 入口。

业务代码统一通过 `get_gateway().run(request)` 调用外部模型；gateway 负责：
1. 路由：按 action / provider_hint / 可用性选择 provider
2. 调用：把 provider 抛出的异常 / 失败统一转为 RenderResult
3. 记账：成功 / 失败都写一条 model_calls
4. 降级：未来支持 fallback chain（Phase 2）
"""
from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Optional

from .cost import estimate_cost, record_call
from .providers import (
    BaiduASRProvider,
    BaseProvider,
    FasterWhisperLocalProvider,
    KlingProvider,
    OpenAICompatLLMProvider,
    OpenAIWhisperProvider,
    SiliconFlowASRProvider,
    SiliconFlowImageProvider,
    SiliconFlowTTSProvider,
    SiliconFlowVideoProvider,
)
from .types import CallStatus, ModelAction, ProviderName, RenderRequest, RenderResult

logger = logging.getLogger(__name__)


class Gateway:
    """统一外部模型调用入口。线程安全；当前进程内单例。

    同一 `ProviderName` 下可注册多个 provider 实现（例如 SiliconFlow 同时有
    LLM provider 与视频 provider）；`select_provider` 按 `supports(action)` 选择。
    """

    def __init__(self) -> None:
        self._providers: dict[ProviderName, list[BaseProvider]] = {}
        # 默认按 action 的偏好顺序；后续可由 settings/数据库覆盖。
        self._default_routing: dict[ModelAction, list[ProviderName]] = {
            ModelAction.LLM: [ProviderName.SILICONFLOW, ProviderName.OPENAI],
            ModelAction.GENERATE_VIDEO: [ProviderName.KLING, ProviderName.SILICONFLOW],
            ModelAction.IMAGE_TO_VIDEO: [ProviderName.KLING],
            ModelAction.GENERATE_IMAGE: [ProviderName.SILICONFLOW],
            ModelAction.TTS: [ProviderName.ELEVENLABS, ProviderName.SILICONFLOW],
            # ASR 四段降级：
            #   1. OpenAI Whisper-1     云端 word-level，最稳；要 OPENAI_API_KEY
            #   2. faster-whisper 本地  离线 word-level fallback；要装 faster-whisper 包
            #   3. 百度智能云短语音      国内合规云端文本（不返 word，voice 退 v3 行级）
            #   4. SiliconFlow SenseVoice 兜底（不返 word；voice 退 v3 行级）
            ModelAction.ASR: [
                ProviderName.OPENAI,
                ProviderName.FASTER_WHISPER_LOCAL,
                ProviderName.BAIDU,
                ProviderName.SILICONFLOW,
            ],
        }

    def register(self, provider: BaseProvider) -> None:
        self._providers.setdefault(provider.name, []).append(provider)

    def has_provider(self, name: ProviderName) -> bool:
        return bool(self._providers.get(name))

    def select_provider(
        self,
        action: ModelAction,
        hint: Optional[ProviderName] = None,
    ) -> Optional[BaseProvider]:
        """按 hint → default routing 顺序选择第一个 supports + available 的 provider。"""

        candidates: list[ProviderName] = []
        if hint:
            candidates.append(hint)
        for name in self._default_routing.get(action, []):
            if name not in candidates:
                candidates.append(name)

        for name in candidates:
            for provider in self._providers.get(name, []):
                if not provider.supports(action):
                    continue
                if not provider.is_available():
                    continue
                return provider
        return None

    def estimate(self, request: RenderRequest) -> float:
        """业务在调用前用于额度预扣 / 提示。"""

        provider = self.select_provider(request.action, request.provider_hint)
        if not provider:
            return 0.0
        return estimate_cost(provider.name, request.action, request.params or {})

    def run(self, request: RenderRequest) -> RenderResult:
        """执行调用 + 记账。永远不抛异常。

        配额 v2：若 request 带 `tenant_id`，调用前 acquire 对应 (tenant, provider) 并发槽，
        finally release；拿不到槽返回 `CallStatus.RATE_LIMITED`，不真发请求、不计费。
        """

        provider = self.select_provider(request.action, request.provider_hint)
        if not provider:
            result = RenderResult(
                status=CallStatus.FAILED,
                error=f"no provider available for {request.action.value}",
            )
            self._record(request, result)
            return result

        # ── v2：尝试 acquire 并发槽
        # tenant_id 优先用 request 显式传的；缺失则从 user_id 推断（兼容历史 agent 调用方）
        # plan 同理：显式 > user 表 > 'free' 兜底（保证 bucket 按真实 plan 派生 max）
        effective_tenant_id = request.tenant_id
        effective_plan = request.tenant_plan  # 可能 None
        if (not effective_tenant_id or not effective_plan) and request.user_id:
            try:
                from app.services.pipeline.tenant import resolve_tenant_context

                tctx = resolve_tenant_context(request.user_id)
                if not effective_tenant_id:
                    effective_tenant_id = tctx.tenant_id
                if not effective_plan:
                    effective_plan = tctx.plan
            except Exception:  # pragma: no cover - 解析失败就跳过限制
                logger.exception("resolve_tenant_context fallback failed")
        if not effective_plan:
            effective_plan = "free"

        bucket_acquired = False
        bucket_tenant_id: Optional[str] = None
        if effective_tenant_id:
            from app.services.pipeline import provider_buckets

            try:
                provider_buckets.acquire(
                    effective_tenant_id,
                    provider.name.value,
                    plan=effective_plan,
                    user_id=request.user_id,
                )
                bucket_acquired = True
                bucket_tenant_id = effective_tenant_id
            except provider_buckets.BucketFull as bf:
                snap = bf.snapshot
                detail = (
                    f"provider {provider.name.value} bucket full"
                    + (
                        f" ({snap.current_in_flight}/{snap.max_concurrent})"
                        if snap
                        else ""
                    )
                )
                result = RenderResult(
                    status=CallStatus.RATE_LIMITED,
                    provider=provider.name,
                    error=detail,
                )
                self._record(request, result)
                return result

        started = time.time()
        try:
            result = provider.call(request)
        except Exception as exc:
            logger.exception("provider %s call raised", provider.name.value)
            result = RenderResult(
                status=CallStatus.FAILED,
                provider=provider.name,
                duration_ms=int((time.time() - started) * 1000),
                error=str(exc),
            )
        finally:
            if bucket_acquired and bucket_tenant_id:
                # release 必须执行；release 内部静默处理 0 兜底，不抛
                from app.services.pipeline import provider_buckets

                provider_buckets.release(bucket_tenant_id, provider.name.value)

        if not result.duration_ms:
            result.duration_ms = int((time.time() - started) * 1000)
        if not result.provider:
            result.provider = provider.name

        if result.cost_usd <= 0 and result.status != CallStatus.RATE_LIMITED:
            result.cost_usd = estimate_cost(
                result.provider, request.action, request.params or {}
            )

        self._record(request, result)
        return result

    def _record(self, request: RenderRequest, result: RenderResult) -> None:
        try:
            request_summary = _summarise_request(request)
            record_id = record_call(
                user_id=request.user_id,
                # Track-18：把 request 显式塞的 tenant_id 透传到记账层；
                # cost.record_call 内部会兜底成 'u:{user_id}'，记账与配额 v2 同维度
                tenant_id=request.tenant_id,
                file_id=request.file_id,
                pipeline_step_id=request.pipeline_step_id,
                provider=result.provider or ProviderName.DEMO,
                model=result.model,
                action=request.action,
                cost_usd=result.cost_usd,
                duration_ms=result.duration_ms,
                status=result.status,
                error=result.error,
                request_summary=request_summary,
            )
            result.model_call_id = record_id
        except Exception:  # pragma: no cover
            logger.exception("record_call failed; ignored")


_lock = Lock()
_gateway: Optional[Gateway] = None


def get_gateway() -> Gateway:
    """进程内单例。首次调用时注册默认 providers。"""

    global _gateway
    if _gateway is not None:
        return _gateway
    with _lock:
        if _gateway is None:
            gw = Gateway()
            gw.register(OpenAICompatLLMProvider())
            gw.register(KlingProvider())
            gw.register(SiliconFlowVideoProvider())
            gw.register(SiliconFlowImageProvider())
            gw.register(SiliconFlowTTSProvider())
            gw.register(SiliconFlowASRProvider())
            gw.register(OpenAIWhisperProvider())
            gw.register(FasterWhisperLocalProvider())
            gw.register(BaiduASRProvider())
            _gateway = gw
    return _gateway


def _summarise_request(request: RenderRequest) -> str:
    """把请求参数压成一行可读摘要，便于日后审计。"""

    params = request.params or {}
    pieces: list[str] = [f"action={request.action.value}"]
    if request.provider_hint:
        pieces.append(f"hint={request.provider_hint.value}")
    if request.model_hint:
        pieces.append(f"model={request.model_hint}")
    if "messages" in params:
        try:
            user_msg = next(
                (m for m in params["messages"] if m.get("role") == "user"),
                None,
            )
            if user_msg:
                pieces.append(f"user={str(user_msg.get('content', ''))[:80]}")
        except Exception:
            pass
    if "prompt" in params:
        pieces.append(f"prompt={str(params['prompt'])[:80]}")
    if "duration" in params:
        pieces.append(f"duration={params['duration']}")
    return " | ".join(pieces)
