"""平台 OAuth 凭证读 / 写 / 刷新（发布执行器 v1）。

存储说明
-------
- v1：access_token / refresh_token 直接 plain text 存到 `platform_credentials`。
  **生产环境**：service 层应套 Fernet (cryptography 包) 对称加密；密钥来自环境变量。
  TODO 留在这里：`_encrypt(token)` / `_decrypt(token)`。
- (user_id, platform) 唯一；revoke 时 row 直接 DELETE。
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import create_engine, text

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class CredentialPayload:
    """从 DB 读出来的 platform_credentials 行（dict 视图）。"""

    id: str
    user_id: str
    platform: str
    display_name: Optional[str]
    external_user_id: Optional[str]
    access_token: Optional[str]
    refresh_token: Optional[str]
    token_expires_at: Optional[datetime]
    scope: list[str]
    meta: dict[str, Any]
    status: str

    def to_adapter_input(self) -> dict[str, Any]:
        """转成 adapter PublishRequest.credential 字典。"""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.token_expires_at,
            "scope": self.scope,
            "external_user_id": self.external_user_id,
            "display_name": self.display_name,
            "meta": self.meta,
        }


def _engine():
    return create_engine(get_settings().database_url_sync)


def list_user_credentials(user_id: str) -> list[CredentialPayload]:
    if not user_id:
        return []
    with _engine().connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, user_id, platform, display_name, external_user_id,
                       access_token, refresh_token, token_expires_at,
                       scope_json, meta_json, status
                  FROM platform_credentials
                 WHERE user_id = :uid
                 ORDER BY platform ASC
                """
            ),
            {"uid": user_id},
        ).fetchall()
    return [_row_to_payload(r) for r in rows]


def get_credential(user_id: str, platform: str) -> Optional[CredentialPayload]:
    if not user_id or not platform:
        return None
    with _engine().connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, user_id, platform, display_name, external_user_id,
                       access_token, refresh_token, token_expires_at,
                       scope_json, meta_json, status
                  FROM platform_credentials
                 WHERE user_id = :uid AND platform = :pf
                """
            ),
            {"uid": user_id, "pf": platform},
        ).fetchone()
    return _row_to_payload(row) if row else None


def upsert_credential(
    *,
    user_id: str,
    platform: str,
    access_token: Optional[str] = None,
    refresh_token: Optional[str] = None,
    token_expires_at: Optional[datetime] = None,
    scope: Optional[list[str]] = None,
    display_name: Optional[str] = None,
    external_user_id: Optional[str] = None,
    meta: Optional[dict[str, Any]] = None,
    status_value: str = "active",
) -> CredentialPayload:
    """upsert (user_id, platform) 行；存在则覆盖 access_token / expires。

    refresh_token 仅在 caller 显式传入时覆盖（OAuth refresh 通常不返新 refresh_token，
    保留旧的）。
    """
    if not user_id or not platform:
        raise ValueError("user_id and platform required")

    existing = get_credential(user_id, platform)
    if existing:
        new_refresh = refresh_token if refresh_token is not None else existing.refresh_token
        with _engine().begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE platform_credentials
                       SET access_token = :at,
                           refresh_token = :rt,
                           token_expires_at = :exp,
                           scope_json = CAST(:scope AS JSON),
                           meta_json = CAST(:meta AS JSON),
                           display_name = COALESCE(:dn, display_name),
                           external_user_id = COALESCE(:eid, external_user_id),
                           status = :st,
                           updated_at = NOW()
                     WHERE user_id = :uid AND platform = :pf
                    """
                ),
                {
                    "at": access_token,
                    "rt": new_refresh,
                    "exp": token_expires_at,
                    "scope": json.dumps(scope or [], ensure_ascii=False),
                    "meta": json.dumps(meta or {}, ensure_ascii=False),
                    "dn": display_name,
                    "eid": external_user_id,
                    "st": status_value,
                    "uid": user_id,
                    "pf": platform,
                },
            )
    else:
        with _engine().begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO platform_credentials
                        (id, user_id, platform, display_name, external_user_id,
                         access_token, refresh_token, token_expires_at,
                         scope_json, meta_json, status)
                    VALUES
                        (:id, :uid, :pf, :dn, :eid, :at, :rt, :exp,
                         CAST(:scope AS JSON), CAST(:meta AS JSON), :st)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "uid": user_id,
                    "pf": platform,
                    "dn": display_name,
                    "eid": external_user_id,
                    "at": access_token,
                    "rt": refresh_token,
                    "exp": token_expires_at,
                    "scope": json.dumps(scope or [], ensure_ascii=False),
                    "meta": json.dumps(meta or {}, ensure_ascii=False),
                    "st": status_value,
                },
            )

    out = get_credential(user_id, platform)
    if not out:
        raise RuntimeError("credential row missing after upsert")
    return out


def revoke_credential(user_id: str, platform: str) -> bool:
    """删 (user_id, platform) 行；返 True 表示真有 row 删了。"""
    if not user_id or not platform:
        return False
    with _engine().begin() as conn:
        res = conn.execute(
            text(
                "DELETE FROM platform_credentials WHERE user_id = :uid AND platform = :pf"
            ),
            {"uid": user_id, "pf": platform},
        )
    return (res.rowcount or 0) > 0


def update_after_publish(
    *,
    user_id: str,
    platform: str,
    access_token: Optional[str] = None,
    token_expires_at: Optional[datetime] = None,
) -> None:
    """adapter 在 upload 内部 refresh 了 token 时回写新值；只动 access/expires，
    refresh_token 保留旧的。"""
    if not user_id or not platform:
        return
    if access_token is None and token_expires_at is None:
        return
    with _engine().begin() as conn:
        conn.execute(
            text(
                """
                UPDATE platform_credentials
                   SET access_token = COALESCE(:at, access_token),
                       token_expires_at = COALESCE(:exp, token_expires_at),
                       updated_at = NOW()
                 WHERE user_id = :uid AND platform = :pf
                """
            ),
            {
                "at": access_token,
                "exp": token_expires_at,
                "uid": user_id,
                "pf": platform,
            },
        )


# ── helpers ──────────────────────────────────────────────────────────────────


def _row_to_payload(row: Any) -> CredentialPayload:
    scope_raw = row[8] if isinstance(row[8], (list, dict)) else []
    if isinstance(scope_raw, dict):
        scope_raw = list(scope_raw.values())
    scope: list[str] = [str(x) for x in scope_raw] if isinstance(scope_raw, list) else []
    meta_raw = row[9] if isinstance(row[9], dict) else {}
    return CredentialPayload(
        id=row[0],
        user_id=row[1],
        platform=row[2],
        display_name=row[3],
        external_user_id=row[4],
        access_token=row[5],
        refresh_token=row[6],
        token_expires_at=row[7],
        scope=scope,
        meta=meta_raw,
        status=row[10] or "active",
    )


__all__ = [
    "CredentialPayload",
    "get_credential",
    "list_user_credentials",
    "revoke_credential",
    "update_after_publish",
    "upsert_credential",
]
