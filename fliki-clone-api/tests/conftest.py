"""共享 fixture（Track-08 pytest 工程化）。

设计取舍
--------
1. **单元 vs 集成分离**：``unit`` 标的 case 完全 in-memory（mock gateway / 直接调 helper），
   ``integration`` 标的 case 走真 PG（开发机的 ``fliki`` 库）。
2. **PG 自动跳过**：CI runner 没装 PG 时通过 ``pg_engine`` fixture 主动 ``pytest.skip``，
   避免红 CI；本机有 PG 直接跑。
3. **测试隔离**：所有写库的 fixture 都用唯一前缀（``test_t:`` / ``test_u:`` / ``test_p:``）+
   teardown 一次性 DELETE。绝不 truncate 已有业务数据。
4. **gateway 单例 reset**：fake provider 注入后通过 ``patch_gateway`` fixture 接管，
   避免污染其它 case；test 结束自动恢复真单例。
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any, Iterator, Optional

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


# ── 兼容性 hook：放宽 Settings extra 校验 ──────────────────────────────────
# 背景：track-01-credentials-fernet 在 .env 里加了 PUBLISH_CREDENTIAL_FERNET_KEY，
# 但 app/config.py 还没合并对应字段（Track-01 / Track-08 互不依赖、并行 merge）。
# pydantic-settings 默认对 .env 多余字段抛 ValidationError，会让所有 case 启动就挂。
#
# 解法：在 conftest 顶层（任何 case 之前）：
# 1. 临时把 ``app.config.Settings`` 包一层，强制 ``extra='ignore'``，并装回 module
# 2. 清掉 ``get_settings`` 的 lru_cache，让后续调用走新版
# 3. **不**碰真 app/config.py（互斥锁规则）；Track-01 落库 fernet 字段后这段
#    workaround 应自动失效但仍无害（extra='ignore' 永远向后兼容）
def _relax_settings_extra() -> None:
    try:
        from pydantic_settings import SettingsConfigDict

        from app import config as cfg_mod

        OrigSettings = cfg_mod.Settings

        # pydantic v2 用 model_config dict 控制行为；旧版 class Config 也兼容
        new_model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            case_sensitive=False,
            extra="ignore",
        )

        class _PatchedSettings(OrigSettings):  # type: ignore[misc, valid-type]
            model_config = new_model_config

        cfg_mod.Settings = _PatchedSettings  # 替换模块级符号
        cfg_mod.get_settings.cache_clear()
    except Exception:
        # workaround 失败也别阻塞收集；后面 case 会暴露真问题
        pass


_relax_settings_extra()

# ── 默认 DB 配置 ─────────────────────────────────────────────────────────────
# 优先 env，其次 .env 默认（fliki@localhost 走 peer auth）。
# 测试不应该改变 DATABASE_URL_SYNC，但 fixture 主动读这一个，避免依赖 settings。
DEFAULT_DSN = os.getenv(
    "TEST_DATABASE_URL_SYNC",
    os.getenv(
        "DATABASE_URL_SYNC",
        "postgresql://zhaoguangyuan@localhost:5432/fliki",
    ),
)


# ── 通用 helpers ────────────────────────────────────────────────────────────


def _try_pg() -> Optional[Engine]:
    """尝试连一次 PG；不可达返 None，让 fixture 触发 skip。"""
    try:
        engine = create_engine(DEFAULT_DSN, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except Exception:
        return None


@pytest.fixture(scope="session")
def pg_engine() -> Engine:
    """会话级 PG engine。不可达时跳过；有则返回 engine（不在 fixture 里清表）。"""
    engine = _try_pg()
    if engine is None:
        pytest.skip(
            f"PostgreSQL 不可用 (DSN={DEFAULT_DSN})；"
            "集成测试已跳过。本地跑 PG 后重试。"
        )
    return engine


# ── tenant / user / file 临时数据 ───────────────────────────────────────────


@dataclass
class TempTenant:
    """临时 tenant 句柄。teardown 时删 tenant_quotas + provider_concurrency_buckets +
    pipeline_runs（仅 tenant_id 命中）。
    """

    tenant_id: str
    plan: str = "free"


@pytest.fixture
def temp_tenant(pg_engine: Engine) -> Iterator[TempTenant]:
    """单 case 一个 tenant；前缀 ``test_t:`` 与生产 ``ws:``/``u:`` 命名空间互斥。"""
    tid = f"test_t:{uuid.uuid4().hex[:12]}"
    yield TempTenant(tenant_id=tid)
    _cleanup_tenant(pg_engine, tid)


def _cleanup_tenant(engine: Engine, tenant_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM provider_concurrency_buckets WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
        conn.execute(
            text("DELETE FROM tenant_quotas WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
        conn.execute(
            text("UPDATE pipeline_runs SET tenant_id = NULL WHERE tenant_id = :t"),
            {"t": tenant_id},
        )


@pytest.fixture
def temp_user(pg_engine: Engine) -> Iterator[dict[str, Any]]:
    """临时用户行；publish_plans / platform_credentials 需要真 user 行外键。

    users 表对 plan / email 有 NOT NULL 约束；fixture 一次写齐。
    """
    uid = f"test_u_{uuid.uuid4().hex[:10]}"
    email = f"{uid}@pytest.local"
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO users
                    (id, email, name, hashed_password, plan,
                     credits_used, credits_total, email_notifications,
                     youtube_channel_ids, created_at, updated_at)
                VALUES
                    (:id, :em, :nm, '!', 'free',
                     0, 0, false,
                     '{}', NOW(), NOW())
                """
            ),
            {"id": uid, "em": email, "nm": "pytest user"},
        )
    try:
        yield {"id": uid, "email": email, "plan": "free"}
    finally:
        with pg_engine.begin() as conn:
            # 删掉所有依赖：先 publish_plans / platform_credentials / files / pipeline_runs / renders
            # 顺序避免外键报错
            conn.execute(
                text(
                    "DELETE FROM publish_plans WHERE file_id IN "
                    "(SELECT id FROM files WHERE user_id = :u)"
                ),
                {"u": uid},
            )
            conn.execute(
                text(
                    "DELETE FROM renders WHERE file_id IN "
                    "(SELECT id FROM files WHERE user_id = :u)"
                ),
                {"u": uid},
            )
            conn.execute(
                text("DELETE FROM platform_credentials WHERE user_id = :u"),
                {"u": uid},
            )
            conn.execute(
                text("DELETE FROM pipeline_runs WHERE user_id = :u"),
                {"u": uid},
            )
            conn.execute(text("DELETE FROM files WHERE user_id = :u"), {"u": uid})
            conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})


@pytest.fixture
def temp_file(pg_engine: Engine, temp_user: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """临时 file 行；publish_plans 必填。"""
    fid = f"test_f_{uuid.uuid4().hex[:10]}"
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO files
                    (id, user_id, title, status, scene_count, type, language,
                     project_type, aspect_ratio, copyright_confirmed,
                     created_at, updated_at)
                VALUES
                    (:id, :u, 'pytest file', 'draft', 0, 'video', 'zh',
                     'video', '16:9', true, NOW(), NOW())
                """
            ),
            {"id": fid, "u": temp_user["id"]},
        )
    yield {"id": fid, "user_id": temp_user["id"], "user": temp_user}
    # files 由 temp_user teardown 一并清掉


@pytest.fixture
def temp_run(pg_engine: Engine, temp_file: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """临时 pipeline_run；renders / publish_plans 都通过它的 id 关联回去。"""
    rid = f"test_run_{uuid.uuid4().hex[:10]}"
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO pipeline_runs
                    (id, file_id, user_id, template_name, state,
                     graph_json, inputs_json, outputs_json,
                     cost_estimated_usd, cost_actual_usd, cost_reserved_usd,
                     created_at, updated_at)
                VALUES
                    (:id, :f, :u, 'script_only', 'succeeded',
                     'null', 'null', 'null',
                     0, 0, 0,
                     NOW(), NOW())
                """
            ),
            {"id": rid, "f": temp_file["id"], "u": temp_file["user_id"]},
        )
    yield {"id": rid, "file_id": temp_file["id"], "user_id": temp_file["user_id"]}


@pytest.fixture
def temp_render(
    pg_engine: Engine,
    temp_file: dict[str, Any],
    temp_run: dict[str, Any],
) -> Iterator[dict[str, Any]]:
    """临时 render 行；publish_plans.render_id 外键必填且 url 必非空。"""
    rid = f"test_r_{uuid.uuid4().hex[:10]}"
    url = f"https://test.local/render/{rid}.mp4"
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO renders
                    (id, run_id, file_id, aspect_ratio, is_primary, url,
                     duration_s, shot_count, muxed, burned_in_subtitles,
                     looped_video, status, created_at)
                VALUES
                    (:id, :r, :f, '16:9', false, :url,
                     12.5, 0, false, false,
                     false, 'ready', NOW())
                """
            ),
            {"id": rid, "r": temp_run["id"], "f": temp_file["id"], "url": url},
        )
    yield {
        "id": rid,
        "file_id": temp_file["id"],
        "run_id": temp_run["id"],
        "url": url,
    }


# ── gateway mock ─────────────────────────────────────────────────────────────
# 思路：不替换全局单例，而是给 caller 提供一个 ``FakeGateway`` 类
# + 一个 ``patch_gateway`` 上下文 fixture：把 ``app.services.model_gateway.get_gateway``
# 临时换成返回 fake 的 callable，case 退出后还原。
#
# 这样既不污染单例，也不需要碰真 provider 注册。


@dataclass
class FakeCall:
    """记录一次 gateway.run() 调用，方便 assert 顺序与参数。"""

    action: str
    params: dict[str, Any]
    user_id: Optional[str]
    tenant_id: Optional[str]


class FakeGateway:
    """最小 gateway 替身。

    - 业务侧只用 ``run(request)`` / ``estimate(request)``；其余方法不实现
    - 通过 ``responses`` 列表按调用顺序返回；缺失时返 SUCCEEDED 空 output
    - ``calls`` 列表记录所有进来的请求，便于 case 断言顺序
    """

    def __init__(self) -> None:
        self.responses: list[Any] = []  # list of RenderResult or callable(req)->RenderResult
        self.calls: list[FakeCall] = []

    def queue(self, *results: Any) -> "FakeGateway":
        self.responses.extend(results)
        return self

    def estimate(self, request: Any) -> float:
        return 0.0

    def run(self, request: Any) -> Any:
        from app.services.model_gateway.types import (
            CallStatus,
            ProviderName,
            RenderResult,
        )

        self.calls.append(
            FakeCall(
                action=getattr(request.action, "value", str(request.action)),
                params=request.params or {},
                user_id=request.user_id,
                tenant_id=getattr(request, "tenant_id", None),
            )
        )
        if not self.responses:
            return RenderResult(
                status=CallStatus.SUCCEEDED,
                provider=ProviderName.DEMO,
                output=None,
                cost_usd=0.0,
            )
        nxt = self.responses.pop(0)
        if callable(nxt):
            return nxt(request)
        return nxt


@pytest.fixture
def fake_gateway() -> FakeGateway:
    """单纯的 FakeGateway 实例，case 自己拼 responses。"""
    return FakeGateway()


@pytest.fixture
def patch_gateway(monkeypatch: pytest.MonkeyPatch, fake_gateway: FakeGateway) -> FakeGateway:
    """把 ``app.services.model_gateway.get_gateway`` 替换成返回 fake 的 callable。

    ArtAgent / VoiceAgent 内部都是 ``from app.services.model_gateway import get_gateway``
    然后 ``get_gateway()``；patch 模块内属性即可（monkeypatch 自动 undo）。
    """
    import app.services.model_gateway as mg
    import app.services.pipeline.agents.art as art_module
    import app.services.pipeline.agents.voice as voice_module

    def _get():
        return fake_gateway

    monkeypatch.setattr(mg, "get_gateway", _get, raising=True)
    monkeypatch.setattr(art_module, "get_gateway", _get, raising=True)
    monkeypatch.setattr(voice_module, "get_gateway", _get, raising=True)
    return fake_gateway


# ── PipelineContext 工厂 ─────────────────────────────────────────────────────


def make_ctx(
    *,
    user_id: Optional[str] = "test-user",
    file_id: Optional[str] = "test-file",
    tenant_id: Optional[str] = None,
    inputs: Optional[dict[str, Any]] = None,
    upstream: Optional[dict[str, dict[str, Any]]] = None,
):
    """统一的 PipelineContext 构造器，不需要真起 run/step。"""
    from app.services.pipeline.types import PipelineContext

    return PipelineContext(
        run_id=f"test-run-{uuid.uuid4().hex[:6]}",
        step_id=f"test-step-{uuid.uuid4().hex[:6]}",
        user_id=user_id,
        file_id=file_id,
        inputs=inputs or {},
        upstream_outputs=upstream or {},
        tenant_id=tenant_id,
    )


__all__ = [
    "DEFAULT_DSN",
    "FakeCall",
    "FakeGateway",
    "TempTenant",
    "fake_gateway",
    "make_ctx",
    "patch_gateway",
    "pg_engine",
    "temp_file",
    "temp_render",
    "temp_tenant",
    "temp_user",
]
