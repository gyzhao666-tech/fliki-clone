"""内置 Pipeline 模板。

模板返回一个 graph：节点 + 依赖；交给 runner.start_run 落库。

当前模板：
- `script_only`：研究 → 脚本（最快路径，便于调试 LLM 链路）
- `video_demo` ：研究 → 脚本 → 视频 → 拼接 → 质检（端到端 demo；不接入风格/配音）
- `video_full` ：研究 → 脚本 → 美术 → 视频 → 配音 → 拼接 → 质检
                （ArtAgent 注入 style_board / character_cards / 增强 prompt；
                  VoiceAgent 输出 narration TTS + 字幕；EditAgent 把视频 + 配音合成）

设计原则：
- 任何带"高花费 / 不可逆"语义的节点都强制 awaiting_review（脚本、视频生成）
- ArtAgent / VoiceAgent v1 不强制审批：人在 script 已审过故事，再多审太重；
  仍可单步重跑覆盖
"""
from __future__ import annotations

from typing import Any, Callable


def script_only_graph() -> list[dict[str, Any]]:
    return [
        {"name": "research", "agent_type": "research", "depends_on": []},
        {
            "name": "script",
            "agent_type": "script",
            "depends_on": ["research"],
            "requires_review": True,
        },
    ]


def video_demo_graph() -> list[dict[str, Any]]:
    return [
        {"name": "research", "agent_type": "research", "depends_on": []},
        {
            "name": "script",
            "agent_type": "script",
            "depends_on": ["research"],
            "requires_review": True,
        },
        {
            "name": "video",
            "agent_type": "video",
            "depends_on": ["script"],
            "requires_review": True,
        },
        {
            "name": "edit",
            "agent_type": "edit",
            "depends_on": ["video"],
        },
        {
            "name": "review",
            "agent_type": "review",
            "depends_on": ["video", "edit", "script"],
        },
    ]


def video_full_graph() -> list[dict[str, Any]]:
    return [
        {"name": "research", "agent_type": "research", "depends_on": []},
        {
            "name": "script",
            "agent_type": "script",
            "depends_on": ["research"],
            "requires_review": True,
        },
        {
            "name": "art",
            "agent_type": "art",
            "depends_on": ["script"],
        },
        {
            "name": "voice",
            "agent_type": "voice",
            "depends_on": ["script"],
        },
        {
            "name": "video",
            "agent_type": "video",
            "depends_on": ["script", "art"],
            "requires_review": True,
        },
        {
            "name": "edit",
            "agent_type": "edit",
            "depends_on": ["video", "voice"],
        },
        {
            "name": "review",
            "agent_type": "review",
            "depends_on": ["video", "edit", "script", "voice"],
        },
    ]


TEMPLATES: dict[str, Callable[[], list[dict[str, Any]]]] = {
    "script_only": script_only_graph,
    "video_demo": video_demo_graph,
    "video_full": video_full_graph,
}


def get_template(name: str) -> list[dict[str, Any]] | None:
    fn = TEMPLATES.get(name)
    return fn() if fn else None


def list_templates() -> list[str]:
    return sorted(TEMPLATES.keys())
