"""
Generate a local Telegram auth session for crawler development.

Run with:
    python scripts/generate_telegram_session.py
"""
import asyncio
import getpass
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv
import socks
from telethon import TelegramClient


DEFAULT_SESSION_DIR = Path("var/telegram")
DEFAULT_SESSION_NAME = "finwise"
PROXY_SCHEMES = {
    "socks4": socks.SOCKS4,
    "socks5": socks.SOCKS5,
    "socks5h": socks.SOCKS5,
    "http": socks.HTTP,
}


def read_required_value(env_name: str, prompt: str, hidden: bool = False) -> str:
    value = os.getenv(env_name, "").strip()
    if value:
        return value

    if hidden:
        value = getpass.getpass(prompt).strip()
    else:
        value = input(prompt).strip()

    if not value:
        raise ValueError(f"{env_name} is required")

    return value


def parse_proxy_url(proxy_url: str) -> tuple | None:
    if not proxy_url:
        return None

    parsed = urlparse(proxy_url)
    proxy_type = PROXY_SCHEMES.get(parsed.scheme.lower())
    if proxy_type is None or not parsed.hostname or not parsed.port:
        supported = ", ".join(sorted(PROXY_SCHEMES))
        raise ValueError(f"TELEGRAM_PROXY must look like socks5://127.0.0.1:7890; supported: {supported}")

    username = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None
    rdns = parsed.scheme.lower() in {"socks5", "socks5h"}
    return (proxy_type, parsed.hostname, parsed.port, rdns, username, password)


async def main() -> None:
    load_dotenv()

    api_id_raw = read_required_value("TELEGRAM_API_ID", "Telegram api_id: ")
    api_hash = read_required_value("TELEGRAM_API_HASH", "Telegram api_hash: ", hidden=True)
    phone = os.getenv("TELEGRAM_PHONE", "").strip() or input("Telegram phone (+countrycode...): ").strip()
    if not phone:
        raise ValueError("TELEGRAM_PHONE is required")

    session_dir = Path(os.getenv("TELEGRAM_SESSION_DIR", DEFAULT_SESSION_DIR))
    session_name = os.getenv("TELEGRAM_SESSION_NAME", DEFAULT_SESSION_NAME).strip() or DEFAULT_SESSION_NAME
    session_dir.mkdir(parents=True, exist_ok=True)

    session_path = session_dir / session_name
    proxy_url = os.getenv("TELEGRAM_PROXY", "").strip()
    proxy = parse_proxy_url(proxy_url)
    if proxy:
        print(f"Using Telegram proxy: {proxy_url}")

    client = TelegramClient(
        str(session_path),
        int(api_id_raw),
        api_hash,
        proxy=proxy,
        connection_retries=3,
        timeout=20,
    )

    await client.start(phone=phone)
    me = await client.get_me()
    await client.disconnect()

    username = f"@{me.username}" if me and me.username else "(no username)"
    print(f"Telegram session generated: {session_path}.session")
    print(f"Logged in as: {username}")


if __name__ == "__main__":
    asyncio.run(main())
