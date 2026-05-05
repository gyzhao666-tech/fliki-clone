"""灰度发布 / canary feature flags 服务（Track-10）。

设计目标
-------
按 `tenant_id` hash 染色让一部分 tenant 走 ArtAgent v4，一部分走 v3 prompt-only；
机制要可复用到任意 agent 版本切换（voice / video / publishing 后续都能复用）。

存储
----
`feature_flags` 表（alembic head `a1b2c3d4e5f6`）：
- `tenant_id`：与 `tenant_quotas.tenant_id` 同口径（`ws:{wid}` / `u:{uid}` /
  `anon:default`）
- `flag_name`：稳定 ASCII，例如 `art_ipadapter_pct`
- `value_json`：任意 JSON；典型形态：
    - `{"pct": 50}`        百分比闸门（0..100）
    - `{"enabled": true}`  布尔闸门
    - `{"variant": "v4"}`  版本切换
- 唯一约束 `(tenant_id, flag_name)`：每 tenant 同名 flag 只 1 行

API
---
- `get_flag(tenant_id, flag_name) -> dict | None`：读单个 flag value（dict）
- `set_flag(tenant_id, flag_name, value) -> dict`：upsert（同 tenant_id+flag_name 覆盖）
- `delete_flag(tenant_id, flag_name) -> bool`：删除；False 表示原本就不存在
- `load_for_tenant(tenant_id) -> dict[name, value]`：批量；runner 在 build ctx 时调用
- `is_enabled(tenant_id, flag_name, *, key=None) -> bool`：通用染色判断
    - value 形如 `{"enabled": bool}` → 直接返
    - value 形如 `{"pct": int}` → 用 (tenant_id|key, flag_name) 求稳定 hash 落 0..99
    - value 形如 `{"variant": str}` → variant 非空且非 "off"/"disabled" 视为 enabled

并发 / 事务
----------
- `set_flag` 用 INSERT ... ON CONFLICT (tenant_id, flag_name) DO UPDATE（PG 原生）
- 读路径不加锁；缓存放在 runner 一次 build ctx 调用粒度（不进 process global cache）

为什么不直接走 ORM session：
- 与 `quota.py` / `runner.py` 一致：sync engine 让 Celery worker / BackgroundTask
  / async router 都能调；不引 async session 依赖
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any, Optional

from sqlalchemy import create_engine, text

from app.config import get_settings

logger = logging.getLogger(__name__)


# ── 已知 flag 名（仅做集中文档；agent / 路由可自行加新名）─────────────────────
# 不做强制白名单：admin 给任意未知 flag 写值是允许的，方便临时灰度新功能。
KNOWN_FLAGS = {
    "art_ipadapter_pct": (
        "ArtAgent: 主角镜走 v4 IP-Adapter 的百分比；其余镜降到 v3 prompt-only。"
        " 取值：{\"pct\": 0..100}"
    ),
    # 占位：后续 voice / video / publishing 复用时把名字记到这里
}


def _engine():
    return create_engine(get_settings().database_url_sync)


# ── 读 ───────────────────────────────────────────────────────────────────────


def get_flag(tenant_id: str, flag_name: str) -> Optional[dict[str, Any]]:
    """读单 flag value（dict）；不存在返 None。"""
    if not tenant_id or not flag_name:
        return None
    try:
        with _engine().connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT value_json FROM feature_flags
                     WHERE tenant_id = :tid AND flag_name = :fn
                    """
                ),
                {"tid": tenant_id, "fn": flag_name},
            ).fetchone()
    except Exception:  # pragma: no cover - 表缺失时兜底（dev / 未迁移环境）
        logger.exception(
            "feature_flags read failed tenant=%s flag=%s", tenant_id, flag_name
        )
        return None
    if not row:
        return None
    val = row[0]
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, dict) else None
        except Exception:  # pragma: no cover - JSON 列保证返 dict，这里只是兜底
            return None
    return None


def load_for_tenant(tenant_id: str) -> dict[str, dict[str, Any]]:
    """一次拉某 tenant 全部 flag → {flag_name: value_dict}。

    runner 在 build ctx 时调一次，避免 agent 内部每次读 flag 都击一次 DB。
    """
    if not tenant_id:
        return {}
    try:
        with _engine().connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT flag_name, value_json FROM feature_flags WHERE tenant_id = :tid"
                ),
                {"tid": tenant_id},
            ).fetchall()
    except Exception:
        logger.exception("feature_flags load_for_tenant failed tenant=%s", tenant_id)
        return {}
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        name = r[0]
        val = r[1]
        if isinstance(val, dict):
            out[name] = val
        elif isinstance(val, str):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, dict):
                    out[name] = parsed
            except Exception:  # pragma: no cover
                continue
    return out


# ── 写 ───────────────────────────────────────────────────────────────────────


def set_flag(
    tenant_id: str, flag_name: str, value: dict[str, Any]
) -> dict[str, Any]:
    """upsert flag。返回写入后的 value_json（dict）。

    `value` 必须是 JSON-serializable 的 dict；非 dict 抛 ValueError。
    """
    if not tenant_id or not flag_name:
        raise ValueError("tenant_id / flag_name required")
    if not isinstance(value, dict):
        raise ValueError("value must be a dict (JSON object)")
    # 提前 dump 一次确保可序列化；同时把内嵌 NaN/Inf 这类异常提早暴露
    payload = json.dumps(value, ensure_ascii=False)

    with _engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO feature_flags
                    (id, tenant_id, flag_name, value_json, created_at, updated_at)
                VALUES
                    (:id, :tid, :fn, CAST(:val AS JSON), NOW(), NOW())
                ON CONFLICT (tenant_id, flag_name) DO UPDATE
                  SET value_json = EXCLUDED.value_json,
                      updated_at = NOW()
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tid": tenant_id,
                "fn": flag_name,
                "val": payload,
            },
        )
    # set 完后立即读回，给 admin 路由作返值（便于 UI 展示落库后的 normalised value）
    written = get_flag(tenant_id, flag_name)
    return written or value


def delete_flag(tenant_id: str, flag_name: str) -> bool:
    """删除 flag；返回是否真的删了一行。"""
    if not tenant_id or not flag_name:
        return False
    with _engine().begin() as conn:
        result = conn.execute(
            text(
                """
                DELETE FROM feature_flags
                 WHERE tenant_id = :tid AND flag_name = :fn
                """
            ),
            {"tid": tenant_id, "fn": flag_name},
        )
        return (result.rowcount or 0) > 0


# ── 染色判断 ────────────────────────────────────────────────────────────────


def _stable_bucket_0_99(seed: str) -> int:
    """对任意 seed 字符串求稳定 0..99 桶号；同 seed 永远落同桶。

    用 SHA-1 的前 8 hex 取整 → mod 100；够稳够便宜，且与 Python 进程随机 seed
    无关（避免跨 worker 同 tenant 落不同桶的灾难）。
    """
    if not seed:
        return 0
    h = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
    return int(h, 16) % 100


def is_enabled(
    tenant_id: str,
    flag_name: str,
    *,
    key: Optional[str] = None,
    flags: Optional[dict[str, dict[str, Any]]] = None,
) -> bool:
    """通用染色判断；支持三种 value 形态。

    - `{"enabled": bool}`     → 直接返
    - `{"pct": 0..100}`       → 用 (tenant_id|key, flag_name) hash 落 0..99；
                                bucket < pct 视为命中（pct=100 全开 / pct=0 全关）
    - `{"variant": "v4"}`     → variant ∈ {"", "off", "disabled"} → 关；其它 → 开

    `flags` 可选：调用方已经 load_for_tenant 时传进来避免再击一次 DB；
    `key` 可选：染色二级 key，常用 `run_id` / `step_id` —— 想要「同 tenant 同
        run 一致、不同 run 之间也能继续 50/50」时传 key=None；想做「按 run 染
        色让单个 tenant 内部也分流」时传 key=run_id。
    Track-10 art canary：传 key=None，让同 tenant 多次启动也能稳定走同一档，
        这样人工对比 v4/v3 效果时不会被同 tenant 同 run 不同步打断；
        想要按 run 分流时改 art.py 入口透传 ctx.run_id 即可。
    """
    if not tenant_id or not flag_name:
        return False
    val = (flags or {}).get(flag_name) if flags else None
    if val is None:
        val = get_flag(tenant_id, flag_name)
    if val is None:
        return False

    if "enabled" in val:
        return bool(val.get("enabled"))

    if "pct" in val:
        try:
            pct = int(val.get("pct") or 0)
        except Exception:
            return False
        pct = max(0, min(100, pct))
        if pct <= 0:
            return False
        if pct >= 100:
            return True
        seed = f"{tenant_id}|{flag_name}"
        if key:
            seed = f"{seed}|{key}"
        return _stable_bucket_0_99(seed) < pct

    if "variant" in val:
        v = str(val.get("variant") or "").strip().lower()
        return v not in ("", "off", "disabled", "none")

    return False


__all__ = [
    "KNOWN_FLAGS",
    "get_flag",
    "set_flag",
    "delete_flag",
    "load_for_tenant",
    "is_enabled",
]
