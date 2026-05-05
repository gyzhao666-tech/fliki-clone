"""ScriptAgent

输入：上游 ResearchAgent 输出的 topics + Brief 中指定的目标 topic 索引或标题
输出：脚本（含开头钩子、3-6 段正文、结尾 CTA）+ 分镜表草稿（每镜镜头描述、时长、视觉关键词）

注意：分镜表只是“草稿”——具体镜头落到 shots 表是 Phase 2 的事。本 agent 仅产出结构化 JSON。
"""
from __future__ import annotations

import json
from typing import Any

from app.services.model_gateway import ModelAction, RenderRequest, get_gateway

from ..types import PipelineContext, Step, StepResult, StepStatus, register_agent


SYSTEM_PROMPT = (
    "你是一位短视频编剧 + 分镜导演。"
    " 给定一个具体选题 + Brief，请输出 JSON 对象，字段如下："
    " {\n"
    "   \"title\": 视频成片标题,\n"
    "   \"hook\": 前 3 秒钩子文案,\n"
    "   \"script\": 完整口播稿（≤300 字）,\n"
    "   \"cta\": 结尾行动号召,\n"
    "   \"shots\": [\n"
    "     { \"index\": 1, \"duration_s\": 3, \"visual\": 视觉描述（英文，便于喂给视频模型）, \"narration\": 这一镜的口播文案, \"camera\": 镜头运动 },\n"
    "     ...（共 4-8 镜）\n"
    "   ]\n"
    " }\n"
    " 严格输出合法 JSON 对象，不要包含其它文字。"
)


@register_agent("script")
class ScriptAgent(Step):
    def estimate_cost_usd(self, ctx: PipelineContext) -> float:
        return 0.004

    def run(self, ctx: PipelineContext) -> StepResult:  # noqa: D401
        brief = (ctx.inputs or {}).get("brief") or {}
        target = (ctx.inputs or {}).get("target_topic")

        topics = (ctx.upstream_outputs.get("research") or {}).get("topics") or []
        chosen: dict[str, Any] | None = None
        if isinstance(target, dict):
            chosen = target
        elif isinstance(target, str) and topics:
            for t in topics:
                if t.get("title") == target:
                    chosen = t
                    break
        if not chosen and topics:
            chosen = topics[0]
        if not chosen:
            return StepResult(
                status=StepStatus.FAILED,
                error="script: no topic available (research output empty and no target provided)",
            )

        user_msg = (
            "Brief：\n"
            + json.dumps(brief, ensure_ascii=False, indent=2)
            + "\n\n选题：\n"
            + json.dumps(chosen, ensure_ascii=False, indent=2)
        )

        gateway = get_gateway()
        result = gateway.run(
            RenderRequest(
                action=ModelAction.LLM,
                params={
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": 0.6,
                    "max_tokens": 1800,
                    "approx_tokens": 2000,
                },
                user_id=ctx.user_id,
                file_id=ctx.file_id,
                pipeline_step_id=ctx.step_id,
            )
        )

        if not result.ok or not isinstance(result.output, str):
            return StepResult(
                status=StepStatus.FAILED,
                error=result.error or "script: invalid LLM output",
                cost_usd=result.cost_usd,
            )

        parsed = _parse_json_object(result.output)
        if not parsed:
            return StepResult(
                status=StepStatus.FAILED,
                error="script: cannot parse LLM JSON object",
                cost_usd=result.cost_usd,
            )

        outputs = {
            "topic": chosen,
            "title": str(parsed.get("title", "")).strip()[:120],
            "hook": str(parsed.get("hook", "")).strip()[:200],
            "script": str(parsed.get("script", "")).strip()[:2000],
            "cta": str(parsed.get("cta", "")).strip()[:200],
            "shots": _normalise_shots(parsed.get("shots") or []),
        }
        if not outputs["shots"]:
            return StepResult(
                status=StepStatus.FAILED,
                error="script: empty shots",
                cost_usd=result.cost_usd,
            )

        # 脚本是流程链上人最关心的产物，强制人工审批
        return StepResult(
            status=StepStatus.AWAITING_REVIEW,
            outputs=outputs,
            cost_usd=result.cost_usd,
        )


def _parse_json_object(content: str) -> dict[str, Any] | None:
    import re

    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group())
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalise_shots(items: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return out
    for i, item in enumerate(items[:12]):
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "index": int(item.get("index", i + 1) or i + 1),
                "duration_s": float(item.get("duration_s", 4.0) or 4.0),
                "visual": str(item.get("visual", "")).strip()[:400],
                "narration": str(item.get("narration", "")).strip()[:300],
                "camera": str(item.get("camera", "")).strip()[:80],
            }
        )
    return out
