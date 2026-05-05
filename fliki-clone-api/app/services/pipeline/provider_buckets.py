"""Provider 级并发分桶（配额 v2 的「微观」分量）。

为什么要 provider 桶
-------------------
v1 只有 user/tenant 月度额度 + 整体 concurrent_max。但「整体并发 5」并不意味着可以
同时打 5 个 Kling i2v 调用——Kling 后端本身有 QPS / 并发上限，超了就 403/429。
v2 给每个 (tenant_id, provider_name) 一个槽位计数：调用前 acquire / 调用后 release。

并发模型
-------
- `acquire`：单条 UPDATE `WHERE current_in_flight < max_concurrent`；rowcount==1 即获取成功。
- `release`：`UPDATE ... SET current_in_flight = GREATEST(in_flight - 1, 0)`（不会负数）。
- 不用 `SELECT FOR UPDATE`：UPDATE 自带行锁，且条件并发更安全。
- `acquire` 如果行不存在会先 upsert 默认值再重试一次。

不在这里做的：
- 自动 backoff / 排队等待：当前直接抛 `BucketFull`；caller 决定 retry 还是返回 429。
- 跨 tenant 的 provider 总并发上限：v2 只做 per-tenant；后续可加 `provider_global` 桶。
"""
from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional

from sqlalchemy import create_engine, text

from app.config import get_settings

logger = logging.getLogger(__name__)


# (tenant_plan, provider_name) → max_concurrent；新桶第一次落库时使用
PROVIDER_DEFAULT_MAX: dict[str, dict[str, int]] = {
    "free":     {"siliconflow": 2, "kling": 1, "openai": 2, "elevenlabs": 1, "demo": 100},
    "standard": {"siliconflow": 4, "kling": 2, "openai": 3, "elevenlabs": 2, "demo": 100},
    "premium":  {"siliconflow": 8, "kling": 4, "openai": 6, "elevenlabs": 4, "demo": 100},
    "enterprise": {"siliconflow": 20, "kling": 10, "openai": 15, "elevenlabs": 10, "demo": 100},
}


def default_max_for(plan: str, provider_name: str) -> int:
    plan_table = PROVIDER_DEFAULT_MAX.get(plan, PROVIDER_DEFAULT_MAX["free"])
    return int(plan_table.get(provider_name, plan_table.get("siliconflow", 2)))


@dataclass
class BucketSnapshot:
    tenant_id: str
    provider_name: str
    current_in_flight: int
    max_concurrent: int

    @property
    def remaining(self) -> int:
        return max(0, self.max_concurrent - self.current_in_flight)

    @property
    def utilization_pct(self) -> float:
        if self.max_concurrent <= 0:
            return 100.0
        return min(100.0, 100.0 * self.current_in_flight / self.max_concurrent)


class BucketFull(Exception):
    """`acquire` 找不到可用槽位时抛出。"""

    def __init__(self, tenant_id: str, provider_name: str, snapshot: Optional[BucketSnapshot] = None):
        self.tenant_id = tenant_id
        self.provider_name = provider_name
        self.snapshot = snapshot
        msg = f"provider bucket full: tenant={tenant_id} provider={provider_name}"
        if snapshot:
            msg += f" ({snapshot.current_in_flight}/{snapshot.max_concurrent})"
        super().__init__(msg)


def _engine():
    return create_engine(get_settings().database_url_sync)


def ensure_bucket(
    tenant_id: str,
    provider_name: str,
    *,
    plan: str = "free",
    max_override: Optional[int] = None,
) -> BucketSnapshot:
    """读取 (tenant, provider) 桶；不存在则按 plan 默认值 INSERT；存在但 max 偏小则按 plan 自动 bump。

    plan 升级（free→standard→premium）路径：自动把 max_concurrent 调到新 plan 默认值；
    不会缩小（保护运维手动调过的桶）。`max_override` 显式指定时强制覆盖（运维用）。
    """
    if not tenant_id or not provider_name:
        raise ValueError("tenant_id and provider_name required")

    desired_max = max_override if max_override is not None else default_max_for(plan, provider_name)
    engine = _engine()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT tenant_id, provider_name, current_in_flight, max_concurrent
                  FROM provider_concurrency_buckets
                 WHERE tenant_id = :tid AND provider_name = :pn
                """
            ),
            {"tid": tenant_id, "pn": provider_name},
        ).fetchone()
        if row:
            current_max = int(row[3] or 0)
            # plan 升级 / override 显式给了更大值时自动 bump；缩小则保留旧值
            if max_override is not None or desired_max > current_max:
                new_max = max_override if max_override is not None else desired_max
                if new_max != current_max:
                    conn.execute(
                        text(
                            """
                            UPDATE provider_concurrency_buckets
                               SET max_concurrent = :nm, updated_at = NOW()
                             WHERE tenant_id = :tid AND provider_name = :pn
                            """
                        ),
                        {"tid": tenant_id, "pn": provider_name, "nm": int(new_max)},
                    )
                    current_max = int(new_max)
            return BucketSnapshot(
                tenant_id=row[0],
                provider_name=row[1],
                current_in_flight=int(row[2] or 0),
                max_concurrent=current_max,
            )

        try:
            conn.execute(
                text(
                    """
                    INSERT INTO provider_concurrency_buckets
                        (id, tenant_id, provider_name,
                         current_in_flight, max_concurrent,
                         created_at, updated_at)
                    VALUES
                        (:id, :tid, :pn, 0, :cmax, NOW(), NOW())
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "tid": tenant_id,
                    "pn": provider_name,
                    "cmax": desired_max,
                },
            )
        except Exception:
            # 并发竞态：可能另一个请求刚插入；再读一次
            logger.debug("ensure_bucket insert race tenant=%s provider=%s", tenant_id, provider_name)

    # 重读（不论 INSERT 命中与否）
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT tenant_id, provider_name, current_in_flight, max_concurrent
                  FROM provider_concurrency_buckets
                 WHERE tenant_id = :tid AND provider_name = :pn
                """
            ),
            {"tid": tenant_id, "pn": provider_name},
        ).fetchone()
    return BucketSnapshot(
        tenant_id=row[0],
        provider_name=row[1],
        current_in_flight=int(row[2] or 0),
        max_concurrent=int(row[3] or 0),
    )


def acquire(
    tenant_id: str,
    provider_name: str,
    *,
    plan: str = "free",
    user_id: Optional[str] = None,
) -> BucketSnapshot:
    """获取一个槽位；失败抛 BucketFull。

    Track-25：桶满时在 `user:{user_id}` 频道推一条 `bucket_full` 事件，让前端
    layout.tsx 全局 hook 用 `feedback.warning` 提示「Provider {name} 并发到上限」。
    `user_id` 缺省 None 时保留向后兼容（gateway 内部从 `request.user_id` 透传，
    其他调用方可不传）。
    """
    if not tenant_id:
        raise ValueError("tenant_id required")

    # 第一遍：直接 UPDATE（最常见路径，桶已存在）
    snap = _try_acquire(tenant_id, provider_name)
    if snap is not None:
        return snap

    # 第二遍：可能桶不存在，先 ensure 再 UPDATE
    pre = ensure_bucket(tenant_id, provider_name, plan=plan)
    snap = _try_acquire(tenant_id, provider_name)
    if snap is not None:
        return snap

    # 桶满：先广播再抛，event 路径失败不影响 caller 拿到 BucketFull
    if user_id:
        try:
            from . import events as pipeline_events

            pipeline_events.publish_user_event(
                user_id,
                "bucket_full",
                {
                    "tenant_id": tenant_id,
                    "kind": "provider_bucket",
                    "provider_name": provider_name,
                    "message": (
                        f"Provider {provider_name} 并发到上限"
                        + (
                            f" ({pre.current_in_flight}/{pre.max_concurrent})"
                            if pre
                            else ""
                        )
                    ),
                    "current_in_flight": int(pre.current_in_flight) if pre else None,
                    "max_concurrent": int(pre.max_concurrent) if pre else None,
                },
            )
        except Exception:  # pragma: no cover - publish 失败不阻断 BucketFull 主流程
            logger.warning(
                "publish_user_event bucket_full failed user=%s tenant=%s provider=%s",
                user_id,
                tenant_id,
                provider_name,
            )

    raise BucketFull(tenant_id, provider_name, snapshot=pre)


def _try_acquire(tenant_id: str, provider_name: str) -> Optional[BucketSnapshot]:
    """尝试一次条件 UPDATE。成功返回新 snapshot；条件不满足返回 None。"""
    engine = _engine()
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE provider_concurrency_buckets
                   SET current_in_flight = current_in_flight + 1,
                       last_acquired_at = NOW(),
                       updated_at = NOW()
                 WHERE tenant_id = :tid
                   AND provider_name = :pn
                   AND current_in_flight < max_concurrent
                """
            ),
            {"tid": tenant_id, "pn": provider_name},
        )
        if result.rowcount != 1:
            return None
        row = conn.execute(
            text(
                """
                SELECT tenant_id, provider_name, current_in_flight, max_concurrent
                  FROM provider_concurrency_buckets
                 WHERE tenant_id = :tid AND provider_name = :pn
                """
            ),
            {"tid": tenant_id, "pn": provider_name},
        ).fetchone()
    return BucketSnapshot(
        tenant_id=row[0],
        provider_name=row[1],
        current_in_flight=int(row[2] or 0),
        max_concurrent=int(row[3] or 0),
    )


def release(tenant_id: str, provider_name: str) -> None:
    """归还槽位；用 GREATEST 兜底，避免重复 release 把计数打负。"""
    if not tenant_id or not provider_name:
        return
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE provider_concurrency_buckets
                   SET current_in_flight = GREATEST(current_in_flight - 1, 0),
                       last_released_at = NOW(),
                       updated_at = NOW()
                 WHERE tenant_id = :tid AND provider_name = :pn
                """
            ),
            {"tid": tenant_id, "pn": provider_name},
        )


@contextmanager
def provider_slot(
    tenant_id: Optional[str],
    provider_name: str,
    *,
    plan: str = "free",
) -> Iterator[Optional[BucketSnapshot]]:
    """`with provider_slot(...)`：进 acquire / 退 release；tenant_id 为空则透传不计数。

    例：
        with provider_slot(tenant_id, "siliconflow", plan="standard") as snap:
            ...  # 调 provider；snap.remaining 可读
    """
    if not tenant_id:
        yield None
        return
    snap = acquire(tenant_id, provider_name, plan=plan)
    try:
        yield snap
    finally:
        release(tenant_id, provider_name)


def list_buckets(tenant_id: str) -> list[BucketSnapshot]:
    """前端「Provider 并发」面板的数据源。"""
    if not tenant_id:
        return []
    engine = _engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT tenant_id, provider_name, current_in_flight, max_concurrent
                  FROM provider_concurrency_buckets
                 WHERE tenant_id = :tid
                 ORDER BY provider_name ASC
                """
            ),
            {"tid": tenant_id},
        ).fetchall()
    return [
        BucketSnapshot(
            tenant_id=r[0],
            provider_name=r[1],
            current_in_flight=int(r[2] or 0),
            max_concurrent=int(r[3] or 0),
        )
        for r in rows
    ]


def reset_in_flight(tenant_id: str, provider_name: Optional[str] = None) -> int:
    """运维 / 单元测试用：把 in_flight 强制清零（卡死时兜底）。返回受影响行数。"""
    engine = _engine()
    with engine.begin() as conn:
        if provider_name:
            res = conn.execute(
                text(
                    """
                    UPDATE provider_concurrency_buckets
                       SET current_in_flight = 0, updated_at = NOW()
                     WHERE tenant_id = :tid AND provider_name = :pn
                    """
                ),
                {"tid": tenant_id, "pn": provider_name},
            )
        else:
            res = conn.execute(
                text(
                    """
                    UPDATE provider_concurrency_buckets
                       SET current_in_flight = 0, updated_at = NOW()
                     WHERE tenant_id = :tid
                    """
                ),
                {"tid": tenant_id},
            )
        return res.rowcount or 0


__all__ = [
    "BucketFull",
    "BucketSnapshot",
    "PROVIDER_DEFAULT_MAX",
    "acquire",
    "default_max_for",
    "ensure_bucket",
    "list_buckets",
    "provider_slot",
    "release",
    "reset_in_flight",
]
