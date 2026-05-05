"""内置 Agent 工位实现。

import 本包会触发各 agent 自注册到 pipeline 的 registry。
"""
from . import art, edit, research, review, script, video, voice  # noqa: F401

__all__ = ["art", "edit", "research", "review", "script", "video", "voice"]
