"""
AI 辅助路由：脚本生成 / 改写 / 翻译
全部使用硅基流动 SiliconFlow（OpenAI 兼容接口）
"""
from fastapi import APIRouter, HTTPException
from app.config import get_settings
from app.deps import CurrentUser
from app.schemas import (
    AIScriptRequest, AIScriptResponse,
    AIRewriteRequest, AIRewriteResponse,
    AITranslateRequest, AITranslateResponse,
)

router = APIRouter(tags=["AI"])
settings = get_settings()


async def _siliconflow_chat(messages: list[dict], max_tokens: int = 1024) -> str:
    """
    调用硅基流动 LLM Chat Completion（OpenAI 兼容格式）。
    支持模型：deepseek-ai/DeepSeek-V3 / Qwen/Qwen2.5-72B-Instruct / THUDM/GLM-4 等
    """
    if not settings.siliconflow_api_key:
        raise HTTPException(status_code=503, detail="SILICONFLOW_API_KEY 未配置")

    import httpx
    headers = {
        "Authorization": f"Bearer {settings.siliconflow_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            res = await client.post(
                f"{settings.siliconflow_base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            res.raise_for_status()
            return res.json()["choices"][0]["message"]["content"].strip()
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        body = ""
        try:
            body = (e.response.text or "")[:1200]
        except Exception:
            pass
        model = settings.llm_model
        if code in (401, 403):
            raise HTTPException(
                status_code=502,
                detail=(
                    f"硅基流动拒绝访问（HTTP {code}）：请打开 https://cloud.siliconflow.cn 检查 "
                    f"① API 密钥是否正确、是否过期；② 账户余额；③ 当前密钥是否有权使用模型「{model}」。"
                    + (f" 上游返回：{body}" if body else "")
                ),
            )
        if code == 429:
            raise HTTPException(
                status_code=502,
                detail=f"硅基流动请求过于频繁（429），请稍后重试。{body[:300]}",
            )
        raise HTTPException(
            status_code=502,
            detail=f"硅基流动错误 HTTP {code}：{body or e!s}",
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail=f"无法连接硅基流动（{settings.siliconflow_base_url}）：{e!s}",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI 服务异常: {e!s}")


@router.post("/ai/script", response_model=AIScriptResponse)
async def generate_script(body: AIScriptRequest, current_user: CurrentUser):
    """给定主题，用 AI 生成视频脚本。"""
    duration_sec = body.duration or 60
    # 每个场景约 5 秒，估算场景数量（至少 2 段，最多 20 段）
    scene_count = max(2, min(20, round(duration_sec / 5)))
    messages = [
        {
            "role": "system",
            "content": (
                "你是一名专业视频脚本撰写人，擅长为短视频平台创作简洁有力的解说词。\n"
                f"请将脚本分成恰好 {scene_count} 个场景段落，每段对应约 {round(duration_sec / scene_count)} 秒画面。\n"
                "每段之间必须用一个空行（即两个换行符 \\n\\n）分隔。\n"
                "只输出脚本文本，不要加场景编号、标题或任何额外说明。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"请为以下主题写一段{body.tone or '专业'}风格的视频脚本：\n"
                f"主题：{body.topic}\n"
                f"目标总时长：{duration_sec} 秒，共 {scene_count} 个场景段落\n"
                f"语言：{body.language}\n"
                "只输出脚本文本，段落之间用空行分隔。"
            ),
        },
    ]
    # 场景越多，所需 token 越多，按比例放大上限
    max_tokens = min(1500, 200 + scene_count * 120)
    script = await _siliconflow_chat(messages, max_tokens=max_tokens)
    return AIScriptResponse(script=script)


@router.post("/ai/rewrite", response_model=AIRewriteResponse)
async def rewrite_text(body: AIRewriteRequest, current_user: CurrentUser):
    """按指令改写指定文本。"""
    messages = [
        {
            "role": "system",
            "content": "你是专业文案编辑，按用户指令改写文本，保持原文长度相近，只输出改写结果。",
        },
        {
            "role": "user",
            "content": f"改写要求：{body.instruction}\n\n原文：\n{body.text}",
        },
    ]
    result = await _siliconflow_chat(messages, max_tokens=500)
    return AIRewriteResponse(result=result)


@router.post("/ai/translate", response_model=AITranslateResponse)
async def translate_text(body: AITranslateRequest, current_user: CurrentUser):
    """将文本翻译到目标语言。"""
    messages = [
        {
            "role": "system",
            "content": f"你是专业翻译，请将以下文本翻译为{body.target_language}，只输出译文。",
        },
        {"role": "user", "content": body.text},
    ]
    result = await _siliconflow_chat(messages, max_tokens=600)
    return AITranslateResponse(result=result)
