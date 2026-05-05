from typing import Optional

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.deps import DB
from app.models.template import Template
from app.schemas import TemplateOut
from app.services.template_modes import get_template_mode

router = APIRouter(tags=["Templates"])


@router.get("/templates", response_model=list[TemplateOut])
async def list_templates(
    db: DB,
    category: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
):
    stmt = select(Template)
    if category:
        stmt = stmt.where(Template.category == category)
    if q:
        stmt = stmt.where(Template.title.ilike(f"%{q}%"))
    result = await db.execute(stmt.order_by(Template.uses_count.desc()))
    return [
        TemplateOut(
            id=t.id, title=t.title, category=t.category,
            thumbnail_url=t.thumbnail_url, preview_url=t.preview_url,
            duration=t.duration, lang=t.lang, uses_count=t.uses_count,
            is_premium=bool(t.is_premium),
            config_json=get_template_mode(t.id, t.title),
        )
        for t in result.scalars().all()
    ]


@router.get("/templates/{template_id}", response_model=TemplateOut)
async def get_template(template_id: str, db: DB):
    from fastapi import HTTPException
    result = await db.execute(select(Template).where(Template.id == template_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    return TemplateOut(
        id=t.id, title=t.title, category=t.category,
        thumbnail_url=t.thumbnail_url, preview_url=t.preview_url,
        duration=t.duration, lang=t.lang, uses_count=t.uses_count,
        is_premium=bool(t.is_premium),
        config_json=get_template_mode(t.id, t.title),
    )
