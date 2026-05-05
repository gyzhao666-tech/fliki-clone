"""调用成本估算与记账

estimate_cost：调用前给业务用于额度预扣 / 弹窗提示。
record_call：调用完成后强制写入 `model_calls` 表，作为账单与可观测性来源。

价格表只是“估算”用途，真实结算以供应商账单为准；新增 provider/model 时维护本表。
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from sqlalchemy import create_engine, text

from app.config import get_settings

from .types import CallStatus, ModelAction, ProviderName

logger = logging.getLogger(__name__)


# 价格表：USD per unit
# 单位口径：
#   llm        → 1k tokens（输入+输出粗算）
#   tts        → 1k characters
#   asr        → 1 minute
#   image      → 1 image
#   video      → 1 second of generated video
#   lipsync    → 1 minute
_PRICE_TABLE: dict[tuple[ProviderName, ModelAction], float] = {
    (ProviderName.SILICONFLOW, ModelAction.LLM): 0.0006,
    (ProviderName.SILICONFLOW, ModelAction.GENERATE_VIDEO): 0.10,
    (ProviderName.SILICONFLOW, ModelAction.GENERATE_IMAGE): 0.005,
    (ProviderName.SILICONFLOW, ModelAction.TTS): 0.05,
    # SenseVoiceSmall 在 SiliconFlow 现行报价 ~$0.0006/min，按往上估到 $0.001/min 兜底
    (ProviderName.SILICONFLOW, ModelAction.ASR): 0.001,
    (ProviderName.KLING, ModelAction.GENERATE_VIDEO): 0.20,
    (ProviderName.KLING, ModelAction.IMAGE_TO_VIDEO): 0.20,
    (ProviderName.ELEVENLABS, ModelAction.TTS): 0.30,
    (ProviderName.OPENAI, ModelAction.LLM): 0.005,
    # OpenAI Whisper-1 公开报价：$0.006/min
    (ProviderName.OPENAI, ModelAction.ASR): 0.006,
    # faster-whisper 本地推理零外部成本（占 CPU/RAM，调用方自行感知冷启动延迟）
    (ProviderName.FASTER_WHISPER_LOCAL, ModelAction.ASR): 0.0,
}


def estimate_cost(
    provider: ProviderName,
    action: ModelAction,
    params: dict[str, Any],
) -> float:
    """根据 provider/action 与请求参数粗估成本（USD）。"""

    unit_price = _PRICE_TABLE.get((provider, action), 0.0)
    if unit_price <= 0:
        return 0.0

    if action == ModelAction.LLM:
        approx_tokens = int(params.get("approx_tokens") or 1000)
        return unit_price * (approx_tokens / 1000.0)
    if action == ModelAction.TTS:
        text_value = str(params.get("text") or "")
        chars = len(text_value)
        return unit_price * (chars / 1000.0)
    if action == ModelAction.ASR or action == ModelAction.LIPSYNC:
        minutes = float(params.get("duration_minutes") or 1.0)
        return unit_price * minutes
    if action == ModelAction.GENERATE_IMAGE:
        n = int(params.get("n") or 1)
        return unit_price * n
    if action in (ModelAction.GENERATE_VIDEO, ModelAction.IMAGE_TO_VIDEO):
        seconds = float(params.get("duration") or params.get("duration_s") or 5.0)
        return unit_price * seconds

    return 0.0


def _resolve_tenant_for_record(
    explicit_tenant_id: Optional[str],
    user_id: Optional[str],
) -> Optional[str]:
    """Track-18：决定写入 model_calls.tenant_id 的值。

    优先级：explicit_tenant_id > 'u:{user_id}' > None（让 DB 端 NULL 兜底）。
    与 `app.services.pipeline.tenant.resolve_tenant_id` 的兜底约定保持一致：
    `ws:{workspace_id}` 由调用方自己塞 explicit_tenant_id；user 级走 `u:{user_id}`；
    完全匿名路径（user_id 也缺失）保持 NULL，让 backfill 后的 alembic 维持 idempotent。
    """
    if explicit_tenant_id:
        return explicit_tenant_id
    if user_id:
        return f"u:{user_id}"
    return None


def record_call(
    *,
    user_id: Optional[str],
    file_id: Optional[str],
    pipeline_step_id: Optional[str],
    provider: ProviderName,
    model: Optional[str],
    action: ModelAction,
    cost_usd: float,
    duration_ms: int,
    status: CallStatus,
    error: Optional[str] = None,
    request_summary: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> str:
    """同步写入一条 model_calls。

    采用同步引擎写入，保证从 Celery worker / BackgroundTask / async router 都能调用。
    返回 model_call id；写库失败时仍返回生成的 id，但会记 warning（不让记账失败影响业务）。

    Track-18：参数 ``tenant_id`` 由 gateway 显式传入（来自 RenderRequest.tenant_id）；
    缺失时按 ``user_id`` 推 ``u:{user_id}``，与 pipeline.tenant.resolve_tenant_id 兜底一致。
    """

    settings = get_settings()
    record_id = str(uuid.uuid4())
    effective_tenant_id = _resolve_tenant_for_record(tenant_id, user_id)
    try:
        engine = create_engine(settings.database_url_sync)
        with engine.connect() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO model_calls
                        (id, user_id, tenant_id, file_id, pipeline_step_id,
                         provider, model, action,
                         cost_usd, duration_ms, status, error, request_summary, created_at)
                    VALUES
                        (:id, :user_id, :tenant_id, :file_id, :pipeline_step_id,
                         :provider, :model, :action,
                         :cost_usd, :duration_ms, :status, :error, :request_summary, NOW())
                    """
                ),
                {
                    "id": record_id,
                    "user_id": user_id,
                    "tenant_id": effective_tenant_id,
                    "file_id": file_id,
                    "pipeline_step_id": pipeline_step_id,
                    "provider": provider.value,
                    "model": model,
                    "action": action.value,
                    "cost_usd": float(cost_usd or 0.0),
                    "duration_ms": int(duration_ms or 0),
                    "status": status.value,
                    "error": (error or "")[:1024] if error else None,
                    "request_summary": (request_summary or "")[:2048] if request_summary else None,
                },
            )
            conn.commit()
    except Exception as exc:  # pragma: no cover - 记账失败不能影响业务
        logger.warning("model_calls 记账失败 id=%s: %s", record_id, exc)
    return record_id
