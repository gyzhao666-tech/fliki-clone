"""一次性把 platform_credentials 里 plain text 的 access_token / refresh_token 升级成 Fernet 密文。

幂等：通过 ``_looks_encrypted`` 跳过已经加密的行；可重复跑多次。

前置：
  1. ``.env`` 已配 ``PUBLISH_CREDENTIAL_FERNET_KEY``
  2. ``config.publish_credential_fernet_key`` validator 已通过

使用：
  cd /Users/zhaoguangyuan/project/empty/fliki-clone-api
  .venv/bin/python scripts/migrate_encrypt_creds.py            # 真跑
  .venv/bin/python scripts/migrate_encrypt_creds.py --dry-run  # 仅打印不改库

退出码：
  0 = 成功（可能是 0 行变化）
  2 = KEY 未配置（不会乱写明文）
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services.publishing.credentials import (  # noqa: E402
    _encrypt,
    _get_fernet,
    _looks_encrypted,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="仅打印不写库")
    args = parser.parse_args()

    settings = get_settings()
    fernet = _get_fernet()
    if fernet is None:
        print(
            "[ERROR] PUBLISH_CREDENTIAL_FERNET_KEY 未配置；先在 .env 里设好再跑",
            file=sys.stderr,
        )
        return 2

    engine = create_engine(settings.database_url_sync)
    upgraded = 0
    already = 0
    skipped = 0
    total = 0

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, user_id, platform, access_token, refresh_token
                  FROM platform_credentials
                 ORDER BY platform, user_id
                """
            )
        ).fetchall()

    for row in rows:
        total += 1
        cred_id, user_id, platform, at, rt = row
        new_at = at
        new_rt = rt
        changed_at = False
        changed_rt = False

        if at and not _looks_encrypted(at):
            new_at = _encrypt(at)
            changed_at = True
        if rt and not _looks_encrypted(rt):
            new_rt = _encrypt(rt)
            changed_rt = True

        if not (changed_at or changed_rt):
            already += 1
            continue

        label = (
            f"[{platform}/{user_id[:8]}…]"
            f" access={'enc' if changed_at else 'keep'}"
            f" refresh={'enc' if changed_rt else 'keep'}"
        )
        if args.dry_run:
            print(f"[DRY] would upgrade {label}")
            skipped += 1
            continue

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE platform_credentials
                       SET access_token  = :at,
                           refresh_token = :rt,
                           updated_at    = NOW()
                     WHERE id = :id
                    """
                ),
                {"at": new_at, "rt": new_rt, "id": cred_id},
            )
        print(f"[OK]  upgraded {label}")
        upgraded += 1

    print(
        "\n--- summary ---\n"
        f"  total rows scanned : {total}\n"
        f"  already encrypted  : {already}\n"
        f"  upgraded           : {upgraded}\n"
        f"  dry-run skipped    : {skipped}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
