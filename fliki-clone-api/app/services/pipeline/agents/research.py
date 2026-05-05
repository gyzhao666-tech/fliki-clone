"""ResearchAgent

输入：Brief（赛道、平台、受众、目标、参考链接、禁区）
输出：候选选题列表（每条含标题、钩子、形态建议）

v1：纯 LLM 调用；后续接热点榜 / 竞品抓取 / 关键词扩散等技能。
"""
from __future__ import annotations

import json
from typing import Any

from app.services.model_gateway import ModelAction, RenderRequest, get_gateway

from ..types import PipelineContext, Step, StepResult, StepStatus, register_agent


SYSTEM_PROMPT = (
    "你是一位资深短视频策划师，擅长把品牌 / 创作者的 Brief 转换成可拍摄的选题。"
    " 给定 Brief，请输出 6 条不同角度的选题候选。"
    " 每条选题包含：title（≤20 字）、hook（前 3 秒钩子）、format（口播 / 数字人 / 短剧 / UGC 广告 / 资讯 / 教程之一）、reason（为什么这条值得做）。"
    " 严格输出 JSON 数组，不要包含其它文字。"
)


@register_agent("research")
class ResearchAgent(Step):
    def estimate_cost_usd(self, ctx: PipelineContext) -> float:
        return 0.002  # LLM 一次调用粗估

    def run(self, ctx: PipelineContext) -> StepResult:  # noqa: D401
        brief = (ctx.inputs or {}).get("brief") or {}
        if not brief:
            return StepResult(
                status=StepStatus.FAILED,
                error="research: missing brief in pipeline inputs",
            )

        user_msg = (
            "Brief：\n" + json.dumps(brief, ensure_ascii=False, indent=2)
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
                    "temperature": 0.7,
                    "max_tokens": 1200,
                    "response_format": "json_array",
                    "approx_tokens": 1500,
                },
                user_id=ctx.user_id,
                file_id=ctx.file_id,
                pipeline_step_id=ctx.step_id,
            )
        )

        if not result.ok or not isinstance(result.output, list):
            return StepResult(
                status=StepStatus.FAILED,
                error=result.error or "research: invalid LLM output",
                cost_usd=result.cost_usd,
            )

        topics: list[dict[str, Any]] = []
        for item in result.output[:10]:
            if not isinstance(item, dict):
                continue
            topics.append(
                {
                    "title": str(item.get("title", "")).strip()[:60],
                    "hook": str(item.get("hook", "")).strip()[:200],
                    "format": str(item.get("format", "")).strip()[:30],
                    "reason": str(item.get("reason", "")).strip()[:300],
                }
            )

        if not topics:
            return StepResult(
                status=StepStatus.FAILED,
                error="research: empty topics after parsing",
                cost_usd=result.cost_usd,
            )

        return StepResult(
            status=StepStatus.SUCCEEDED,
            outputs={"topics": topics},
            cost_usd=result.cost_usd,
        )
