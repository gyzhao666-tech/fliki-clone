"""Model Gateway 公共类型

统一描述外部模型调用的输入与输出，避免业务代码触碰具体供应商 SDK。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ModelAction(str, Enum):
    """gateway 支持的动作类型。

    新增 action 时同步更新 providers 的 capability 矩阵。
    """

    LLM = "llm"
    TTS = "tts"
    ASR = "asr"
    GENERATE_IMAGE = "generate_image"
    GENERATE_VIDEO = "generate_video"
    IMAGE_TO_VIDEO = "image_to_video"
    LIPSYNC = "lipsync"
    TRANSLATE = "translate"


class ProviderName(str, Enum):
    """已知 provider 标识。

    与 settings 中各供应商的 API key 对应；新增供应商时同步扩展。
    """

    SILICONFLOW = "siliconflow"
    KLING = "kling"
    ELEVENLABS = "elevenlabs"
    OPENAI = "openai"
    # 本地 faster-whisper（懒导入；用户无 OPENAI_API_KEY 时的 word-level fallback）
    FASTER_WHISPER_LOCAL = "faster_whisper_local"
    DEMO = "demo"  # 无 key 时的本地占位，便于离线开发与测试


class CallStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    DEGRADED = "degraded"
    # 配额 v2：tenant × provider 并发桶满，未发起调用就被拒
    RATE_LIMITED = "rate_limited"


@dataclass
class RenderRequest:
    """统一的模型调用请求。

    - 业务侧用 `params` 传供应商无关的参数（prompt, duration, num_frames...）
    - `provider_hint` / `model_hint` 仅作偏好；实际 routing 由 gateway 决定
    - `idempotency_key` 用于流水线节点重跑时的去重
    """

    action: ModelAction
    params: dict[str, Any] = field(default_factory=dict)
    user_id: Optional[str] = None
    file_id: Optional[str] = None
    pipeline_step_id: Optional[str] = None
    provider_hint: Optional[ProviderName] = None
    model_hint: Optional[str] = None
    idempotency_key: Optional[str] = None
    # 单次调用的硬超时（秒）；None 走 provider 默认。
    timeout_s: Optional[float] = None
    # 配额 v2：tenant 命名空间（`ws:{wid}` / `u:{uid}` / `anon:default`）
    # gateway 在 run() 入口按此 tenant_id + provider_name acquire/release 槽位。
    # 不传时（老调用方）跳过并发限制，保持向后兼容。
    tenant_id: Optional[str] = None
    # plan 也用 None 表示「调用方不知道，gateway 自己 resolve」；显式传 "free"/"standard"/...
    # 时跳过 user 表查询，按显式 plan 派生 bucket max。
    tenant_plan: Optional[str] = None


@dataclass
class RenderResult:
    """统一的模型调用响应。

    - `output` 是 provider-agnostic 的负载（文本、URL、片段列表等）
    - `model_call_id` 是写入 `model_calls` 表后的主键，业务可据此回溯
    """

    status: CallStatus
    output: Any = None
    provider: Optional[ProviderName] = None
    model: Optional[str] = None
    cost_usd: float = 0.0
    duration_ms: int = 0
    error: Optional[str] = None
    raw: Any = None  # 调试用，生产可截断
    model_call_id: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status in (CallStatus.SUCCEEDED, CallStatus.DEGRADED)
