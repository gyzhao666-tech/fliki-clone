"""Pipeline 编排引擎（轻量版，对应 ADR-001 方案 C）。

公开接口：
- `Step`：Agent 工位需实现的协议
- `StepResult`：Agent 执行返回
- `register_agent`：注册 agent_type → Step class
- `PipelineContext`：Agent 在执行时拿到的上下文
- `runner`：基于 Celery 的执行器（v1：同进程同步执行 + 调度器钩子）
- `templates`：内置模板，把已有功能拼成一条 Pipeline
"""
from .types import (
    PipelineContext,
    Step,
    StepResult,
    StepStatus,
    register_agent,
    get_agent_class,
    list_agent_types,
)

__all__ = [
    "PipelineContext",
    "Step",
    "StepResult",
    "StepStatus",
    "register_agent",
    "get_agent_class",
    "list_agent_types",
]
