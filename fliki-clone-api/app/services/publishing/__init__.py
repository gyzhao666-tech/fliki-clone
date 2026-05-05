"""发布执行器（v1）。

把 publish_plans 表里的 draft / scheduled 计划真正推到目标平台。

模块结构
-------
- `adapters/`：平台抽象层。每平台一个 PlatformAdapter 实现。
- `credentials.py`：user × platform 的 OAuth token 读 / 写 / 刷新。
- `executor.py`：`execute_publish_plan(plan_id)`。读 plan + render →
  根据 platform 选 adapter → upload → 写回 plan.status / external_id /
  published_at / error。失败入 DLQ，便于人手 retry。
- `oauth.py`：通用 OAuth 流程帮手（state nonce / authorize URL / callback 兑换 token）。

适配的平台
---------
- `dry-run`（始终启用）：dev 兜底，不真发，回 mock external_id；用于本地走通 UI / 测 DLQ
- `youtube`（real）：YouTube Data API v3 upload 端点；scope `youtube.upload`；
  缺 `GOOGLE_CLIENT_ID/SECRET` 时降级到 dry-run + warning
- `bilibili`（stub）：B 站 video upload 公开 API 受限，stub 返 "not_implemented"
  + 详细引导，留 follow-up

设计取舍
-------
- 真实上传调用走 sync requests（与 gateway / runner 一致）；celery worker 兼容
- adapter 失败抛 PublishError；executor 把异常翻译成 plan.status='failed' + plan.error
- DLQ：上传抛非业务异常（连接错 / OOM / 认证刷新失败）入 dead_letter_tasks，
  用户可在前端 DLQ panel 触发重试
- 不强校验 render_id 必须 succeeded：caller 责任；执行器只读 url
"""
from __future__ import annotations

from .executor import (
    PublishError,
    PublishOutcome,
    execute_publish_plan,
    list_supported_platforms,
)

__all__ = [
    "PublishError",
    "PublishOutcome",
    "execute_publish_plan",
    "list_supported_platforms",
]
