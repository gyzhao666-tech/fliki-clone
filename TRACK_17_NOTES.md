# Track-17 · SSE 断网重连 last_event_id 续传

> 分支：`track-17-sse-resume`（worktree：`/Users/zhaoguangyuan/project/empty-track17`）
> 基线：`main` @ `68fccd3`（第三波 backlog 文档）+ alembic head `a1b2c3d4e5f6`（不动）
> 状态：✅ 完成；本地 51/51 PASS（基线 41 + 本 Track 新加 10）；真连 redis 烟测 3/3 PASS

## 背景 / 为什么做

当前 SSE 在网络抖动断流后，客户端只能从 `snapshot` 重头拉 → 丢一批 step_state；
浏览器原生 `EventSource` 已经支持自动断网重连 + 通过 `Last-Event-ID` 头续传，但
后端 `events.py` 是纯 redis pub/sub（无持久化、无 id），客户端拿不到 id 也续不了。

Track-17 把 `events.py` 升级为 **redis Stream（XADD + XREAD）+ pub/sub 双写**：
每条事件落到 `{channel}:stream`（MAXLEN ~ 1000 trim），SSE 端 emit `id: <stream_id>`
让浏览器缓存到 `lastEventId`；断网重连时浏览器自动带 `Last-Event-ID` 头，后端
从该 id **之后**续推 redis Stream，不丢断网期间的事件。pipeline run 与 publish_plan
两条 SSE 一起做。

## 改了哪些文件 / 为什么

### 后端

| 文件 | 改动 | 为什么 |
|---|---|---|
| `fliki-clone-api/app/services/pipeline/events.py` | `_publish_to_channel` 双写 `XADD {ch}:stream * data <json>`（MAXLEN ~ 1000 approximate trim）+ `PUBLISH {ch}`；`_subscribe_channel` 改用 `client.xread({stream_key: cursor}, block=1000)`，`cursor=last_event_id or "$"`；yield 升级为 3-tuple `(event_type, payload, entry_id)`；`subscribe` / `subscribe_publish_plan` 加 `last_event_id` 透传参数 | Stream 是 last_event_id 续传的源；pub/sub 保留兼容老消费者，0-延迟 push 互为冗余；XREAD BLOCK 1000ms 短超时仍 idle yield None 让上层心跳/断连检测继续工作；MAXLEN 1000 ≈ 6 个完整 video_full run |
| `fliki-clone-api/app/routers/pipelines.py` | `_sse_format(event, data, event_id=None)`：非空时 prepend `id: <event_id>\n`；`_pipeline_sse_stream(...)` 多接 `last_event_id`；`pipeline_events_stream` 从 `request.headers.get("Last-Event-ID")` 透传；async for 解 3-tuple | 浏览器原生 EventSource 仅认 `id:` 字段更新 `lastEventId`；`Last-Event-ID` 是 W3C SSE 规范规定的请求头 |
| `fliki-clone-api/app/routers/production.py` | 同样：`_sse_format` 加 `event_id` kwarg；`_publish_plan_sse_stream` 加 `last_event_id`；`publish_plan_events_stream` 从请求头取 `Last-Event-ID` 透传 | 让 publish_plan 的 SSE 也支持续传，前端 `usePublishPlanStream` 同步受益 |
| `fliki-clone-api/tests/test_track17_sse_resume.py`（**新**）| 10 个 unit case：publish 双写 + XADD MAXLEN/approximate；XADD 失败不阻塞 PUBLISH；无 redis 时 noop；subscribe 把 `last_event_id` 透传给 xread，cursor 推进，事件 id 单调递增；缺省 cursor=`$`；redis ping 失败 subscribe 安静退；两个 router 的 `_sse_format` 在 event_id 非空时 emit `id:`，缺省不 emit | 锁住关键边界，避免后续重构悄悄破坏断网续传链路 |

### 前端

| 文件 | 改动 | 为什么 |
|---|---|---|
| `fliki-clone/src/hooks/use-pipeline-stream.ts` | onerror handler：先看 `es.readyState`；`CONNECTING(0)` 时**不打断**（浏览器在带 `Last-Event-ID` 自动重连）；只有 `CLOSED(2)` 才计 `consecutiveErrors`，达 2 次 fallback polling；顶部协议注释加 `id:` 字段 + 续传行为描述 | 浏览器原生 EventSource 在断网恢复后自动重连并送 `Last-Event-ID`，后端从断点续推 → 不丢事件；hook 主动 close 会破坏该机制，所以仅在不可恢复（CLOSED）路径计入失败 |
| `fliki-clone/src/hooks/use-publish-plan-stream.ts` | onerror handler 同样区分 `readyState`；顶部协议注释加 `id:` 字段 + 续传行为描述 | publish_plan SSE 与 pipeline SSE 共用同一 redis Stream 续传内核，前端续传策略也对齐 |

> **互斥锁错峰**：T-13（YouTube chunked upload）改的是 hook 内 `addEventListener`
> 的 switch case（即 `handleEvent` 加 `upload_progress`）；T-17 改的是 `addEventListener("error", ...)`
> 与文件顶部协议 doc。同文件不同函数体，零冲突。

## 烟测结果

### 1. 单元测试（mock redis）

```bash
cd fliki-clone-api && \
  /Users/zhaoguangyuan/project/empty/fliki-clone-api/.venv/bin/python -m pytest \
  tests/test_track17_sse_resume.py -v
```

```
tests/test_track17_sse_resume.py::test_publish_to_channel_writes_xadd_and_pubsub PASSED [ 10%]
tests/test_track17_sse_resume.py::test_publish_xadd_failure_does_not_break_pubsub PASSED [ 20%]
tests/test_track17_sse_resume.py::test_publish_with_no_redis_client_is_noop PASSED [ 30%]
tests/test_track17_sse_resume.py::test_subscribe_passes_last_event_id_to_xread_and_yields_id PASSED [ 40%]
tests/test_track17_sse_resume.py::test_subscribe_default_cursor_is_dollar_sign PASSED [ 50%]
tests/test_track17_sse_resume.py::test_subscribe_redis_init_failure_is_silent PASSED [ 60%]
tests/test_track17_sse_resume.py::test_sse_format_emits_id_when_event_id_present_pipeline PASSED [ 70%]
tests/test_track17_sse_resume.py::test_sse_format_skips_id_when_none_pipeline PASSED [ 80%]
tests/test_track17_sse_resume.py::test_sse_format_emits_id_when_event_id_present_production PASSED [ 90%]
tests/test_track17_sse_resume.py::test_sse_format_skips_id_when_none_production PASSED [100%]
============================== 10 passed in 1.03s ==============================
```

### 2. 全量回归（41 baseline + 10 新）

```bash
cd fliki-clone-api && /Users/zhaoguangyuan/project/empty/fliki-clone-api/.venv/bin/python -m pytest tests/ -q
```

```
51 passed in 1.38s
```

### 3. 真连 redis Stream 续传烟测（local redis on :6379）

跑 inline python 串：publish 3 条 → 看 XLEN/XRANGE → subscribe(last_event_id=ids[0])
应只回放 ids[1:] → subscribe(无 last_event_id) 应用 `$` 不重放历史 → cleanup DEL stream key。

```
[1] publish 3 events to pipeline:run:track17-smoke-...:stream ...
    XLEN=3; entries=
      id=...031-0 type=step_state data={'i': 1, 'state': 'running'}
      id=...032-0 type=step_state data={'i': 2, 'state': 'running'}
      id=...032-1 type=run_state  data={'i': 3, 'state': 'succeeded'}

[2] subscribe(last_event_id=...031-0) → expect only ids[1:]
      type=step_state eid=...032-0 payload={'i': 2, 'state': 'running'}
      type=run_state  eid=...032-1 payload={'i': 3, 'state': 'succeeded'}
      idle tick × 2
    ✓ resumed from ...031-0, got entries [...032-0, ...032-1]

[3] subscribe(last_event_id=None) → expect $ → only idle (no replay)
    first yield = None
    ✓ default cursor = $ (no replay of historical events)

=== all 3 smoke checks PASS ===
```

> 烟测命令是 inline python，跑完即清理 stream key（按规则 12 不留 ad-hoc 脚本）。
> 完整脚本写在本 NOTES「Follow-up」「人工 e2e」段供协调者复用。

### 4. lint / typecheck

- 后端 `ReadLints` 关键 4 文件：0 error
- 前端 `tsc --noEmit -p tsconfig.json`：0 error
- 前端 `eslint src/hooks/use-pipeline-stream.ts src/hooks/use-publish-plan-stream.ts`：
  0 error，2 warning（pre-existing「Unused eslint-disable directive」，与本 Track 无关）

## 已知边界 / 设计取舍

1. **MAXLEN ~ 1000 approximate trim**：单 stream 最多保留 1000 条事件。一次完整
   `video_full` run 约 100-150 条 step_state + 几条 run_state ≈ 130 条；1000 条够覆
   盖 ~6 个 run 的滞留事件 + 浏览器重连历史。tab 后台 30 分钟 + 重连请求历史能拿
   到的事件覆盖率 ≈ 100%。如果未来 step_state 频次大幅上升（卡拉 OK / shot-level
   流式），考虑把 MAXLEN 调到 5000 或拆 per-step substream。
2. **publish 双写但订阅只走 Stream**：当前订阅端已切到 XREAD；pub/sub 仅保留
   写路径（兼容老消费者）。未来可在确认无老消费者后单写 XADD 简化。
3. **Stream 持久化时长**：redis Stream 默认随 redis 进程生命周期；redis 重启或
   `redis-cli FLUSHDB` 后所有 stream 清空。当前 redis 是开发机本地实例，重启等
   于「断网无法续传 → 客户端拉 snapshot 兜底」是 acceptable。生产 redis（如
   ElastiCache）需要确认开 AOF / RDB 持久化。
4. **`$` 默认游标不接历史**：新连接（无 `Last-Event-ID` 头）只接连接后产生的
   新事件，与原 pub/sub 行为对齐。这意味着首连前发生的事件**靠 snapshot** 对齐，
   不靠 Stream 回放——避免老 client 第一次连就被 1000 条历史淹没。
5. **跨进程 fan-out**：当前 SSE 每个客户端各跑一个 XREAD BLOCK；redis 5+ 单
   reader 性能足够；多客户端共享一个 reader / consumer group 是 follow-up。
6. **snapshot 不带 id**：snapshot 是 SSE 端点直接生成的全量对齐，不来自 redis
   Stream，emit `id:` 没意义（浏览器只把最后一条 id 缓存为 lastEventId）。

## Follow-up

1. **真账号 e2e 烟测**（背景：sandbox 起 backend 会被注入 HTTP_PROXY，`curl -N`
   走 SSE 不稳；留给协调者在合并主仓后真启 backend 跑）：

   ```bash
   # 需要先 kill 旧 backend pid 30876，重启加载新代码：
   kill 30876
   cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && \
     .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

   # 启 video_full / 任意 run 拿到 run_id；用 curl 拉一会再 kill 模拟断网：
   TOKEN=<browser cookie 里的 token>
   curl -N -H "Cookie: token=$TOKEN" -H "Accept: text/event-stream" \
     http://127.0.0.1:8000/api/pipelines/<run_id>/events &
   CURL_PID=$!
   sleep 5  # 收几条事件，记下最后一条的 id
   kill $CURL_PID

   # 重连带 Last-Event-ID：应只拿到 prev id 之后的事件，不重放
   curl -N -H "Cookie: token=$TOKEN" -H "Accept: text/event-stream" \
     -H "Last-Event-ID: <最后一条 id>" \
     http://127.0.0.1:8000/api/pipelines/<run_id>/events
   ```

   预期：每条事件前有 `id: <stream_id>` 行；snapshot 仍照发；后续事件只回放
   `Last-Event-ID` 之后的（XREAD 语义）。

2. **生产 redis 持久化**：上线前确认 redis Stream 的 AOF/RDB 配置，避免 redis 重
   启清空 stream → 客户端续传断流（虽然有 snapshot 兜底，但短时间多 client 涌入
   snapshot 会增加 PG 压力）。

3. **跨 SSE 进程 consumer group**：未来如果 web 进程横向扩到多副本（Cloud Run /
   多 uvicorn worker），可以用 redis Stream consumer group 让一个事件被任意一个
   副本的 SSE 客户端收到一次（当前是各副本各自 XREAD，等于 fan-out）。当前架
   构单进程 web，不需要。

4. **MAXLEN 监控**：加一条 metric `pipeline_event_stream_xlen{channel=...}` 让运
   维能看到单 run 是否接近 1000 条上限；超阈值告警。当前规模不需要。

5. **inline 真连 redis 续传烟测脚本**（写在本 NOTES 段「3. 真连 redis Stream 续
   传烟测」上面那条 inline python；跑完即清理；不留 ad-hoc 脚本到仓库；协调者
   复现可直接复用 NOTES 里那段）：

   ```bash
   cd /Users/zhaoguangyuan/project/empty-track17/fliki-clone-api && \
     /Users/zhaoguangyuan/project/empty/fliki-clone-api/.venv/bin/python <<'PY'
   # ... 见 NOTES「3. 真连 redis Stream 续传烟测」段，已删除原脚本文件 ...
   PY
   ```

## 互斥锁 & 合规检查

- ✅ 没改 `.env` / `app/config.py`
- ✅ 没改 alembic / schema（Track-16 独占迁移槽 `b2c3d4e5f6a7`）
- ✅ `events.py` 内核独占（与 Track-15 / Track-16 不冲突）
- ✅ `pipelines.py` SSE generator 段、`production.py` SSE generator 段独占
- ✅ 前端 hook `addEventListener("error", ...)` 段独占（**与 Track-13 错峰**：T-13
  改 `handleEvent`/`addEventListener("upload_progress", ...)` 加 upload_progress
  case；T-17 改 onerror connection 框架；同文件不同函数体）
- ✅ 没 push 到 remote
- ✅ 没更新 `SESSION_HANDOFF.md`（留给协调者）
- ✅ 全量 pytest 51 PASS，前端 typecheck 0 error，eslint 仅 2 个 pre-existing warning
