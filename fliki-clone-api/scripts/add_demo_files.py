"""
Add demo files for demo-user-001. Safe to run multiple times (skips if already exist).
Run: python scripts/add_demo_files.py
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select
from app.config import get_settings
from app.models.file import File

settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

DEMO_USER_ID = "demo-user-001"

FILES = [
    dict(id="f-01", title="Product Launch Video",      status="done",       duration="1:32", scene_count=8,  type="video"),
    dict(id="f-02", title="Weekly News Roundup",        status="done",       duration="3:15", scene_count=12, type="video"),
    dict(id="f-03", title="Tutorial: Getting Started",  status="generating", duration=None,   scene_count=10, type="video"),
    dict(id="f-04", title="Brand Story",                status="draft",      duration="0:58", scene_count=4,  type="video"),
    dict(id="f-05", title="Social Media Reel",          status="done",       duration="0:30", scene_count=6,  type="video"),
    dict(id="f-06", title="Customer Testimonial",       status="error",      duration="1:10", scene_count=5,  type="video"),
]

async def main():
    async with Session() as db:
        existing = (await db.execute(
            select(File.id).where(File.user_id == DEMO_USER_ID)
        )).scalars().all()
        existing_ids = set(existing)

        added = 0
        for f in FILES:
            if f["id"] in existing_ids:
                print(f"  skip {f['id']} (already exists)")
                continue
            db.add(File(user_id=DEMO_USER_ID, **f))
            added += 1

        await db.commit()
        print(f"✓ Done — {added} files added, {len(existing_ids)} already existed.")

asyncio.run(main())
