from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.deps import DB, CurrentUser
from app.models.export_job import ExportJob
from app.models.file import File
from app.schemas import ExportJobOut, ExportRequest, MessageResponse
from app.utils.tasks import export_file_task

router = APIRouter(tags=["Exports"])


def _job_to_out(j: ExportJob, title: str = "") -> ExportJobOut:
    return ExportJobOut(
        id=j.id,
        file_id=j.file_id,
        title=title,
        format=j.format,
        status=j.status,
        file_url=j.file_url,
        file_size=j.file_size,
        created_at=j.created_at,
    )


@router.post("/files/{file_id}/export", response_model=ExportJobOut, status_code=status.HTTP_201_CREATED)
async def export_file(file_id: str, body: ExportRequest, current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(File).where(File.id == file_id, File.user_id == current_user.id, File.deleted_at.is_(None))
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="File not found")

    job = ExportJob(file_id=file_id, user_id=current_user.id, format=body.format, status="pending")
    db.add(job)
    await db.commit()
    await db.refresh(job)

    export_file_task.delay(job.id, file_id, body.format)
    return _job_to_out(job)


@router.get("/exports", response_model=list[ExportJobOut])
async def list_exports(current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(ExportJob, File.title)
        .join(File, File.id == ExportJob.file_id)
        .where(ExportJob.user_id == current_user.id)
        .order_by(ExportJob.created_at.desc())
    )
    return [_job_to_out(job, title=title) for job, title in result.all()]


@router.get("/exports/{job_id}/download")
async def download_export(job_id: str, current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(ExportJob).where(ExportJob.id == job_id, ExportJob.user_id == current_user.id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Export not found")
    if job.status != "done" or not job.file_url:
        raise HTTPException(status_code=400, detail="Export not ready")

    from app.utils.storage import generate_presigned_download_url
    s3_key = job.file_url.split("/")[-1]
    signed_url = generate_presigned_download_url(s3_key)
    return RedirectResponse(url=signed_url)


@router.delete("/exports/{job_id}", response_model=MessageResponse)
async def delete_export(job_id: str, current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(ExportJob).where(ExportJob.id == job_id, ExportJob.user_id == current_user.id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Export not found")
    await db.delete(job)
    await db.commit()
    return MessageResponse(message="Export deleted")
