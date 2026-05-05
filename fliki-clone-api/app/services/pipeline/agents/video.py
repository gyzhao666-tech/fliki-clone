"""VideoAgent v2 / v3 — 用 ArtAgent 锚点作 IMAGE_TO_VIDEO 主参考帧（含 v5 多角色）

输入：上游 ArtAgent 的 shots（含 enhanced_prompt / keyframe_url / character_locked
     / locked_character）
     上游 ArtAgent 的 `outputs.character_anchors`（v5 多角色字典：{name -> anchor}）
     —— 缺省时退到 v3 单字段 `outputs.character_anchor`（兼容老 run）
输出：每个 shot 的视频片段 URL（不做拼接 —— 拼接交给 EditAgent）

ref-image 选择策略（v2 + v5）
-----------------------------
逐镜按下面顺序挑 ref-image，并把结果写到 `outputs.shots[i].ref_image_source`,
便于前端/调试观察哪些镜真用了对应角色锚点：

1. **anchor**：`shot.character_locked === True` 且
   `art.character_anchors[shot.locked_character].url` 存在
   → 用对应角色 URL 走 IMAGE_TO_VIDEO；该角色跨镜锁脸 / 服装。
   v5 关键升级：从「全片只用主角 anchor」升级到「逐镜按 locked_character 选对应
   anchor」，配角镜真会拿到该配角的 anchor。
2. **keyframe**：否则若 `shot.keyframe_url` 存在 → 用每镜独立关键帧走 IMAGE_TO_VIDEO；
   character_locked=False 镜（focus_character 没匹配到任何 character_card）走这里。
3. **none**：以上都缺 → 降级 GENERATE_VIDEO（无 ref-image 一致性）。

为什么这样选：ArtAgent v3+v5 已经在 character_locked=True 的镜里把对应角色描述拼到
prompt 头部；如果 image provider 拿到该角色锚点参考板（哪怕 i2v 模型只是把 ref
当首帧），该角色跨镜脸 / 服装会更稳定。配角镜（focus_character 显式标了别人）
v5 之前会被迫走每镜独立 keyframe；v5 之后如果 ArtAgent 也给该配角出了 anchor，
就可以走 anchor 路径继续锁定。

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
        anchors_by_role = _character_anchors_by_role(ctx)
        # v3 兼容：保留主角单 URL 给 outputs（旧前端读 character_anchor_url）
        protagonist_name = _protagonist_name(ctx)
        anchor_url = (
            anchors_by_role.get(protagonist_name) if protagonist_name else None
        ) or next(iter(anchors_by_role.values()), None)

        gateway = get_gateway()
        results: list[dict[str, Any]] = []
        total_cost = 0.0
        any_ok = False
        anchor_used_count = 0
        keyframe_used_count = 0
        none_count = 0
        # v5：统计每个角色 anchor 被多少镜引用，便于前端 / 调试
        anchor_used_by_role: dict[str, int] = {}

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

            ref_image_url, ref_image_source, ref_anchor_role = _select_ref_image(
                shot=shot,
                anchors_by_role=anchors_by_role,
                keyframe_url=keyframe_url,
            )
            mode_used = "image_to_video" if ref_image_url else "generate_video"

            if ref_image_source == "anchor":
                anchor_used_count += 1
                if ref_anchor_role:
                    anchor_used_by_role[ref_anchor_role] = (
                        anchor_used_by_role.get(ref_anchor_role, 0) + 1
                    )
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
                    # v5：写回这一镜真正用了哪个角色的 anchor（前端徽标读这个）
                    "ref_anchor_role": ref_anchor_role,
                }
            )

        outputs = {
            "shots": results,
            "total_cost_usd": total_cost,
            # v2 / v5 摘要：anchor 复用情况 + 多角色细分
            "ref_image_summary": {
                "anchor": anchor_used_count,
                "keyframe": keyframe_used_count,
                "none": none_count,
                "by_role": anchor_used_by_role,
            },
            "character_anchor_url": anchor_url,
            # v5：暴露 anchors_by_role 字典让前端能列每角色的 URL
            "character_anchors_by_role": anchors_by_role or None,
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


def _character_anchors_by_role(ctx: PipelineContext) -> dict[str, str]:
    """从 ArtAgent v3 / v5 outputs 拉每角色的锚点参考板 URL，返回 {name -> url}。

    支持的形态（按优先级）：
    - `outputs.art.character_anchors`（v5 主路径，dict[name, anchor_dict]）
    - `outputs.art.character_anchor`（v3 fallback，single anchor；映射回 dict）

    缺失返空 dict（caller 退到 keyframe / GENERATE_VIDEO）。
    """
    art_out = ctx.upstream_outputs.get("art") or {}
    if not isinstance(art_out, dict):
        return {}

    out: dict[str, str] = {}
    anchors = art_out.get("character_anchors")
    if isinstance(anchors, dict):
        for name, anchor in anchors.items():
            if not isinstance(anchor, dict):
                continue
            url = anchor.get("url")
            if isinstance(url, str) and url.strip():
                out[str(name)] = url.strip()
        if out:
            return out

    # v3 fallback：单 anchor 字段
    anchor = art_out.get("character_anchor")
    if isinstance(anchor, dict):
        url = anchor.get("url")
        if isinstance(url, str) and url.strip():
            name = str(anchor.get("name") or "").strip()
            if name:
                out[name] = url.strip()
    return out


def _protagonist_name(ctx: PipelineContext) -> str | None:
    """从 ArtAgent outputs 拿主角名（向后兼容字段 outputs.protagonist_name）。"""
    art_out = ctx.upstream_outputs.get("art") or {}
    if not isinstance(art_out, dict):
        return None
    name = art_out.get("protagonist_name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _select_ref_image(
    *,
    shot: dict[str, Any],
    anchors_by_role: dict[str, str],
    keyframe_url: Any,
) -> tuple[str | None, str, str | None]:
    """按优先级选 ref-image。

    返回 `(url_or_none, source, anchor_role_or_none)`：
    - source ∈ {"anchor", "keyframe", "none"}
    - anchor_role：source=='anchor' 时返回该 anchor 对应的角色名；其它情况 None

    规则（v5）：
    1. shot.character_locked=True 且 anchors_by_role 非空：
       a. 优先用 shot.locked_character 命中的角色 anchor（v5 ArtAgent 写回的字段）
       b. 缺失时退到 shot.focus_character 命中的角色（旧 run / 兼容）
       c. 都没命中时取 anchors_by_role 第一个（v3 行为：只有主角 anchor）
    2. 有 keyframe_url → ("...", "keyframe", None)
       —— character_locked=False 镜（focus 没匹配卡）走每镜独立关键帧
    3. 否则 → (None, "none", None)，调用方降级 GENERATE_VIDEO
    """
    locked = bool(shot.get("character_locked"))
    if locked and anchors_by_role:
        # 大小写不敏感的角色名查找
        lower_to_name = {k.lower(): k for k in anchors_by_role.keys()}

        target_keys: list[str] = []
        lc = str(shot.get("locked_character") or "").strip()
        fc = str(shot.get("focus_character") or "").strip()
        if lc:
            target_keys.append(lc)
        if fc and fc != lc:
            target_keys.append(fc)

        for key in target_keys:
            if key in anchors_by_role:
                return anchors_by_role[key], "anchor", key
            real = lower_to_name.get(key.lower())
            if real:
                return anchors_by_role[real], "anchor", real

        # 兜底：取第一个 anchor（v3 老 run 没 locked_character 字段时仍工作）
        first_name = next(iter(anchors_by_role.keys()))
        return anchors_by_role[first_name], "anchor", first_name

    if isinstance(keyframe_url, str) and keyframe_url.strip():
        return keyframe_url.strip(), "keyframe", None
    return None, "none", None
