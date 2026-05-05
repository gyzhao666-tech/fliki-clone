"""ReviewAgent（v1：纯静态规则）

收集上游所有产物，输出 issues 列表。当前只做最低限度的健全性检查；
后续可加入：
- LLM 事实核查
- 关键帧抽样 + 视觉模型检测瑕疵
- 字幕 / 口播 / 镜头时长一致性比对

v1 行为：
- 只要发现 severity >= "error" 的 issue，整个 step 进入 awaiting_review
- 否则直接 succeeded
"""
from __future__ import annotations

from typing import Any

from ..types import PipelineContext, Step, StepResult, StepStatus, register_agent


@register_agent("review")
class ReviewAgent(Step):
    def run(self, ctx: PipelineContext) -> StepResult:  # noqa: D401
        issues: list[dict[str, Any]] = []

        script = ctx.upstream_outputs.get("script") or {}
        if not script.get("shots"):
            issues.append(_issue("script", "error", "缺少分镜表"))
        else:
            shots = script["shots"]
            for shot in shots:
                if not str(shot.get("visual") or "").strip():
                    issues.append(
                        _issue(
                            "script",
                            "warning",
                            f"shot {shot.get('index')} 没有 visual 描述",
                        )
                    )

        video = ctx.upstream_outputs.get("video") or {}
        video_shots = video.get("shots") or []
        if video_shots:
            failed = [s for s in video_shots if not s.get("video_url")]
            if failed:
                names = ", ".join(str(s.get("index")) for s in failed)
                issues.append(
                    _issue(
                        "video",
                        "error",
                        f"以下 shot 视频生成失败：{names}",
                        meta={"failed_indices": [s.get("index") for s in failed]},
                    )
                )
        elif "video" in ctx.upstream_outputs:
            issues.append(_issue("video", "error", "video step 没有产出 shots"))

        edit = ctx.upstream_outputs.get("edit") or {}
        if "edit" in ctx.upstream_outputs:
            if not edit.get("preview_url"):
                issues.append(_issue("edit", "error", "edit step 没有产出 preview_url"))
            elif edit.get("skipped_indices"):
                issues.append(
                    _issue(
                        "edit",
                        "warning",
                        f"拼接时跳过了 {len(edit['skipped_indices'])} 个 shot",
                        meta={"skipped_indices": edit.get("skipped_indices")},
                    )
                )
            if edit.get("narration_url") and edit.get("muxed") is False:
                # v2 默认会混音；走到这里说明 ffmpeg 失败 / 缺二进制；preview_url 已经回退
                msg = edit.get("warning") or "旁白未能与视频混音；preview_url 是静默版本"
                issues.append(_issue("edit", "warning", str(msg)))

        voice = ctx.upstream_outputs.get("voice") or {}
        if "voice" in ctx.upstream_outputs:
            if voice.get("warning"):
                issues.append(_issue("voice", "warning", str(voice["warning"])))
            elif not voice.get("narration_url"):
                issues.append(
                    _issue(
                        "voice",
                        "warning",
                        "voice step 没有产出 narration_url（TTS 未启用或失败）",
                    )
                )
            subs = voice.get("subtitles") or []
            empty_subs = [s for s in subs if not str(s.get("text") or "").strip()]
            if empty_subs:
                issues.append(
                    _issue(
                        "voice",
                        "warning",
                        f"{len(empty_subs)} 条字幕缺少文字（来自空 narration 的 shot）",
                    )
                )

        art = ctx.upstream_outputs.get("art") or {}
        if "art" in ctx.upstream_outputs:
            if not (art.get("style_board") or {}).get("style_keywords"):
                issues.append(_issue("art", "warning", "style_board 缺少 style_keywords"))
            art_shots = art.get("shots") or []
            without_prompt = [
                s for s in art_shots if not str(s.get("enhanced_prompt") or "").strip()
            ]
            if without_prompt:
                issues.append(
                    _issue(
                        "art",
                        "warning",
                        f"{len(without_prompt)} 个 shot 缺少 enhanced_prompt（已回退到原始 visual）",
                    )
                )

        outputs = {
            "issues": issues,
            "summary": _summary(issues),
        }

        has_error = any(i.get("severity") == "error" for i in issues)
        if has_error:
            return StepResult(
                status=StepStatus.AWAITING_REVIEW,
                outputs=outputs,
            )
        return StepResult(status=StepStatus.SUCCEEDED, outputs=outputs)


def _issue(area: str, severity: str, message: str, meta: dict | None = None) -> dict:
    return {
        "area": area,
        "severity": severity,
        "message": message,
        "meta": meta or {},
    }


def _summary(issues: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"error": 0, "warning": 0, "info": 0}
    for issue in issues:
        sev = issue.get("severity") or "info"
        counts[sev] = counts.get(sev, 0) + 1
    return counts
