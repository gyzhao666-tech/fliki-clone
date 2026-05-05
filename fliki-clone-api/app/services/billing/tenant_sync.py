"""把「user 维度的 plan 切换」映射到「v2 tenant 维度的 plan + 配额」。

为什么单拎一层
-------------
v2 配额（`tenant_quotas`）是按 tenant_id 主键的，而 stripe 订阅是挂在 user 上的。
当 webhook 收到 user X 升级到 standard 时，要做：

1. 解析 user X 的 tenant_id（沿用 pipeline.tenant.resolve_tenant_id 的逻辑：
   优先 `ws:{workspace.id}` → 兜底 `u:{user_id}`）
2. 调 quota.update_tenant_plan(tenant_id, new_plan) —— 它会
   - UPDATE tenant_quotas.plan
   - bump monthly_limit_usd / concurrent_max（升级取大、降级保留运维手调过的值）
   - 遍历该 tenant 已存在的 provider_concurrency_buckets，按新 plan ensure_bucket 自动 bump

不在这里改 users.plan / subscriptions：那由 webhook_handlers 完成（一次事务 + 写日志）。
本模块只关心 tenant 视图的同步。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from app.services.pipeline import tenant as pipeline_tenant
from app.services.pipeline.quota import (
    TenantQuotaSnapshot,
    update_tenant_plan,
)

logger = logging.getLogger(__name__)


@dataclass
class TenantSyncResult:
    user_id: str
    tenant_id: str
    plan: str
    snapshot: Optional[TenantQuotaSnapshot]
    skipped_reason: Optional[str] = None  # 非空时表示无操作（匿名 / 缺 user_id）


def sync_user_plan(user_id: Optional[str], new_plan: str) -> TenantSyncResult:
    """user_id 升级 / 降级到 new_plan 后，把 tenant 视图同步过去。

    匿名 user / 空 user_id 直接返回 skipped 结果（webhook 不应阻塞）。
    解析 tenant_id 异常时也兜底返 skipped；具体异常上抛由 caller 处理。

    返回 TenantSyncResult，便于 caller 写结构化日志 / 单元测试断言。
    """
    if not user_id:
        return TenantSyncResult(
            user_id="",
            tenant_id="",
            plan=new_plan,
            snapshot=None,
            skipped_reason="empty user_id",
        )

    # 主动清缓存：避免 60s TTL 内拿到过期 plan 信息（stripe 回调通常马上有 UI 刷新）
    pipeline_tenant.clear_cache()
    tctx = pipeline_tenant.resolve_tenant_context(user_id, user_plan=new_plan)
    tenant_id = tctx.tenant_id

    if tenant_id.startswith("anon:"):
        # 匿名 tenant 不该走 webhook 路径；以防万一返 skipped 不落库
        logger.warning("sync_user_plan got anon tenant user=%s plan=%s", user_id, new_plan)
        return TenantSyncResult(
            user_id=user_id,
            tenant_id=tenant_id,
            plan=new_plan,
            snapshot=None,
            skipped_reason="anonymous tenant",
        )

    snap = update_tenant_plan(
        tenant_id,
        new_plan,
        display_name=tctx.display_name,
    )
    logger.info(
        "billing tenant sync user=%s tenant=%s plan=%s monthly_limit_usd=%s concurrent_max=%s",
        user_id,
        tenant_id,
        new_plan,
        snap.monthly_limit_usd,
        snap.concurrent_max,
    )
    return TenantSyncResult(
        user_id=user_id,
        tenant_id=tenant_id,
        plan=new_plan,
        snapshot=snap,
    )


__all__ = ["TenantSyncResult", "sync_user_plan"]
