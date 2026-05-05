"""平台 OAuth 凭证读 / 写 / 刷新（发布执行器 v1 + Track-01 Fernet 加密）。

存储说明
-------
- access_token / refresh_token 落库前用 Fernet 对称加密；读出后透明解密。
  KEY 来自 ``settings.publish_credential_fernet_key``（``.env`` 里
  ``PUBLISH_CREDENTIAL_FERNET_KEY``）。
- KEY 缺失（空串）时**降级到 plain text**，并在模块首次访问时
  ``logger.warning`` 一次（避免每行都刷日志）；这样老库 / 新机器
  没配 KEY 也能继续工作，只是不安全。
- 解密时如果 token 不是合法 Fernet 密文（比如老的 plain text 行），
  会回退到 "原样返回"——所以 KEY 设好后，老行不需要立即跑迁移，
  正常 publish 流程不会炸；要彻底升级再跑 ``scripts/migrate_encrypt_creds.py``。
- (user_id, platform) 唯一；revoke 时 row 直接 DELETE。
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import create_engine, text

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class CredentialPayload:
    """从 DB 读出来的 platform_credentials 行（dict 视图，token 已解密）。"""

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


# ── Fernet 加密 ──────────────────────────────────────────────────────────────

_FERNET_CACHE: dict[str, Fernet | None] = {}
_WARNED_NO_KEY = False


def _get_fernet() -> Optional[Fernet]:
    """惰性拿 Fernet 实例；KEY 缺失返 None（caller 自行 fallback plain text）。"""
    global _WARNED_NO_KEY
    key = (get_settings().publish_credential_fernet_key or "").strip()
    if not key:
        if not _WARNED_NO_KEY:
            logger.warning(
                "PUBLISH_CREDENTIAL_FERNET_KEY 未配置；platform_credentials.access_token "
                "/ refresh_token 将以 plain text 落库（仅适用于本机 dev / 兼容老库）。"
                "生产环境请尽快生成 KEY 并跑 scripts/migrate_encrypt_creds.py。"
            )
            _WARNED_NO_KEY = True
        return None
    cached = _FERNET_CACHE.get(key)
    if cached is None:
        cached = Fernet(key.encode("ascii"))
        _FERNET_CACHE[key] = cached
    return cached


def _encrypt(token: Optional[str]) -> Optional[str]:
    """plain text → base64 密文（gAAAAA...）；None / 空串原样返；无 KEY 原样返。"""
    if token is None:
        return None
    if token == "":
        return ""
    f = _get_fernet()
    if f is None:
        return token
    return f.encrypt(token.encode("utf-8")).decode("ascii")


def _decrypt(token: Optional[str]) -> Optional[str]:
    """base64 密文 → plain text；None / 空串原样返；无 KEY 原样返；
    不是合法密文（老 plain text 行）也原样返。"""
    if token is None:
        return None
    if token == "":
        return ""
    f = _get_fernet()
    if f is None:
        return token
    try:
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        # 老 plain text 行：bytes 不是合法 Fernet token，原样返回
        # （info 级别足够，避免 publish 链路被 warning 刷屏）
        logger.info(
            "platform_credentials token 非 Fernet 密文（很可能是老 plain text 行），"
            "原样返回；建议跑 scripts/migrate_encrypt_creds.py 升级"
        )
        return token


def _looks_encrypted(token: Optional[str]) -> bool:
    """快速判断 token 是不是 Fernet 密文；migrate 脚本用，幂等保证。"""
    if not token:
        return False
    f = _get_fernet()
    if f is None:
        return False
    try:
        f.decrypt(token.encode("ascii"))
        return True
    except (InvalidToken, ValueError):
        return False


# ── DAO ──────────────────────────────────────────────────────────────────────


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

    入参的 access_token / refresh_token 永远是 plain text；这里负责加密。
    """
    if not user_id or not platform:
        raise ValueError("user_id and platform required")

    existing = get_credential(user_id, platform)
    enc_access = _encrypt(access_token)
    if existing:
        # existing.refresh_token 已经是 _row_to_payload 解密后的 plain text，
        # 这里走加密路径回写
        new_refresh_plain = (
            refresh_token if refresh_token is not None else existing.refresh_token
        )
        enc_refresh = _encrypt(new_refresh_plain)
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
                    "at": enc_access,
                    "rt": enc_refresh,
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
        enc_refresh = _encrypt(refresh_token)
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
                    "at": enc_access,
                    "rt": enc_refresh,
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
    refresh_token 保留旧的。

    入参 access_token 是 plain text；这里负责加密。
    """
    if not user_id or not platform:
        return
    if access_token is None and token_expires_at is None:
        return
    enc_access = _encrypt(access_token) if access_token is not None else None
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
                "at": enc_access,
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
        access_token=_decrypt(row[5]),
        refresh_token=_decrypt(row[6]),
        token_expires_at=row[7],
        scope=scope,
        meta=meta_raw,
        status=row[10] or "active",
    )


__all__ = [
    "CredentialPayload",
    "_decrypt",
    "_encrypt",
    "_looks_encrypted",
    "get_credential",
    "list_user_credentials",
    "revoke_credential",
    "update_after_publish",
    "upsert_credential",
]
