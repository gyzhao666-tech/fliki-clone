import uuid
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select

from app.deps import DB, CurrentUser
from app.models.asset import Asset
from app.schemas import AssetOut, MessageResponse

router = APIRouter(tags=["Assets"])


@router.get("/assets", response_model=list[AssetOut])
async def search_assets(
    db: DB,
    type: Optional[str] = Query(default=None),  # video|image|music
    q: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),  # pexels|pixabay|user
):
    """
    Search stock assets or user-uploaded assets.
    In production: proxy Pexels / Pixabay / Freesound APIs for stock content.
    """
    stmt = select(Asset).where(Asset.is_stock == True)  # noqa: E712
    if type:
        stmt = stmt.where(Asset.type == type)
    if q:
        stmt = stmt.where(Asset.name.ilike(f"%{q}%"))
    if source:
        stmt = stmt.where(Asset.source == source)

    result = await db.execute(stmt.limit(50))
    return [
        AssetOut(
            id=a.id, type=a.type, name=a.name, url=a.url,
            thumbnail_url=a.thumbnail_url, duration=a.duration, is_stock=a.is_stock,
        )
        for a in result.scalars().all()
    ]


@router.post("/assets/upload", response_model=AssetOut, status_code=status.HTTP_201_CREATED)
async def upload_asset(
    current_user: CurrentUser,
    db: DB,
    file: UploadFile = File(...),
    asset_type: str = Query(default="video"),
):
    content = await file.read()
    ext = file.filename.split(".")[-1] if file.filename else "bin"
    s3_key = f"user-assets/{current_user.id}/{uuid.uuid4()}.{ext}"

    from app.utils.storage import upload_bytes
    url = upload_bytes(s3_key, content, file.content_type or "application/octet-stream")

    asset = Asset(
        user_id=current_user.id,
        type=asset_type,
        name=file.filename or s3_key,
        url=url,
        is_stock=False,
        source="user",
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return AssetOut(
        id=asset.id, type=asset.type, name=asset.name, url=asset.url,
        thumbnail_url=asset.thumbnail_url, duration=asset.duration, is_stock=asset.is_stock,
    )


@router.get("/assets/my", response_model=list[AssetOut])
async def list_my_assets(
    current_user: CurrentUser,
    db: DB,
    type: Optional[str] = Query(default=None),
):
    stmt = select(Asset).where(Asset.user_id == current_user.id)
    if type:
        stmt = stmt.where(Asset.type == type)
    result = await db.execute(stmt.order_by(Asset.created_at.desc()))
    return [
        AssetOut(
            id=a.id, type=a.type, name=a.name, url=a.url,
            thumbnail_url=a.thumbnail_url, duration=a.duration, is_stock=a.is_stock,
        )
        for a in result.scalars().all()
    ]
