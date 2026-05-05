"""
Seed script: populate the database with demo data for development.
Run with: make seed
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.config import get_settings
from app.models.user import User
from app.models.voice import Voice
from app.models.template import Template
from app.models.character import Character
from app.services.template_modes import get_template_mode
from app.utils.auth import hash_password

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def seed():
    async with SessionLocal() as db:
        # ── Demo user ──────────────────────────────────────────
        demo = User(
            id="demo-user-001",
            email="demo@fliki.ai",
            name="Demo User",
            hashed_password=hash_password("demo1234"),
            plan="standard",
            credits_used=3,
            credits_total=20,
            referral_code="DEMO2026",
        )
        db.add(demo)

        # ── Voices ────────────────────────────────────────────
        voices = [
            Voice(id="v-en-f-01", name="Aria", lang="English", gender="female", accent="American", style="Conversational", tags=["natural", "warm"], is_premium=False),
            Voice(id="v-en-m-01", name="Brian", lang="English", gender="male", accent="British", style="News", tags=["professional", "clear"], is_premium=False),
            Voice(id="v-en-f-02", name="Emma", lang="English", gender="female", accent="British", style="Storytelling", tags=["expressive"], is_premium=True),
            Voice(id="v-zh-f-01", name="晓晓", lang="Chinese", gender="female", accent="Mandarin", style="Conversational", tags=["natural"], is_premium=False),
            Voice(id="v-zh-m-01", name="云扬", lang="Chinese", gender="male", accent="Mandarin", style="News", tags=["professional"], is_premium=False),
            Voice(id="v-es-f-01", name="Conchita", lang="Spanish", gender="female", accent="Spain", style="Conversational", tags=["natural"], is_premium=False),
            Voice(id="v-fr-m-01", name="Henri", lang="French", gender="male", accent="France", style="Professional", tags=["clear"], is_premium=True),
            Voice(id="v-de-f-01", name="Katja", lang="German", gender="female", accent="Germany", style="Conversational", tags=["natural"], is_premium=False),
            Voice(id="v-ja-f-01", name="Nanami", lang="Japanese", gender="female", accent="Japan", style="Conversational", tags=["natural"], is_premium=True),
        ]
        for v in voices:
            db.add(v)

        # ── Templates ─────────────────────────────────────────
        templates = [
            Template(id="t-01", title="Product Launch", category="Marketing", thumbnail_url="/templates/t1.jpg", duration="26s", lang="English", uses_count=1234, is_premium=False, config_json=get_template_mode("t-01")),
            Template(id="t-02", title="Tutorial Walkthrough", category="Education", thumbnail_url="/templates/t4.jpg", duration="26s", lang="English", uses_count=987, is_premium=False, config_json=get_template_mode("t-02")),
            Template(id="t-03", title="Social Media Promo", category="Social", thumbnail_url="/templates/t2.jpg", duration="20s", lang="English", uses_count=2341, is_premium=False, config_json=get_template_mode("t-03")),
            Template(id="t-04", title="Corporate Presentation", category="Business", thumbnail_url="/templates/t10.jpg", duration="29s", lang="English", uses_count=456, is_premium=True, config_json=get_template_mode("t-04")),
            Template(id="t-05", title="YouTube Intro", category="Entertainment", thumbnail_url="/templates/t12.jpg", duration="13s", lang="English", uses_count=3120, is_premium=False, config_json=get_template_mode("t-05")),
            Template(id="t-06", title="News Report", category="News", thumbnail_url="/templates/t8.jpg", duration="30s", lang="English", uses_count=234, is_premium=True, config_json=get_template_mode("t-06")),
            Template(id="t-07", title="Recipe Video", category="Lifestyle", thumbnail_url="/templates/t15.jpg", duration="26s", lang="English", uses_count=891, is_premium=False, config_json=get_template_mode("t-07")),
            Template(id="t-08", title="Travel Vlog", category="Travel", thumbnail_url="/templates/t14.jpg", duration="26s", lang="English", uses_count=1567, is_premium=True, config_json=get_template_mode("t-08")),
        ]
        for t in templates:
            db.add(t)

        # ── Default characters ────────────────────────────────
        characters = [
            Character(id="c-01", name="Alex", style="Professional", is_default=True),
            Character(id="c-02", name="Sofia", style="Casual", is_default=True),
            Character(id="c-03", name="Marcus", style="Tech", is_default=True),
        ]
        for c in characters:
            db.add(c)

        await db.commit()
        print("✓ Seed data inserted successfully.")


if __name__ == "__main__":
    asyncio.run(seed())
