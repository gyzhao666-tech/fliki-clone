from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import DB, CurrentUser
from app.models.character import Character
from app.schemas import CharacterOut, CreateCharacterRequest, MessageResponse

router = APIRouter(tags=["Characters"])


@router.get("/characters", response_model=list[CharacterOut])
async def list_characters(current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(Character).where(
            (Character.user_id == current_user.id) | (Character.is_default == True)  # noqa: E712
        ).order_by(Character.created_at.desc())
    )
    return [
        CharacterOut(id=c.id, name=c.name, style=c.style, image_url=c.image_url, is_default=bool(c.is_default))
        for c in result.scalars().all()
    ]


@router.post("/characters", response_model=CharacterOut, status_code=status.HTTP_201_CREATED)
async def create_character(body: CreateCharacterRequest, current_user: CurrentUser, db: DB):
    """
    Create a new AI-generated character.
    In production: call an AI avatar generation API, upload result to S3.
    """
    char = Character(
        user_id=current_user.id,
        name=body.name,
        style=body.style,
        is_default=False,
    )
    db.add(char)
    await db.commit()
    await db.refresh(char)
    return CharacterOut(id=char.id, name=char.name, style=char.style, image_url=char.image_url, is_default=False)


@router.delete("/characters/{char_id}", response_model=MessageResponse)
async def delete_character(char_id: str, current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(Character).where(Character.id == char_id, Character.user_id == current_user.id)
    )
    char = result.scalar_one_or_none()
    if not char:
        raise HTTPException(status_code=404, detail="Character not found")
    await db.delete(char)
    await db.commit()
    return MessageResponse(message="Character deleted")
