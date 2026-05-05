"""dry-run adapter：dev 兜底 / UI 测试 / 不真发。

行为：
- `upload()` 一定成功，返一个伪造的 external_id（`dryrun-{plan_id[:8]}-{ts}`）
- 不调用任何外部 API；不需要 OAuth
- 平台名 `dry-run`：用户主动选 dry-run（演示流程）
- 也作为兜底：`get_adapter` 在未知平台时回退到这里
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from .base import (
    PlatformAdapter,
    PublishOutcome,
    PublishRequest,
    register_adapter,
)

logger = logging.getLogger(__name__)


@register_adapter("dry-run")
class DryRunAdapter(PlatformAdapter):
    is_real = False
    requires_credential = False

    def upload(self, req: PublishRequest) -> PublishOutcome:
        ts = int(time.time())
        ext_id = f"dryrun-{req.plan_id[:8]}-{ts}"
        logger.info(
            "dry-run publish OK plan=%s render=%s url=%s -> %s",
            req.plan_id,
            req.render_id,
            req.render_url,
            ext_id,
        )
        return PublishOutcome(
            ok=True,
            external_id=ext_id,
            external_url=f"https://dry-run.local/v/{ext_id}",
            status="published",
            published_at=datetime.now(tz=timezone.utc),
            meta={
                "platform": "dry-run",
                "title": req.title,
                "tags": req.tags,
                "render_url": req.render_url,
            },
        )


__all__ = ["DryRunAdapter"]
