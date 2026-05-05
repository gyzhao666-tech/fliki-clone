"""
Celery 异步任务
视频生成 / 导出 / 声音克隆 — 均通过硅基流动 API 实现
"""
from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "fliki_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


# ── 视频生成 ──────────────────────────────────────────────────────────────────
@celery_app.task(bind=True, name="tasks.generate_video")
def generate_video_task(self, file_id: str, user_id: str):
    """
    调用硅基流动视频生成 API（Wan2.1-T2V）。
    流程：
      1. 从数据库取 scenes[0].script 作为 prompt
      2. POST /v1/video/submit → 获得 requestId
      3. 轮询 GET /v1/video/status/{requestId} 直到完成
      4. 把 result URL 写回 files.preview_url，status → done
    """
    import time
    import requests  # sync in Celery worker context

    sf_key = settings.siliconflow_api_key
    base_url = settings.siliconflow_base_url

    # --- Step 1: 提交生成任务 ---
    self.update_state(state="PROGRESS", meta={"progress": 5, "status": "submitting"})

    # 从 DB 取 script（同步方式，Celery worker 里用同步 SQLAlchemy）
    prompt = f"A short cinematic video for file {file_id}"
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(settings.database_url_sync)
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT script FROM files WHERE id = :fid"),
                {"fid": file_id}
            ).fetchone()
            if row and row[0]:
                prompt = row[0][:500]
    except Exception:
        pass

    if not sf_key:
        # 没有 API key 时模拟完成
        time.sleep(3)
        _update_file_status(file_id, "done", None)
        return {"status": "done", "preview_url": None}

    # --- Step 2: 提交请求 ---
    submit_res = requests.post(
        f"{base_url}/video/submit",
        json={
            "model": settings.video_model,
            "prompt": prompt,
            "negative_prompt": "blurry, low quality",
            "image_size": "1280x720",
            "num_frames": 81,
        },
        headers={"Authorization": f"Bearer {sf_key}"},
        timeout=30,
    )
    if submit_res.status_code != 200:
        self.update_state(state="FAILURE", meta={"error": submit_res.text})
        _update_file_status(file_id, "error", None)
        return

    request_id = submit_res.json().get("requestId")
    self.update_state(state="PROGRESS", meta={"progress": 10, "status": "generating", "job_id": request_id})

    # --- Step 3: 轮询状态 ---
    for i in range(120):  # 最多等 10 分钟
        time.sleep(5)
        status_res = requests.get(
            f"{base_url}/video/status/{request_id}",
            headers={"Authorization": f"Bearer {sf_key}"},
            timeout=10,
        )
        if status_res.status_code != 200:
            continue

        data = status_res.json()
        sf_status = data.get("status", "")
        progress = min(10 + i * 2, 90)
        self.update_state(state="PROGRESS", meta={"progress": progress, "status": "generating"})

        if sf_status == "Succeed":
            video_url = data.get("results", {}).get("videos", [{}])[0].get("url")
            _update_file_status(file_id, "done", video_url)
            return {"status": "done", "preview_url": video_url}

        if sf_status in ("Failed", "Canceled"):
            reason = data.get("reason", "Unknown error")
            _update_file_status(file_id, "error", None)
            return {"status": "error", "error": reason}

    _update_file_status(file_id, "error", None)
    return {"status": "error", "error": "Timeout"}


def _update_file_status(file_id: str, status: str, preview_url):
    """更新数据库里 file 的状态（同步）。"""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(settings.database_url_sync)
        with engine.connect() as conn:
            conn.execute(
                text("UPDATE files SET status = :s, preview_url = :u WHERE id = :id"),
                {"s": status, "u": preview_url, "id": file_id},
            )
            conn.commit()
    except Exception:
        pass


# ── 导出任务 ──────────────────────────────────────────────────────────────────
@celery_app.task(bind=True, name="tasks.export_file")
def export_file_task(self, export_job_id: str, file_id: str, fmt: str):
    """
    将已生成视频重新封装为指定格式并上传 S3。
    当前为占位实现；实际需接入 ffmpeg 或云端转码服务。
    """
    import time
    self.update_state(state="PROGRESS", meta={"progress": 20, "status": "processing"})
    time.sleep(5)
    # TODO: 调用 ffmpeg 转码，上传 S3，更新 export_jobs 表
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(settings.database_url_sync)
        with engine.connect() as conn:
            conn.execute(
                text("UPDATE export_jobs SET status = 'done' WHERE id = :id"),
                {"id": export_job_id},
            )
            conn.commit()
    except Exception:
        pass
    return {"status": "done", "file_url": None}


# ── 声音克隆（硅基流动暂不支持，保留接口待未来接入）────────────────────────────
@celery_app.task(name="tasks.clone_voice")
def clone_voice_task(clone_id: str, audio_url: str, name: str):
    """
    声音克隆任务。
    硅基流动目前不支持声音克隆，可替换为 ElevenLabs /v1/voices/add 或 Fish Audio API。
    当前直接将状态置为 error，前端会提示用户该功能暂不可用。
    """
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(settings.database_url_sync)
        with engine.connect() as conn:
            conn.execute(
                text("UPDATE voice_clones SET status = 'error' WHERE id = :id"),
                {"id": clone_id},
            )
            conn.commit()
    except Exception:
        pass
