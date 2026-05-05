.PHONY: install install-dev dev worker migrate upgrade seed lint fmt test test-unit test-integration test-cov

# ── Setup ─────────────────────────────────────────────
install:
	python -m pip install -r requirements.txt

# 测试 / 开发依赖（pytest 等），独立于业务运行时依赖
install-dev:
	python -m pip install -r requirements-dev.txt

venv:
	python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# ── Dev server ────────────────────────────────────────
dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# ── Celery workers ────────────────────────────────────
# 旧 worker：服务 scene-based 单段视频 / 声音克隆 / 导出（utils.tasks 那一套）
worker:
	celery -A app.utils.tasks.celery_app worker --loglevel=info --concurrency=4

# Pipeline 调度 worker：监听三条队列 (interactive / media / default)
# 配合 .env 里的 CELERY_ENABLED=true 让 router 走 Celery dispatch
pipeline-worker:
	celery -A app.services.pipeline.celery_app worker \
	  --loglevel=info \
	  -Q interactive,media,default \
	  --concurrency=2

# 单队列 high-throughput 模式（生产可拆三个进程，每队列一个）
pipeline-worker-media:
	celery -A app.services.pipeline.celery_app worker --loglevel=info -Q media --concurrency=2

pipeline-worker-interactive:
	celery -A app.services.pipeline.celery_app worker --loglevel=info -Q interactive --concurrency=4

# ── Database migrations ───────────────────────────────
migrate:
	alembic revision --autogenerate -m "$(msg)"

upgrade:
	alembic upgrade head

downgrade:
	alembic downgrade -1

# ── Seed data ─────────────────────────────────────────
seed:
	python scripts/seed.py

# ── Code quality ──────────────────────────────────────
lint:
	ruff check app/

fmt:
	ruff format app/

# ── Tests ─────────────────────────────────────────────
# 全套（unit + integration；缺 PG 时 integration 自动 skip 不挂红）
test:
	pytest tests/ -v

# 仅纯单元（不连 PG / 不调外部）；CI 默认门禁推荐用这条
test-unit:
	pytest tests/ -v -m unit

# 仅集成（需要本地 PG 跑过 alembic upgrade head）
test-integration:
	pytest tests/ -v -m integration

test-cov:
	pytest tests/ -v --cov=app --cov-report=html
