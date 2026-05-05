"""媒体处理工具集合：ffmpeg 拼接、抽帧、切段。

与 model_gateway 解耦：gateway 负责"调用外部模型生成视频片段"，
services/media 负责"拿到本地/远端 URL 后做 ffmpeg 加工并上传"。
"""
from .ffmpeg import (
    ASPECT_SUBTITLE_STYLE,
    ASPECT_TARGET_RES,
    aspect_target_resolution,
    build_subtitle_force_style,
    concat_video_segments,
    extract_last_frame,
    mux_video_with_audio,
    probe_audio_duration_bytes,
)
from .segments import split_to_sub_segments
from .subtitles import subtitles_to_srt, upload_srt

__all__ = [
    "ASPECT_SUBTITLE_STYLE",
    "ASPECT_TARGET_RES",
    "aspect_target_resolution",
    "build_subtitle_force_style",
    "concat_video_segments",
    "extract_last_frame",
    "mux_video_with_audio",
    "probe_audio_duration_bytes",
    "split_to_sub_segments",
    "subtitles_to_srt",
    "upload_srt",
]
