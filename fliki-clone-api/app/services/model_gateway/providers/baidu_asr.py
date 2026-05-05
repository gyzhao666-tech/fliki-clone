"""百度智能云短语音识别 ASR provider。

设计意图
--------
当用户没有 ``OPENAI_API_KEY`` / 没装 ``faster-whisper`` 但想要稳定云端 ASR 时，
本 provider 提供国内合规、低成本的兜底通路。配套 Track-26 卡拉 OK 字幕的
**降级语义**：百度短语音 REST API 只返完整 text 不返 word/segment-level 时间戳，
voice.py v4 health check 会把 ``words=[]`` 视为不可用，自动降到 v3 行级字幕（与
SiliconFlow SenseVoice 同一 tier）。如要保留卡拉 OK，请并存装 ``faster-whisper``，
gateway 路由 ``[OPENAI, FASTER_WHISPER_LOCAL, BAIDU, SILICONFLOW]`` 会优先用本地。

激活条件
~~~~~~~~
- ``.env`` 配 ``BAIDU_ASR_API_KEY`` + ``BAIDU_ASR_SECRET_KEY``（在百度智能云
  「应用配置」页拿）。
- 无任何 SDK 依赖（只用 stdlib + requests），不引第三方包。

接口约束
~~~~~~~~
- 单次音频 ≤ 60s 且 ≤ 10MB（百度官方限制）；超过应走异步长语音 LASR（留作 follow-up）
- ``rate`` 必须 8000 / 16000；mp3 / m4a 等压缩格式百度按 header 内的真实采样率
  解码，外面声明的 ``rate`` 字段不影响识别效果，只用于元数据
- ``dev_pid`` 默认 1537（普通话近场）；常用：1737 英语 / 1637 粤语 / 1837 四川话

``RenderRequest.params``（与 OpenAIWhisperProvider / SiliconFlowASRProvider 一致）
- ``audio_bytes``  : 必填，bytes / bytearray
- ``audio_format`` : 可选，默认 "mp3"
- ``language``     : 可选；命中 "en" 时自动覆盖 dev_pid=1737，否则按 settings 的 dev_pid
- ``dev_pid``      : 可选，直接覆盖 settings 默认
- 其余字段（``model`` / ``response_format``）被忽略，百度 API 没有对应概念

返回 ``RenderResult.output``（**与其它 ASR provider 严格一致**）::

    {
        "text":       str,                    # 完整识别文本
        "duration_s": float | None,           # 百度不返；caller 用 ffprobe 兜底
        "segments":   [],                     # 百度短语音不返，固定空
        "words":      [],                     # 百度短语音不返，voice.py 自动退 v3
        "language":   str | None,             # 'zh-CN' / 'en' 等约定值
    }

token 管理
~~~~~~~~~~
- ``access_token`` 由 OAuth2 client_credentials 获取，有效期 30 天
- 进程内 ``_token_cache`` 单例 + 锁缓存；过期前 60s 主动刷新
- ``err_no=3302``（鉴权失败）触发一次 invalidate + retry，避免假死

Token 端点 / ASR 端点
~~~~~~~~~~~~~~~~~~~~~
- token : ``https://aip.baidubce.com/oauth/2.0/token``
  param  ``grant_type=client_credentials``, ``client_id``, ``client_secret``
- asr   : ``https://vop.baidu.com/server_api``（短语音标准版）
  payload JSON: format / rate / channel / cuid / token / dev_pid / speech (base64) / len

错误码节选（写到 ``RenderResult.error`` 里方便排错）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- 3300 输入参数不正确
- 3301 音频质量过差
- 3302 鉴权失败  → 触发 token invalidate + retry 一次
- 3304 用户请求超限
- 3308 音频时长超长（>60s）
- 3309 音频格式不支持
- 3310 音频太大（>10MB）
"""
from __future__ import annotations

import base64
import logging
import threading
import time
from typing import Any, Optional

import requests

from app.config import get_settings

from ..types import CallStatus, ModelAction, ProviderName, RenderRequest, RenderResult
from .base import BaseProvider

logger = logging.getLogger(__name__)


# token 缓存：(api_key, secret_key) → (access_token, expires_at_unix)
# 进程内全局；多 worker 时各自独立缓存（百度允许多端并发拿同一 client_id 的 token）
_TOKEN_CACHE_LOCK = threading.Lock()
_TOKEN_CACHE: dict[tuple[str, str], tuple[str, float]] = {}

# 提前刷新 token 的安全窗口（百度 token 30 天有效；提前 60s 重拿避开 boundary）
_TOKEN_REFRESH_WINDOW_SEC = 60.0

_TOKEN_ENDPOINT = "https://aip.baidubce.com/oauth/2.0/token"
_ASR_ENDPOINT = "https://vop.baidu.com/server_api"

# 百度 dev_pid 矩阵
_DEV_PID_MANDARIN = 1537
_DEV_PID_ENGLISH = 1737


class BaiduASRProvider(BaseProvider):
    """百度智能云 ASR provider（短语音 REST 标准版）。"""

    name = ProviderName.BAIDU

    def supports(self, action: ModelAction) -> bool:
        return action == ModelAction.ASR

    def is_available(self) -> bool:
        s = get_settings()
        return bool(s.baidu_asr_api_key and s.baidu_asr_secret_key)

    def call(self, request: RenderRequest) -> RenderResult:
        settings = get_settings()
        api_key = settings.baidu_asr_api_key
        secret_key = settings.baidu_asr_secret_key
        if not (api_key and secret_key):
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                error="missing baidu_asr_api_key / baidu_asr_secret_key",
            )

        params: dict[str, Any] = dict(request.params or {})
        audio = params.get("audio_bytes")
        if not isinstance(audio, (bytes, bytearray)) or not audio:
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                error="missing audio_bytes",
            )
        audio_bytes = bytes(audio)
        audio_len = len(audio_bytes)
        if audio_len > 10 * 1024 * 1024:
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                error=f"audio too large: {audio_len} bytes (baidu 短语音 ≤ 10MB)",
            )

        audio_format = (params.get("audio_format") or "mp3").lower()
        language = (params.get("language") or "").lower() or None
        # dev_pid 优先级：params 显式 > 语言映射 > settings 默认
        dev_pid = params.get("dev_pid")
        if dev_pid is None:
            if language and language.startswith("en"):
                dev_pid = _DEV_PID_ENGLISH
            else:
                dev_pid = settings.baidu_asr_dev_pid or _DEV_PID_MANDARIN
        try:
            dev_pid_int = int(dev_pid)
        except (TypeError, ValueError):
            dev_pid_int = _DEV_PID_MANDARIN

        timeout_s = request.timeout_s or 30.0
        started = time.time()

        # 1. 拿 token（缓存 / 过期判定）
        try:
            token = _get_access_token(api_key, secret_key, timeout_s=timeout_s)
        except _BaiduTokenError as exc:
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                duration_ms=int((time.time() - started) * 1000),
                error=f"token fetch failed: {exc}",
            )

        # 2. 调短语音识别；err_no=3302 时 invalidate + retry 一次
        for attempt in (1, 2):
            payload = _build_asr_payload(
                audio_bytes=audio_bytes,
                audio_format=audio_format,
                token=token,
                dev_pid=dev_pid_int,
                cuid=settings.baidu_asr_cuid or "fliki-clone-server",
            )
            try:
                resp = requests.post(
                    _ASR_ENDPOINT,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=timeout_s,
                )
            except requests.Timeout:
                return RenderResult(
                    status=CallStatus.TIMEOUT,
                    provider=self.name,
                    duration_ms=int((time.time() - started) * 1000),
                    error="upstream timeout",
                )
            except Exception as exc:
                return RenderResult(
                    status=CallStatus.FAILED,
                    provider=self.name,
                    duration_ms=int((time.time() - started) * 1000),
                    error=str(exc),
                )

            if resp.status_code != 200:
                return RenderResult(
                    status=CallStatus.FAILED,
                    provider=self.name,
                    duration_ms=int((time.time() - started) * 1000),
                    error=f"http {resp.status_code}: {resp.text[:200]}",
                )

            try:
                body = resp.json()
            except Exception:
                return RenderResult(
                    status=CallStatus.FAILED,
                    provider=self.name,
                    duration_ms=int((time.time() - started) * 1000),
                    error=f"non-json response: {resp.text[:200]}",
                )

            err_no = int(body.get("err_no") or 0)
            if err_no == 0:
                # 识别成功
                results = body.get("result") or []
                text = ""
                if isinstance(results, list) and results:
                    text = str(results[0] or "").strip()
                lang = "en" if dev_pid_int == _DEV_PID_ENGLISH else "zh-CN"
                return RenderResult(
                    status=CallStatus.SUCCEEDED,
                    output={
                        "text": text,
                        "duration_s": None,  # 百度不返；caller ffprobe 兜底
                        "segments": [],
                        "words": [],
                        "language": lang,
                    },
                    provider=self.name,
                    model=f"baidu-dev_pid-{dev_pid_int}",
                    duration_ms=int((time.time() - started) * 1000),
                    raw={"sn": body.get("sn"), "corpus_no": body.get("corpus_no")},
                )

            # 鉴权失败：清缓存 + 重拿 token，重试一次
            if err_no == 3302 and attempt == 1:
                logger.warning(
                    "baidu ASR 鉴权失败 (err_no=3302)，invalidate token 重试",
                )
                _invalidate_token(api_key, secret_key)
                try:
                    token = _get_access_token(
                        api_key, secret_key, timeout_s=timeout_s
                    )
                except _BaiduTokenError as exc:
                    return RenderResult(
                        status=CallStatus.FAILED,
                        provider=self.name,
                        duration_ms=int((time.time() - started) * 1000),
                        error=f"token re-fetch failed: {exc}",
                    )
                continue

            # 其它错误：直接返
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                duration_ms=int((time.time() - started) * 1000),
                error=f"baidu err_no={err_no}: {body.get('err_msg') or ''}",
                raw=body,
            )

        # 不应该到这里（loop 内必返）；兜底返失败
        return RenderResult(
            status=CallStatus.FAILED,
            provider=self.name,
            duration_ms=int((time.time() - started) * 1000),
            error="unreachable",
        )


# ── 内部 helpers ─────────────────────────────────────────────────────────────


class _BaiduTokenError(Exception):
    """token 端点错误专用异常，便于 caller 翻译成 RenderResult.error。"""


def _build_asr_payload(
    *,
    audio_bytes: bytes,
    audio_format: str,
    token: str,
    dev_pid: int,
    cuid: str,
    rate: int = 16000,
    channel: int = 1,
) -> dict[str, Any]:
    speech_b64 = base64.b64encode(audio_bytes).decode("ascii")
    return {
        "format": audio_format,
        "rate": rate,
        "channel": channel,
        "cuid": cuid,
        "token": token,
        "dev_pid": dev_pid,
        "speech": speech_b64,
        "len": len(audio_bytes),
    }


def _get_access_token(
    api_key: str,
    secret_key: str,
    *,
    timeout_s: float = 10.0,
) -> str:
    """拿 baidu access_token；缓存命中且未过期直接返。"""
    cache_key = (api_key, secret_key)
    now = time.time()
    with _TOKEN_CACHE_LOCK:
        cached = _TOKEN_CACHE.get(cache_key)
        if cached and cached[1] - _TOKEN_REFRESH_WINDOW_SEC > now:
            return cached[0]

    # 真发请求（不持锁，避免阻塞其它调用）
    try:
        resp = requests.post(
            _TOKEN_ENDPOINT,
            params={
                "grant_type": "client_credentials",
                "client_id": api_key,
                "client_secret": secret_key,
            },
            timeout=timeout_s,
        )
    except requests.RequestException as exc:
        raise _BaiduTokenError(str(exc)) from exc

    if resp.status_code != 200:
        raise _BaiduTokenError(
            f"http {resp.status_code}: {resp.text[:200]}"
        )

    try:
        body = resp.json()
    except Exception as exc:
        raise _BaiduTokenError(f"non-json: {resp.text[:200]}") from exc

    token = body.get("access_token")
    expires_in = float(body.get("expires_in") or 0)
    if not token or expires_in <= 0:
        raise _BaiduTokenError(
            f"invalid response: {body.get('error_description') or body}"
        )

    expires_at = time.time() + expires_in
    with _TOKEN_CACHE_LOCK:
        _TOKEN_CACHE[cache_key] = (str(token), expires_at)
    return str(token)


def _invalidate_token(api_key: str, secret_key: str) -> None:
    """从缓存里强制移除一组 token（用于鉴权失败后强制下次重拿）。"""
    with _TOKEN_CACHE_LOCK:
        _TOKEN_CACHE.pop((api_key, secret_key), None)


def _clear_token_cache() -> None:
    """单元测试 / dev 工具 —— 强制清空所有 token。"""
    with _TOKEN_CACHE_LOCK:
        _TOKEN_CACHE.clear()


__all__ = ["BaiduASRProvider"]
