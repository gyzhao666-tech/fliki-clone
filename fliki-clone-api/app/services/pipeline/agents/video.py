"""VideoAgent

输入：上游 ScriptAgent 的 shots（含 visual / duration_s）
输出：每个 shot 的视频片段 URL（不做拼接 —— 拼接交给 EditAgent）

设计要点：
- 走 model_gateway，按 provider 偏好（默认 Kling → SiliconFlow）
- 单 shot 生成失败 → 标记 shot.error 但不让整个 step 失败；最后由 ReviewAgent 决定
- AWAITING_REVIEW 触发条件：任何 shot 失败 / 或所有 shot 都失败时直接 FAILED
- v1 不做风格延续 / 角色一致性：留给 ArtAgent 与 reference image
"""
from __future__ import annotations

from typing import Any

from app.services.model_gateway import (
    CallStatus,
    ModelAction,
    RenderRequest,
    get_gateway,
)

from ..types import PipelineContext, Step, StepResult, StepStatus, register_agent


@register_agent("video")
class VideoAgent(Step):
    def estimate_cost_usd(self, ctx: PipelineContext) -> float:
        shots = _shots_from_ctx(ctx)
        # 5s/镜均价取 Kling $0.20/s = $1/镜，10 镜 ≈ $10
        return sum(float(s.get("duration_s") or 5.0) * 0.20 for s in shots)

    def run(self, ctx: PipelineContext) -> StepResult:  # noqa: D401
        shots = _shots_from_ctx(ctx)
        if not shots:
            return StepResult(
                status=StepStatus.FAILED,
                error="video: no shots in upstream script outputs",
            )
        default_aspect = _default_aspect(ctx)

        gateway = get_gateway()
        results: list[dict[str, Any]] = []
        total_cost = 0.0
        any_ok = False

        for shot in shots:
            # 优先使用 ArtAgent 增强后的 prompt；缺失则回退到 ScriptAgent 的 visual。
            prompt = str(
                shot.get("enhanced_prompt") or shot.get("visual") or shot.get("narration") or ""
            ).strip()
            if not prompt:
                results.append(
                    {
                        **shot,
                        "video_url": None,
                        "error": "empty visual prompt",
                        "model_call_id": None,
                    }
                )
                continue

            duration = float(shot.get("duration_s") or 5.0)
            aspect = str(shot.get("aspect_ratio") or default_aspect)
            negative_prompt = str(shot.get("negative_prompt") or "").strip()
            keyframe_url = shot.get("keyframe_url")
            mode_used = "image_to_video" if keyframe_url else "generate_video"

            params: dict[str, Any] = {
                "prompt": prompt,
                "duration": int(max(5, round(duration))),
                "aspect_ratio": aspect,
            }
            if negative_prompt:
                params["negative_prompt"] = negative_prompt

            if keyframe_url:
                params["ref_image"] = keyframe_url
                action = ModelAction.IMAGE_TO_VIDEO
            else:
                action = ModelAction.GENERATE_VIDEO

            request = RenderRequest(
                action=action,
                params=params,
                user_id=ctx.user_id,
                file_id=ctx.file_id,
                pipeline_step_id=ctx.step_id,
                timeout_s=900.0,
            )
            result = gateway.run(request)
            total_cost += float(result.cost_usd or 0.0)

            video_url = None
            if result.ok and isinstance(result.output, dict):
                video_url = result.output.get("video_url")
                if video_url:
                    any_ok = True

            results.append(
                {
                    **shot,
                    "video_url": video_url,
                    "mode": mode_used,
                    "provider": result.provider.value if result.provider else None,
                    "model": result.model,
                    "cost_usd": float(result.cost_usd or 0.0),
                    "duration_ms": int(result.duration_ms or 0),
                    "model_call_id": result.model_call_id,
                    "error": result.error if result.status != CallStatus.SUCCEEDED else None,
                }
            )

        outputs = {"shots": results, "total_cost_usd": total_cost}

        if not any_ok:
            return StepResult(
                status=StepStatus.FAILED,
                error="video: all shots failed",
                outputs=outputs,
                cost_usd=total_cost,
            )
        # 视频生成是高风险 + 高花费节点，强制人工审批后再继续
        return StepResult(
            status=StepStatus.AWAITING_REVIEW,
            outputs=outputs,
            cost_usd=total_cost,
        )


def _shots_from_ctx(ctx: PipelineContext) -> list[dict[str, Any]]:
    """优先取 ArtAgent 输出（含 enhanced_prompt 与 aspect_ratio），否则回退 ScriptAgent。"""

    art_out = ctx.upstream_outputs.get("art") or {}
    if isinstance(art_out, dict) and art_out.get("shots"):
        return [s for s in art_out["shots"] if isinstance(s, dict)]
    script_out = ctx.upstream_outputs.get("script") or {}
    return [s for s in (script_out.get("shots") or []) if isinstance(s, dict)]


def _default_aspect(ctx: PipelineContext) -> str:
    art_out = ctx.upstream_outputs.get("art") or {}
    sb = (art_out or {}).get("style_board") or {}
    aspect = str(sb.get("aspect_ratio") or "").strip()
    return aspect or "16:9"
