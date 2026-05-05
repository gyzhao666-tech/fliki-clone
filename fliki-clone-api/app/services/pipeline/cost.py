"""Pipeline 启动前的总成本预估。

每个 Agent 已经在 `Step.estimate_cost_usd(ctx)` 里给出了「单步预估」；
本模块负责按 graph 顺序模拟一遍上下文，把每步预估加起来，给出整条 run 的预估值。

设计要点：
- 不真正执行任何 step；只构造一个最小的 PipelineContext 让 estimator 看到 inputs.brief 与
  shots 数量等关键参数（部分 estimator 会依赖 shots 数量算关键帧 / 视频成本）
- 每步预估之间能不能拿到上一步真正的 outputs？v1 不模拟，估值用「典型默认值」即可
- 缺失 agent / 估值 raise → 返回 0，但不阻断启动，让记录在 model_calls 中体现
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .types import PipelineContext, get_agent_class

logger = logging.getLogger(__name__)


# 内置模板对每个 agent 的「典型 shots 数」估值；让 video / art / voice 这些按数量算成本的
# agent 在没有真实 shots 时也能给出有意义预估。
_DEFAULT_SHOT_ESTIMATES = {
    "research": 0,
    "script": 6,
    "art": 6,
    "voice": 6,
    "video": 6,
    "edit": 6,
    "review": 0,
}


def estimate_pipeline_cost(
    *,
    graph: list[dict[str, Any]],
    brief: dict[str, Any] | None,
    user_id: Optional[str] = None,
    file_id: Optional[str] = None,
) -> dict[str, Any]:
    """返回 `{"total_usd": float, "by_step": [{name, agent_type, est_usd}], "missing_agents": [...]}`

    `total_usd` 是给配额预扣用的「上限粗估」；实际花费由 model_calls 累计得出。
    """

    by_step: list[dict[str, Any]] = []
    missing: list[str] = []
    total = 0.0

    inputs: dict[str, Any] = {"brief": brief or {}}

    # 给 estimator 一组 mock 上游 outputs，覆盖大多数 agent 需要的字段
    upstream_outputs: dict[str, dict[str, Any]] = {
        "research": {"topics": [{"title": "mock", "format": "口播"}]},
        "script": _mock_script_outputs(brief or {}),
    }
    upstream_outputs["art"] = _mock_art_outputs(upstream_outputs["script"])
    upstream_outputs["voice"] = _mock_voice_outputs(upstream_outputs["script"])
    upstream_outputs["video"] = _mock_video_outputs(upstream_outputs["script"])
    upstream_outputs["edit"] = {"preview_url": "mock://", "duration_s": 24.0}
    upstream_outputs["review"] = {"issues": []}

    for node in graph:
        name = str(node.get("name") or "")
        agent_type = str(node.get("agent_type") or "")
        agent_cls = get_agent_class(agent_type)
        if not agent_cls:
            missing.append(name or agent_type)
            by_step.append(
                {"name": name, "agent_type": agent_type, "est_usd": 0.0, "missing": True}
            )
            continue

        ctx = PipelineContext(
            run_id="estimate",
            step_id=f"estimate:{name}",
            user_id=user_id,
            file_id=file_id,
            inputs=inputs,
            upstream_outputs={
                # 仅暴露依赖项的 outputs；超过 graph 已声明依赖的 key 也允许（容错）
                k: v for k, v in upstream_outputs.items() if k != name
            },
        )

        try:
            est = float(agent_cls().estimate_cost_usd(ctx) or 0.0)
        except Exception:  # pragma: no cover - estimator 不该 raise，留兜底
            logger.exception("estimate_cost_usd raised for %s", agent_type)
            est = 0.0

        by_step.append(
            {"name": name, "agent_type": agent_type, "est_usd": round(est, 6)}
        )
        total += est

    return {
        "total_usd": round(total, 6),
        "by_step": by_step,
        "missing_agents": missing,
    }


# ── helpers ──────────────────────────────────────────────────────────────────


def _mock_script_outputs(brief: dict[str, Any]) -> dict[str, Any]:
    n = _DEFAULT_SHOT_ESTIMATES.get("script", 6)
    return {
        "topic": {"title": "mock", "format": "口播"},
        "title": "mock title",
        "hook": "mock hook",
        "script": "mock " * 60,  # 让 voice estimator 用 char 数算
        "cta": "mock cta",
        "shots": [
            {
                "index": i + 1,
                "duration_s": 4.0,
                "visual": "mock visual",
                "narration": "mock narration",
                "camera": "mock",
            }
            for i in range(n)
        ],
    }


def _mock_art_outputs(script_outputs: dict[str, Any]) -> dict[str, Any]:
    shots = script_outputs.get("shots") or []
    return {
        "style_board": {"aspect_ratio": "9:16", "style_keywords": ["cinematic"]},
        "character_cards": [],
        "shots": [
            {
                **s,
                "enhanced_prompt": "mock prompt",
                "negative_prompt": "mock negative",
                "aspect_ratio": "9:16",
                "keyframe_url": f"mock://keyframe/{s.get('index')}",
            }
            for s in shots
        ],
    }


def _mock_voice_outputs(script_outputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "narration_url": "mock://narration",
        "voice": "mock",
        "voice_model": "mock",
        "subtitles": [
            {"index": i + 1, "start": i * 4.0, "end": (i + 1) * 4.0, "text": "mock"}
            for i in range(len(script_outputs.get("shots") or []))
        ],
        "char_count": len(script_outputs.get("script") or ""),
        "total_duration_s": 4.0 * len(script_outputs.get("shots") or []),
    }


def _mock_video_outputs(script_outputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "shots": [
            {
                **s,
                "video_url": f"mock://video/{s.get('index')}",
                "mode": "image_to_video",
            }
            for s in (script_outputs.get("shots") or [])
        ],
        "total_cost_usd": 0.0,
    }
