"""VoiceAgent v4 — 字幕对齐 + 行级细切 + word-level 强对齐

字幕对齐版本演进
----------------
- v1: 按 shots.duration_s 之和累加，每镜 1 条字幕；不调 ASR
- v2: 按 ASR/ffprobe 拿真实 audio_duration → 按 shot.narration 字符占比重切；每镜仍 1 条
- v3: 在 v2 基础上，每个 shot 按标点（。！？ 主切 + ，； 兜底）切成多条，每条按字符占比再分时间
       → 字幕粒度从 shot-level 变成 line-level，更符合阅读节奏（每条 ~10-20 字 / 1-3s）
- v4: 当 ASR 返 word-level timestamps（OpenAI Whisper-1 / faster-whisper）时，
       按 word 边界做强对齐：每条 line 的 start/end 用真实 word 起止替换字符比例估算，
       同时给每条 line 挂 `words: [{start, end, word}]` 让前端做卡拉 OK 高亮。
       SiliconFlow SenseVoice 仍不返 word，自动降级到 v3。

输入
----
- 上游 ScriptAgent 的 outputs（`script` 整段口播 + 每镜 `narration` + `duration_s`）
- Brief 中可选 `voice` / `voice_model` / `voice_speed` / `subtitle_max_chars` (默认 20)

输出
----
- `narration_url`         : 整段旁白 mp3 公开 URL
- `voice` / `voice_model` : TTS voice ref / 模型
- `subtitles`             : [{index, start, end, text, shot_index}]，v3 一镜可多条
- `total_duration_s`      : subtitles 末端 end（与真实音频时长基本一致）
- `audio_duration_s`      : 真实音频时长（ASR / ffprobe），可能与 shots 之和差很多
- `aligned`               : 是否用 ASR/ffprobe 拿到真实时长重切
- `subtitle_granularity`  : 'word' (v4 word 强对齐) / 'line' (v3 行级) / 'shot' (v2 镜级) / 'merged' (v1 兜底)
- `subtitle_lines_per_shot`: list[int]，每镜实际产生的字幕条数
- `subtitle_alignment_quality`: 'word' / 'segment' / 'char-ratio' / 'shots-duration'
       —— 对齐精度档位，前端徽标的实际依据
- `subtitles[i].words`     : 仅 word 级时存在，[{start, end, word}]，便于前端卡拉 OK 高亮
- `asr_provider` / `asr_model` / `asr_duration_ms` / `asr_segments_count` / `asr_words_count`
- `char_count`            : 全文字符数，用于 metric
- `align_warning`         : 对齐降级原因（仅退化场景写入）

设计取舍
--------
- 一次合成整段 + 一次 ASR：减少调用数，且整段语调更自然
- ASR 路径：ASR.duration > ffprobe(audio_bytes) > shots.duration_s 之和
- 行级细切只在 ASR/ffprobe 拿到真实时长后启用；否则保持 shot-level v2 / v1 行为
- subtitle_max_chars 默认 20（中文常见字幕宽度），过短反而切碎；用 brief 覆盖
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any, Optional

from app.config import get_settings
from app.services.media import probe_audio_duration_bytes
from app.services.model_gateway import ModelAction, RenderRequest, get_gateway

from ..types import PipelineContext, Step, StepResult, StepStatus, register_agent

logger = logging.getLogger(__name__)


# 默认每条字幕最多多少字符（中文）；shot 内行级切分时使用
DEFAULT_SUBTITLE_MAX_CHARS = 20


@register_agent("voice")
class VoiceAgent(Step):
    def estimate_cost_usd(self, ctx: PipelineContext) -> float:
        text = _full_narration(ctx)
        chars = len(text)
        # SiliconFlow Fish-Speech / CosyVoice 估价 ≈ $0.05 / 1k chars
        tts_cost = 0.05 * (chars / 1000.0)
        # ASR 估价：按 240 字/分钟换算分钟数 × $0.001/min（SenseVoice）
        asr_minutes = max(1.0, chars / 240.0) / 60.0 if chars else 0.0
        asr_cost = 0.001 * asr_minutes
        return round(tts_cost + asr_cost, 6)

    def run(self, ctx: PipelineContext) -> StepResult:  # noqa: D401
        script_out = ctx.upstream_outputs.get("script") or {}
        full_text = _full_narration(ctx)
        shots = [s for s in (script_out.get("shots") or []) if isinstance(s, dict)]

        if not full_text:
            return StepResult(
                status=StepStatus.FAILED,
                error="voice: missing script text from upstream",
            )

        brief = (ctx.inputs or {}).get("brief") or {}
        voice_ref = (brief.get("voice") or "").strip()
        model_hint = (brief.get("voice_model") or "").strip() or None
        try:
            max_chars = int(brief.get("subtitle_max_chars") or DEFAULT_SUBTITLE_MAX_CHARS)
        except Exception:
            max_chars = DEFAULT_SUBTITLE_MAX_CHARS
        max_chars = max(8, min(60, max_chars))  # 防极端值

        gateway = get_gateway()
        request = RenderRequest(
            action=ModelAction.TTS,
            params={
                "text": full_text,
                "voice": voice_ref or None,
                "speed": float(brief.get("voice_speed") or 1.0),
                "format": "mp3",
            },
            user_id=ctx.user_id,
            file_id=ctx.file_id,
            pipeline_step_id=ctx.step_id,
            model_hint=model_hint,
            timeout_s=120.0,
        )
        result = gateway.run(request)

        narration_url: Optional[str] = None
        used_voice: Optional[str] = None
        used_model: Optional[str] = result.model
        audio_bytes: Optional[bytes] = None

        if result.ok and isinstance(result.output, dict):
            raw_audio = result.output.get("audio_bytes")
            used_voice = result.output.get("voice")
            if isinstance(raw_audio, (bytes, bytearray)) and raw_audio:
                audio_bytes = bytes(raw_audio)
                narration_url = _upload_audio(audio_bytes)

        # ── v3 字幕对齐 + 行级细切 ────────────────────────────────────────
        align_info = _align_subtitles(
            ctx=ctx,
            shots=shots,
            full_text=full_text,
            audio_bytes=audio_bytes,
            max_chars_per_line=max_chars,
        )
        subtitles = align_info["subtitles"]
        total_duration = align_info["total_duration_s"]

        outputs: dict[str, Any] = {
            "narration_url": narration_url,
            "voice": used_voice,
            "voice_model": used_model,
            "subtitles": subtitles,
            "total_duration_s": total_duration,
            "char_count": len(full_text),
            "audio_duration_s": align_info["audio_duration_s"],
            "aligned": align_info["aligned"],
            "asr_provider": align_info["asr_provider"],
            "asr_model": align_info["asr_model"],
            "asr_duration_ms": align_info["asr_duration_ms"],
            "asr_segments_count": align_info["asr_segments_count"],
            "alignment_source": align_info["alignment_source"],
            "subtitle_granularity": align_info["subtitle_granularity"],
            "subtitle_lines_per_shot": align_info["subtitle_lines_per_shot"],
            "subtitle_max_chars": max_chars,
        }
        if align_info["warning"]:
            outputs["align_warning"] = align_info["warning"]

        if not result.ok:
            outputs["warning"] = result.error or "voice synthesis failed; no audio produced"
            logger.warning("VoiceAgent degraded: %s", outputs["warning"])

        cost = result.cost_usd + (align_info["asr_cost_usd"] or 0.0)

        return StepResult(
            status=StepStatus.SUCCEEDED,
            outputs=outputs,
            cost_usd=cost,
        )


# ── helpers ──────────────────────────────────────────────────────────────────


def _full_narration(ctx: PipelineContext) -> str:
    """优先用 ScriptAgent.script（整段口播）；缺失则按 shots.narration 拼。"""

    script_out = ctx.upstream_outputs.get("script") or {}
    full = str(script_out.get("script") or "").strip()
    if full:
        return full

    shots = script_out.get("shots") or []
    parts = [str(s.get("narration") or "").strip() for s in shots if isinstance(s, dict)]
    return " ".join(p for p in parts if p)


def _align_subtitles(
    *,
    ctx: PipelineContext,
    shots: list[dict[str, Any]],
    full_text: str,
    audio_bytes: Optional[bytes],
    max_chars_per_line: int,
) -> dict[str, Any]:
    """v3 主对齐入口：返回 subtitles + 调试 / metric 字段。

    步骤：
    1. 没有音频字节 → 没法 ASR / 没法 ffprobe → 走 v1 (按 shots.duration_s 均分)
    2. 调 ASR → 拿到 `duration_s` + 可选 segments；duration 缺失则 ffprobe 兜底
    3. 用真实音频时长按字符占比为每个 shot 重新映射 start/end
    4. v3：每个 shot 内部再按标点切成多条字幕，按字符占比再分时间
    5. 全部失败时回退 v1
    """

    info: dict[str, Any] = {
        "subtitles": [],
        "total_duration_s": 0.0,
        "audio_duration_s": None,
        "aligned": False,
        "asr_provider": None,
        "asr_model": None,
        "asr_duration_ms": 0,
        "asr_segments_count": 0,
        "asr_words_count": 0,  # v4：word-level timestamp 数量
        "asr_cost_usd": 0.0,
        "alignment_source": "shots_duration",  # shots_duration / asr / ffprobe
        "subtitle_granularity": "merged",  # merged (v1) / shot (v2) / line (v3) / word (v4)
        "subtitle_alignment_quality": "shots-duration",
        "subtitle_lines_per_shot": [],
        "warning": None,
    }

    if not audio_bytes:
        # TTS 没出音频：v1 均分
        subs, total = _build_subtitles_v1(shots, full_text)
        info.update(subtitles=subs, total_duration_s=total)
        info["subtitle_lines_per_shot"] = [1] * len(subs) if subs else []
        return info

    audio_duration_s: Optional[float] = None
    asr_words: list[dict[str, Any]] = []  # v4：OpenAI Whisper-1 词级 timestamp

    # ── 1. 调 ASR ────────────────────────────────────────────────────────
    try:
        gateway = get_gateway()
        asr_started = time.time()
        asr_req = RenderRequest(
            action=ModelAction.ASR,
            params={
                "audio_bytes": audio_bytes,
                "audio_format": "mp3",
                "response_format": "verbose_json",
                "duration_minutes": max(1.0, len(full_text) / 240.0) / 60.0,
            },
            user_id=ctx.user_id,
            file_id=ctx.file_id,
            pipeline_step_id=ctx.step_id,
            timeout_s=60.0,
        )
        asr_result = gateway.run(asr_req)
        info["asr_duration_ms"] = int((time.time() - asr_started) * 1000)
        info["asr_provider"] = (
            asr_result.provider.value if asr_result.provider else None
        )
        info["asr_model"] = asr_result.model
        info["asr_cost_usd"] = float(asr_result.cost_usd or 0.0)

        if asr_result.ok and isinstance(asr_result.output, dict):
            audio_duration_s = asr_result.output.get("duration_s")
            segments = asr_result.output.get("segments") or []
            if isinstance(segments, list):
                info["asr_segments_count"] = len(segments)
            words_raw = asr_result.output.get("words") or []
            if isinstance(words_raw, list):
                # 标准化（OpenAI provider 已经做过；防御性 sanitize）
                asr_words = [
                    w for w in words_raw
                    if isinstance(w, dict)
                    and isinstance(w.get("start"), (int, float))
                    and isinstance(w.get("end"), (int, float))
                    and float(w["end"]) > float(w["start"])
                    and (w.get("word") or w.get("text"))
                ]
                info["asr_words_count"] = len(asr_words)
            if audio_duration_s:
                info["alignment_source"] = "asr"
        else:
            info["warning"] = (
                "asr failed: " + (asr_result.error or "unknown error")
            )[:200]
    except Exception as exc:  # pragma: no cover - 兜底，不阻断 voice
        logger.exception("voice: ASR call raised")
        info["warning"] = f"asr exception: {exc}"[:200]

    # ── 2. duration 缺失 → ffprobe 兜底 ──────────────────────────────────
    if not audio_duration_s:
        probed = probe_audio_duration_bytes(audio_bytes, fmt="mp3")
        if probed and probed > 0:
            audio_duration_s = probed
            info["alignment_source"] = "ffprobe"

    # word-level：如果 words 全部完整覆盖到 audio_duration，且最后一个 word.end > audio_duration*0.7，认为可信
    # 否则即使有 words 也不进 v4，避免 ASR 截尾导致最后几条字幕异常
    word_aligned_eligible = bool(
        asr_words
        and audio_duration_s
        and audio_duration_s > 0
        and float(asr_words[-1]["end"]) >= audio_duration_s * 0.7
    )

    info["audio_duration_s"] = (
        round(audio_duration_s, 3) if audio_duration_s else None
    )

    # ── 3a. v4 word-level 强对齐（仅当有可信 words） ─────────────────────
    if word_aligned_eligible and shots:
        try:
            subs, lines_per_shot = _build_subtitles_v4_word_aligned(
                shots=shots,
                words=asr_words,
                audio_duration_s=float(audio_duration_s),
                max_chars_per_line=max_chars_per_line,
            )
        except Exception:  # pragma: no cover - word 对齐异常时降级 v3
            logger.exception("voice: v4 word-align failed; falling back to v3")
            subs, lines_per_shot = [], []
        if subs:
            info["subtitles"] = subs
            info["total_duration_s"] = subs[-1]["end"]
            info["aligned"] = True
            info["subtitle_lines_per_shot"] = lines_per_shot
            info["subtitle_granularity"] = "word"
            info["subtitle_alignment_quality"] = "word"
            return info

    # ── 3b. v3 行级（按字符比例） ─────────────────────────────────────────
    if audio_duration_s and audio_duration_s > 0 and shots:
        subs, lines_per_shot = _rescale_subtitles_v3(
            shots, audio_duration_s, max_chars_per_line
        )
        if subs:
            info["subtitles"] = subs
            info["total_duration_s"] = subs[-1]["end"]
            info["aligned"] = True
            info["subtitle_lines_per_shot"] = lines_per_shot
            info["subtitle_granularity"] = (
                "line" if any(c > 1 for c in lines_per_shot) else "shot"
            )
            info["subtitle_alignment_quality"] = "char-ratio"
            return info

    # ── 4. 全部失败 → v1 均分 ─────────────────────────────────────────────
    subs, total = _build_subtitles_v1(shots, full_text)
    info["subtitles"] = subs
    info["total_duration_s"] = total
    info["subtitle_lines_per_shot"] = [1] * len(subs) if subs else []
    return info


def _build_subtitles_v4_word_aligned(
    shots: list[dict[str, Any]],
    words: list[dict[str, Any]],
    audio_duration_s: float,
    max_chars_per_line: int,
) -> tuple[list[dict[str, Any]], list[int]]:
    """v4：用 ASR word-level timestamps 强对齐每条字幕的 start/end，并挂 line.words。

    算法（按字符比例做 origin↔asr 文本映射，避开两端文本不完全一致的问题）：
    1. 用 v3 的逻辑切出每个 shot 的 lines（保持 v3 切分质量）
    2. 把所有 line.text 拼成 origin_text；记录每条 line 在 origin_text 中的 [O_s, O_e]
    3. 把 ASR words 按时间序拼成 asr_text；每个 word 占用 [W_char_s, W_char_e]
    4. 对每条 line：origin char range 按比例映射到 asr_text → [A_s, A_e]
       找出 char range 与 [A_s, A_e] 有重叠（>=1 char）的所有 words
       line.start = first_overlap_word.start
       line.end   = last_overlap_word.end
       line.words = 该子集（前端可做 word-by-word 高亮）
    5. 边界：第一条 start 强制为 0；最后一条 end 强制为 audio_duration_s
       （ASR 偶尔会在尾部漏 word，避免最后字幕断在中间）
    6. 单调性：保证 line[i].end <= line[i+1].start；如果重叠，把 mid 取均值矫正

    退化：words 太少（< 总 lines 的一半）→ 返回 [] 让 caller 降级 v3
    """
    if not shots or not words or audio_duration_s <= 0:
        return [], []

    # Step 1: v3 切 lines；同时记录 (shot_index, line_text) 顺序
    items: list[tuple[int, str]] = []  # (shot_index, line_text)
    lines_per_shot: list[int] = []
    for i, shot in enumerate(shots):
        narration = str(shot.get("narration") or "").strip()
        shot_index = int(shot.get("index") or i + 1)
        lines = _split_narration_into_lines(narration, max_chars_per_line)
        if not lines:
            items.append((shot_index, ""))  # 空镜占位，与 v3 行为一致
            lines_per_shot.append(1)
            continue
        for line in lines:
            items.append((shot_index, line))
        lines_per_shot.append(len(lines))

    if not items:
        return [], []

    # 早退：words 太少（粗略：< lines / 2，且 < 5 时直接降级）
    if len(words) < max(5, len(items) // 2):
        return [], []

    # Step 2: origin_text + 每 line 的 char range
    origin_text_parts: list[str] = []
    line_origin_ranges: list[tuple[int, int]] = []
    cursor = 0
    for _, line in items:
        text = line  # 已 strip
        origin_text_parts.append(text)
        line_origin_ranges.append((cursor, cursor + len(text)))
        cursor += len(text)
    origin_total = cursor or 1  # 防 0

    # Step 3: asr_text + 每 word 的 char range
    asr_word_chars: list[tuple[int, int, dict[str, Any]]] = []  # (s, e, word_obj)
    pos = 0
    for w in words:
        text = str(w.get("word") or w.get("text") or "")
        if not text:
            continue
        asr_word_chars.append((pos, pos + len(text), w))
        pos += len(text)
    asr_total = pos or 1

    if not asr_word_chars:
        return [], []

    # 健康检查：asr_total 与 origin_total 比例严重失调 → 降级 v3
    ratio = asr_total / origin_total
    if ratio < 0.4 or ratio > 2.5:
        return [], []

    # Step 4: 每条 line 找重叠 words
    out: list[dict[str, Any]] = []
    counter = 0
    for (shot_index, text), (o_s, o_e) in zip(items, line_origin_ranges):
        counter += 1
        if o_s >= o_e:
            # 空镜占位：用其前一条的 end 作为 start，无 words
            prev_end = out[-1]["end"] if out else 0.0
            out.append({
                "index": counter,
                "start": prev_end,
                "end": prev_end,  # 后续会被边界约束 / 单调性矫正
                "text": "",
                "shot_index": shot_index,
                "words": [],
            })
            continue

        a_s = int(round(o_s / origin_total * asr_total))
        a_e = int(round(o_e / origin_total * asr_total))
        a_s = max(0, min(a_s, asr_total - 1))
        a_e = max(a_s + 1, min(a_e, asr_total))

        overlapped = [
            w for (ws, we, w) in asr_word_chars
            if not (we <= a_s or ws >= a_e)
        ]

        if not overlapped:
            # 找不到重叠 → 这条 line 退化用比例估算时间（保持有 start/end，但 words 为空）
            ts_start = (o_s / origin_total) * audio_duration_s
            ts_end = (o_e / origin_total) * audio_duration_s
            out.append({
                "index": counter,
                "start": round(ts_start, 3),
                "end": round(ts_end, 3),
                "text": text,
                "shot_index": shot_index,
                "words": [],
            })
            continue

        first_w, last_w = overlapped[0], overlapped[-1]
        line_start = float(first_w["start"])
        line_end = float(last_w["end"])
        out.append({
            "index": counter,
            "start": round(line_start, 3),
            "end": round(line_end, 3),
            "text": text,
            "shot_index": shot_index,
            "words": [
                {
                    "start": round(float(w["start"]), 3),
                    "end": round(float(w["end"]), 3),
                    "word": str(w.get("word") or w.get("text") or ""),
                }
                for w in overlapped
            ],
        })

    # Step 5: 边界规整
    if out:
        out[0]["start"] = 0.0
        out[-1]["end"] = round(audio_duration_s, 3)

    # Step 6: 单调性矫正（相邻 line 重叠或乱序时取中点）
    for i in range(len(out) - 1):
        cur, nxt = out[i], out[i + 1]
        if cur["end"] > nxt["start"]:
            mid = round((cur["end"] + nxt["start"]) / 2.0, 3)
            cur["end"] = mid
            nxt["start"] = mid
        # 同时保证每条 line 自身 end >= start
        if cur["end"] < cur["start"]:
            cur["end"] = cur["start"]
    # 最后一条
    if out and out[-1]["end"] < out[-1]["start"]:
        out[-1]["end"] = out[-1]["start"]

    return out, lines_per_shot


def _rescale_subtitles_v3(
    shots: list[dict[str, Any]],
    audio_duration_s: float,
    max_chars_per_line: int,
) -> tuple[list[dict[str, Any]], list[int]]:
    """v3：先按字符占比把 audio_duration 分配给 shot，再在 shot 内按标点切成多行
    并按行字符占比线性分配该 shot 的时间块。

    返回 (subtitles, lines_per_shot)：
    - subtitles 每条带 `shot_index`，便于前端按镜头分组高亮
    - lines_per_shot 每镜实际字幕条数（用于前端徽标 / metric）
    """

    if not shots or audio_duration_s <= 0:
        return [], []

    # shot 权重 = max(1, len(narration))，避免空镜分到 0 时长
    shot_weights = [max(1, len(str(s.get("narration") or "").strip())) for s in shots]
    total_weight = sum(shot_weights)

    out: list[dict[str, Any]] = []
    lines_per_shot: list[int] = []
    cursor = 0.0
    counter = 0
    for i, shot in enumerate(shots):
        share = shot_weights[i] / total_weight
        shot_dur = audio_duration_s * share
        shot_start = cursor
        shot_end = (
            cursor + shot_dur if i < len(shots) - 1 else audio_duration_s
        )
        cursor = shot_end

        narration = str(shot.get("narration") or "").strip()
        shot_index = int(shot.get("index") or i + 1)
        lines = _split_narration_into_lines(narration, max_chars_per_line)
        if not lines:
            # 纯空镜：保留一条空字幕占位，避免 EditAgent 字幕轨缺一段
            counter += 1
            out.append({
                "index": counter,
                "start": round(shot_start, 3),
                "end": round(shot_end, 3),
                "text": "",
                "shot_index": shot_index,
            })
            lines_per_shot.append(1)
            continue

        line_weights = [max(1, len(line)) for line in lines]
        line_total = sum(line_weights)
        line_cursor = shot_start
        for j, line in enumerate(lines):
            counter += 1
            line_share = line_weights[j] / line_total
            line_dur = shot_dur * line_share
            line_start = line_cursor
            line_end = (
                line_cursor + line_dur if j < len(lines) - 1 else shot_end
            )
            line_cursor = line_end
            out.append({
                "index": counter,
                "start": round(line_start, 3),
                "end": round(line_end, 3),
                "text": line,
                "shot_index": shot_index,
            })
        lines_per_shot.append(len(lines))

    return out, lines_per_shot


# 主分隔符：句末标点 → 必切；保留标点在前一段末尾
_STRONG_SPLIT_RE = re.compile(r"(?<=[。！？!?])")
# 弱分隔符：在 strong 切完后，若某段仍超过 max_chars_per_line，再用这个切
_WEAK_SPLIT_RE = re.compile(r"(?<=[，；、,;])")


def _split_narration_into_lines(text: str, max_chars: int) -> list[str]:
    """把一段 narration 按标点切成若干字幕行。

    算法：
    1. 先按句末标点（。！？!?）切成多段
    2. 对每段长度 > max_chars 的，再按弱标点（，；、,;）细切
    3. 仍 > max_chars 的，按 max_chars 硬切（保险，防止失控）
    4. 末尾留容忍：1.3 * max_chars 以内不强切，避免最后一段过短
    """

    s = (text or "").strip()
    if not s:
        return []

    # Step 1: strong split
    parts: list[str] = [p.strip() for p in _STRONG_SPLIT_RE.split(s) if p.strip()]
    if not parts:
        parts = [s]

    # Step 2: 对超长 part 用弱分隔符再切
    refined: list[str] = []
    for part in parts:
        if len(part) <= max_chars:
            refined.append(part)
            continue
        chunks = [c.strip() for c in _WEAK_SPLIT_RE.split(part) if c.strip()]
        if len(chunks) <= 1:
            # 弱标点也切不开，直接 hard-wrap
            refined.extend(_hard_wrap(part, max_chars))
            continue
        # 把碎片合并到不超 max_chars 的窗口里，避免过度切碎
        buf = ""
        for chunk in chunks:
            if not buf:
                buf = chunk
                continue
            if len(buf) + len(chunk) <= int(max_chars * 1.3):
                buf = buf + chunk
            else:
                if len(buf) > max_chars:
                    refined.extend(_hard_wrap(buf, max_chars))
                else:
                    refined.append(buf)
                buf = chunk
        if buf:
            if len(buf) > max_chars:
                refined.extend(_hard_wrap(buf, max_chars))
            else:
                refined.append(buf)

    # Step 3: 合并极短行（< 0.4*max）到下一行，避免「一字一条」
    min_chars = max(4, int(max_chars * 0.4))
    merged: list[str] = []
    for line in refined:
        if merged and len(merged[-1]) < min_chars:
            merged[-1] = merged[-1] + line
        else:
            merged.append(line)
    return merged


def _hard_wrap(text: str, max_chars: int) -> list[str]:
    """没有标点可用时，按 max_chars 硬切；最后一段允许 < max_chars。"""

    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]


def _build_subtitles_v1(
    shots: list[dict[str, Any]], full_text: str
) -> tuple[list[dict[str, Any]], float]:
    """v1 fallback：按 shots.duration_s 累加得到字幕轨；缺 shots 时把全文当作单条字幕。"""

    if not shots:
        est_duration = max(1.0, len(full_text) / 4.0)
        return (
            [
                {
                    "index": 1,
                    "start": 0.0,
                    "end": round(est_duration, 2),
                    "text": full_text,
                    "shot_index": 1,
                }
            ],
            est_duration,
        )

    cursor = 0.0
    subs: list[dict[str, Any]] = []
    for shot in shots:
        dur = float(shot.get("duration_s") or 4.0)
        text = str(shot.get("narration") or "").strip()
        subs.append(
            {
                "index": int(shot.get("index") or len(subs) + 1),
                "start": round(cursor, 2),
                "end": round(cursor + dur, 2),
                "text": text,
                "shot_index": int(shot.get("index") or len(subs) + 1),
            }
        )
        cursor += dur
    return subs, round(cursor, 2)


def _upload_audio(audio_bytes: bytes) -> Optional[str]:
    """上传到 S3/R2，没配 S3 时落地到本地 static/videos/ 兜底目录。"""

    try:
        from app.utils.storage import upload_bytes

        if get_settings().s3_access_key:
            key = f"audio/voice_{uuid.uuid4()}.mp3"
        else:
            key = f"voice_{uuid.uuid4()}.mp3"
        return upload_bytes(key, audio_bytes, content_type="audio/mpeg")
    except Exception:
        logger.exception("voice: upload_audio failed")
        return None
