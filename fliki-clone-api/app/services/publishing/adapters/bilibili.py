"""bilibili adapter（stub，v1 不真发）。

为什么是 stub
-----------
B 站没有公开稳定的「视频上传」开放 API：
- 站内上传走 `member.bilibili.com` 私有协议（cookie + bili_jct CSRF）
- 「合作伙伴 / MCN」入驻才能拿到正式 OpenAPI
- 私有协议每隔几个月会变 + 反自动化越来越严

所以 v1 直接 stub：返 PublishOutcome(ok=False, error="bilibili 暂不支持自动发布")，
用户可以在前端看到清晰的错误信息，然后手动下载 render.url 自己上传。
"""
from __future__ import annotations

from datetime import datetime, timezone

from .base import (
    PlatformAdapter,
    PublishOutcome,
    PublishRequest,
    register_adapter,
)


@register_adapter("bilibili")
class BilibiliAdapter(PlatformAdapter):
    is_real = False  # 标 False 让前端显示「stub」徽标
    requires_credential = False

    def upload(self, req: PublishRequest) -> PublishOutcome:
        return PublishOutcome(
            ok=False,
            status="failed",
            error=(
                "bilibili 自动发布尚未实现：B 站无公开 video upload API（需要 MCN/合作伙伴入驻）。"
                f"请手动下载 render 视频后到 https://member.bilibili.com 上传：{req.render_url}"
            ),
            published_at=datetime.now(tz=timezone.utc),
            meta={"platform": "bilibili", "stub": True},
        )


__all__ = ["BilibiliAdapter"]
