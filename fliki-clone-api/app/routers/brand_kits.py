from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import DB, CurrentUser
from app.models.brand_kit import BrandKit
from app.schemas import BrandKitOut, CreateBrandKitRequest, MessageResponse, PatchBrandKitRequest

router = APIRouter(tags=["Brand Kits"])


def _kit_to_out(k: BrandKit) -> BrandKitOut:
    return BrandKitOut(
        id=k.id, name=k.name, logo_url=k.logo_url,
        primary_color=k.primary_color, secondary_color=k.secondary_color,
        font=k.font, created_at=k.created_at,
    )


@router.get("/brand-kits", response_model=list[BrandKitOut])
async def list_brand_kits(current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(BrandKit).where(BrandKit.user_id == current_user.id).order_by(BrandKit.created_at.desc())
    )
    return [_kit_to_out(k) for k in result.scalars().all()]


@router.post("/brand-kits", response_model=BrandKitOut, status_code=status.HTTP_201_CREATED)
async def create_brand_kit(body: CreateBrandKitRequest, current_user: CurrentUser, db: DB):
    kit = BrandKit(
        user_id=current_user.id,
        name=body.name,
        primary_color=body.primary_color,
        secondary_color=body.secondary_color,
        font=body.font,
    )
    db.add(kit)
    await db.commit()
    await db.refresh(kit)
    return _kit_to_out(kit)


@router.patch("/brand-kits/{kit_id}", response_model=BrandKitOut)
async def update_brand_kit(kit_id: str, body: PatchBrandKitRequest, current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(BrandKit).where(BrandKit.id == kit_id, BrandKit.user_id == current_user.id)
    )
    kit = result.scalar_one_or_none()
    if not kit:
        raise HTTPException(status_code=404, detail="Brand kit not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(kit, field, value)
    await db.commit()
    await db.refresh(kit)
    return _kit_to_out(kit)


@router.delete("/brand-kits/{kit_id}", response_model=MessageResponse)
async def delete_brand_kit(kit_id: str, current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(BrandKit).where(BrandKit.id == kit_id, BrandKit.user_id == current_user.id)
    )
    kit = result.scalar_one_or_none()
    if not kit:
        raise HTTPException(status_code=404, detail="Brand kit not found")
    await db.delete(kit)
    await db.commit()
    return MessageResponse(message="Brand kit deleted")
