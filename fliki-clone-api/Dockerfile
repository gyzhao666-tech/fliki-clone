# Track-28 · backend + celery worker 共用镜像
# 单镜像两种 entrypoint：
#   - backend:  默认 CMD `uvicorn app.main:app --host 0.0.0.0 --port 8000`
#   - worker:   docker-compose 通过 `command:` 覆盖为 `celery -A app.services.pipeline.celery_app worker ...`
# 这样保证 backend / worker 代码一致、依赖一致；少维护一份 Dockerfile。
#
# 镜像基础：python:3.10-slim（与本机 venv Python 3.10 对齐，避免任何 ABI 漂移）
# 依赖：
#   - ffmpeg：EditAgent / 视频转码 + 字幕烧录硬依赖（本地 brew 装 6.0；apt 给 5.x 也够用）
#   - libpq5：psycopg2-binary 运行时；libpq-dev + gcc：极少数源码编译路径（reportlab / cryptography 走 wheel 不会触发，但留作兜底）
#   - curl：docker-compose backend healthcheck 用
FROM python:3.10-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libpq5 \
        libpq-dev \
        gcc \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先 COPY requirements 单独装，最大化 layer cache：
# 业务代码 / alembic 改动后无需重新装依赖。
COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# 业务代码 + 迁移 + Makefile + scripts
# .dockerignore（同目录）已经过滤掉 .venv / __pycache__ / .pytest_cache / .env 等
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY Makefile ./Makefile
COPY scripts ./scripts
COPY pytest.ini ./pytest.ini

EXPOSE 8000

# 默认起 backend；worker 在 docker-compose.yml 用 `command:` 覆盖
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
