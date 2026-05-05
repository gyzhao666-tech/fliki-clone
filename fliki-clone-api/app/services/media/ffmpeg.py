"""基于 ffmpeg 的本地媒体处理。

仅依赖系统 `ffmpeg` 二进制；缺失时静默返回 None，便于在没有 ffmpeg 的开发环境下也能跑通。
"""
from __future__ import annotations

import base64
import logging
import os
import subprocess
import tempfile
import uuid
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def concat_video_segments(video_urls: list[str]) -> Optional[str]:
    """把多段视频按顺序拼接成一段，上传到 S3/R2/本地静态目录后返回公开 URL。

    - 长度为 1 时直接返回原 URL，省去拼接成本
    - 三层 ffmpeg 策略：流复制 → 重编码 + 音轨 → 重编码仅视频
    - 任何环节失败均返回 None；调用方需处理（通常降级为返回首段 URL）
    """
    if not video_urls:
        return None
    if len(video_urls) == 1:
        return video_urls[0]

    local_paths: list[str] = []
    list_path: str | None = None
    out_path: str | None = None

    try:
        for url in video_urls:
            r = requests.get(url, timeout=120, stream=True)
            if r.status_code != 200:
                logger.warning(
                    "concat: download failed url=%s status=%s",
                    url[:80],
                    r.status_code,
                )
                return None
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
                local_paths.append(f.name)

        list_path = _write_concat_list(local_paths)
        fd, out_path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)

        # 1) 流复制（最快；要求各段编码 / 容器 / 时间基一致）
        ok, err = _try_ffmpeg(list_path, out_path, ["-c", "copy"])
        if not ok:
            logger.info("concat copy failed, will reencode: %s", _tail(err))
            ok, err2 = _try_ffmpeg(
                list_path,
                out_path,
                [
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-crf", "23",
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-movflags", "+faststart",
                ],
            )
            if not ok:
                logger.info("concat reencode failed, fall back to video-only: %s", _tail(err2))
                ok, err3 = _try_ffmpeg(
                    list_path,
                    out_path,
                    ["-c:v", "libx264", "-preset", "fast", "-crf", "23", "-an", "-movflags", "+faststart"],
                )
                if not ok:
                    logger.error("concat all strategies failed: %s", _tail(err3, 4000))
                    return None

        with open(out_path, "rb") as f:
            video_bytes = f.read()

        # 延迟 import，避免在缺失 boto3 / settings 的极端环境下挂掉
        from app.utils.storage import upload_bytes

        key = f"videos/concat_{uuid.uuid4()}.mp4"
        return upload_bytes(key, video_bytes, content_type="video/mp4")

    except FileNotFoundError as exc:
        logger.warning("ffmpeg not found, concat skipped: %s", exc)
        return None
    except Exception:
        logger.exception("concat: unexpected error")
        return None
    finally:
        for p in local_paths:
            _safe_unlink(p)
        if list_path:
            _safe_unlink(list_path)
        if out_path:
            _safe_unlink(out_path)


# aspect → 目标分辨率（保高宽较短一边为 1080，行业惯例）
ASPECT_TARGET_RES: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "4:5":  (1080, 1350),
    "1:1":  (1080, 1080),
    "4:3":  (1440, 1080),
}


def aspect_target_resolution(aspect: str) -> Optional[tuple[int, int]]:
    """把 `9:16` / `16:9` / `4:5` / `1:1` / `4:3` 等映射到目标 (W, H)；不识别返回 None。"""

    return ASPECT_TARGET_RES.get(aspect.strip())


# aspect → 字幕样式参数（v5：每个 aspect 走不同字号 / 边距）
# 设计依据：
# - 9:16（竖屏，TikTok / 抖音 / Reels）：屏幕窄，单行字数少 → 字号大 + MarginV 高（避开
#   底部 UI 「点赞 / 评论 / 分享」+ 顶部「关注 / 描述」叠加层）
# - 4:5（小红书 / Instagram portrait）：比 9:16 略宽，但底部仍有平台 UI
# - 1:1（Instagram 方屏）：字号介于 9:16 与 16:9 之间
# - 16:9（YouTube / B 站横屏）：保持 v4 既有 Fontsize=24 / MarginV=72，行业惯例
# - 4:3（旧 TV / 中视频）：与 16:9 类同
# Outline / Shadow：竖屏背景往往更复杂（人物特写多），加粗描边 + 阴影提升对比度
ASPECT_SUBTITLE_STYLE: dict[str, dict[str, int]] = {
    "9:16": {"font_size": 44, "margin_v": 220, "outline": 3, "shadow": 1},
    "4:5":  {"font_size": 36, "margin_v": 180, "outline": 3, "shadow": 1},
    "1:1":  {"font_size": 32, "margin_v": 90,  "outline": 2, "shadow": 0},
    "16:9": {"font_size": 24, "margin_v": 72,  "outline": 2, "shadow": 0},
    "4:3":  {"font_size": 24, "margin_v": 72,  "outline": 2, "shadow": 0},
}
DEFAULT_SUBTITLE_STYLE = ASPECT_SUBTITLE_STYLE["16:9"]


def build_subtitle_force_style(
    aspect: Optional[str],
    *,
    font_name: Optional[str] = None,
    scale: float = 1.0,
) -> tuple[str, dict[str, Any]]:
    """生成 ffmpeg `subtitles=...:force_style='...'` 中那段 force_style 字串。

    返回 (force_style_str, debug_dict)。debug_dict 暴露给上层（EditAgent.outputs）让前端
    能展示「9:16 用了字号 44 / MarginV 220」之类的调试信息。

    参数
    ----
    aspect : 目标比例字符串；缺省 / 不识别 → 走 16:9 默认
    font_name : 覆盖系统字体；缺省自动选 (`_pick_subtitle_font` 已处理 CJK)
    scale : 用户缩放系数（brief.subtitle_scale），1.0=默认；clamp 到 [0.5, 2.0]
            字号、MarginV、Outline 都按比例缩放；Alignment 不缩
    """

    base = ASPECT_SUBTITLE_STYLE.get(
        (aspect or "").strip(), DEFAULT_SUBTITLE_STYLE
    )
    if scale <= 0:
        scale = 1.0
    scale = max(0.5, min(2.0, float(scale)))

    font = font_name or _pick_subtitle_font()
    font_size = max(12, int(round(base["font_size"] * scale)))
    margin_v = max(8, int(round(base["margin_v"] * scale)))
    outline = max(1, int(round(base["outline"] * scale)))
    shadow = max(0, int(round(base["shadow"] * scale)))

    parts = [
        f"Fontname={font}",
        f"Fontsize={font_size}",
        f"Outline={outline}",
        f"Shadow={shadow}",
        f"MarginV={margin_v}",
        "Alignment=2",  # 2 = bottom center；保持
    ]
    style_str = ",".join(parts)
    debug = {
        "aspect_used": (aspect or "").strip() or "default(16:9)",
        "font_name": font,
        "font_size": font_size,
        "margin_v": margin_v,
        "outline": outline,
        "shadow": shadow,
        "alignment": "bottom_center",
        "scale": round(scale, 3),
    }
    return style_str, debug


def mux_video_with_audio(
    video_url: str,
    audio_url: str,
    *,
    keep_video_audio: bool = False,
    srt_path: Optional[str] = None,
    target_aspect: Optional[str] = None,
    aspect_fit: str = "cover",
    loop_video_to_audio: bool = True,
    subtitle_scale: float = 1.0,
) -> Optional[str]:
    """把 narration 音轨与已拼接视频合成成片；可选硬烧字幕、转目标比例、按旁白循环视频。

    参数
    ----
    keep_video_audio : bool
        - False（默认）：直接替换音轨为旁白
        - True：把旁白与视频原音以 0.9 / 0.3 比例混合（环境音不喧宾夺主）
    srt_path : Optional[str]
        本地 SRT 文件路径；传入则强制重编码视频流并烧入字幕（subtitles 滤镜在 scale 之后，
        字号才不被缩放影响）
    target_aspect : Optional[str]
        目标 aspect，如 `"9:16"` / `"16:9"` / `"4:5"` / `"1:1"` / `"4:3"`；
        缺省（None）保持原视频 aspect。识别不到的值同 None 处理。
    aspect_fit : str
        - `"cover"`（默认）：等比缩放后裁掉多余部分填满目标画幅，无黑边
        - `"contain"`：letterbox 黑边 padding，画面完整不变形
    loop_video_to_audio : bool
        - True（默认，v4 行为）：当 `audio_dur > video_dur` 时用 `-stream_loop -1`
          让视频无缝循环到 audio 时长；`audio_dur <= video_dur` 时按 audio 截短
        - False（v3 行为）：取 `min(video_dur, audio_dur)` 截短；旁白比视频长时旁白末尾被切

    时长策略说明
    -----------
    都用 `-t` 显式截到目标时长；不用 `-shortest`，绕过 ffmpeg 6.0 mp3+libx264 组合下
    `-shortest` 丢 audio 的 bug。

    单次 ffmpeg 失败时按 (主路径 → 重编码 → fallback) 三层降级；都失败返回 None，
    调用方应降级到不混音的视频 URL。
    """
    if not video_url or not audio_url:
        return None

    video_path: str | None = None
    audio_path: str | None = None
    out_path: str | None = None

    try:
        video_path = _download(video_url, suffix=".mp4")
        audio_path = _download(audio_url, suffix=".mp3")
        if not video_path or not audio_path:
            return None

        fd, out_path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)

        target_res = aspect_target_resolution(target_aspect) if target_aspect else None
        # 字幕滤镜：若传 srt_path，强制视频重编码 + subtitles filter（在 scale 之后烧）。
        # v5：force_style 按 target_aspect 走 ASPECT_SUBTITLE_STYLE 表，9:16 字号大 / MarginV 高，
        # 16:9 沿用 v4 的 24/72 参数。subtitle_scale 让 brief 能整体缩放（默认 1.0）。
        vf_subtitles: str | None = None
        if srt_path and os.path.exists(srt_path):
            escaped = _escape_subtitle_path(srt_path)
            style_str, _style_debug = build_subtitle_force_style(
                target_aspect, scale=subtitle_scale
            )
            vf_subtitles = f"subtitles='{escaped}':force_style='{style_str}'"

        # 字幕 + 转 aspect 都需要重编码视频流；都没有时才尝试流复制
        force_reencode = bool(vf_subtitles) or bool(target_res)

        # 决定时长：循环模式下以 audio 为准；否则取 min
        video_duration = _probe_duration(video_path)
        audio_duration = _probe_duration(audio_path)
        loop_input = (
            loop_video_to_audio
            and video_duration is not None
            and audio_duration is not None
            and audio_duration > video_duration + 0.05
        )
        if loop_input:
            clip_duration: Optional[float] = audio_duration
        elif video_duration and audio_duration:
            clip_duration = min(video_duration, audio_duration)
        elif video_duration:
            clip_duration = video_duration
        elif audio_duration:
            clip_duration = audio_duration
        else:
            clip_duration = None

        audio_stage_args: list[str]
        if keep_video_audio:
            audio_stage_args = [
                "-filter_complex",
                "[0:a]volume=0.3[a0];[1:a]volume=0.9[a1];[a0][a1]amix=inputs=2:duration=shortest:dropout_transition=0[aout]",
                "-map", "0:v:0",
                "-map", "[aout]",
            ]
        else:
            audio_stage_args = ["-map", "0:v:0", "-map", "1:a:0"]

        # vf chain 顺序很关键：先 scale → 再 crop/pad → 最后烧字幕
        # 字幕烧在最终分辨率上，字号不被 scale 拉伸/压缩，跨比例视觉一致
        def build_vf(target_res: Optional[tuple[int, int]]) -> Optional[str]:
            parts: list[str] = []
            if target_res:
                w, h = target_res
                if aspect_fit == "contain":
                    parts.append(
                        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"
                    )
                else:  # cover（默认）：等比放大后裁掉超出部分
                    parts.append(
                        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                        f"crop={w}:{h}"
                    )
                # 强制 SAR=1:1，避免某些播放器按 DAR 又拉伸一次
                parts.append("setsar=1")
            if vf_subtitles:
                parts.append(vf_subtitles)
            return ",".join(parts) if parts else None

        def build_args(reencode_video: bool) -> list[str]:
            args = [
                "ffmpeg", "-hide_banner", "-y",
            ]
            # `-stream_loop -1` 必须在 `-i video` 之前，对该输入生效
            if loop_input:
                args += ["-stream_loop", "-1"]
            args += ["-i", video_path]
            args += ["-i", audio_path]
            args += [*audio_stage_args]
            if reencode_video:
                vf = build_vf(target_res)
                args += ["-c:v", "libx264", "-preset", "fast", "-crf", "23",
                         "-pix_fmt", "yuv420p"]
                if vf:
                    args += ["-vf", vf]
            else:
                args += ["-c:v", "copy"]
            args += ["-c:a", "aac", "-b:a", "192k"]
            if clip_duration:
                args += ["-t", f"{clip_duration:.3f}"]
            args += ["-movflags", "+faststart", out_path]
            return args

        # 主路径：force_reencode 时直接重编码；否则先尝试流复制
        proc = subprocess.run(
            build_args(reencode_video=force_reencode),
            capture_output=True,
            timeout=1200,
        )
        ok = (
            proc.returncode == 0
            and os.path.exists(out_path)
            and os.path.getsize(out_path) > 0
        )
        if not ok and not force_reencode:
            logger.info(
                "mux copy failed (keep_video_audio=%s); reencoding: %s",
                keep_video_audio,
                _tail(proc.stderr),
            )
            proc2 = subprocess.run(
                build_args(reencode_video=True),
                capture_output=True,
                timeout=1500,
            )
            ok = (
                proc2.returncode == 0
                and os.path.exists(out_path)
                and os.path.getsize(out_path) > 0
            )
            if not ok:
                logger.error("mux reencode also failed: %s", _tail(proc2.stderr, 4000))
        if not ok:
            if force_reencode:
                logger.error(
                    "mux failed (loop=%s, target_aspect=%s, fit=%s, burn_subs=%s): %s",
                    loop_input,
                    target_aspect,
                    aspect_fit,
                    bool(vf_subtitles),
                    _tail(proc.stderr, 4000),
                )
            return None

        with open(out_path, "rb") as f:
            video_bytes = f.read()

        from app.utils.storage import upload_bytes  # 延迟 import

        # 文件名带 aspect / 是否烧字幕，方便对账
        prefix_parts = []
        if vf_subtitles:
            prefix_parts.append("burned")
        else:
            prefix_parts.append("muxed")
        if target_aspect:
            prefix_parts.append(target_aspect.replace(":", "x"))
        prefix = "_".join(prefix_parts) + "_"
        key = f"videos/{prefix}{uuid.uuid4()}.mp4"
        return upload_bytes(key, video_bytes, content_type="video/mp4")

    except FileNotFoundError as exc:
        logger.warning("ffmpeg not found, mux skipped: %s", exc)
        return None
    except Exception:
        logger.exception("mux: unexpected error")
        return None
    finally:
        for p in (video_path, audio_path, out_path):
            if p:
                _safe_unlink(p)


def _probe_duration(path: str) -> Optional[float]:
    """用 ffprobe 取媒体文件的总时长（秒）；失败返回 None。"""

    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            timeout=15,
        )
        if proc.returncode != 0:
            return None
        out = proc.stdout.decode("utf-8", errors="replace").strip()
        return float(out) if out else None
    except Exception:
        return None


def probe_audio_duration_bytes(audio_bytes: bytes, fmt: str = "mp3") -> Optional[float]:
    """从内存中的音频 bytes 拿到真实播放时长（秒）；失败返回 None。

    用于 VoiceAgent v2：当 ASR provider 没回 duration 时（SiliconFlow SenseVoice
    实测 verbose_json 也不一定带 duration 字段），用 ffprobe 兜底从 TTS 字节里读出
    真实长度，作为字幕重切的纠偏基准。
    """

    if not audio_bytes:
        return None
    suffix = f".{(fmt or 'mp3').lstrip('.')}"
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        return _probe_duration(tmp_path)
    except FileNotFoundError:
        logger.warning("ffprobe not found, probe_audio_duration_bytes skipped")
        return None
    except Exception:
        logger.exception("probe_audio_duration_bytes failed")
        return None
    finally:
        if tmp_path:
            _safe_unlink(tmp_path)


def _pick_subtitle_font() -> str:
    """选择当前平台 libass 能找到、且含 CJK glyph 的字体名。

    实测：
    - macOS：`Hiragino Sans GB`（位于 `/System/Library/Fonts/Hiragino Sans GB.ttc`）系统自带且 libass 可见
    - Linux：`Noto Sans CJK SC` 是几乎所有发行版可装的标准字体；其它发行版也可手动安装
    - 找不到时退到 `Sans`（libass 默认），中文会渲染成豆腐块，但至少不报错

    可由 `EDIT_SUBTITLE_FONT` 环境变量覆盖。
    """
    env_override = os.environ.get("EDIT_SUBTITLE_FONT")
    if env_override:
        return env_override
    if os.path.exists("/System/Library/Fonts/Hiragino Sans GB.ttc"):
        return "Hiragino Sans GB"
    if os.path.exists("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
        return "Noto Sans CJK SC"
    return "Sans"


def _escape_subtitle_path(path: str) -> str:
    """ffmpeg 滤镜参数里 `:` 与 `'` 是分隔符，必须转义；Windows 盘符的 `C:` 也需处理。

    macOS / Linux 下路径多半没有 `:`，但保险起见仍统一处理。
    """
    return (
        path.replace("\\", "\\\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
    )


def _download(url: str, *, suffix: str) -> Optional[str]:
    """把远端 URL 拉到本地临时文件；失败返回 None。"""

    try:
        r = requests.get(url, timeout=120, stream=True)
        if r.status_code != 200:
            logger.warning("download failed url=%s status=%s", url[:80], r.status_code)
            return None
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
            return f.name
    except Exception:
        logger.exception("download: unexpected error")
        return None


def extract_last_frame(video_url: str) -> Optional[str]:
    """下载视频并用 ffmpeg 抽取最后一帧，返回 base64 data URL。

    用途：风格延续 / image2video 的参考帧。
    """
    video_path: str | None = None
    frame_path: str | None = None

    try:
        resp = requests.get(video_url, timeout=120, stream=True)
        if resp.status_code != 200:
            return None

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as vf:
            for chunk in resp.iter_content(8192):
                vf.write(chunk)
            video_path = vf.name

        frame_path = video_path.replace(".mp4", "_frame.jpg")
        proc = subprocess.run(
            [
                "ffmpeg", "-sseof", "-1", "-i", video_path,
                "-update", "1", "-q:v", "2", "-y", frame_path,
            ],
            capture_output=True,
            timeout=30,
        )
        if proc.returncode != 0 or not os.path.exists(frame_path):
            return None

        with open(frame_path, "rb") as f:
            img_data = f.read()
        return "data:image/jpeg;base64," + base64.b64encode(img_data).decode()

    except FileNotFoundError:
        logger.warning("ffmpeg not found, extract_last_frame skipped")
        return None
    except Exception:
        logger.exception("extract_last_frame failed")
        return None
    finally:
        if video_path:
            _safe_unlink(video_path)
        if frame_path:
            _safe_unlink(frame_path)


# ── helpers ──────────────────────────────────────────────────────────────────


def _write_concat_list(paths: list[str]) -> str:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
    try:
        for p in paths:
            safe = os.path.normpath(p).replace("\\", "/")
            tmp.write(f"file '{safe}'\n")
        return tmp.name
    finally:
        tmp.close()


def _try_ffmpeg(concat_list: str, output: str, args_after_input: list[str]) -> tuple[bool, bytes]:
    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_list,
        *args_after_input, output,
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=600)
    return proc.returncode == 0 and os.path.exists(output), proc.stderr


def _tail(err: bytes | None, n: int = 2000) -> str:
    if not err:
        return ""
    return err.decode("utf-8", errors="replace")[-n:]


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except Exception:
        pass
