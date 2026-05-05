"""可灵（Kling AI）视频生成 provider。

本 provider 仅负责"单段调用"：
- GENERATE_VIDEO ：text2video
- IMAGE_TO_VIDEO ：需要 `ref_image`（base64 data URL 或公开 URL）

不负责：进度推送、ffmpeg 拼接、风格延续多轮编排 —— 这些归编排层（pipeline / scenes router）。
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from app.config import get_settings

from ..types import CallStatus, ModelAction, ProviderName, RenderRequest, RenderResult
from .base import BaseProvider

logger = logging.getLogger(__name__)


_SUPPORTED = {ModelAction.GENERATE_VIDEO, ModelAction.IMAGE_TO_VIDEO}


class KlingProvider(BaseProvider):
    name = ProviderName.KLING

    def supports(self, action: ModelAction) -> bool:
        return action in _SUPPORTED

    def is_available(self) -> bool:
        s = get_settings()
        return bool(s.kling_access_key and s.kling_secret_key)

    def call(self, request: RenderRequest) -> RenderResult:
        settings = get_settings()
        params = dict(request.params or {})
        prompt = str(params.get("prompt") or "").strip()
        if not prompt:
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                error="missing prompt",
            )

        duration = int(params.get("duration") or params.get("duration_s") or 5)
        aspect_ratio = str(params.get("aspect_ratio") or "16:9")
        mode = str(params.get("mode") or "std")
        model = request.model_hint or settings.kling_model
        negative_prompt = str(params.get("negative_prompt") or "").strip()

        if request.action == ModelAction.IMAGE_TO_VIDEO:
            ref_image = params.get("ref_image")
            if not ref_image:
                return RenderResult(
                    status=CallStatus.FAILED,
                    provider=self.name,
                    model=model,
                    error="image_to_video requires ref_image",
                )
            i2v_payload = {
                "model_name": model,
                "image": ref_image,
                "prompt": prompt,
                "duration": str(duration),
                "aspect_ratio": aspect_ratio,
                "mode": mode,
            }
            if negative_prompt:
                i2v_payload["negative_prompt"] = negative_prompt
            url = _submit_and_poll(
                endpoint_path="/v1/videos/image2video",
                payload=i2v_payload,
                poll_path_tpl="/v1/videos/image2video/{task_id}",
                settings=settings,
                timeout_s=request.timeout_s,
            )
        else:
            t2v_payload = {
                "model_name": model,
                "prompt": prompt,
                "duration": str(duration),
                "aspect_ratio": aspect_ratio,
                "mode": mode,
            }
            if negative_prompt:
                t2v_payload["negative_prompt"] = negative_prompt
            url = _submit_and_poll(
                endpoint_path="/v1/videos/text2video",
                payload=t2v_payload,
                poll_path_tpl="/v1/videos/text2video/{task_id}",
                settings=settings,
                timeout_s=request.timeout_s,
            )

        if not url:
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                model=model,
                error="kling returned empty url",
            )

        return RenderResult(
            status=CallStatus.SUCCEEDED,
            output={"video_url": url, "duration_s": duration, "aspect_ratio": aspect_ratio},
            provider=self.name,
            model=model,
        )


def _kling_jwt(access_key: str, secret_key: str) -> str:
    import jwt as pyjwt

    payload = {
        "iss": access_key,
        "exp": int(time.time()) + 1800,
        "nbf": int(time.time()) - 5,
    }
    return pyjwt.encode(
        payload,
        secret_key,
        algorithm="HS256",
        headers={"alg": "HS256", "typ": "JWT"},
    )


def _submit_and_poll(
    *,
    endpoint_path: str,
    payload: dict,
    poll_path_tpl: str,
    settings,
    timeout_s: Optional[float] = None,
) -> Optional[str]:
    """提交可灵任务 + 轮询直到 succeed/failed/超时。"""

    try:
        token = _kling_jwt(settings.kling_access_key, settings.kling_secret_key)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        submit_res = requests.post(
            f"{settings.kling_base_url}{endpoint_path}",
            json=payload,
            headers=headers,
            timeout=30,
        )
        if submit_res.status_code != 200:
            logger.warning(
                "kling submit failed http %s body=%s",
                submit_res.status_code,
                submit_res.text[:200],
            )
            return None
        resp_json = submit_res.json() if "application/json" in submit_res.headers.get("content-type", "") else {}
        if resp_json.get("code", -1) != 0:
            logger.warning("kling submit non-zero code: %s", resp_json)
            return None

        task_id = resp_json["data"]["task_id"]
        poll_path = poll_path_tpl.format(task_id=task_id)
        poll_iv = float(getattr(settings, "video_api_poll_interval_sec", 2.0) or 2.0)
        poll_iv = max(0.5, min(poll_iv, 10.0))

        # 默认上限：单次最多 ~15 分钟（300 帧 × poll_iv 2s = 600s + 缓冲）
        max_polls = int(((timeout_s or 900.0)) / poll_iv) + 10

        for _ in range(max_polls):
            time.sleep(poll_iv)
            try:
                poll_token = _kling_jwt(settings.kling_access_key, settings.kling_secret_key)
                poll_res = requests.get(
                    f"{settings.kling_base_url}{poll_path}",
                    headers={"Authorization": f"Bearer {poll_token}"},
                    timeout=15,
                )
            except Exception:
                continue

            if poll_res.status_code != 200:
                continue

            data = poll_res.json().get("data", {})
            task_status = data.get("task_status", "")
            if task_status == "succeed":
                videos = (data.get("task_result") or {}).get("videos", [])
                if not videos:
                    return None
                return videos[0].get("url")
            if task_status == "failed":
                logger.warning("kling task failed: %s", data)
                return None

    except Exception:
        logger.exception("kling submit/poll unexpected error")
    return None
