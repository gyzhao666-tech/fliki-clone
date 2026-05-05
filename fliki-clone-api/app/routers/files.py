from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select, func

from app.deps import DB, CurrentUser
from app.models.file import File, Folder
from app.models.scene import Scene
from app.schemas import (

    CreateFileRequest,
    CreateFolderRequest,
    FileListResponse,
    FileOut,
    FolderOut,
    MessageResponse,
    PatchFileRequest,
    PatchFolderRequest,
)
from app.services.template_modes import (
    build_template_scenes,
    get_template_mode,
    normalize_template_slot_values,
)

router = APIRouter(tags=["Files"])


# ── Helper ────────────────────────────────────────────────────────────────────
def _effective_thumbnail_url(f: File, first_scene: Optional[Scene]) -> Optional[str]:
    """优先 DB 中的 thumbnail_url；否则用首分镜视频/素材，再退回成片 preview。"""
    if f.thumbnail_url:
        return f.thumbnail_url
    if first_scene:
        if first_scene.video_url:
            return first_scene.video_url
        if first_scene.media_url:
            return first_scene.media_url
    if f.preview_url:
        return f.preview_url
    return None


async def _first_scenes_by_file_id(db: DB, file_ids: list[str]) -> dict[str, Scene]:
    if not file_ids:
        return {}
    result = await db.execute(
        select(Scene)
        .where(Scene.file_id.in_(file_ids))
        .order_by(Scene.file_id, Scene.order_index)
    )
    scenes = result.scalars().all()
    out: dict[str, Scene] = {}
    for s in scenes:
        if s.file_id not in out:
            out[s.file_id] = s
    return out


def _file_to_out(f: File, first_scene: Optional[Scene] = None) -> FileOut:
    return FileOut(
        id=f.id,
        title=f.title,
        thumbnail_url=_effective_thumbnail_url(f, first_scene),
        preview_url=f.preview_url,
        duration=f.duration,
        status=f.status,
        updated_at=f.updated_at,
        scene_count=f.scene_count,
        type=f.type,
        template_id=f.template_id,
        project_type=f.project_type,
        product_name=f.product_name,
        target_market=f.target_market,
        selling_points=f.selling_points_json.splitlines() if f.selling_points_json else [],
        brand_terms=f.brand_terms,
        avoid_terms=f.avoid_terms,
        aspect_ratio=f.aspect_ratio,
        copyright_confirmed=f.copyright_confirmed,
    )


# ── Files CRUD ────────────────────────────────────────────────────────────────
@router.get("/files", response_model=FileListResponse)
async def list_files(
    current_user: CurrentUser,
    db: DB,
    folder_id: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    cursor: Optional[str] = Query(default=None),
    limit: int = Query(default=20, le=100),
):
    stmt = (
        select(File)
        .where(File.user_id == current_user.id, File.deleted_at.is_(None))
        .order_by(File.updated_at.desc())
    )
    if folder_id:
        stmt = stmt.where(File.folder_id == folder_id)
    if q:
        stmt = stmt.where(File.title.ilike(f"%{q}%"))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    if cursor:
        stmt = stmt.where(File.updated_at < cursor)
    stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    files = result.scalars().all()

    first_scenes = await _first_scenes_by_file_id(db, [f.id for f in files])
    next_cursor = str(files[-1].updated_at) if len(files) == limit else None
    return FileListResponse(
        items=[_file_to_out(f, first_scenes.get(f.id)) for f in files],
        total=total,
        next_cursor=next_cursor,
    )


@router.post("/files", response_model=FileOut, status_code=status.HTTP_201_CREATED)
async def create_file(body: CreateFileRequest, current_user: CurrentUser, db: DB):
    file = File(
        user_id=current_user.id,
        title=body.title,
        script=body.script,
        template_id=body.template_id,
        voice_id=body.voice_id,
        language=body.language,
        folder_id=body.folder_id,
        project_type=body.project_type,
        product_name=body.product_name,
        target_market=body.target_market,
        selling_points_json="\n".join(body.selling_points) if body.selling_points else None,
        brand_terms=body.brand_terms,
        avoid_terms=body.avoid_terms,
        aspect_ratio=body.aspect_ratio,
        copyright_confirmed=body.copyright_confirmed,
    )
    db.add(file)
    await db.flush()  # 先 flush 拿到 file.id

    template_mode = get_template_mode(body.template_id or "", body.title) if body.template_id else None
    if template_mode:
        slot_values = normalize_template_slot_values(
            template_mode,
            slot_values=body.template_slot_values,
            title=body.title,
            script=body.script,
            product_name=body.product_name,
            selling_points=body.selling_points,
            target_market=body.target_market,
        )
        template_scenes = build_template_scenes(
            template_mode,
            slot_values,
            fallback_script=body.script,
        )
        for i, scene_data in enumerate(template_scenes):
            db.add(Scene(
                file_id=file.id,
                order_index=i,
                title=scene_data.get("title") or f"Scene {i + 1}",
                script=scene_data.get("script"),
                voice_id=body.voice_id,
                scene_goal=scene_data.get("scene_goal"),
                selling_point=scene_data.get("selling_point"),
                duration=scene_data.get("duration") or body.scene_duration,
                video_prompt=scene_data.get("video_prompt"),
                video_status="pending",
            ))
        file.scene_count = len(template_scenes)
    # 自动从脚本创建 Scene 记录（按段落拆分）
    elif body.script and body.script.strip():
        paragraphs = [p.strip() for p in body.script.split("\n\n") if p.strip()]
        if not paragraphs:
            paragraphs = [body.script.strip()]
        # 若调用方传入了 scene_duration，用它；否则按 10s 兜底
        per_scene_dur = body.scene_duration if body.scene_duration and body.scene_duration > 0 else None
        for i, para in enumerate(paragraphs):
            db.add(Scene(
                file_id=file.id,
                order_index=i,
                title=f"Scene {i + 1}",
                script=para,
                voice_id=body.voice_id,
                duration=per_scene_dur,
            ))
        file.scene_count = len(paragraphs)

    await db.commit()
    await db.refresh(file)
    first_scenes = await _first_scenes_by_file_id(db, [file.id])
    return _file_to_out(file, first_scenes.get(file.id))


@router.get("/files/trash", response_model=FileListResponse)
async def list_trash(current_user: CurrentUser, db: DB):
    stmt = (
        select(File)
        .where(File.user_id == current_user.id, File.deleted_at.isnot(None))
        .order_by(File.deleted_at.desc())
    )
    result = await db.execute(stmt)
    files = result.scalars().all()
    first_scenes = await _first_scenes_by_file_id(db, [f.id for f in files])
    return FileListResponse(
        items=[_file_to_out(f, first_scenes.get(f.id)) for f in files],
        total=len(files),
    )


@router.delete("/files/trash", response_model=MessageResponse)
async def empty_trash(current_user: CurrentUser, db: DB):
    stmt = select(File).where(File.user_id == current_user.id, File.deleted_at.isnot(None))
    result = await db.execute(stmt)
    for f in result.scalars().all():
        await db.delete(f)
    await db.commit()
    return MessageResponse(message="Trash emptied")


@router.get("/files/{file_id}", response_model=FileOut)
async def get_file(file_id: str, current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(File).where(File.id == file_id, File.user_id == current_user.id, File.deleted_at.is_(None))
    )
    file = result.scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    first_scenes = await _first_scenes_by_file_id(db, [file.id])
    return _file_to_out(file, first_scenes.get(file.id))


@router.patch("/files/{file_id}", response_model=FileOut)
async def patch_file(file_id: str, body: PatchFileRequest, current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(File).where(File.id == file_id, File.user_id == current_user.id)
    )
    file = result.scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    if body.title is not None:
        file.title = body.title
    if body.status is not None:
        file.status = body.status
    if body.folder_id is not None:
        file.folder_id = body.folder_id
    await db.commit()
    await db.refresh(file)
    first_scenes = await _first_scenes_by_file_id(db, [file.id])
    return _file_to_out(file, first_scenes.get(file.id))


@router.delete("/files/{file_id}", response_model=MessageResponse)
async def delete_file(file_id: str, current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(File).where(File.id == file_id, File.user_id == current_user.id)
    )
    file = result.scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    file.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return MessageResponse(message="File moved to trash")


@router.post("/files/{file_id}/duplicate", response_model=FileOut, status_code=status.HTTP_201_CREATED)
async def duplicate_file(file_id: str, current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(File).where(File.id == file_id, File.user_id == current_user.id)
    )
    original = result.scalar_one_or_none()
    if not original:
        raise HTTPException(status_code=404, detail="File not found")

    copy = File(
        user_id=current_user.id,
        title=f"{original.title} (Copy)",
        script=original.script,
        template_id=original.template_id,
        voice_id=original.voice_id,
        language=original.language,
        folder_id=original.folder_id,
    )
    db.add(copy)
    await db.flush()

    # Duplicate scenes
    scene_result = await db.execute(
        select(Scene).where(Scene.file_id == original.id).order_by(Scene.order_index)
    )
    for s in scene_result.scalars().all():
        db.add(Scene(
            file_id=copy.id,
            order_index=s.order_index,
            title=s.title,
            script=s.script,
            voice_id=s.voice_id,
            media_url=s.media_url,
            media_type=s.media_type,
            scene_goal=s.scene_goal,
            selling_point=s.selling_point,
            asset_id=s.asset_id,
            duration=s.duration,
            video_prompt=s.video_prompt,
            video_url=s.video_url,
            video_status=s.video_status,
        ))

    copy.scene_count = original.scene_count
    await db.commit()
    await db.refresh(copy)
    first_scenes = await _first_scenes_by_file_id(db, [copy.id])
    return _file_to_out(copy, first_scenes.get(copy.id))


@router.post("/files/{file_id}/restore", response_model=FileOut)
async def restore_file(file_id: str, current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(File).where(File.id == file_id, File.user_id == current_user.id)
    )
    file = result.scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    file.deleted_at = None
    await db.commit()
    await db.refresh(file)
    first_scenes = await _first_scenes_by_file_id(db, [file.id])
    return _file_to_out(file, first_scenes.get(file.id))


@router.post("/files/{file_id}/merge-preview", response_model=FileOut)
async def merge_file_preview(file_id: str, current_user: CurrentUser, db: DB):
    """
    将已生成的分镜视频按顺序拼接为完整成片，写入 files.preview_url。
    适用于各分镜已有 video_url 但成片 URL 缺失的情况。
    """
    result = await db.execute(
        select(File).where(File.id == file_id, File.user_id == current_user.id, File.deleted_at.is_(None))
    )
    file = result.scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    from app.config import get_settings
    from app.routers.scenes import _merge_scene_videos_to_file_preview

    settings = get_settings()
    final_url = _merge_scene_videos_to_file_preview(file_id, settings)
    if not final_url:
        raise HTTPException(
            status_code=400,
            detail="无法合并：请确保至少一个分镜已成功生成视频片段。",
        )

    await db.refresh(file)
    result2 = await db.execute(select(File).where(File.id == file_id))
    file = result2.scalar_one()
    first_scenes = await _first_scenes_by_file_id(db, [file.id])
    return _file_to_out(file, first_scenes.get(file.id))


# ── Folders ───────────────────────────────────────────────────────────────────
@router.post("/folders", response_model=FolderOut, status_code=status.HTTP_201_CREATED)
async def create_folder(body: CreateFolderRequest, current_user: CurrentUser, db: DB):
    folder = Folder(user_id=current_user.id, name=body.name, parent_id=body.parent_id)
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return FolderOut.model_validate(folder)


@router.patch("/folders/{folder_id}", response_model=FolderOut)
async def rename_folder(folder_id: str, body: PatchFolderRequest, current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(Folder).where(Folder.id == folder_id, Folder.user_id == current_user.id)
    )
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    folder.name = body.name
    await db.commit()
    await db.refresh(folder)
    return FolderOut.model_validate(folder)


@router.delete("/folders/{folder_id}", response_model=MessageResponse)
async def delete_folder(folder_id: str, current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(Folder).where(Folder.id == folder_id, Folder.user_id == current_user.id)
    )
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    await db.delete(folder)
    await db.commit()
    return MessageResponse(message="Folder deleted")
