"""VideoAgent v2 — 用 ArtAgent 锚点作 IMAGE_TO_VIDEO 主参考帧

输入：上游 ArtAgent 的 shots（含 enhanced_prompt / keyframe_url / character_locked）
     上游 ArtAgent 的 outputs.character_anchor.url（v3 主角锚点参考板，可选）
输出：每个 shot 的视频片段 URL（不做拼接 —— 拼接交给 EditAgent）

ref-image 选择策略（v2 新增）
-----------------------------
逐镜按下面顺序挑 ref-image，并把结果写到 `outputs.shots[i].ref_image_source`,
便于前端/调试观察哪些镜真用了角色锚点：

1. **anchor**：`shot.character_locked === True`（ArtAgent v3 已注入主角一致性 prompt）
   且 `art.character_anchor.url` 存在 → 用该 URL 走 IMAGE_TO_VIDEO；
   主角跨镜更稳定（结合 ArtAgent v3 的 prompt 锁定 + 防漂 negative）。
2. **keyframe**：否则若 `shot.keyframe_url` 存在 → 用每镜独立关键帧走 IMAGE_TO_VIDEO；
   非主角镜 / 多角色镜 / character_locked=False 走这里。
3. **none**：以上都缺 → 降级 GENERATE_VIDEO（无 ref-image 一致性）。

为什么这样选：ArtAgent v3 已经在 character_locked=True 的镜里把主角描述拼到 prompt
头部；如果 image provider 还能拿到锚点参考板（哪怕 i2v 模型只是把 ref 当首帧），
跨镜主角脸 / 服装会更稳定。非主角镜（focus_character 显式标了别人）应继续用
本镜独立 keyframe，避免主角被强行拉进画面。

其它设计要点（v1 沿用）
- 走 model_gateway，按 provider 偏好（默认 Kling → SiliconFlow）
- 单 shot 生成失败 → 标记 shot.error 但不让整个 step 失败；最后由 ReviewAgent 决定
- AWAITING_REVIEW 触发条件：任何 shot 失败 / 或所有 shot 都失败时直接 FAILED
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
        anchor_url = _character_anchor_url(ctx)

        gateway = get_gateway()
        results: list[dict[str, Any]] = []
        total_cost = 0.0
        any_ok = False
        anchor_used_count = 0
        keyframe_used_count = 0
        none_count = 0

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
                        "ref_image_source": "none",
                    }
                )
                none_count += 1
                continue

            duration = float(shot.get("duration_s") or 5.0)
            aspect = str(shot.get("aspect_ratio") or default_aspect)
            negative_prompt = str(shot.get("negative_prompt") or "").strip()
            keyframe_url = shot.get("keyframe_url")

            ref_image_url, ref_image_source = _select_ref_image(
                shot=shot,
                anchor_url=anchor_url,
                keyframe_url=keyframe_url,
            )
            mode_used = "image_to_video" if ref_image_url else "generate_video"

            if ref_image_source == "anchor":
                anchor_used_count += 1
            elif ref_image_source == "keyframe":
                keyframe_used_count += 1
            else:
                none_count += 1

            params: dict[str, Any] = {
                "prompt": prompt,
                "duration": int(max(5, round(duration))),
                "aspect_ratio": aspect,
            }
            if negative_prompt:
                params["negative_prompt"] = negative_prompt

            if ref_image_url:
                params["ref_image"] = ref_image_url
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
                    "ref_image_source": ref_image_source,
                    "ref_image_url": ref_image_url,
                }
            )

        outputs = {
            "shots": results,
            "total_cost_usd": total_cost,
            # v2 摘要：让前端 / 调试一眼看出 anchor 复用情况
            "ref_image_summary": {
                "anchor": anchor_used_count,
                "keyframe": keyframe_used_count,
                "none": none_count,
            },
            "character_anchor_url": anchor_url,
        }

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


def _character_anchor_url(ctx: PipelineContext) -> str | None:
    """从 ArtAgent v3 outputs 拉主角锚点参考板 URL；缺失返 None。

    支持的形态：
    - `outputs.art.character_anchor.url`（v3 主路径）
    """
    art_out = ctx.upstream_outputs.get("art") or {}
    if not isinstance(art_out, dict):
        return None
    anchor = art_out.get("character_anchor")
    if isinstance(anchor, dict):
        url = anchor.get("url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    return None


def _select_ref_image(
    *,
    shot: dict[str, Any],
    anchor_url: str | None,
    keyframe_url: Any,
) -> tuple[str | None, str]:
    """按优先级选 ref-image。

    返回 `(url_or_none, source)`，source ∈ {"anchor", "keyframe", "none"}。

    规则：
    1. shot.character_locked=True 且有 anchor_url → ("...", "anchor")
       —— 主角镜：用全片唯一锚点参考板锁脸 / 服装
    2. 有 keyframe_url → ("...", "keyframe")
       —— 非主角镜（含 character_locked=False / focus_character 标了别人）走每镜独立关键帧
    3. 否则 → (None, "none")，调用方降级 GENERATE_VIDEO
    """
    locked = bool(shot.get("character_locked"))
    if locked and anchor_url:
        return anchor_url, "anchor"
    if isinstance(keyframe_url, str) and keyframe_url.strip():
        return keyframe_url.strip(), "keyframe"
    return None, "none"
