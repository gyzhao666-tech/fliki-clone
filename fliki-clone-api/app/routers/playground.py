"""
Playground 路由：文字→图像生成
使用硅基流动图像生成 API（OpenAI images 兼容格式）
支持模型：black-forest-labs/FLUX.1-schnell / FLUX.1-dev / Kolors / SD3.5 等
"""
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.config import get_settings
from app.deps import DB, CurrentUser
from app.models.playground import PlaygroundGen
from app.schemas import MessageResponse, PlaygroundGenOut, PlaygroundImageRequest

router = APIRouter(tags=["Playground"])
settings = get_settings()

# 硅基流动图像尺寸映射（ratio → width x height）
RATIO_SIZE_MAP = {
    "1:1":  {"width": 1024, "height": 1024},
    "16:9": {"width": 1280, "height": 720},
    "9:16": {"width": 720,  "height": 1280},
    "4:3":  {"width": 1024, "height": 768},
    "3:4":  {"width": 768,  "height": 1024},
    "21:9": {"width": 1680, "height": 720},
}

# 前端 model 名称 → 硅基流动 model ID
MODEL_MAP = {
    "z-turbo":   "black-forest-labs/FLUX.1-schnell",
    "z-pro":     "black-forest-labs/FLUX.1-dev",
    "kolors":    "Kwai-Kolors/Kolors",
    "sd35":      "stabilityai/stable-diffusion-3-5-large",
    "flux-schnell": "black-forest-labs/FLUX.1-schnell",
}


async def _siliconflow_image_gen(prompt: str, model_alias: str, ratio: str, style: str | None) -> str:
    """
    调用硅基流动图像生成接口，返回图片 URL。
    文档：https://docs.siliconflow.cn/cn/api-reference/images/create-images
    """
    if not settings.siliconflow_api_key:
        raise HTTPException(status_code=503, detail="SILICONFLOW_API_KEY 未配置")

    sf_model = MODEL_MAP.get(model_alias, settings.image_model)
    size_info = RATIO_SIZE_MAP.get(ratio, RATIO_SIZE_MAP["16:9"])

    full_prompt = f"{style + ' style, ' if style else ''}{prompt}"

    payload = {
        "model": sf_model,
        "prompt": full_prompt,
        "image_size": f"{size_info['width']}x{size_info['height']}",
        "batch_size": 1,
        "num_inference_steps": 20,
    }
    headers = {
        "Authorization": f"Bearer {settings.siliconflow_api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            res = await client.post(
                f"{settings.siliconflow_base_url}/images/generations",
                json=payload,
                headers=headers,
            )
            res.raise_for_status()
            data = res.json()
            return data["images"][0]["url"]
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"SiliconFlow 图像生成错误: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"图像生成异常: {str(e)}")


@router.post("/playground/image", response_model=PlaygroundGenOut, status_code=status.HTTP_201_CREATED)
async def generate_image(body: PlaygroundImageRequest, current_user: CurrentUser, db: DB):
    """文字→图像生成（同步，直接返回结果 URL）。"""
    gen = PlaygroundGen(
        user_id=current_user.id,
        prompt=body.prompt,
        model=body.model,
        ratio=body.ratio,
        style=body.style,
        status="pending",
    )
    db.add(gen)
    await db.commit()
    await db.refresh(gen)

    # 直接同步调用（图像生成通常 5–30s，可接受）
    try:
        result_url = await _siliconflow_image_gen(body.prompt, body.model, body.ratio, body.style)
        gen.result_url = result_url
        gen.status = "done"
    except HTTPException:
        gen.status = "error"
        await db.commit()
        raise
    finally:
        await db.commit()
        await db.refresh(gen)

    return PlaygroundGenOut(
        id=gen.id, prompt=gen.prompt, model=gen.model, ratio=gen.ratio,
        style=gen.style, result_url=gen.result_url, status=gen.status, created_at=gen.created_at,
    )


@router.get("/playground/history", response_model=list[PlaygroundGenOut])
async def get_history(
    current_user: CurrentUser,
    db: DB,
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0),
):
    result = await db.execute(
        select(PlaygroundGen)
        .where(PlaygroundGen.user_id == current_user.id)
        .order_by(PlaygroundGen.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [
        PlaygroundGenOut(
            id=g.id, prompt=g.prompt, model=g.model, ratio=g.ratio,
            style=g.style, result_url=g.result_url, status=g.status, created_at=g.created_at,
        )
        for g in result.scalars().all()
    ]


@router.delete("/playground/history/{gen_id}", response_model=MessageResponse)
async def delete_history(gen_id: str, current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(PlaygroundGen).where(PlaygroundGen.id == gen_id, PlaygroundGen.user_id == current_user.id)
    )
    gen = result.scalar_one_or_none()
    if not gen:
        raise HTTPException(status_code=404, detail="Record not found")
    await db.delete(gen)
    await db.commit()
    return MessageResponse(message="History record deleted")
