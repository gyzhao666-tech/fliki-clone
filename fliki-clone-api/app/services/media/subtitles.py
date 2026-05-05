"""字幕工具：把 VoiceAgent 输出的 subtitles 序列化成标准 SRT，并能上传成可下载链接。

VoiceAgent 给到的 `subtitles` 形如：
    [
      {"index": 1, "start": 0.0, "end": 3.0, "text": "..."},
      {"index": 2, "start": 3.0, "end": 7.0, "text": "..."},
    ]

我们只关心 start / end / text；index 不用，直接顺序编号，避免 index 重复或缺号导致 SRT 不合规。
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Iterable

logger = logging.getLogger(__name__)


def subtitles_to_srt(subtitles: Iterable[dict[str, Any]] | None) -> str:
    """把 subtitles 列表转 SRT 文本。空输入返回 ""。"""

    if not subtitles:
        return ""

    blocks: list[str] = []
    counter = 0
    for sub in subtitles:
        if not isinstance(sub, dict):
            continue
        text = str(sub.get("text") or "").strip()
        if not text:
            continue
        try:
            start = float(sub.get("start") or 0.0)
            end = float(sub.get("end") or 0.0)
        except Exception:
            continue
        if end <= start:
            # 容忍模糊数据：给一秒默认时长
            end = start + 1.0

        counter += 1
        blocks.append(
            f"{counter}\n"
            f"{_format_timestamp(start)} --> {_format_timestamp(end)}\n"
            f"{text}\n"
        )

    return "\n".join(blocks).strip() + ("\n" if blocks else "")


def upload_srt(srt_text: str) -> str | None:
    """把 SRT 文本上传到 R2 / 本地 static，返回公开 URL。"""

    if not srt_text:
        return None
    try:
        from app.utils.storage import upload_bytes  # 延迟 import：兼容缺 boto3 的极端环境

        key = f"subtitles_{uuid.uuid4()}.srt"
        # 走 static/videos 兜底目录与现有视频/音频共用；S3 配置时按 subtitles/ 命名空间
        from app.config import get_settings

        if get_settings().s3_access_key:
            key = f"subtitles/{key}"
        return upload_bytes(
            key, srt_text.encode("utf-8"), content_type="application/x-subrip"
        )
    except Exception:
        logger.exception("upload_srt failed")
        return None


def _format_timestamp(seconds: float) -> str:
    """SRT 时间格式：HH:MM:SS,mmm"""

    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    s = (total_ms // 1000) % 60
    m = (total_ms // 60_000) % 60
    h = total_ms // 3_600_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
