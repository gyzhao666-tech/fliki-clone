import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select

from app.config import get_settings
from app.deps import DB, CurrentUser
from app.models.voice import Voice, VoiceClone, VoiceCustom
from app.schemas import (
    CreateVoiceCustomRequest,
    MessageResponse,
    VoiceCloneOut,
    VoiceCustomOut,
    VoiceOut,
)
from app.utils.tasks import clone_voice_task

router = APIRouter(tags=["Voices"])
settings = get_settings()


async def _siliconflow_tts(text: str, voice_ref: str) -> bytes:
    """
    调用硅基流动 TTS 接口生成音频（返回 mp3 bytes）。
    文档：https://docs.siliconflow.cn/cn/api-reference/audio/create-speech
    voice_ref 格式：{speaker_name}:{reference_audio_url}  或直接传内置 speaker name
    """
    headers = {
        "Authorization": f"Bearer {settings.siliconflow_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.tts_model,         # FishAudio/fish-speech-1.5
        "input": text,
        "voice": voice_ref,
        "response_format": "mp3",
        "speed": 1.0,
        "gain": 0.0,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{settings.siliconflow_base_url}/audio/speech",
            json=payload,
            headers=headers,
        )
        if res.status_code != 200:
            raise HTTPException(status_code=502, detail=f"TTS 服务错误: {res.text}")
        return res.content


# ── Voice Library ─────────────────────────────────────────────────────────────
@router.get("/voices", response_model=list[VoiceOut])
async def list_voices(
    db: DB,
    lang: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
):
    stmt = select(Voice)
    if lang:
        stmt = stmt.where(Voice.lang == lang)
    if q:
        stmt = stmt.where(Voice.name.ilike(f"%{q}%"))
    result = await db.execute(stmt.order_by(Voice.name))
    return [
        VoiceOut(
            id=v.id, name=v.name, lang=v.lang, accent=v.accent,
            style=v.style, gender=v.gender, tags=v.tags or [],
            preview_url=v.preview_url, is_premium=v.is_premium,
        )
        for v in result.scalars().all()
    ]


@router.post("/voices/{voice_id}/preview")
async def preview_voice(voice_id: str, db: DB):
    """
    用硅基流动 TTS 实时合成一段示例音频并返回 mp3 流。
    若声音记录有 preview_url 则直接重定向，否则实时生成。
    """
    result = await db.execute(select(Voice).where(Voice.id == voice_id))
    voice = result.scalar_one_or_none()
    if not voice:
        raise HTTPException(status_code=404, detail="Voice not found")

    # 优先返回预存的试听 URL
    if voice.preview_url:
        return {"preview_url": voice.preview_url}

    if not settings.siliconflow_api_key:
        raise HTTPException(status_code=503, detail="SILICONFLOW_API_KEY 未配置")

    sample_text = f"大家好，我是 {voice.name}，这是我的声音示例。"
    # provider_voice_id 存储硅基流动 TTS speaker 名称，如 "anna" / "xiaoyan"
    voice_ref = voice.provider_voice_id or "anna"

    audio_bytes = await _siliconflow_tts(sample_text, voice_ref)
    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={"Content-Disposition": f'inline; filename="{voice_id}.mp3"'},
    )


# ── Voice Clone ───────────────────────────────────────────────────────────────
@router.post("/voices/clone", response_model=VoiceCloneOut, status_code=status.HTTP_201_CREATED)
async def clone_voice(
    current_user: CurrentUser,
    db: DB,
    name: str = Query(...),
    file: UploadFile = File(...),
):
    content = await file.read()
    s3_key = f"voice-clones/{current_user.id}/{uuid.uuid4()}.{file.filename.split('.')[-1]}"

    from app.utils.storage import upload_bytes
    audio_url = upload_bytes(s3_key, content, file.content_type or "audio/mpeg")

    clone = VoiceClone(user_id=current_user.id, name=name, audio_url=audio_url, status="processing")
    db.add(clone)
    await db.commit()
    await db.refresh(clone)

    clone_voice_task.delay(clone.id, audio_url, name)
    return VoiceCloneOut(id=clone.id, name=clone.name, status=clone.status, audio_url=clone.audio_url, created_at=clone.created_at)


@router.get("/voices/clone", response_model=list[VoiceCloneOut])
async def list_clones(current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(VoiceClone)
        .where(VoiceClone.user_id == current_user.id)
        .order_by(VoiceClone.created_at.desc())
    )
    return [
        VoiceCloneOut(id=c.id, name=c.name, status=c.status, audio_url=c.audio_url, created_at=c.created_at)
        for c in result.scalars().all()
    ]


@router.delete("/voices/clone/{clone_id}", response_model=MessageResponse)
async def delete_clone(clone_id: str, current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(VoiceClone).where(VoiceClone.id == clone_id, VoiceClone.user_id == current_user.id)
    )
    clone = result.scalar_one_or_none()
    if not clone:
        raise HTTPException(status_code=404, detail="Clone not found")
    await db.delete(clone)
    await db.commit()
    return MessageResponse(message="Voice clone deleted")


# ── Custom Voice ──────────────────────────────────────────────────────────────
@router.post("/voices/custom", response_model=VoiceCustomOut, status_code=status.HTTP_201_CREATED)
async def create_custom_voice(body: CreateVoiceCustomRequest, current_user: CurrentUser, db: DB):
    custom = VoiceCustom(user_id=current_user.id, name=body.name, prompt=body.prompt, status="processing")
    db.add(custom)
    await db.commit()
    await db.refresh(custom)
    # In production: trigger AI generation via Celery task
    return VoiceCustomOut(
        id=custom.id, name=custom.name, prompt=custom.prompt,
        status=custom.status, preview_url=custom.preview_url, created_at=custom.created_at,
    )


@router.get("/voices/custom", response_model=list[VoiceCustomOut])
async def list_custom_voices(current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(VoiceCustom)
        .where(VoiceCustom.user_id == current_user.id)
        .order_by(VoiceCustom.created_at.desc())
    )
    return [
        VoiceCustomOut(
            id=c.id, name=c.name, prompt=c.prompt,
            status=c.status, preview_url=c.preview_url, created_at=c.created_at,
        )
        for c in result.scalars().all()
    ]
