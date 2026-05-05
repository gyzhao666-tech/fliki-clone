# Track-13 · YouTube chunked PUT + 真账号 e2e

> 分支：`track-13-youtube-chunked-upload`
> 基线：`main` @ `68fccd3`（第三波派发起点；alembic head `a1b2c3d4e5f6`，未触迁移槽）
> 互斥锁遵守：✅ 没改 `.env`/`app/config.py`；✅ 没占 alembic 槽（T-16 独占）；✅ `use-publish-plan-stream.ts` 只动 `addEventListener("upload_progress")`，没动 T-17 的 `buildEventSource` 框架；✅ `pipeline/page.tsx` 只动 `PlanRow` 进度条段。

## 1. 改了什么 / 为什么

### 后端

| 文件 | 改动 | 为什么 |
|---|---|---|
| `fliki-clone-api/app/services/publishing/adapters/base.py` | `PublishRequest` 加 `progress_cb: Optional[Callable[[dict], None]]`（不参与 dataclass 比较 / repr） + 新增 `ProgressInfo` / `ProgressCb` 类型别名导出 | adapter 与 executor 之间需要一个不污染序列化、可注入的回调通道；放 dataclass 字段是最简单的扩展点（保持现有 `adapter.upload(req)` 协议不变） |
| `fliki-clone-api/app/services/publishing/adapters/youtube.py` | 完全重写真发路径：删掉 v1 的 `multipart` 一把发；改成 ① `_initiate_resumable_upload`（POST 拿 `Location` session uri，带 `X-Upload-Content-Length` 预声明）→ ② `_chunked_put` 把视频切成 8 MiB 片，每片带 `Content-Range: bytes X-Y/total` PUT，308 滚下一片，最后片 200/201 + JSON `{id}`；③ 单片 5xx/408/429 指数退避重试（1s/2s/4s）最多 3 次，4xx 立即抛 `PublishError`；④ 每完成一片调一次 `progress_cb({phase, bytes_uploaded, total, percent, chunk_index, chunk_count})`；⑤ 下载阶段也回调一次 start + complete 让前端进度条不在 0% 卡着 | 1080p / 60s+ 视频在 v1 单 multipart + 60s HTTP timeout 下经常断流；resumable upload v2 是 YouTube 推荐的官方协议；进度回调让前端能渲流畅进度条而不是只看 spinner 干转 |
| `fliki-clone-api/app/services/publishing/executor.py` | 新增 `_make_progress_cb(plan_id)`：闭包返一个回调，负责 (a) read-modify-write `publish_plans.meta_json` 把 `upload_progress` 字段 merge 进去；(b) 调 `pipeline.events.publish_plan_event(plan_id, "upload_progress", {...})` 推 SSE。`execute_publish_plan` 构造 `PublishRequest` 时把 cb 透传进去 | `meta_json` 是 PG `JSON` 列不是 `JSONB`，没法用 `||` 直接合并 → read-modify-write 是最稳的兼容写法；进度同时写 DB 和 SSE 是为了：刷新页面也能看到当前进度（DB 是权威），实时推送是为了流畅交互（SSE） |
| `fliki-clone-api/tests/test_youtube_chunked_upload.py` | **新增** 8 个 `@pytest.mark.unit` case：① `_chunked_put` 3 片 progress_cb 单调递增 + Content-Range 正确分片；② 单片 200 直接返 video_id；③ 5xx 重试一次后 200 + 断 sleeper 被调；④ 持续 5xx 超过 MAX_RETRIES_PER_CHUNK 抛 PublishError；⑤ 401 不重试立即抛；⑥ `_initiate_resumable_upload` 200 + `Location` 头返 session uri 且 headers 含 `X-Upload-Content-Length`；⑦ initiate 500 抛 PublishError；⑧ adapter 端到端走 chunked 路径返 `ok=True` + `meta.upload_mode=resumable_chunked` + 进度事件含 downloading + uploading 两个 phase | 网络协议层全 mock `requests.put/post/get`，`sleeper` 注入空 lambda 跳过指数退避真等待；保持 unit marker（不依赖 PG），纯协议测试不污染集成层 |

### 前端

| 文件 | 改动 | 为什么 |
|---|---|---|
| `fliki-clone/src/hooks/use-publish-plan-stream.ts` | 加 `UploadProgressEvent` 类型 + `onUploadProgress` 可选回调 + `latestProgress` state；start() 时清空，stop() 不动（让 PlanRow 自己决定何时不展示）；新增 `es.addEventListener("upload_progress", ...)` 与既有 `publish_plan_state` listener 平级 | T-13 互斥锁只占 `handleEvent` switch case 段（这里实际是 addEventListener 平级新增；T-17 后续可能整体改成 switch dispatch）；progress 不是终态事件，不能让它触发 finishWith |
| `fliki-clone/src/app/[locale]/(app)/app/project/[id]/pipeline/page.tsx::PlanRow` | 新增局部 `uploadProgress = executing ? planStream.latestProgress : null`；新增 `<UploadProgressBar>` 子组件（细横条 + percent + `{uploaded}/{total}` 文案 + `formatBytes`），仅 executing + 收到 progress 时挂在 plan.error 之前 | 进度条只在「派发到 worker + 收到第一片进度」之后才出现，避免 dry-run / bilibili 等不分片的 platform 莫名渲一根空条；下载阶段灰色 / 上传阶段 sky 主色，让用户看清「下载渲染」vs「真上传」 |

## 2. 烟测命令 + 结果

### 单元 + 集成（pytest）

```bash
cd /Users/zhaoguangyuan/project/empty-track13/fliki-clone-api && \
  /Users/zhaoguangyuan/project/empty/fliki-clone-api/.venv/bin/python -m pytest tests/ -q
```

结果：**49 passed in 0.66s**（41 baseline + 8 new `test_youtube_chunked_upload.py`，零回归）。

新增测试明细：

```
tests/test_youtube_chunked_upload.py::test_chunked_put_streams_progress_per_chunk PASSED
tests/test_youtube_chunked_upload.py::test_chunked_put_returns_video_id_on_final_chunk PASSED
tests/test_youtube_chunked_upload.py::test_chunked_put_retries_on_5xx_with_backoff PASSED
tests/test_youtube_chunked_upload.py::test_chunked_put_gives_up_after_max_retries PASSED
tests/test_youtube_chunked_upload.py::test_chunked_put_4xx_non_retriable_raises_immediately PASSED
tests/test_youtube_chunked_upload.py::test_initiate_resumable_upload_returns_session_uri PASSED
tests/test_youtube_chunked_upload.py::test_initiate_resumable_upload_5xx_raises PASSED
tests/test_youtube_chunked_upload.py::test_youtube_adapter_uses_chunked_path_when_real_publish_on PASSED
```

### 后端 import 健康检查

```bash
cd /Users/zhaoguangyuan/project/empty-track13/fliki-clone-api && \
  /Users/zhaoguangyuan/project/empty/fliki-clone-api/.venv/bin/python \
    -c "import app.main; print('ok routes=' + str(len(app.main.app.routes)))"
# → ok routes=116
```

### 前端 TypeScript 类型检查

```bash
cd /Users/zhaoguangyuan/project/empty-track13/fliki-clone && \
  /Users/zhaoguangyuan/project/empty/fliki-clone/node_modules/.bin/tsc --noEmit
# → 0 errors（ln -s 借用主 worktree node_modules 后跑，跑完 unlink）
```

### 真账号 e2e（**未跑**，留给协调者人工）

需要真 OAuth 凭证 + 一段 60MB 测试 mp4：

```bash
# 1. 启 backend（必须 cd fliki-clone-api，不要带 --reload）
cd /Users/zhaoguangyuan/project/empty-track13/fliki-clone-api && \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2. 用前端 PlatformCredentialsPanel 绑 YouTube OAuth（要 .env 配 GOOGLE_CLIENT_ID/SECRET）

# 3. 在 pipeline 页面对一个 plan 开「真发」开关 → 点 Upload

# 4. SSE 流应看到（每 8 MiB 一帧）：
#    upload_progress { phase: "downloading", percent: 0 }
#    upload_progress { phase: "downloading", percent: 100 }
#    upload_progress { phase: "uploading", percent: 13.3, chunk_index: 0/8, ... }
#    upload_progress { phase: "uploading", percent: 26.7, chunk_index: 1/8, ... }
#    ...
#    upload_progress { phase: "uploading", percent: 100, chunk_index: 7/8 }
#    publish_plan_state { phase: "completed", ok: true, external_id: "<real_youtube_id>" }

# 5. DB 检查：
psql fliki -c "SELECT meta_json->'upload_progress' FROM publish_plans WHERE id='<plan_id>';"
# → 终态时应是 {"phase":"uploading","bytes_uploaded":<total>,"percent":100,...}
```

不在 sandbox 里跑真上传是因为 cursor agent backend 启动会被注入 HTTP_PROXY，向 google.com 发会 403（AGENTS_BACKLOG.md §1.11）。

## 3. 已知边界 / 跳过的子任务

1. **进度回调线程模型**：当前 `progress_cb` 在 adapter 主线程同步调用；如果 SSE publish 卡了（redis 抖动）会拖慢上传节奏。已用 `try/except + logger.exception` 兜底成功路径；redis 不可用时 `_get_sync_client()` 直接返 None，cb 内 SSE publish 是 no-op。线上如果遇到拖慢可以把 cb 改成放进 thread pool / asyncio task，本次没做（当前每片间 1-2s，redis publish 微秒级，不阻碍）。
2. **下载阶段进度只发 2 帧**（start 0% + complete 100%）：因为 `requests.get(stream=True).content` 读完才返；要细粒度需要切到 `iter_content(chunk_size=...)` 里发，但下载本身一般几秒，不值得多塞代码。
3. **`requests` 同步 IO**：进度回调每片同步等 PUT 返回；这是 v1 的 IO 模型；要并发上传多片（管道化）需切 httpx async + `asyncio.Semaphore`，留给将来。
4. **`meta_json` JSON vs JSONB**：每片进度做 read-modify-write，并发更新同 plan_id 时**理论上**会丢一帧（worker 串行执行同 plan，实际不会发生）。如果将来 worker 改并行多片上传，需切 JSONB + `jsonb_set(meta_json, '{upload_progress}', :info)`；本次不动 schema（互斥锁）。
5. **没补一条端到端集成测试**（write→PG→SSE 全链路）：依赖真 redis + 后端进程；当前 publishing 集成测试 `test_publishing.py` 也没覆盖 SSE。前端类型检查 + 后端单元 8/8 + adapter 端到端 mock unit 已能保证协议正确。
6. **进度回调期间凭证刷新没透传**：`_chunked_put` 不会主动 refresh access_token；如果 4 GB 大视频上传超过 1 小时，token 过期会让最后几片 401。本次假设 60MB / 8 chunks * 1-2s = 30s 内完成，远小于 token TTL（~1h）。大文件场景留 follow-up。

## 4. 后续 follow-up

| 优先级 | 任务 | 估时 |
|---|---|---|
| ★★ | 真账号 e2e：用户在 `.env` 配 `GOOGLE_CLIENT_ID/SECRET` 跑一次 60MB 真上传，验证 progress 流 + DB `meta_json.upload_progress` + 真 youtube id 落 `external_id` 闭环 | 30 min（依赖人工 OAuth） |
| ★ | `progress_cb` 切到异步线程（thread pool / asyncio）：当前每片之间会 sync 等 redis publish 返回；redis 抖动时会拖慢上传节奏 | 1-2 小时 |
| ★ | 进度断点续传：`Content-Range` 已传 total，下次 retry 可以查 `Range: bytes=*` 拿当前 server-side 偏移；本次只做单片 retry 不做跨进程续传 | 半天 |
| ★ | 大文件（> 100MB）上传期 access_token 自动 refresh：在 `_chunked_put` 循环里检查 `expires_at < now()` 时 invoke refresh + 更新 cred；当前只在 adapter 入口检查一次 | 2-3 小时 |
| ★ | 前端进度条加「速率」（MB/s）+ 「ETA」估算：基于最近 N 片的 `bytes_uploaded` 时间差；状态跟 `latestProgress` 走，纯前端 derived state | 1-2 小时 |

## 5. 协调者合并 checklist 提示

- alembic：**未触**（无新迁移）；不需要 `alembic upgrade`
- env：**未触**（不需要新增配置项）
- 互斥锁状态：
  - `use-publish-plan-stream.ts`：T-13 占 `addEventListener("upload_progress")` + `latestProgress` state；T-17（SSE 重连）改 `start()` 内 `new EventSource(...)` 框架时不会冲突
  - `pipeline/page.tsx::PlanRow`：T-13 占 `<UploadProgressBar>` 子组件 + `uploadProgress` 局部变量；其它 Track 不要碰 `PlanRow` 内部
- 重启 backend 必要性：✅（adapter / executor 改动都在 import 期）
- 前端 hot-reload 即可（hook + page 都是 client component）
