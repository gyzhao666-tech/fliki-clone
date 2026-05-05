"""add_production_tables

Revision ID: a4d72b91e3c5
Revises: c1e8d3b2f0a9
Create Date: 2026-05-04 20:00:00.000000+00:00

数据模型扩展 v1：把原来塞在 `pipeline_steps.outputs_json` 里的「分镜 / 关键帧 /
视频片段 / 成片 / 质检 / 发布计划 / 指标 / 版本」拆成独立表。

新表：
- `shot_lists`     一个 run 一个分镜表
- `shots`          每个 shot 一行（含 ArtAgent 关键帧 + VideoAgent 视频片段）
- `renders`        EditAgent v4 每个 aspect 一行成片
- `reviews`        ReviewAgent 每条 issue 一行
- `publish_plans`  发布计划
- `metrics`        指标时间序列
- `versions`       run 快照标签

数据迁移：
- 迁移现有 pipeline_runs 的 art / video / voice / edit / review step outputs_json
  到对应新表。容错：单个 run 解析失败仅 log skip，不阻断整个迁移。
- 迁移用纯 SQL（避免 alembic 加载 ORM 模型的循环依赖）。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional, Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision: str = "a4d72b91e3c5"
down_revision: Union[str, None] = "c1e8d3b2f0a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


logger = logging.getLogger("alembic.production_tables")


# ── upgrade ──────────────────────────────────────────────────────────────────


def upgrade() -> None:
    _create_tables()
    _backfill_from_outputs_json()


def _create_tables() -> None:
    op.create_table(
        "shot_lists",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("file_id", sa.String(), sa.ForeignKey("files.id", ondelete="CASCADE"),
                  nullable=True),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("hook", sa.Text(), nullable=True),
        sa.Column("script", sa.Text(), nullable=True),
        sa.Column("cta", sa.Text(), nullable=True),
        sa.Column("topic_json", sa.JSON(), nullable=True),
        sa.Column("style_board_json", sa.JSON(), nullable=True),
        sa.Column("character_cards_json", sa.JSON(), nullable=True),
        sa.Column("aspect_ratio", sa.String(8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_index("ix_shot_lists_run_id", "shot_lists", ["run_id"])
    op.create_index("ix_shot_lists_file_id", "shot_lists", ["file_id"])

    op.create_table(
        "shots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("shot_list_id", sa.String(),
                  sa.ForeignKey("shot_lists.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(),
                  sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("duration_s", sa.Float(), nullable=False, server_default="4.0"),
        sa.Column("narration", sa.Text(), nullable=True),
        sa.Column("visual", sa.Text(), nullable=True),
        sa.Column("camera", sa.String(120), nullable=True),
        sa.Column("enhanced_prompt", sa.Text(), nullable=True),
        sa.Column("negative_prompt", sa.Text(), nullable=True),
        sa.Column("aspect_ratio", sa.String(8), nullable=True),
        sa.Column("focus_character", sa.String(80), nullable=True),
        sa.Column("keyframe_url", sa.Text(), nullable=True),
        sa.Column("keyframe_provider", sa.String(40), nullable=True),
        sa.Column("keyframe_model", sa.String(120), nullable=True),
        sa.Column("keyframe_size", sa.String(40), nullable=True),
        sa.Column("keyframe_error", sa.Text(), nullable=True),
        sa.Column("video_url", sa.Text(), nullable=True),
        sa.Column("video_provider", sa.String(40), nullable=True),
        sa.Column("video_model", sa.String(120), nullable=True),
        sa.Column("video_mode", sa.String(40), nullable=True),
        sa.Column("video_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("video_duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("video_model_call_id", sa.String(), nullable=True),
        sa.Column("video_error", sa.Text(), nullable=True),
        sa.Column("meta_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_index("ix_shots_shot_list_id", "shots", ["shot_list_id"])
    op.create_index("ix_shots_run_id", "shots", ["run_id"])
    op.create_index("ix_shots_run_index", "shots", ["run_id", "index"])

    op.create_table(
        "renders",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(),
                  sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_id", sa.String(),
                  sa.ForeignKey("files.id", ondelete="CASCADE"), nullable=True),
        sa.Column("aspect_ratio", sa.String(8), nullable=False),
        sa.Column("aspect_fit", sa.String(16), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("silent_video_url", sa.Text(), nullable=True),
        sa.Column("subtitle_url", sa.Text(), nullable=True),
        sa.Column("narration_url", sa.Text(), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=False, server_default="0"),
        sa.Column("shot_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("muxed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("burned_in_subtitles", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("looped_video", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(40), nullable=False, server_default="succeeded"),
        sa.Column("warning", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_index("ix_renders_run_id", "renders", ["run_id"])
    op.create_index("ix_renders_file_id", "renders", ["file_id"])
    op.create_index("ix_renders_aspect", "renders", ["aspect_ratio"])
    # 一个 run 内同一 aspect 只允许一条 primary（partial unique 索引）；非 primary 不限
    op.execute(
        "CREATE UNIQUE INDEX ux_renders_run_aspect_primary ON renders (run_id, aspect_ratio) "
        "WHERE is_primary = true"
    )

    op.create_table(
        "reviews",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(),
                  sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_id", sa.String(),
                  sa.ForeignKey("pipeline_steps.id", ondelete="CASCADE"), nullable=True),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("area", sa.String(40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("meta_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_index("ix_reviews_run_id", "reviews", ["run_id"])
    op.create_index("ix_reviews_severity", "reviews", ["severity"])
    op.create_index("ix_reviews_area", "reviews", ["area"])

    op.create_table(
        "publish_plans",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("file_id", sa.String(),
                  sa.ForeignKey("files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(),
                  sa.ForeignKey("pipeline_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("render_id", sa.String(),
                  sa.ForeignKey("renders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("platform", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_id", sa.String(120), nullable=True),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags_json", sa.JSON(), nullable=True),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("meta_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_index("ix_publish_plans_file_id", "publish_plans", ["file_id"])
    op.create_index("ix_publish_plans_render_id", "publish_plans", ["render_id"])
    op.create_index("ix_publish_plans_platform", "publish_plans", ["platform"])
    op.create_index("ix_publish_plans_status", "publish_plans", ["status"])

    op.create_table(
        "metrics",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(),
                  sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=True),
        sa.Column("step_id", sa.String(),
                  sa.ForeignKey("pipeline_steps.id", ondelete="CASCADE"), nullable=True),
        sa.Column("file_id", sa.String(),
                  sa.ForeignKey("files.id", ondelete="CASCADE"), nullable=True),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("value_num", sa.Float(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(20), nullable=True),
        sa.Column("meta_json", sa.JSON(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_index("ix_metrics_run_id", "metrics", ["run_id"])
    op.create_index("ix_metrics_file_id", "metrics", ["file_id"])
    op.create_index("ix_metrics_kind", "metrics", ["kind"])
    op.create_index("ix_metrics_captured_at", "metrics", ["captured_at"])

    op.create_table(
        "versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("file_id", sa.String(),
                  sa.ForeignKey("files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(),
                  sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("primary_render_id", sa.String(),
                  sa.ForeignKey("renders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_index("ix_versions_file_id", "versions", ["file_id"])
    op.create_index("ix_versions_published", "versions", ["is_published"])


# ── backfill ─────────────────────────────────────────────────────────────────


def _backfill_from_outputs_json() -> None:
    """把现有 pipeline_runs 的 step outputs_json 解析进新表。

    幂等：每个 run 进 backfill 前先按 run_id 删一遍新表行，避免重复迁移产生重复数据。
    """

    bind = op.get_bind()
    runs = bind.execute(sa.text(
        "SELECT id, file_id FROM pipeline_runs ORDER BY created_at ASC"
    )).fetchall()

    migrated = {"shot_lists": 0, "shots": 0, "renders": 0, "reviews": 0}
    for run in runs:
        run_id = run[0]
        file_id = run[1]
        try:
            steps = bind.execute(sa.text(
                "SELECT id, name, agent_type, outputs_json FROM pipeline_steps "
                "WHERE run_id = :rid ORDER BY created_at ASC"
            ), {"rid": run_id}).fetchall()
        except Exception:
            logger.exception("backfill: failed to load steps for run=%s", run_id)
            continue

        # 收集本 run 各 step 的 outputs，按 agent_type 聚合
        outputs_by_agent: dict[str, dict[str, Any]] = {}
        step_id_by_agent: dict[str, str] = {}
        for step in steps:
            step_id, _name, agent_type, outputs_json = step
            data = _json(outputs_json)
            if not isinstance(data, dict):
                continue
            outputs_by_agent[agent_type] = data
            step_id_by_agent[agent_type] = step_id

        # 删旧 backfill（幂等）
        for table in ("shots", "renders", "reviews"):
            bind.execute(sa.text(f"DELETE FROM {table} WHERE run_id = :rid"), {"rid": run_id})
        bind.execute(sa.text("DELETE FROM shot_lists WHERE run_id = :rid"), {"rid": run_id})

        # 1) shot_list
        script_out = outputs_by_agent.get("script") or {}
        art_out = outputs_by_agent.get("art") or {}
        video_out = outputs_by_agent.get("video") or {}

        # 没有 script outputs 就完全跳过本 run（research-only / 早期 run）
        if not script_out and not art_out:
            continue

        shot_list_id = str(uuid4())
        style_board = (art_out or {}).get("style_board") or {}
        bind.execute(
            sa.text(
                "INSERT INTO shot_lists (id, run_id, file_id, title, hook, script, cta, "
                "topic_json, style_board_json, character_cards_json, aspect_ratio) VALUES "
                "(:id, :rid, :fid, :title, :hook, :script, :cta, "
                "CAST(:topic AS JSON), CAST(:sb AS JSON), CAST(:cc AS JSON), :aspect)"
            ),
            {
                "id": shot_list_id,
                "rid": run_id,
                "fid": file_id,
                "title": _str(script_out.get("title"), 200),
                "hook": _str(script_out.get("hook")),
                "script": _str(script_out.get("script")),
                "cta": _str(script_out.get("cta")),
                "topic": _dump(script_out.get("topic")),
                "sb": _dump(style_board),
                "cc": _dump(art_out.get("character_cards") or []),
                "aspect": _str(style_board.get("aspect_ratio"), 8) or None,
            },
        )
        migrated["shot_lists"] += 1

        # 2) shots：先按 script 的 shots 做骨架，按 art / video 同 index 合并
        shots = _normalise_shots_for_backfill(
            script_shots=script_out.get("shots") or [],
            art_shots=art_out.get("shots") or [],
            video_shots=video_out.get("shots") or [],
            default_aspect=str(style_board.get("aspect_ratio") or "16:9"),
        )
        for s in shots:
            bind.execute(
                sa.text(
                    "INSERT INTO shots (id, shot_list_id, run_id, index, duration_s, "
                    "narration, visual, camera, enhanced_prompt, negative_prompt, aspect_ratio, "
                    "focus_character, keyframe_url, keyframe_provider, keyframe_model, "
                    "keyframe_size, keyframe_error, video_url, video_provider, video_model, "
                    "video_mode, video_cost_usd, video_duration_ms, video_model_call_id, "
                    "video_error) VALUES "
                    "(:id, :slid, :rid, :idx, :dur, :nar, :vis, :cam, :ep, :np, :ar, "
                    ":fc, :kf, :kp, :km, :ks, :ke, :vu, :vp, :vm, :vmd, :vc, :vd, :vmc, :ve)"
                ),
                {
                    "id": str(uuid4()),
                    "slid": shot_list_id,
                    "rid": run_id,
                    "idx": s["index"],
                    "dur": s["duration_s"],
                    "nar": s.get("narration"),
                    "vis": s.get("visual"),
                    "cam": _str(s.get("camera"), 120),
                    "ep": s.get("enhanced_prompt"),
                    "np": s.get("negative_prompt"),
                    "ar": _str(s.get("aspect_ratio"), 8),
                    "fc": _str(s.get("focus_character"), 80),
                    "kf": s.get("keyframe_url"),
                    "kp": _str(s.get("keyframe_provider"), 40),
                    "km": _str(s.get("keyframe_model"), 120),
                    "ks": _str(s.get("keyframe_size"), 40),
                    "ke": s.get("keyframe_error"),
                    "vu": s.get("video_url"),
                    "vp": _str(s.get("video_provider"), 40),
                    "vm": _str(s.get("video_model"), 120),
                    "vmd": _str(s.get("video_mode"), 40),
                    "vc": float(s.get("video_cost_usd") or 0.0),
                    "vd": int(s.get("video_duration_ms") or 0),
                    "vmc": s.get("video_model_call_id"),
                    "ve": s.get("video_error"),
                },
            )
            migrated["shots"] += 1

        # 3) renders：v4 走 previews_by_aspect；v3 只有顶层字段
        edit_out = outputs_by_agent.get("edit") or {}
        if edit_out:
            for r in _renders_for_backfill(edit_out):
                bind.execute(
                    sa.text(
                        "INSERT INTO renders (id, run_id, file_id, aspect_ratio, aspect_fit, "
                        "is_primary, url, silent_video_url, subtitle_url, narration_url, "
                        "duration_s, shot_count, muxed, burned_in_subtitles, looped_video, "
                        "status, warning) VALUES "
                        "(:id, :rid, :fid, :ar, :af, :ip, :url, :svu, :sub, :nar, "
                        ":dur, :sc, :mx, :bs, :lv, :st, :w)"
                    ),
                    {
                        "id": str(uuid4()),
                        "rid": run_id,
                        "fid": file_id,
                        "ar": r["aspect_ratio"],
                        "af": r.get("aspect_fit"),
                        "ip": r["is_primary"],
                        "url": r.get("url"),
                        "svu": r.get("silent_video_url"),
                        "sub": r.get("subtitle_url"),
                        "nar": r.get("narration_url"),
                        "dur": float(r.get("duration_s") or 0.0),
                        "sc": int(r.get("shot_count") or 0),
                        "mx": bool(r.get("muxed")),
                        "bs": bool(r.get("burned_in_subtitles")),
                        "lv": bool(r.get("looped_video")),
                        "st": r.get("status") or "succeeded",
                        "w": r.get("warning"),
                    },
                )
                migrated["renders"] += 1

        # 4) reviews
        review_out = outputs_by_agent.get("review") or {}
        review_step_id = step_id_by_agent.get("review")
        for issue in (review_out.get("issues") or []):
            if not isinstance(issue, dict):
                continue
            severity = str(issue.get("severity") or "info").lower()
            if severity not in ("error", "warning", "info"):
                severity = "info"
            bind.execute(
                sa.text(
                    "INSERT INTO reviews (id, run_id, step_id, severity, area, message, meta_json) "
                    "VALUES (:id, :rid, :sid, :sev, :area, :msg, CAST(:meta AS JSON))"
                ),
                {
                    "id": str(uuid4()),
                    "rid": run_id,
                    "sid": review_step_id,
                    "sev": severity,
                    "area": _str(issue.get("area"), 40) or "unknown",
                    "msg": _str(issue.get("message")) or "",
                    "meta": _dump(issue.get("meta") or {}),
                },
            )
            migrated["reviews"] += 1

    logger.info("backfill done: %s", migrated)


def _normalise_shots_for_backfill(
    *,
    script_shots: list,
    art_shots: list,
    video_shots: list,
    default_aspect: str,
) -> list[dict[str, Any]]:
    """按 index 把 script/art/video 三处的 shot 信息合并成一行。"""

    by_index: dict[int, dict[str, Any]] = {}

    def _ensure(idx: int) -> dict[str, Any]:
        if idx not in by_index:
            by_index[idx] = {"index": idx, "duration_s": 4.0, "aspect_ratio": default_aspect}
        return by_index[idx]

    # script：底层 narration / visual / camera / duration
    for i, s in enumerate(script_shots or [], start=1):
        if not isinstance(s, dict):
            continue
        idx = int(s.get("index") or i)
        m = _ensure(idx)
        m["duration_s"] = float(s.get("duration_s") or m["duration_s"])
        m["narration"] = s.get("narration")
        m["visual"] = s.get("visual")
        m["camera"] = s.get("camera")

    # art：覆盖 enhanced_prompt / aspect / keyframe
    for i, s in enumerate(art_shots or [], start=1):
        if not isinstance(s, dict):
            continue
        idx = int(s.get("index") or i)
        m = _ensure(idx)
        m["enhanced_prompt"] = s.get("enhanced_prompt")
        m["negative_prompt"] = s.get("negative_prompt")
        m["aspect_ratio"] = s.get("aspect_ratio") or m.get("aspect_ratio") or default_aspect
        m["focus_character"] = s.get("focus_character")
        m["keyframe_url"] = s.get("keyframe_url")
        m["keyframe_provider"] = s.get("keyframe_provider")
        m["keyframe_model"] = s.get("keyframe_model")
        m["keyframe_size"] = s.get("keyframe_size")
        m["keyframe_error"] = s.get("keyframe_error")
        # narration / visual / camera / duration_s 也可能在 art 里被改写
        if s.get("narration"):
            m["narration"] = s.get("narration")
        if s.get("visual"):
            m["visual"] = s.get("visual")
        if s.get("camera"):
            m["camera"] = s.get("camera")
        if s.get("duration_s") is not None:
            try:
                m["duration_s"] = float(s.get("duration_s"))
            except Exception:
                pass

    # video：覆盖 video_url / provider / model / mode / cost / duration_ms / error
    for i, s in enumerate(video_shots or [], start=1):
        if not isinstance(s, dict):
            continue
        idx = int(s.get("index") or i)
        m = _ensure(idx)
        m["video_url"] = s.get("video_url")
        m["video_provider"] = s.get("provider")
        m["video_model"] = s.get("model")
        m["video_mode"] = s.get("mode")
        m["video_cost_usd"] = float(s.get("cost_usd") or 0.0)
        m["video_duration_ms"] = int(s.get("duration_ms") or 0)
        m["video_model_call_id"] = s.get("model_call_id")
        m["video_error"] = s.get("error")

    return [by_index[k] for k in sorted(by_index.keys())]


def _renders_for_backfill(edit_out: dict[str, Any]) -> list[dict[str, Any]]:
    """从 edit step outputs_json 解析出 0-N 个 render 行。

    - v4 优先走 previews_by_aspect；每条 entry 一行 render
    - v3 fallback：用顶层 preview_url 构造一条 render，aspect 取 'unknown' 占位
    """

    out: list[dict[str, Any]] = []
    primary_aspect = str(edit_out.get("primary_aspect") or "").strip()
    aspect_fit_default = edit_out.get("aspect_fit")
    common = {
        "silent_video_url": edit_out.get("silent_video_url"),
        "subtitle_url": edit_out.get("subtitle_url"),
        "narration_url": edit_out.get("narration_url"),
        "duration_s": edit_out.get("duration_s"),
        "shot_count": edit_out.get("shot_count"),
    }

    pba = edit_out.get("previews_by_aspect")
    if isinstance(pba, dict) and pba:
        for aspect, entry in pba.items():
            if not isinstance(entry, dict):
                continue
            row = dict(common)
            row.update({
                "aspect_ratio": str(aspect),
                "aspect_fit": entry.get("aspect_fit") or aspect_fit_default,
                "is_primary": (str(aspect) == primary_aspect)
                if primary_aspect
                else False,
                "url": entry.get("url"),
                "muxed": entry.get("muxed"),
                "burned_in_subtitles": entry.get("burned_in_subtitles"),
                "looped_video": entry.get("looped_video"),
                "warning": entry.get("warning"),
                "status": "succeeded" if entry.get("url") else "failed",
            })
            out.append(row)
        if out and not any(r["is_primary"] for r in out):
            # primary_aspect 没匹配上 → 第一个标 primary 兜底
            out[0]["is_primary"] = True
        return out

    # v3 fallback
    if edit_out.get("preview_url"):
        out.append({
            **common,
            "aspect_ratio": "unknown",
            "aspect_fit": aspect_fit_default,
            "is_primary": True,
            "url": edit_out.get("preview_url"),
            "muxed": edit_out.get("muxed"),
            "burned_in_subtitles": edit_out.get("burned_in_subtitles"),
            "looped_video": edit_out.get("looped_video"),
            "warning": edit_out.get("warning"),
            "status": "succeeded",
        })
    return out


def _json(value: Any) -> Any:
    """outputs_json 在 PG JSON 列上应该已经是 dict / list，但兼容字符串保险。"""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return None
    return None


def _dump(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _str(value: Any, max_len: Optional[int] = None) -> Optional[str]:
    if value is None:
        return None
    s = str(value)
    if max_len is not None:
        s = s[:max_len]
    return s


# ── downgrade ────────────────────────────────────────────────────────────────


def downgrade() -> None:
    op.drop_index("ix_versions_published", table_name="versions")
    op.drop_index("ix_versions_file_id", table_name="versions")
    op.drop_table("versions")

    op.drop_index("ix_metrics_captured_at", table_name="metrics")
    op.drop_index("ix_metrics_kind", table_name="metrics")
    op.drop_index("ix_metrics_file_id", table_name="metrics")
    op.drop_index("ix_metrics_run_id", table_name="metrics")
    op.drop_table("metrics")

    op.drop_index("ix_publish_plans_status", table_name="publish_plans")
    op.drop_index("ix_publish_plans_platform", table_name="publish_plans")
    op.drop_index("ix_publish_plans_render_id", table_name="publish_plans")
    op.drop_index("ix_publish_plans_file_id", table_name="publish_plans")
    op.drop_table("publish_plans")

    op.drop_index("ix_reviews_area", table_name="reviews")
    op.drop_index("ix_reviews_severity", table_name="reviews")
    op.drop_index("ix_reviews_run_id", table_name="reviews")
    op.drop_table("reviews")

    op.execute("DROP INDEX IF EXISTS ux_renders_run_aspect_primary")
    op.drop_index("ix_renders_aspect", table_name="renders")
    op.drop_index("ix_renders_file_id", table_name="renders")
    op.drop_index("ix_renders_run_id", table_name="renders")
    op.drop_table("renders")

    op.drop_index("ix_shots_run_index", table_name="shots")
    op.drop_index("ix_shots_run_id", table_name="shots")
    op.drop_index("ix_shots_shot_list_id", table_name="shots")
    op.drop_table("shots")

    op.drop_index("ix_shot_lists_file_id", table_name="shot_lists")
    op.drop_index("ix_shot_lists_run_id", table_name="shot_lists")
    op.drop_table("shot_lists")
