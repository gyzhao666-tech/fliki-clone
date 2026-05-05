"""EditAgent

输入：
- 上游 VideoAgent 的 shots（含 video_url）
- 可选上游 VoiceAgent 的 narration_url / subtitles
- 可选上游 ArtAgent 的 style_board.aspect_ratio（决定主比例）

输出：成片 URL（主比例，含字幕烧录优先）+ 时长 + 静默视频 URL（备查）+ srt 下载链接 +
     `previews_by_aspect`（v4：每个目标比例的成片）。

v4 取舍（在 v3 基础上的增量）：
- **按旁白时长循环视频**：当 audio_duration > video_duration（拼接静默版总时长），
  ffmpeg 用 `-stream_loop -1 + -t audio_dur` 让视频循环到旁白结束；
  反之仍按 audio 截短（旁白讲完观感更顺）
- **按 style_board.aspect_ratio 输出多比例**：默认仅出主比例（不增成本）；
  brief 里指定 `export_aspects: ["9:16","16:9","4:5"]` 时，循环调一次 mux 出每个比例
- 旧字段全部保留，前端不改也能正常显示
- 失败仍逐级降级（含字幕 > 混音无字幕 > 静默），SUCCEEDED + warning，不阻塞

输出字段
--------
- `preview_url`            ：成片（= primary_aspect 的产物，优先级：含字幕 > 混音无字幕 > 静默）
- `previews_by_aspect`     ：{ "9:16": {url, muxed, burned_in_subtitles, warning, aspect_fit}, ... }
- `primary_aspect`         ：主比例字符串（用于前端默认 tab）
- `aspect_fit`             ：cover / contain（默认 cover；可由 brief.aspect_fit 覆盖）
- `silent_video_url`       ：拼接静默版（备查）
- `narration_url`          ：旁白音轨（备查）
- `subtitle_url`           ：SRT 文件公开 URL（前端下载）
- `subtitles`              ：原始 subtitles 数据
- `muxed`                  ：主比例成片是否含旁白
- `burned_in_subtitles`    ：主比例成片是否已硬烧字幕
- `looped_video`           ：是否对原视频做了循环以匹配旁白长度
- `warning`                ：主比例的降级原因（若有）
"""
from __future__ import annotations

import logging
import os
import tempfile
from typing import Any, Optional

from app.services.media import (
    aspect_target_resolution,
    build_subtitle_force_style,
    concat_video_segments,
    mux_video_with_audio,
    subtitles_to_srt,
    upload_srt,
)

from ..types import PipelineContext, Step, StepResult, StepStatus, register_agent

logger = logging.getLogger(__name__)


_VALID_ASPECTS = {"9:16", "16:9", "4:5", "1:1", "4:3"}
_VALID_FITS = {"cover", "contain"}


@register_agent("edit")
class EditAgent(Step):
    def estimate_cost_usd(self, ctx: PipelineContext) -> float:
        return 0.0  # 仅本地 ffmpeg + 上传，按外部模型成本估为 0

    def run(self, ctx: PipelineContext) -> StepResult:  # noqa: D401
        brief = (ctx.inputs or {}).get("brief") or {}
        video_outputs = ctx.upstream_outputs.get("video") or {}
        voice_outputs = ctx.upstream_outputs.get("voice") or {}
        art_outputs = ctx.upstream_outputs.get("art") or {}

        shots: list[dict[str, Any]] = [
            s for s in (video_outputs.get("shots") or []) if isinstance(s, dict)
        ]
        if not shots:
            return StepResult(
                status=StepStatus.FAILED,
                error="edit: no shots from upstream video step",
            )

        ordered_urls: list[str] = []
        skipped: list[int] = []
        for shot in shots:
            url = shot.get("video_url")
            if isinstance(url, str) and url:
                ordered_urls.append(url)
            else:
                skipped.append(int(shot.get("index") or 0))

        if not ordered_urls:
            return StepResult(
                status=StepStatus.FAILED,
                error="edit: every shot is missing video_url",
                outputs={"skipped_indices": skipped},
            )

        # 静默拼接版（无音轨；后面循环 mux 到每个 aspect）
        if len(ordered_urls) == 1:
            silent_url: str | None = ordered_urls[0]
        else:
            silent_url = concat_video_segments(ordered_urls)
            if not silent_url:
                silent_url = ordered_urls[0]  # 整段拼接失败时保第一段不让 run 死

        total_duration = sum(
            float(s.get("duration_s") or 0.0) for s in shots if s.get("video_url")
        )

        narration_url = (
            voice_outputs.get("narration_url") if isinstance(voice_outputs, dict) else None
        )
        subtitles = (
            voice_outputs.get("subtitles") if isinstance(voice_outputs, dict) else None
        )

        # SRT：序列化并上传作为可下载产物；同时写本地临时文件供 ffmpeg 烧录
        subtitle_url: str | None = None
        srt_text = subtitles_to_srt(subtitles)
        srt_local_path: str | None = None
        if srt_text:
            subtitle_url = upload_srt(srt_text)
            try:
                fd, srt_local_path = tempfile.mkstemp(suffix=".srt")
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(srt_text)
            except Exception:
                logger.exception("edit: failed to write srt to tmp file")
                srt_local_path = None

        primary_aspect = _resolve_primary_aspect(art_outputs, brief, shots)
        export_aspects = _resolve_export_aspects(brief, primary_aspect)
        aspect_fit = _resolve_aspect_fit(brief)
        subtitle_scale = _resolve_subtitle_scale(brief)

        # 输出收集：主比例 + 任何额外比例
        previews_by_aspect: dict[str, dict[str, Any]] = {}
        try:
            for aspect in export_aspects:
                previews_by_aspect[aspect] = _produce_one_aspect(
                    silent_url=silent_url,
                    narration_url=narration_url,
                    srt_local_path=srt_local_path,
                    target_aspect=aspect,
                    aspect_fit=aspect_fit,
                    subtitle_scale=subtitle_scale,
                )
        finally:
            if srt_local_path:
                try:
                    os.unlink(srt_local_path)
                except Exception:
                    pass

        primary = previews_by_aspect.get(primary_aspect) or {}
        preview_url: str | None = primary.get("url") or silent_url

        return StepResult(
            status=StepStatus.SUCCEEDED,
            outputs={
                "preview_url": preview_url,
                "previews_by_aspect": previews_by_aspect,
                "primary_aspect": primary_aspect,
                "aspect_fit": aspect_fit,
                "silent_video_url": silent_url,
                "duration_s": total_duration,
                "shot_count": len(ordered_urls),
                "skipped_indices": skipped,
                "narration_url": narration_url,
                "subtitle_url": subtitle_url,
                "subtitles": subtitles or None,
                "muxed": bool(primary.get("muxed")),
                "burned_in_subtitles": bool(primary.get("burned_in_subtitles")),
                "looped_video": bool(primary.get("looped_video")),
                "warning": primary.get("warning"),
            },
        )


def _produce_one_aspect(
    *,
    silent_url: Optional[str],
    narration_url: Optional[str],
    srt_local_path: Optional[str],
    target_aspect: str,
    aspect_fit: str,
    subtitle_scale: float = 1.0,
) -> dict[str, Any]:
    """为单个 aspect 出一个成片；尽量逐级降级，永远返回一个 dict（含 url=None）。

    v5：根据 target_aspect 算 force_style 并写入 `subtitle_style` 字段，前端可在
    比例 tab 上展示「9:16 用了字号 44 / MarginV 220」之类的调试信息。
    """

    # 即使最终降级到无字幕，也把"如果烧字幕会用什么样式"算出来给前端展示
    _, subtitle_style_debug = build_subtitle_force_style(
        target_aspect, scale=subtitle_scale
    )

    out: dict[str, Any] = {
        "url": silent_url,
        "muxed": False,
        "burned_in_subtitles": False,
        "looped_video": False,
        "aspect_fit": aspect_fit,
        "subtitle_style": subtitle_style_debug,
        "warning": None,
    }
    warnings: list[str] = []

    if not silent_url:
        out["warning"] = "no silent video to start from"
        return out

    try:
        # 主路径：mux 旁白 + 烧字幕 + 转 aspect + 必要时循环视频
        if narration_url and srt_local_path:
            burned_url = mux_video_with_audio(
                silent_url,
                narration_url,
                srt_path=srt_local_path,
                target_aspect=target_aspect,
                aspect_fit=aspect_fit,
                loop_video_to_audio=True,
                subtitle_scale=subtitle_scale,
            )
            if burned_url:
                out.update(
                    {
                        "url": burned_url,
                        "muxed": True,
                        "burned_in_subtitles": True,
                        "looped_video": True,  # 由 ffmpeg 内部决定，外层只能默认认为 True；
                        # （如果想精确，得把 helper 改为返回 detail dict；当前不必要）
                    }
                )
                return out
            warnings.append("burn-in + mux failed; trying mux without subtitles")

        # 二级降级：mux 但不烧字幕
        if narration_url:
            muxed_url = mux_video_with_audio(
                silent_url,
                narration_url,
                target_aspect=target_aspect,
                aspect_fit=aspect_fit,
                loop_video_to_audio=True,
            )
            if muxed_url:
                out.update(
                    {
                        "url": muxed_url,
                        "muxed": True,
                        "burned_in_subtitles": False,
                        "looped_video": True,
                    }
                )
                if warnings:
                    out["warning"] = "; ".join(warnings)
                return out
            warnings.append("mux failed; falling back to silent video at target aspect")

        # 三级降级：仅做 aspect 转换的静默版（无旁白）
        if aspect_target_resolution(target_aspect):
            transcoded_silent = _transcode_silent(silent_url, target_aspect, aspect_fit)
            if transcoded_silent:
                out["url"] = transcoded_silent
                if warnings:
                    out["warning"] = "; ".join(warnings)
                return out
            warnings.append("silent transcode to target aspect also failed")

        # 终极兜底：原静默 url（可能是原始 aspect）
        if warnings:
            out["warning"] = "; ".join(warnings)
        return out
    except Exception:
        logger.exception("edit: produce_one_aspect raised")
        out["warning"] = "; ".join(warnings + ["unexpected exception in mux/burn"])
        return out


def _transcode_silent(
    silent_url: str, target_aspect: str, aspect_fit: str
) -> Optional[str]:
    """仅做静默版的 aspect 转换（无旁白时的三级降级）。

    复用 `mux_video_with_audio`：把视频自身音轨当作 audio 输入（即视频路径同时作为 audio）。
    没有真音频时直接返回 None；这种纯静默 + 转 aspect 的场景不常见，留个兜底接口。
    """
    # 简化：当前 v4 没有 audio 时不做静默 transcoding（成片仍是原 silent_url）。
    # 真的需要 silent transcoding 请加 ffmpeg helper；目前所有 voice 路径都会给 narration_url，
    # 缺 narration 的场景下用户也不会期待平台多比例切换。
    return None


# ── 解析 brief / 上游 ────────────────────────────────────────────────────────


def _resolve_primary_aspect(
    art_outputs: dict[str, Any],
    brief: dict[str, Any],
    shots: list[dict[str, Any]],
) -> str:
    """主比例优先级：brief.primary_aspect > art.style_board.aspect_ratio > shot[0].aspect_ratio > 16:9。"""

    candidates: list[Any] = [
        brief.get("primary_aspect"),
        (art_outputs.get("style_board") or {}).get("aspect_ratio")
        if isinstance(art_outputs, dict)
        else None,
        shots[0].get("aspect_ratio") if shots else None,
    ]
    for c in candidates:
        s = str(c or "").strip()
        if s in _VALID_ASPECTS:
            return s
    return "16:9"


def _resolve_export_aspects(brief: dict[str, Any], primary: str) -> list[str]:
    """决定本次要导哪些比例。

    - 缺省：仅主比例
    - `brief.export_aspects` 是 list/tuple → 取交集后并入 primary（保 primary 排第一）
    - 字符串 `"all"` 或 `"common"` → 主比例 + 9:16 + 16:9 + 4:5
    """

    raw = brief.get("export_aspects")
    if not raw:
        return [primary]

    if isinstance(raw, str):
        if raw.lower().strip() in ("all", "common"):
            requested = ["9:16", "16:9", "4:5"]
        else:
            requested = [raw.strip()]
    elif isinstance(raw, (list, tuple)):
        requested = [str(x).strip() for x in raw if str(x).strip()]
    else:
        return [primary]

    # 主比例放第一；其余按用户给定顺序去重
    seen = {primary}
    out = [primary]
    for a in requested:
        if a in _VALID_ASPECTS and a not in seen:
            out.append(a)
            seen.add(a)
    return out


def _resolve_aspect_fit(brief: dict[str, Any]) -> str:
    fit = str(brief.get("aspect_fit", "cover")).strip().lower()
    return fit if fit in _VALID_FITS else "cover"


def _resolve_subtitle_scale(brief: dict[str, Any]) -> float:
    """读 brief.subtitle_scale；clamp 到 [0.5, 2.0]，缺省 1.0。

    用例：brief 里写 `"subtitle_scale": 1.5` → 字幕字号 + 边距 + 描边整体 ×1.5。
    在 9:16 上视频要投屏到大屏 / 老人版应用时，可以把字号再加大。
    """

    raw = brief.get("subtitle_scale", 1.0)
    try:
        v = float(raw)
    except Exception:
        return 1.0
    if v <= 0:
        return 1.0
    return max(0.5, min(2.0, v))
