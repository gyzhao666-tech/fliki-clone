"""Model Gateway

统一封装外部 AI 模型调用：LLM、TTS、ASR、文/图生视频、口型同步、图像生成等。

设计目标：
1. 业务代码不直接依赖具体 provider SDK；切换/灰度通过配置完成。
2. 每次调用强制走成本估算 + 调用记账（写 model_calls 表）。
3. 失败重试、超时、限流在 gateway 层统一处理。
4. provider 仅负责把统一的请求格式翻译到供应商 API。

公开接口：
- `gateway` 单例：业务代码通过 `gateway.run_llm(...)` / `gateway.generate_video(...)` 等入口调用
- `RenderRequest` / `RenderResult`：统一的请求/响应数据类
- `ModelAction`：枚举所有可调用的动作类型
"""
from .gateway import Gateway, get_gateway
from .types import (
    ModelAction,
    ProviderName,
    RenderRequest,
    RenderResult,
    CallStatus,
)

__all__ = [
    "Gateway",
    "get_gateway",
    "ModelAction",
    "ProviderName",
    "RenderRequest",
    "RenderResult",
    "CallStatus",
]
