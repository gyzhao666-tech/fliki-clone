"""Step outputs → 生产元数据表的持久化层。

设计：
- 单一切入点 `persist_step_outputs(run_id, step_id, agent_type, outputs)`
- 按 agent_type 路由到对应 handler；每个 handler 是 idempotent 的（基于 run_id + index 等
  自然键去重，便于单步重跑 / 重新连接）
- 全部用 raw SQL（避免 ORM session lifecycle 在 runner 上下文里出问题）
- 任何异常只 warning，不阻断 step 状态机；新表数据可以由后续重跑修复

handler 责任划分
---------------
- script  : 创建 shot_list（如不存在）+ 创建/更新 shots 行的 narration/visual/camera/duration
- art     : 更新 shot_list 的 style_board/character_cards/aspect_ratio + 更新 shots 的 art 字段
- video   : 更新 shots 的 video 字段（按 index 匹配）
- voice   : 写一条 narration 长度 metric；subtitles 不单独建表（仍由 outputs_json 提供）
- edit    : 删旧 renders + 按 previews_by_aspect 重建多行 renders
- review  : 删旧 reviews + 按 issues 重建
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Optional

from sqlalchemy import create_engine, text

from app.config import get_settings

logger = logging.getLogger(__name__)


def _engine():
    return create_engine(get_settings().database_url_sync)


def persist_step_outputs(
    *,
    run_id: str,
    step_id: str,
    agent_type: str,
    outputs: Optional[dict[str, Any]],
) -> None:
    """根据 agent_type 把 step outputs 写到对应生产表；失败仅 warning。"""

    if not outputs or not isinstance(outputs, dict):
        return

    handler = _HANDLERS.get(agent_type)
    if handler is None:
        return
    try:
        handler(run_id=run_id, step_id=step_id, outputs=outputs)
    except Exception:  # pragma: no cover - persist 失败不阻断主流程
        logger.exception(
            "persist failed: run=%s step=%s agent=%s",
            run_id,
            step_id,
            agent_type,
        )


# ── helpers ──────────────────────────────────────────────────────────────────


def _file_id_for_run(conn, run_id: str) -> Optional[str]:
    row = conn.execute(
        text("SELECT file_id FROM pipeline_runs WHERE id = :rid"), {"rid": run_id}
    ).fetchone()
    return row[0] if row else None


def _existing_shot_list_id(conn, run_id: str) -> Optional[str]:
    row = conn.execute(
        text("SELECT id FROM shot_lists WHERE run_id = :rid LIMIT 1"),
        {"rid": run_id},
    ).fetchone()
    return row[0] if row else None


def _existing_shot_id(conn, run_id: str, index: int) -> Optional[str]:
    row = conn.execute(
        text("SELECT id FROM shots WHERE run_id = :rid AND index = :idx LIMIT 1"),
        {"rid": run_id, "idx": index},
    ).fetchone()
    return row[0] if row else None


def _str(value: Any, max_len: Optional[int] = None) -> Optional[str]:
    if value is None:
        return None
    s = str(value)
    if max_len is not None:
        s = s[:max_len]
    return s


def _dump(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except Exception:
        return default


def _to_int(v: Any, default: int = 0) -> int:
    try:
        return int(v) if v is not None else default
    except Exception:
        return default


# ── handlers ─────────────────────────────────────────────────────────────────


def _persist_script(*, run_id: str, step_id: str, outputs: dict[str, Any]) -> None:
    shots = outputs.get("shots") or []
    with _engine().begin() as conn:
        file_id = _file_id_for_run(conn, run_id)
        sl_id = _existing_shot_list_id(conn, run_id)

        if sl_id is None:
            sl_id = str(uuid.uuid4())
            conn.execute(
                text(
                    "INSERT INTO shot_lists (id, run_id, file_id, title, hook, script, cta, "
                    "topic_json) VALUES "
                    "(:id, :rid, :fid, :title, :hook, :script, :cta, CAST(:topic AS JSON))"
                ),
                {
                    "id": sl_id,
                    "rid": run_id,
                    "fid": file_id,
                    "title": _str(outputs.get("title"), 200),
                    "hook": _str(outputs.get("hook")),
                    "script": _str(outputs.get("script")),
                    "cta": _str(outputs.get("cta")),
                    "topic": _dump(outputs.get("topic")),
                },
            )
        else:
            conn.execute(
                text(
                    "UPDATE shot_lists SET title=:title, hook=:hook, script=:script, "
                    "cta=:cta, topic_json=CAST(:topic AS JSON), updated_at=NOW() "
                    "WHERE id=:id"
                ),
                {
                    "id": sl_id,
                    "title": _str(outputs.get("title"), 200),
                    "hook": _str(outputs.get("hook")),
                    "script": _str(outputs.get("script")),
                    "cta": _str(outputs.get("cta")),
                    "topic": _dump(outputs.get("topic")),
                },
            )

        for i, s in enumerate(shots, start=1):
            if not isinstance(s, dict):
                continue
            idx = _to_int(s.get("index"), i)
            duration_s = _to_float(s.get("duration_s"), 4.0)
            existing = _existing_shot_id(conn, run_id, idx)
            if existing:
                conn.execute(
                    text(
                        "UPDATE shots SET duration_s=:dur, narration=:nar, visual=:vis, "
                        "camera=:cam, updated_at=NOW() WHERE id=:id"
                    ),
                    {
                        "id": existing,
                        "dur": duration_s,
                        "nar": _str(s.get("narration")),
                        "vis": _str(s.get("visual")),
                        "cam": _str(s.get("camera"), 120),
                    },
                )
            else:
                conn.execute(
                    text(
                        "INSERT INTO shots (id, shot_list_id, run_id, index, duration_s, "
                        "narration, visual, camera) VALUES "
                        "(:id, :slid, :rid, :idx, :dur, :nar, :vis, :cam)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "slid": sl_id,
                        "rid": run_id,
                        "idx": idx,
                        "dur": duration_s,
                        "nar": _str(s.get("narration")),
                        "vis": _str(s.get("visual")),
                        "cam": _str(s.get("camera"), 120),
                    },
                )


def _persist_art(*, run_id: str, step_id: str, outputs: dict[str, Any]) -> None:
    style_board = outputs.get("style_board") or {}
    aspect = _str(style_board.get("aspect_ratio"), 8) if isinstance(style_board, dict) else None
    character_cards = outputs.get("character_cards") or []
    shots = outputs.get("shots") or []

    with _engine().begin() as conn:
        file_id = _file_id_for_run(conn, run_id)
        sl_id = _existing_shot_list_id(conn, run_id)
        if sl_id is None:
            # script 之前没建 → 现在建一个最小骨架
            sl_id = str(uuid.uuid4())
            conn.execute(
                text(
                    "INSERT INTO shot_lists (id, run_id, file_id, style_board_json, "
                    "character_cards_json, aspect_ratio) VALUES "
                    "(:id, :rid, :fid, CAST(:sb AS JSON), CAST(:cc AS JSON), :ar)"
                ),
                {
                    "id": sl_id,
                    "rid": run_id,
                    "fid": file_id,
                    "sb": _dump(style_board),
                    "cc": _dump(character_cards),
                    "ar": aspect,
                },
            )
        else:
            conn.execute(
                text(
                    "UPDATE shot_lists SET style_board_json=CAST(:sb AS JSON), "
                    "character_cards_json=CAST(:cc AS JSON), aspect_ratio=:ar, "
                    "updated_at=NOW() WHERE id=:id"
                ),
                {
                    "id": sl_id,
                    "sb": _dump(style_board),
                    "cc": _dump(character_cards),
                    "ar": aspect,
                },
            )

        for i, s in enumerate(shots, start=1):
            if not isinstance(s, dict):
                continue
            idx = _to_int(s.get("index"), i)
            existing = _existing_shot_id(conn, run_id, idx)
            common = {
                "ep": _str(s.get("enhanced_prompt")),
                "np": _str(s.get("negative_prompt")),
                "ar": _str(s.get("aspect_ratio") or aspect, 8),
                "fc": _str(s.get("focus_character"), 80),
                "kf": _str(s.get("keyframe_url")),
                "kp": _str(s.get("keyframe_provider"), 40),
                "km": _str(s.get("keyframe_model"), 120),
                "ks": _str(s.get("keyframe_size"), 40),
                "ke": _str(s.get("keyframe_error")),
            }
            if existing:
                conn.execute(
                    text(
                        "UPDATE shots SET enhanced_prompt=:ep, negative_prompt=:np, "
                        "aspect_ratio=:ar, focus_character=:fc, keyframe_url=:kf, "
                        "keyframe_provider=:kp, keyframe_model=:km, keyframe_size=:ks, "
                        "keyframe_error=:ke, updated_at=NOW() WHERE id=:id"
                    ),
                    {**common, "id": existing},
                )
            else:
                conn.execute(
                    text(
                        "INSERT INTO shots (id, shot_list_id, run_id, index, duration_s, "
                        "narration, visual, camera, enhanced_prompt, negative_prompt, "
                        "aspect_ratio, focus_character, keyframe_url, keyframe_provider, "
                        "keyframe_model, keyframe_size, keyframe_error) VALUES "
                        "(:id, :slid, :rid, :idx, :dur, :nar, :vis, :cam, :ep, :np, "
                        ":ar, :fc, :kf, :kp, :km, :ks, :ke)"
                    ),
                    {
                        **common,
                        "id": str(uuid.uuid4()),
                        "slid": sl_id,
                        "rid": run_id,
                        "idx": idx,
                        "dur": _to_float(s.get("duration_s"), 4.0),
                        "nar": _str(s.get("narration")),
                        "vis": _str(s.get("visual")),
                        "cam": _str(s.get("camera"), 120),
                    },
                )


def _persist_video(*, run_id: str, step_id: str, outputs: dict[str, Any]) -> None:
    shots = outputs.get("shots") or []
    with _engine().begin() as conn:
        for i, s in enumerate(shots, start=1):
            if not isinstance(s, dict):
                continue
            idx = _to_int(s.get("index"), i)
            existing = _existing_shot_id(conn, run_id, idx)
            common = {
                "vu": _str(s.get("video_url")),
                "vp": _str(s.get("provider"), 40),
                "vm": _str(s.get("model"), 120),
                "vmd": _str(s.get("mode"), 40),
                "vc": _to_float(s.get("cost_usd"), 0.0),
                "vd": _to_int(s.get("duration_ms"), 0),
                "vmc": _str(s.get("model_call_id")),
                "ve": _str(s.get("error")),
            }
            if existing:
                conn.execute(
                    text(
                        "UPDATE shots SET video_url=:vu, video_provider=:vp, video_model=:vm, "
                        "video_mode=:vmd, video_cost_usd=:vc, video_duration_ms=:vd, "
                        "video_model_call_id=:vmc, video_error=:ve, updated_at=NOW() "
                        "WHERE id=:id"
                    ),
                    {**common, "id": existing},
                )
            else:
                # video 跑在 art / script 之后，理论上 shots 行已存在；进到这里说明
                # script/art 输出没把这一镜带进 outputs，仍兜底 insert 保数据完整
                file_id = _file_id_for_run(conn, run_id)
                sl_id = _existing_shot_list_id(conn, run_id)
                if sl_id is None:
                    sl_id = str(uuid.uuid4())
                    conn.execute(
                        text(
                            "INSERT INTO shot_lists (id, run_id, file_id) VALUES (:id,:rid,:fid)"
                        ),
                        {"id": sl_id, "rid": run_id, "fid": file_id},
                    )
                conn.execute(
                    text(
                        "INSERT INTO shots (id, shot_list_id, run_id, index, duration_s, "
                        "video_url, video_provider, video_model, video_mode, video_cost_usd, "
                        "video_duration_ms, video_model_call_id, video_error) VALUES "
                        "(:id, :slid, :rid, :idx, :dur, :vu, :vp, :vm, :vmd, :vc, :vd, :vmc, :ve)"
                    ),
                    {
                        **common,
                        "id": str(uuid.uuid4()),
                        "slid": sl_id,
                        "rid": run_id,
                        "idx": idx,
                        "dur": _to_float(s.get("duration_s"), 4.0),
                    },
                )


def _persist_voice(*, run_id: str, step_id: str, outputs: dict[str, Any]) -> None:
    """voice 不建独立表（subtitles 仍在 outputs_json）；写若干 metric 便于聚合：
    - voice_char_count                 : 全文字符数
    - voice_subtitles_duration_s       : 字幕轨末端 end（v2 对齐后 ≈ 真实音频时长）
    - voice_audio_duration_s (v2)      : ASR / ffprobe 拿到的真实音频时长
    - voice_subtitles_aligned (v2)     : 1.0 / 0.0；是否走 v2 真时长重切（vs 退回 v1 均分）
    - voice_asr_duration_ms (v2)       : ASR 调用耗时，用来观测 SiliconFlow ASR 性能
    - voice_asr_segments_count (v2)    : ASR 返回的 segment 条数（SenseVoice 多半是 0）
    """

    char_count = outputs.get("char_count")
    total_dur = outputs.get("total_duration_s")
    audio_dur = outputs.get("audio_duration_s")
    aligned = outputs.get("aligned")
    asr_ms = outputs.get("asr_duration_ms")
    asr_segs = outputs.get("asr_segments_count")
    align_src = outputs.get("alignment_source")

    if all(
        v is None
        for v in (char_count, total_dur, audio_dur, aligned, asr_ms, asr_segs)
    ):
        return

    rows: list[tuple[str, float, str, Optional[str]]] = []
    if char_count is not None:
        rows.append(("voice_char_count", _to_float(char_count), "chars", None))
    if total_dur is not None:
        rows.append(("voice_subtitles_duration_s", _to_float(total_dur), "s", None))
    if audio_dur is not None:
        rows.append(("voice_audio_duration_s", _to_float(audio_dur), "s", align_src))
    if aligned is not None:
        rows.append(("voice_subtitles_aligned", 1.0 if aligned else 0.0, "bool", align_src))
    if asr_ms is not None:
        rows.append(("voice_asr_duration_ms", _to_float(asr_ms), "ms", None))
    if asr_segs is not None:
        rows.append(("voice_asr_segments_count", _to_float(asr_segs), "count", None))

    with _engine().begin() as conn:
        file_id = _file_id_for_run(conn, run_id)
        for kind, value, unit, value_text in rows:
            conn.execute(
                text(
                    "INSERT INTO metrics (id, run_id, step_id, file_id, kind, "
                    "value_num, value_text, unit) "
                    "VALUES (:id, :rid, :sid, :fid, :k, :v, :vt, :u)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "rid": run_id,
                    "sid": step_id,
                    "fid": file_id,
                    "k": kind,
                    "v": value,
                    "vt": value_text,
                    "u": unit,
                },
            )


def _persist_edit(*, run_id: str, step_id: str, outputs: dict[str, Any]) -> None:
    primary_aspect = _str(outputs.get("primary_aspect"), 8)
    aspect_fit = _str(outputs.get("aspect_fit"), 16)
    common = {
        "svu": _str(outputs.get("silent_video_url")),
        "sub": _str(outputs.get("subtitle_url")),
        "nar": _str(outputs.get("narration_url")),
        "dur": _to_float(outputs.get("duration_s")),
        "sc": _to_int(outputs.get("shot_count")),
    }

    pba = outputs.get("previews_by_aspect")
    rows: list[dict[str, Any]] = []
    if isinstance(pba, dict) and pba:
        for aspect, entry in pba.items():
            if not isinstance(entry, dict):
                continue
            rows.append({
                "aspect_ratio": _str(aspect, 8) or "unknown",
                "aspect_fit": _str(entry.get("aspect_fit"), 16) or aspect_fit,
                "is_primary": _str(aspect, 8) == primary_aspect,
                "url": _str(entry.get("url")),
                "muxed": bool(entry.get("muxed")),
                "burned_in_subtitles": bool(entry.get("burned_in_subtitles")),
                "looped_video": bool(entry.get("looped_video")),
                "warning": _str(entry.get("warning")),
                "status": "succeeded" if entry.get("url") else "failed",
            })
        if rows and not any(r["is_primary"] for r in rows):
            rows[0]["is_primary"] = True
    elif outputs.get("preview_url"):
        rows.append({
            "aspect_ratio": primary_aspect or "unknown",
            "aspect_fit": aspect_fit,
            "is_primary": True,
            "url": _str(outputs.get("preview_url")),
            "muxed": bool(outputs.get("muxed")),
            "burned_in_subtitles": bool(outputs.get("burned_in_subtitles")),
            "looped_video": bool(outputs.get("looped_video")),
            "warning": _str(outputs.get("warning")),
            "status": "succeeded",
        })

    if not rows:
        return

    with _engine().begin() as conn:
        file_id = _file_id_for_run(conn, run_id)
        # 单步重跑时旧 renders 全删，避免 (run, aspect, primary) unique 约束冲突
        conn.execute(text("DELETE FROM renders WHERE run_id = :rid"), {"rid": run_id})
        for r in rows:
            conn.execute(
                text(
                    "INSERT INTO renders (id, run_id, file_id, aspect_ratio, aspect_fit, "
                    "is_primary, url, silent_video_url, subtitle_url, narration_url, "
                    "duration_s, shot_count, muxed, burned_in_subtitles, looped_video, "
                    "status, warning) VALUES "
                    "(:id, :rid, :fid, :ar, :af, :ip, :url, :svu, :sub, :nar, "
                    ":dur, :sc, :mx, :bs, :lv, :st, :w)"
                ),
                {
                    **common,
                    "id": str(uuid.uuid4()),
                    "rid": run_id,
                    "fid": file_id,
                    "ar": r["aspect_ratio"],
                    "af": r["aspect_fit"],
                    "ip": r["is_primary"],
                    "url": r["url"],
                    "mx": r["muxed"],
                    "bs": r["burned_in_subtitles"],
                    "lv": r["looped_video"],
                    "st": r["status"],
                    "w": r["warning"],
                },
            )


def _persist_review(*, run_id: str, step_id: str, outputs: dict[str, Any]) -> None:
    issues = outputs.get("issues") or []
    with _engine().begin() as conn:
        # 单步重跑：把本 step 的旧 review 删掉再写
        conn.execute(
            text("DELETE FROM reviews WHERE run_id = :rid AND step_id = :sid"),
            {"rid": run_id, "sid": step_id},
        )
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            severity = str(issue.get("severity") or "info").lower()
            if severity not in ("error", "warning", "info"):
                severity = "info"
            conn.execute(
                text(
                    "INSERT INTO reviews (id, run_id, step_id, severity, area, message, "
                    "meta_json) VALUES "
                    "(:id, :rid, :sid, :sev, :area, :msg, CAST(:meta AS JSON))"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "rid": run_id,
                    "sid": step_id,
                    "sev": severity,
                    "area": _str(issue.get("area"), 40) or "unknown",
                    "msg": _str(issue.get("message")) or "",
                    "meta": _dump(issue.get("meta") or {}),
                },
            )


_HANDLERS: dict[str, Any] = {
    "script": _persist_script,
    "art": _persist_art,
    "video": _persist_video,
    "voice": _persist_voice,
    "edit": _persist_edit,
    "review": _persist_review,
}


__all__ = ["persist_step_outputs"]
