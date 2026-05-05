"""Pipeline 节点协议 + 上下文 + 注册表。

设计原则：
- Step 是无状态类，每次执行产生一个新实例（避免共享态导致并发 bug）
- PipelineContext 把 db / gateway / 路径等基础设施一次性注入，Step 不再各自造轮子
- 注册表全局唯一；Agent 文件被 import 时通过 `register_agent` 自注册
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Type


class StepStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    AWAITING_REVIEW = "awaiting_review"
    SKIPPED = "skipped"


@dataclass
class StepResult:
    status: StepStatus
    outputs: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    cost_usd: float = 0.0


@dataclass
class PipelineContext:
    """Agent 执行时拿到的上下文。

    `run_id` / `step_id` 已写入数据库；Agent 内部如果调用 gateway，
    应把 `step_id` 透传到 RenderRequest.pipeline_step_id 以便记账串起来。

    配额 v2：`tenant_id` / `tenant_plan` 由 runner 写入，agent 调 gateway 时无需主动透传——
    gateway.run() 入口在 `request.tenant_id` 缺失时会自动从 user_id resolve 兜底；显式传更准。
    """

    run_id: str
    step_id: str
    user_id: Optional[str]
    file_id: Optional[str]
    inputs: dict[str, Any]
    # 上游已完成 step 的 outputs，按 step.name 索引
    upstream_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    # 配额 v2 上下文：tenant 命名空间 + 用户 plan（用于 provider 桶 max 派生）
    tenant_id: Optional[str] = None
    tenant_plan: str = "free"


class Step:
    """Agent 工位需要实现的最小协议。"""

    agent_type: str = "base"

    def estimate_cost_usd(self, ctx: PipelineContext) -> float:
        """提交前用于额度预扣 / 弹窗提示；返回 0 表示忽略。"""
        return 0.0

    def run(self, ctx: PipelineContext) -> StepResult:  # pragma: no cover - abstract
        raise NotImplementedError


# ── 注册表 ────────────────────────────────────────────────────────────────────
_REGISTRY: dict[str, Type[Step]] = {}


def register_agent(agent_type: str) -> Callable[[Type[Step]], Type[Step]]:
    def deco(cls: Type[Step]) -> Type[Step]:
        cls.agent_type = agent_type
        _REGISTRY[agent_type] = cls
        return cls

    return deco


def get_agent_class(agent_type: str) -> Optional[Type[Step]]:
    return _REGISTRY.get(agent_type)


def list_agent_types() -> list[str]:
    return sorted(_REGISTRY.keys())
