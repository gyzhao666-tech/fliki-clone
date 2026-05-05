"""硅基流动文生视频 provider（Wan2.x 系列）。

仅支持 `GENERATE_VIDEO`；单次约 5s，长镜头由编排层切片后多次调用。
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


class SiliconFlowVideoProvider(BaseProvider):
    name = ProviderName.SILICONFLOW

    def supports(self, action: ModelAction) -> bool:
        return action == ModelAction.GENERATE_VIDEO

    def is_available(self) -> bool:
        return bool(get_settings().siliconflow_api_key)

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

        model = request.model_hint or settings.video_model
        num_frames = int(
            params.get("num_frames")
            or settings.siliconflow_wan_num_frames
            or 81
        )
        num_frames = max(17, num_frames)
        timeout_s = request.timeout_s or 600.0

        url = _submit_and_poll(
            settings=settings,
            model=model,
            prompt=prompt,
            num_frames=num_frames,
            timeout_s=timeout_s,
        )
        if not url:
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                model=model,
                error="siliconflow returned empty url",
            )

        # 大致估时长：每秒 16~24 帧；wan2.x 默认 81 帧 ≈ 5s
        duration_s = float(num_frames) / 16.0
        return RenderResult(
            status=CallStatus.SUCCEEDED,
            output={"video_url": url, "duration_s": duration_s, "num_frames": num_frames},
            provider=self.name,
            model=model,
        )


def _submit_and_poll(
    *,
    settings,
    model: str,
    prompt: str,
    num_frames: int,
    timeout_s: float,
) -> Optional[str]:
    try:
        submit_res = requests.post(
            f"{settings.siliconflow_base_url}/video/submit",
            json={"model": model, "prompt": prompt, "num_frames": num_frames},
            headers={"Authorization": f"Bearer {settings.siliconflow_api_key}"},
            timeout=30,
        )
        if submit_res.status_code != 200:
            logger.warning(
                "siliconflow submit failed http %s body=%s",
                submit_res.status_code,
                submit_res.text[:200],
            )
            return None

        request_id = submit_res.json().get("requestId")
        if not request_id:
            return None

        poll_iv = float(getattr(settings, "video_api_poll_interval_sec", 2.0) or 2.0)
        poll_iv = max(0.5, min(poll_iv, 10.0))
        max_polls = int(timeout_s / poll_iv) + 10

        for _ in range(max_polls):
            time.sleep(poll_iv)
            try:
                status_res = requests.post(
                    f"{settings.siliconflow_base_url}/video/status",
                    json={"requestId": request_id},
                    headers={"Authorization": f"Bearer {settings.siliconflow_api_key}"},
                    timeout=10,
                )
            except Exception:
                continue
            if status_res.status_code != 200:
                continue

            data = status_res.json()
            sf_status = data.get("status", "")
            if sf_status == "Succeed":
                videos = (data.get("results") or {}).get("videos", [])
                return videos[0].get("url") if videos else None
            if sf_status in ("Failed", "Canceled"):
                logger.warning("siliconflow job %s ended: %s", request_id, data.get("reason"))
                return None
    except Exception:
        logger.exception("siliconflow submit/poll unexpected")
    return None
