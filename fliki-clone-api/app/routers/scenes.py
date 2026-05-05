import asyncio
import json as _json
import logging
import math
import re as _re
import uuid as _uuid
from typing import AsyncIterator

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.deps import DB, CurrentUser
from app.models.file import File
from app.models.scene import Scene
from app.schemas import (
    CreateSceneRequest,
    GenerateRequest,
    GenerateResponse,
    GenerateStatusResponse,
    MessageResponse,
    PatchSceneRequest,
    RegenerateSceneVideoRequest,
    ReorderSceneRequest,
    SceneOut,
)

router = APIRouter(tags=["Scenes"])


def _scene_to_out(s: Scene) -> SceneOut:
    return SceneOut(
        id=s.id,
        file_id=s.file_id,
        order_index=s.order_index,
        title=s.title,
        script=s.script,
        voice_id=s.voice_id,
        media_url=s.media_url,
        media_type=s.media_type,
        character_id=s.character_id,
        scene_goal=s.scene_goal,
        selling_point=s.selling_point,
        asset_id=s.asset_id,
        duration=s.duration,
        video_prompt=s.video_prompt,
        video_url=s.video_url,
        video_status=s.video_status,
    )


async def _get_file_or_404(file_id: str, user_id: str, db: DB) -> File:
    result = await db.execute(
        select(File).where(File.id == file_id, File.user_id == user_id, File.deleted_at.is_(None))
    )
    file = result.scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    return file


# ── Scenes CRUD ───────────────────────────────────────────────────────────────
@router.get("/files/{file_id}/scenes", response_model=list[SceneOut])
async def list_scenes(file_id: str, current_user: CurrentUser, db: DB):
    await _get_file_or_404(file_id, current_user.id, db)
    result = await db.execute(
        select(Scene).where(Scene.file_id == file_id).order_by(Scene.order_index)
    )
    return [_scene_to_out(s) for s in result.scalars().all()]


@router.post("/files/{file_id}/scenes", response_model=SceneOut, status_code=status.HTTP_201_CREATED)
async def create_scene(file_id: str, body: CreateSceneRequest, current_user: CurrentUser, db: DB):
    file = await _get_file_or_404(file_id, current_user.id, db)

    count_result = await db.execute(
        select(Scene).where(Scene.file_id == file_id)
    )
    current_count = len(count_result.scalars().all())

    scene = Scene(
        file_id=file_id,
        order_index=current_count,
        title=body.title,
        script=body.script,
        voice_id=body.voice_id,
    )
    db.add(scene)
    file.scene_count = current_count + 1
    await db.commit()
    await db.refresh(scene)
    return _scene_to_out(scene)


@router.patch("/scenes/{scene_id}", response_model=SceneOut)
async def patch_scene(scene_id: str, body: PatchSceneRequest, current_user: CurrentUser, db: DB):
    result = await db.execute(select(Scene).where(Scene.id == scene_id))
    scene = result.scalar_one_or_none()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")

    # Verify ownership
    await _get_file_or_404(scene.file_id, current_user.id, db)

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(scene, field, value)

    await db.commit()
    await db.refresh(scene)
    return _scene_to_out(scene)


@router.delete("/scenes/{scene_id}", response_model=MessageResponse)
async def delete_scene(scene_id: str, current_user: CurrentUser, db: DB):
    result = await db.execute(select(Scene).where(Scene.id == scene_id))
    scene = result.scalar_one_or_none()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")

    file = await _get_file_or_404(scene.file_id, current_user.id, db)
    await db.delete(scene)
    file.scene_count = max(0, file.scene_count - 1)
    await db.commit()
    return MessageResponse(message="Scene deleted")


@router.post("/scenes/{scene_id}/regenerate-video", response_model=GenerateResponse)
async def regenerate_scene_video(
    scene_id: str,
    body: RegenerateSceneVideoRequest,
    current_user: CurrentUser,
    db: DB,
    background_tasks: BackgroundTasks,
):
    """
    仅重生成指定分镜的视频并重新拼接完整成片（需可灵 API）。
    进度复用 GET /files/{file_id}/status SSE（按 scene.file_id）。
    """
    result = await db.execute(select(Scene).where(Scene.id == scene_id))
    scene = result.scalar_one_or_none()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    await _get_file_or_404(scene.file_id, current_user.id, db)

    job_id = str(_uuid.uuid4())
    try:
        import redis.asyncio as aioredis
        from app.config import get_settings as _gs
        r = aioredis.from_url(_gs().redis_url, decode_responses=True)
        await r.delete(f"gen_progress:{scene.file_id}")
        await r.aclose()
    except Exception:
        pass

    background_tasks.add_task(_run_regenerate_single_scene_video, scene.file_id, scene_id, body)
    return GenerateResponse(job_id=job_id, estimated_seconds=90)


@router.post("/scenes/{scene_id}/reorder", response_model=SceneOut)
async def reorder_scene(scene_id: str, body: ReorderSceneRequest, current_user: CurrentUser, db: DB):
    result = await db.execute(select(Scene).where(Scene.id == scene_id))
    scene = result.scalar_one_or_none()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")

    await _get_file_or_404(scene.file_id, current_user.id, db)
    scene.order_index = body.new_index
    await db.commit()
    await db.refresh(scene)
    return _scene_to_out(scene)


# ── Video Generation ──────────────────────────────────────────────────────────
_PROGRESS_KEY_TTL = 3600  # Redis key 1 小时过期
_redis_progress_warned = False


def _set_progress(file_id: str, progress: int, step: str = "", status: str = "generating", preview_url: str | None = None) -> None:
    """向 Redis 写入当前生成进度，供 SSE 实时读取。"""
    import redis as redis_lib
    from app.config import get_settings
    settings = get_settings()
    try:
        r = redis_lib.from_url(settings.redis_url, decode_responses=True)
        r.setex(
            f"gen_progress:{file_id}",
            _PROGRESS_KEY_TTL,
            _json.dumps({"progress": progress, "step": step, "status": status, "preview_url": preview_url}),
        )
    except Exception as exc:
        global _redis_progress_warned
        if not _redis_progress_warned:
            logger.warning(
                "gen_progress Redis 写入失败（请检查 Redis 是否运行；进度条可能停在 0%%）: %s",
                exc,
            )
            _redis_progress_warned = True


# ── 数据库同步辅助 ──────────────────────────────────────────────────────────────

def _sync_update_file(file_id: str, new_status: str, preview_url) -> None:
    from sqlalchemy import create_engine, text
    from app.config import get_settings
    settings = get_settings()
    try:
        engine = create_engine(settings.database_url_sync)
        with engine.connect() as conn:
            conn.execute(
                text("UPDATE files SET status = :s, preview_url = :u WHERE id = :id"),
                {"s": new_status, "u": preview_url, "id": file_id},
            )
            conn.commit()
    except Exception:
        pass


def _db_read_scenes(file_id: str) -> list[dict]:
    """同步读取 scenes，按 order_index 排序。"""
    from sqlalchemy import create_engine, text as sa_text
    from app.config import get_settings
    settings = get_settings()
    try:
        engine = create_engine(settings.database_url_sync)
        with engine.connect() as conn:
            rows = conn.execute(
                sa_text(
                    "SELECT id, script, duration, order_index "
                    "FROM scenes WHERE file_id = :fid ORDER BY order_index"
                ),
                {"fid": file_id},
            ).fetchall()
            return [
                {"id": str(r[0]), "script": r[1] or "", "duration": r[2], "order_index": r[3]}
                for r in rows
            ]
    except Exception:
        return []


def _db_read_scenes_full(file_id: str) -> list[dict]:
    """同步读取分镜（含 video_*），按 order_index 排序。"""
    from sqlalchemy import create_engine, text as sa_text
    from app.config import get_settings
    settings = get_settings()
    try:
        engine = create_engine(settings.database_url_sync)
        with engine.connect() as conn:
            rows = conn.execute(
                sa_text(
                    "SELECT id, script, duration, order_index, video_prompt, video_url, video_status "
                    "FROM scenes WHERE file_id = :fid ORDER BY order_index"
                ),
                {"fid": file_id},
            ).fetchall()
            return [
                {
                    "id": str(r[0]),
                    "script": r[1] or "",
                    "duration": r[2],
                    "order_index": r[3],
                    "video_prompt": r[4],
                    "video_url": r[5],
                    "video_status": r[6],
                }
                for r in rows
            ]
    except Exception:
        return []


def _db_update_scene_prompt(scene_id: str, video_prompt: str) -> None:
    """将 LLM 转换后的视觉提示词写回 scenes 表。"""
    from sqlalchemy import create_engine, text as sa_text
    from app.config import get_settings
    settings = get_settings()
    try:
        engine = create_engine(settings.database_url_sync)
        with engine.connect() as conn:
            conn.execute(
                sa_text("UPDATE scenes SET video_prompt = :p WHERE id = :id"),
                {"p": video_prompt, "id": scene_id},
            )
            conn.commit()
    except Exception:
        pass


def _db_update_scene_video(scene_id: str, video_url: str | None, video_status: str) -> None:
    """更新分镜对应的视频片段 URL 及生成状态。"""
    from sqlalchemy import create_engine, text as sa_text
    from app.config import get_settings
    settings = get_settings()
    try:
        engine = create_engine(settings.database_url_sync)
        with engine.connect() as conn:
            conn.execute(
                sa_text("UPDATE scenes SET video_url = :u, video_status = :s WHERE id = :id"),
                {"u": video_url, "s": video_status, "id": scene_id},
            )
            conn.commit()
    except Exception:
        pass


# ── LLM 分镜提示词转换 ─────────────────────────────────────────────────────────

def _llm_to_video_prompts(
    scenes: list[dict],
    api_key: str,
    base_url: str,
    llm_model: str,
    *,
    file_id: str | None = None,
    user_id: str | None = None,
) -> list[str]:
    """
    调用 LLM（经 model_gateway）把每个分镜的 script 批量转换为英文视觉提示词。
    失败 / 无 key / 解析异常时降级为直接截断原始 script。

    走 gateway 的目的：
    - 统一记账写入 model_calls 表
    - 后续切换 provider / 模型不再需要改本函数
    `api_key`/`base_url` 仅作向后兼容保留；gateway 内部按 settings 决定。
    """
    _ = (api_key, base_url)  # 保留签名以兼容旧调用方

    scripts = [s.get("script") or "" for s in scenes]

    fallback = [s[:400] or f"Cinematic video scene {i + 1}" for i, s in enumerate(scripts)]

    from app.services.model_gateway import (
        ModelAction,
        RenderRequest,
        get_gateway,
    )

    gateway = get_gateway()

    system_prompt = (
        "You are a professional storyboard director. "
        "Convert each Chinese/English script snippet into a concise English video generation prompt (under 80 words). "
        "Focus on: visual composition, lighting, camera angle, subject action, atmosphere. "
        "Return ONLY a JSON array of strings, same count as input, no extra text."
    )
    user_content = _json.dumps(
        [{"i": i, "script": s} for i, s in enumerate(scripts)],
        ensure_ascii=False,
    )

    request = RenderRequest(
        action=ModelAction.LLM,
        params={
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.6,
            "max_tokens": max(200, len(scenes) * 200),
            "response_format": "json_array",
            "approx_tokens": max(500, len(scenes) * 250),
        },
        model_hint=llm_model,
        user_id=user_id,
        file_id=file_id,
    )
    result = gateway.run(request)
    if not result.ok or not isinstance(result.output, list):
        return fallback

    prompts = result.output
    if len(prompts) != len(scenes):
        return fallback
    return [str(p) for p in prompts]


def _resolve_video_prompts(
    scenes: list[dict],
    api_key: str,
    base_url: str,
    llm_model: str,
) -> list[str]:
    """模板分镜会预写 video_prompt；只有缺失时才交给 LLM 补齐。"""
    existing = [str(s.get("video_prompt") or "").strip() for s in scenes]
    if all(existing):
        return existing

    generated = _llm_to_video_prompts(
        scenes,
        api_key=api_key,
        base_url=base_url,
        llm_model=llm_model,
    )
    return [preset or generated[index] for index, preset in enumerate(existing)]


# ── 可灵（Kling AI）调用：均通过 model_gateway / KlingProvider 走 ───────────────

def _kling_text2video(
    prompt: str,
    duration: int,
    settings,  # noqa: ARG001  保留签名兼容老调用方
    *,
    file_id: str | None = None,
) -> str | None:
    """通过 model_gateway 调用可灵 text2video。"""
    from app.services.model_gateway import (
        ModelAction,
        RenderRequest,
        get_gateway,
    )

    result = get_gateway().run(
        RenderRequest(
            action=ModelAction.GENERATE_VIDEO,
            params={"prompt": prompt, "duration": int(duration), "aspect_ratio": "16:9", "mode": "std"},
            provider_hint=None,  # 走默认路由（Kling 优先）
            file_id=file_id,
            timeout_s=900.0,
        )
    )
    if result.ok and isinstance(result.output, dict):
        return result.output.get("video_url")
    return None


def _kling_image2video(
    prompt: str,
    duration: int,
    ref_image: str,
    settings,  # noqa: ARG001
    *,
    file_id: str | None = None,
) -> str | None:
    """通过 model_gateway 调用可灵 image2video。"""
    from app.services.model_gateway import (
        ModelAction,
        ProviderName,
        RenderRequest,
        get_gateway,
    )

    result = get_gateway().run(
        RenderRequest(
            action=ModelAction.IMAGE_TO_VIDEO,
            params={
                "prompt": prompt,
                "duration": int(duration),
                "aspect_ratio": "16:9",
                "mode": "std",
                "ref_image": ref_image,
            },
            # image2video 当前只有 Kling 支持
            provider_hint=ProviderName.KLING,
            file_id=file_id,
            timeout_s=900.0,
        )
    )
    if result.ok and isinstance(result.output, dict):
        return result.output.get("video_url")
    return None


# ── 视频处理辅助函数 ──────────────────────────────────────────────────────────

def _split_to_sub_segments(prompt: str, total_duration: float, max_duration: int) -> list[dict]:
    """统一调用 services/media。"""
    from app.services.media import split_to_sub_segments as _impl

    return _impl(prompt, total_duration, max_duration)


def _generate_clips_for_one_scene(
    prompt: str,
    scene_duration: float,
    max_dur: int,
    style_ref_image: str | None,
    prevent_drift: bool,
    settings,
) -> str | None:
    """
    为一个分镜生成成片：若时长超过单次上限则多段子段，子段间用上一段尾帧做 image2video 衔接。
    返回该分镜最终可播放的一条 URL。
    """
    sub_segs = _split_to_sub_segments(prompt, float(scene_duration), max_dur)
    if not sub_segs:
        return None
    part_urls: list[str] = []
    local_ref = style_ref_image
    for seg in sub_segs:
        d = int(seg["duration"])
        p = seg["prompt"]
        if local_ref and prevent_drift:
            u = _kling_image2video(p, d, local_ref, settings)
        else:
            u = _kling_text2video(p, d, settings)
        if u is None:
            return None
        part_urls.append(u)
        if prevent_drift:
            local_ref = _extract_last_frame(u)
    if len(part_urls) == 1:
        return part_urls[0]
    merged = _concat_video_segments(part_urls, settings)
    return merged or part_urls[0]


def _extract_last_frame(video_url: str) -> str | None:
    """统一调用 services/media；保留本函数以兼容老调用方。"""
    from app.services.media import extract_last_frame as _impl

    return _impl(video_url)


def _concat_video_segments(video_urls: list[str], settings) -> str | None:  # noqa: ARG001
    """统一调用 services/media；保留 (urls, settings) 签名以兼容老调用方。"""
    from app.services.media import concat_video_segments as _impl

    return _impl(video_urls)


def _siliconflow_submit_and_poll_one(
    prompt: str,
    num_frames: int,
    settings,  # noqa: ARG001
    *,
    file_id: str | None = None,
) -> str | None:
    """通过 model_gateway 调用硅基流动 Wan 系列文生视频。"""
    from app.services.model_gateway import (
        ModelAction,
        ProviderName,
        RenderRequest,
        get_gateway,
    )

    result = get_gateway().run(
        RenderRequest(
            action=ModelAction.GENERATE_VIDEO,
            params={"prompt": prompt, "num_frames": int(num_frames)},
            provider_hint=ProviderName.SILICONFLOW,
            file_id=file_id,
            timeout_s=600.0,
        )
    )
    if result.ok and isinstance(result.output, dict):
        return result.output.get("video_url")
    return None


def _sf_chunks_for_scene_duration(scene_duration: float) -> int:
    """每个分镜需要的 Wan 单次任务数（单次约 5s）。"""
    d = max(1.0, float(scene_duration))
    return max(1, math.ceil(d / 5.0))


def _generate_sf_clips_for_one_scene(prompt: str, scene_duration: float, settings) -> str | None:
    """
    硅基流动：同一分镜若目标超过 ~5s，则多次 T2V（同提示词）再 concat，接近目标时长。
    """
    n = _sf_chunks_for_scene_duration(scene_duration)
    nf = max(17, int(settings.siliconflow_wan_num_frames))
    part_urls: list[str] = []
    for _i in range(n):
        u = _siliconflow_submit_and_poll_one(prompt, nf, settings)
        if u is None:
            return None
        part_urls.append(u)
    if len(part_urls) == 1:
        return part_urls[0]
    return _concat_video_segments(part_urls, settings) or part_urls[0]


def _run_siliconflow_storyboard(
    file_id: str,
    scenes: list[dict],
    default_scene_duration: float,
    prevent_drift: bool,
    settings,
) -> str | None:
    """
    硅基流动分镜流水线：与可灵类似，按分镜逐段生成（每段内再按 5s 切块），最后 concat。
    prevent_drift 在无 I2V 时仅作占位（后续可接尾帧 + Wan2.2-I2V）。
    """
    _ = prevent_drift
    n = len(scenes)
    _set_progress(file_id, 5, f"共 {n} 个分镜（硅基流动），正在准备视觉提示词…")

    video_prompts = _resolve_video_prompts(
        scenes,
        api_key=settings.siliconflow_api_key,
        base_url=settings.siliconflow_base_url,
        llm_model=settings.llm_model,
    )
    for s, prompt in zip(scenes, video_prompts):
        if s.get("id"):
            _db_update_scene_prompt(s["id"], prompt)
            _db_update_scene_video(s["id"], None, "generating")

    _set_progress(file_id, 12, f"提示词完成，硅基流动并行渲染分镜（共 {n} 镜）…")

    from concurrent.futures import ThreadPoolExecutor, as_completed

    results_sf: list[str | None] = [None] * n
    max_sf = max(1, min(int(getattr(settings, "siliconflow_parallel_max_workers", 2)), n))

    def _sf_scene(idx: int) -> tuple[int, str | None]:
        s = scenes[idx]
        prompt = video_prompts[idx]
        scene_dur = float(s.get("duration") or default_scene_duration)
        try:
            u = _generate_sf_clips_for_one_scene(prompt, scene_dur, settings)
            return idx, u
        except Exception:
            logger.exception("siliconflow parallel scene %s", idx)
            return idx, None

    done_sf = 0
    with ThreadPoolExecutor(max_workers=max_sf) as ex:
        futs = [ex.submit(_sf_scene, i) for i in range(n)]
        for fut in as_completed(futs):
            idx, url = fut.result()
            done_sf += 1
            sid = scenes[idx].get("id")
            if sid:
                if url:
                    _db_update_scene_video(sid, url, "done")
                else:
                    _db_update_scene_video(sid, None, "error")
            results_sf[idx] = url
            pct = 12 + int((done_sf / max(n, 1)) * 75)
            _set_progress(file_id, min(88, pct), f"硅基流动 分镜 {done_sf}/{n}…")

    if any(u is None for u in results_sf):
        return None
    all_urls = [results_sf[i] for i in range(n)]

    _set_progress(file_id, 90, f"合并 {len(all_urls)} 段分镜视频…")
    if len(all_urls) == 1:
        return all_urls[0]
    return _concat_video_segments(all_urls, settings) or all_urls[0]


def _merge_scene_videos_to_file_preview(file_id: str, settings) -> str | None:
    """按分镜顺序拼接所有已生成片段，写入 files.preview_url。"""
    scenes = _db_read_scenes_full(file_id)
    urls = [s["video_url"] for s in scenes if s.get("video_url")]
    if not urls:
        return None
    if len(urls) == 1:
        final_u = urls[0]
    else:
        final_u = _concat_video_segments(urls, settings) or urls[0]
    _sync_update_file(file_id, "done", final_u)
    return final_u


def _run_regenerate_single_scene_video(file_id: str, scene_id: str, body: RegenerateSceneVideoRequest) -> None:
    """
    单镜重生成（可灵）：可选覆盖/刷新提示词，可选承接上一镜尾帧防漂移，完成后重拼完整成片。
    无可灵 Key 时仅将该分镜标记为 error，不修改成片 URL。
    """
    from app.config import get_settings

    settings = get_settings()
    if not (settings.kling_access_key and settings.kling_secret_key):
        _db_update_scene_video(scene_id, None, "error")
        _set_progress(
            file_id,
            0,
            "单镜重生成需要配置可灵 KLING_ACCESS_KEY / KLING_SECRET_KEY",
            status="error",
        )
        return

    scenes = _db_read_scenes_full(file_id)
    idx = next((i for i, s in enumerate(scenes) if s["id"] == scene_id), None)
    if idx is None:
        _set_progress(file_id, 0, "分镜不存在", status="error")
        return

    target = scenes[idx]
    scene_dur = float(target.get("duration") or body.default_scene_duration)
    n = len(scenes)

    if body.video_prompt is not None and body.video_prompt.strip():
        prompt = body.video_prompt.strip()
        _db_update_scene_prompt(scene_id, prompt)
    elif body.refresh_prompt_from_script:
        one = [{"id": target["id"], "script": target.get("script") or "", "duration": target.get("duration"), "order_index": target.get("order_index", 0)}]
        prompt = _llm_to_video_prompts(
            one,
            api_key=settings.siliconflow_api_key,
            base_url=settings.siliconflow_base_url,
            llm_model=settings.llm_model,
        )[0]
        _db_update_scene_prompt(scene_id, prompt)
    else:
        if target.get("video_prompt"):
            prompt = target["video_prompt"]
        else:
            one = [{"id": target["id"], "script": target.get("script") or "", "duration": target.get("duration"), "order_index": target.get("order_index", 0)}]
            prompt = _llm_to_video_prompts(
                one,
                api_key=settings.siliconflow_api_key,
                base_url=settings.siliconflow_base_url,
                llm_model=settings.llm_model,
            )[0]
            _db_update_scene_prompt(scene_id, prompt)

    style_ref_image: str | None = None
    if body.prevent_style_drift and idx > 0:
        prev_url = scenes[idx - 1].get("video_url")
        if prev_url:
            style_ref_image = _extract_last_frame(prev_url)

    _set_progress(file_id, 8, f"重生成镜头 {idx + 1}/{n}…")
    _db_update_scene_video(scene_id, None, "generating")

    try:
        url = _generate_clips_for_one_scene(
            prompt,
            scene_dur,
            settings.kling_max_duration,
            style_ref_image,
            body.prevent_style_drift,
            settings,
        )
    except Exception as e:
        logger.exception("regenerate scene: %s", e)
        url = None

    if url is None:
        _db_update_scene_video(scene_id, None, "error")
        _set_progress(file_id, 0, "该分镜渲染失败", status="error")
        return

    _db_update_scene_video(scene_id, url, "done")
    _set_progress(file_id, 75, "正在合并完整成片…", status="generating")
    final = _merge_scene_videos_to_file_preview(file_id, settings)
    _set_progress(file_id, 100, "完成", status="done", preview_url=final)


# ── 主生成流程 ────────────────────────────────────────────────────────────────

def _run_kling_storyboard(
    file_id: str,
    scenes: list[dict],
    scenes_per_batch: int,
    prevent_drift: bool,
    default_scene_duration: float,
    settings,
) -> str | None:
    """
    可灵分镜流水线：**每个分镜独立生成一段视频**并写入对应 scene.video_url，
    最后将所有分镜片段按顺序 concat 成完整成片（总时长 ≈ 各分镜时长之和）。
    scenes_per_batch 仅保留兼容，不再合并多镜为一批（旧逻辑会导致同批多镜共用一个 URL）。
    """
    _ = scenes_per_batch  # 保留参数签名，避免调用方改动
    n = len(scenes)
    _set_progress(file_id, 5, f"共 {n} 个分镜，正在准备视觉提示词…")

    video_prompts = _resolve_video_prompts(
        scenes,
        api_key=settings.siliconflow_api_key,
        base_url=settings.siliconflow_base_url,
        llm_model=settings.llm_model,
    )
    for s, prompt in zip(scenes, video_prompts):
        if s["id"]:
            _db_update_scene_prompt(s["id"], prompt)
            _db_update_scene_video(s["id"], None, "generating")

    _set_progress(
        file_id,
        15,
        f"提示词完成，{'并行' if not prevent_drift else '顺序'}渲染分镜（共 {n} 段）…",
    )

    all_video_urls: list[str] = []
    style_ref_image: str | None = None
    max_dur = settings.kling_max_duration

    if not prevent_drift:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: list[str | None] = [None] * n
        max_w = max(1, min(int(getattr(settings, "kling_parallel_max_workers", 3)), n))

        def _kling_scene(idx: int) -> tuple[int, str | None]:
            s = scenes[idx]
            prompt = video_prompts[idx]
            scene_dur = float(s.get("duration") or default_scene_duration)
            try:
                u = _generate_clips_for_one_scene(
                    prompt,
                    scene_dur,
                    max_dur,
                    None,
                    False,
                    settings,
                )
                return idx, u
            except Exception:
                logger.exception("kling parallel scene %s", idx)
                return idx, None

        done = 0
        with ThreadPoolExecutor(max_workers=max_w) as ex:
            futs = [ex.submit(_kling_scene, i) for i in range(n)]
            for fut in as_completed(futs):
                idx, url = fut.result()
                done += 1
                sid = scenes[idx].get("id")
                if sid:
                    if url:
                        _db_update_scene_video(sid, url, "done")
                    else:
                        _db_update_scene_video(sid, None, "error")
                results[idx] = url
                pct = 15 + int((done / max(n, 1)) * 72)
                _set_progress(file_id, min(88, pct), f"分镜并行 {done}/{n}…")

        if any(r is None for r in results):
            _set_progress(file_id, 50, "某分镜可灵返回空，准备降级…")
            return None
        all_video_urls = [results[i] for i in range(n)]
    else:
        for idx, (s, prompt) in enumerate(zip(scenes, video_prompts)):
            scene_dur = float(s.get("duration") or default_scene_duration)
            pct = 15 + int((idx / max(n, 1)) * 72)
            ref_label = "（风格延续）" if style_ref_image else ""
            _set_progress(
                file_id,
                min(88, pct),
                f"分镜 {idx + 1}/{n} · 约 {scene_dur:.0f}s{ref_label}",
            )

            url = _generate_clips_for_one_scene(
                prompt,
                scene_dur,
                max_dur,
                style_ref_image,
                True,
                settings,
            )
            if url is None:
                _set_progress(file_id, pct, f"分镜 {idx + 1} 可灵返回空，准备降级…")
                return None

            all_video_urls.append(url)
            if s.get("id"):
                _db_update_scene_video(s["id"], url, "done")

            style_ref_image = _extract_last_frame(url)

    _set_progress(file_id, 90, f"合并 {len(all_video_urls)} 段分镜视频…")
    if len(all_video_urls) == 1:
        return all_video_urls[0]

    final_url = _concat_video_segments(all_video_urls, settings)
    return final_url or all_video_urls[0]


def _generate_with_storyboard(
    file_id: str,
    scenes_per_batch: int = 3,
    prevent_drift: bool = True,
    default_scene_duration: float = 5.0,
) -> None:
    """
    完整视频生成流程，三层降级：
      1. 可灵分镜流水线（LLM 提示词 → 分批 → 切子段 → image2video 风格延续）
      2. 硅基流动（单段整体生成，Wan2.1-T2V）
      3. 演示模式（无 API key 时的 stub）
    任意一层失败则自动降级到下一层，不直接返回 error。
    """
    import time

    from app.config import get_settings

    settings = get_settings()

    try:
        # ── Step 1: 读取分镜 ──────────────────────────────────────────────────
        _set_progress(file_id, 2, "正在读取分镜数据…")
        scenes = _db_read_scenes(file_id)

        if not scenes:
            _set_progress(file_id, 3, "未找到分镜，使用文件描述生成…")
            scenes = [{"id": None, "script": f"A cinematic video for project {file_id}", "duration": None, "order_index": 0}]

        # ══════════════════════════════════════════════════════════════════════
        # 层 1：可灵分镜流水线
        # ══════════════════════════════════════════════════════════════════════
        if settings.kling_access_key and settings.kling_secret_key:
            _set_progress(file_id, 4, "正在使用可灵生成分镜视频…")
            try:
                final_url = _run_kling_storyboard(
                    file_id, scenes, scenes_per_batch, prevent_drift, default_scene_duration, settings
                )
            except Exception as e:
                final_url = None
                _set_progress(file_id, 8, f"可灵异常（{e}），切换硅基流动…")

            if final_url is not None:
                _set_progress(file_id, 100, "视频生成完成！", status="done", preview_url=final_url)
                _sync_update_file(file_id, "done", final_url)
                return

            _set_progress(file_id, 10, "可灵生成失败，降级到硅基流动…")

        # ══════════════════════════════════════════════════════════════════════
        # 层 2：硅基流动（按分镜多段 T2V，每段约 5s，再合并；避免单次超大 num_frames 被截成短视频）
        # ══════════════════════════════════════════════════════════════════════
        if settings.siliconflow_api_key:
            _set_progress(file_id, 11, "正在使用硅基流动按分镜生成视频…")
            final_url_sf: str | None = None
            try:
                final_url_sf = _run_siliconflow_storyboard(
                    file_id,
                    scenes,
                    default_scene_duration,
                    prevent_drift,
                    settings,
                )
            except Exception as e:
                logger.exception("siliconflow storyboard: %s", e)
                _set_progress(file_id, 10, f"硅基流动异常（{e}），降级到演示模式…")

            if final_url_sf is not None:
                _set_progress(file_id, 100, "视频生成完成！", status="done", preview_url=final_url_sf)
                _sync_update_file(file_id, "done", final_url_sf)
                return

            _set_progress(file_id, 12, "硅基流动生成失败，降级到演示模式…")

        # ══════════════════════════════════════════════════════════════════════
        # 层 3：演示模式（无可用 API key 或上层均失败）
        # ══════════════════════════════════════════════════════════════════════
        _set_progress(file_id, 15, "演示模式运行中（无可用 API key）…")
        for pct, label in [(25, "初始化资源…"), (50, "处理素材…"), (75, "合成场景…"), (90, "导出封装…")]:
            time.sleep(0.25)
            _set_progress(file_id, pct, label)
        time.sleep(0.2)
        _set_progress(file_id, 100, "完成（演示模式）", status="done")
        _sync_update_file(file_id, "done", None)

    except Exception as e:
        _set_progress(file_id, 0, str(e), status="error")
        _sync_update_file(file_id, "error", None)


@router.post("/files/{file_id}/generate", response_model=GenerateResponse)
async def generate_video(
    file_id: str,
    current_user: CurrentUser,
    db: DB,
    background_tasks: BackgroundTasks,
    body: GenerateRequest = GenerateRequest(),
):
    file = await _get_file_or_404(file_id, current_user.id, db)
    file.status = "generating"
    await db.commit()

    job_id = str(_uuid.uuid4())
    # 清除旧进度
    try:
        import redis.asyncio as aioredis
        from app.config import get_settings as _gs
        r = aioredis.from_url(_gs().redis_url, decode_responses=True)
        await r.delete(f"gen_progress:{file_id}")
        await r.aclose()
    except Exception:
        pass

    # 启动分镜生成流水线（scenes_per_batch、prevent_style_drift 均由请求体控制）
    # 如果前端只传了 duration，则用它覆盖 default_scene_duration
    scene_duration = body.default_scene_duration if body.default_scene_duration != 5.0 else float(body.duration)
    background_tasks.add_task(
        _generate_with_storyboard,
        file_id,
        body.scenes_per_batch,
        body.prevent_style_drift,
        scene_duration,
    )
    est = max(45, min(3600, (file.scene_count or 1) * (90 if body.prevent_style_drift else 55)))
    return GenerateResponse(job_id=job_id, estimated_seconds=est)


async def _sse_generator(file_id: str, job_id: str) -> AsyncIterator[str]:
    """
    实时推送视频生成进度。
    优先读取 Redis 中后台任务写入的真实进度；
    Redis 不可用时退化为轮询 DB files.status。
    """
    import redis.asyncio as aioredis
    from app.config import get_settings

    settings = get_settings()
    max_polls = 900  # 最多 ~30 分钟 (900 × 2s)，长分镜生成避免 SSE 先超时

    redis_client = None
    try:
        redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    except Exception:
        pass

    try:
        for i in range(max_polls):
            # ── 1. 读 Redis 实时进度 ──────────────────────────────
            redis_data: dict | None = None
            if redis_client:
                try:
                    raw = await redis_client.get(f"gen_progress:{file_id}")
                    if raw:
                        redis_data = _json.loads(raw)
                except Exception:
                    pass

            if redis_data:
                r_status = redis_data.get("status", "generating")
                r_progress = int(redis_data.get("progress", 0))
                r_step = redis_data.get("step", "")
                r_preview = redis_data.get("preview_url")

                if r_status == "done":
                    yield f"data: {GenerateStatusResponse(status='done', progress=100, job_id=job_id, preview_url=r_preview).model_dump_json()}\n\n"
                    return
                if r_status == "error":
                    yield f"data: {GenerateStatusResponse(status='error', job_id=job_id, error=r_step or 'Generation failed').model_dump_json()}\n\n"
                    return

                yield f"data: {GenerateStatusResponse(status='generating', progress=r_progress, job_id=job_id, error=r_step or None).model_dump_json()}\n\n"
                await asyncio.sleep(2)
                continue

            # ── 2. Redis 无数据，从 DB 判断终态 ───────────────────
            db_status: str | None = None
            db_preview: str | None = None
            try:
                async with AsyncSessionLocal() as session:
                    result = await session.execute(select(File).where(File.id == file_id))
                    f = result.scalar_one_or_none()
                    if f:
                        db_status = f.status
                        db_preview = f.preview_url
            except Exception:
                pass

            if db_status == "done":
                yield f"data: {GenerateStatusResponse(status='done', progress=100, job_id=job_id, preview_url=db_preview).model_dump_json()}\n\n"
                return
            if db_status == "error":
                yield f"data: {GenerateStatusResponse(status='error', job_id=job_id, error='Generation failed').model_dump_json()}\n\n"
                return

            # 后台任务还未写入第一个进度，发送等待状态
            yield f"data: {GenerateStatusResponse(status='generating', progress=2, job_id=job_id).model_dump_json()}\n\n"
            await asyncio.sleep(2)

        yield f"data: {GenerateStatusResponse(status='error', job_id=job_id, error='Timeout').model_dump_json()}\n\n"
    finally:
        if redis_client:
            try:
                await redis_client.aclose()
            except Exception:
                pass


@router.get("/files/{file_id}/status")
async def get_generate_status(file_id: str, job_id: str, current_user: CurrentUser, db: DB):
    await _get_file_or_404(file_id, current_user.id, db)
    return StreamingResponse(
        _sse_generator(file_id, job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
