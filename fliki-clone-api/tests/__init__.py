"""pytest 测试套件根 (Track-08)。

子模块布局：
- ``conftest.py``         共享 fixture：DB engine、临时 tenant/user/file 清理、mock gateway
- ``test_quota_v2.py``    配额 v2（tenant_quotas + provider_concurrency_buckets + gateway 接入点）
- ``test_voice_v4.py``    VoiceAgent v4 字幕 word/line/shot 三档对齐 + mock gateway 端到端
- ``test_art_v3.py``      ArtAgent v3 角色一致性 helpers + 集成
- ``test_publishing.py``  发布执行器 v1（dry-run / youtube / bilibili / 重复执行 / 未知平台 fallback）

每个 case 用 ``@pytest.mark.unit`` 或 ``@pytest.mark.integration`` 标分组：
- unit         不需要 DB / 不需要外网；CI 默认全跑
- integration  需要本地 PG（``DATABASE_URL_SYNC`` 默认 ``postgresql://zhaoguangyuan@localhost:5432/fliki``）
               未配 / 不可达时自动 ``pytest.skip``，避免 CI 在缺 PG 的 runner 上失败
"""
