"""Track-13：YouTube 分片上传（chunked PUT + 进度回调 + 重试）单元测试。

覆盖
----
1. ``test_chunked_put_streams_progress_per_chunk``       N 片视频 → progress_cb 调 N 次 + 单调递增
2. ``test_chunked_put_returns_video_id_on_final_chunk``  最后片返 200 + JSON id → 返 video_id
3. ``test_chunked_put_retries_on_5xx_with_backoff``      5xx 触发指数退避；attempt<=MAX 时恢复
4. ``test_chunked_put_gives_up_after_max_retries``       超过 MAX_RETRIES_PER_CHUNK 抛 PublishError
5. ``test_chunked_put_4xx_non_retriable_raises_immediately`` 401/403 等 4xx 不重试，立刻系统失败
6. ``test_initiate_resumable_upload_returns_session_uri`` POST → 200 + Location → 返 uri
7. ``test_initiate_resumable_upload_5xx_raises``         500 → PublishError
8. ``test_youtube_adapter_uses_chunked_path_when_real_publish_on``
   端到端：confirm_real_publish=True + scope OK → adapter 走 chunked path 返 ok=True

设计取舍
--------
- 全程不打真网络：用 ``monkeypatch.setattr(requests, ...)`` 换掉 ``get/post/put``，
  ``sleeper`` 注入空 lambda 跳过指数退避真等待
- 不碰 PG（这层是纯协议测试），避免依赖 conftest 的 ``pg_engine``
"""
from __future__ import annotations

import json
from typing import Any

import pytest

pytestmark = pytest.mark.publishing


class _FakeResponse:
    """最小 requests.Response 替身：status_code + headers + text/content + json()。"""

    def __init__(
        self,
        *,
        status_code: int,
        headers: dict[str, str] | None = None,
        body: bytes | str = b"",
        json_payload: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.content = body
        self._json = json_payload

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> dict[str, Any]:
        if self._json is not None:
            return self._json
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


# ── 1-5: _chunked_put 协议层 ────────────────────────────────────────────────


@pytest.mark.unit
def test_chunked_put_streams_progress_per_chunk(monkeypatch):
    """3 片视频 → put 被调 3 次；progress_cb 每次推进 bytes_uploaded 单调到 total。"""
    from app.services.publishing.adapters import youtube as yt

    total = 9
    chunk_size = 4
    video = b"abcdefghi"  # 9 bytes
    # 期望 3 片：[0-3], [4-7], [8-8]
    put_calls: list[dict[str, Any]] = []

    def fake_put(url, headers=None, data=None, timeout=None, **_):
        put_calls.append({"url": url, "headers": headers, "len": len(data)})
        # 前两片返 308（continue）；最后一片返 200 + id
        if len(put_calls) < 3:
            return _FakeResponse(status_code=308, headers={"Range": "bytes=0-3"})
        return _FakeResponse(
            status_code=200, json_payload={"id": "vid_xyz", "kind": "video"}
        )

    monkeypatch.setattr(yt.requests, "put", fake_put)

    progress_log: list[dict[str, Any]] = []

    video_id = yt._chunked_put(
        upload_url="https://upload.test/session",
        video_bytes=video,
        chunk_size=chunk_size,
        progress_cb=lambda info: progress_log.append(info),
        sleeper=lambda *_: None,
    )

    assert video_id == "vid_xyz"
    assert len(put_calls) == 3
    # Content-Range 头应正确分片
    assert put_calls[0]["headers"]["Content-Range"] == f"bytes 0-3/{total}"
    assert put_calls[1]["headers"]["Content-Range"] == f"bytes 4-7/{total}"
    assert put_calls[2]["headers"]["Content-Range"] == f"bytes 8-8/{total}"

    # progress_cb 每片调一次（最后一片 200 也回调），bytes_uploaded 单调递增到 total
    assert len(progress_log) == 3
    bytes_seq = [p["bytes_uploaded"] for p in progress_log]
    assert bytes_seq == sorted(bytes_seq)
    assert bytes_seq[-1] == total
    assert progress_log[-1]["percent"] == 100.0
    # 中间片 percent 在 (0, 100) 之间
    assert 0 < progress_log[0]["percent"] < 100
    assert progress_log[0]["chunk_index"] == 0
    assert progress_log[-1]["chunk_index"] == 2
    assert progress_log[-1]["chunk_count"] == 3
    # phase 始终是 uploading
    for p in progress_log:
        assert p["phase"] == "uploading"


@pytest.mark.unit
def test_chunked_put_returns_video_id_on_final_chunk(monkeypatch):
    """单片视频（total < chunk_size）走一次 PUT 返 video_id。"""
    from app.services.publishing.adapters import youtube as yt

    def fake_put(url, headers=None, data=None, timeout=None, **_):
        return _FakeResponse(status_code=201, json_payload={"id": "single_chunk_id"})

    monkeypatch.setattr(yt.requests, "put", fake_put)

    video_id = yt._chunked_put(
        upload_url="https://upload.test/session",
        video_bytes=b"hi",
        chunk_size=8,
        progress_cb=None,
        sleeper=lambda *_: None,
    )
    assert video_id == "single_chunk_id"


@pytest.mark.unit
def test_chunked_put_retries_on_5xx_with_backoff(monkeypatch):
    """单片首次 503 → 指数退避后重试 → 第二次 200 成功。
    断 sleeper 被调用，验证退避路径走通。
    """
    from app.services.publishing.adapters import youtube as yt

    attempts: list[int] = []
    sleeps: list[float] = []

    def fake_put(url, headers=None, data=None, timeout=None, **_):
        attempts.append(1)
        if len(attempts) == 1:
            return _FakeResponse(status_code=503, body=b"upstream busy")
        return _FakeResponse(status_code=200, json_payload={"id": "v_after_retry"})

    monkeypatch.setattr(yt.requests, "put", fake_put)

    video_id = yt._chunked_put(
        upload_url="https://upload.test/session",
        video_bytes=b"hi",
        chunk_size=8,
        progress_cb=None,
        sleeper=lambda d: sleeps.append(d),
    )
    assert video_id == "v_after_retry"
    assert len(attempts) == 2
    # 至少一次退避 sleep（attempt=1 后退避 1 秒）
    assert sleeps and sleeps[0] >= 1


@pytest.mark.unit
def test_chunked_put_gives_up_after_max_retries(monkeypatch):
    """连续 4 次 5xx → 超过 MAX_RETRIES_PER_CHUNK(=3) → 抛 PublishError。"""
    from app.services.publishing.adapters import youtube as yt
    from app.services.publishing.adapters.base import PublishError

    n = {"i": 0}

    def fake_put(url, headers=None, data=None, timeout=None, **_):
        n["i"] += 1
        return _FakeResponse(status_code=500, body=b"persistent server error")

    monkeypatch.setattr(yt.requests, "put", fake_put)

    with pytest.raises(PublishError) as exc_info:
        yt._chunked_put(
            upload_url="https://upload.test/session",
            video_bytes=b"hi",
            chunk_size=8,
            progress_cb=None,
            sleeper=lambda *_: None,
        )
    assert "500" in str(exc_info.value)
    # 1 次首发 + MAX_RETRIES_PER_CHUNK(=3) 次重试 = 4 次
    assert n["i"] == yt.MAX_RETRIES_PER_CHUNK + 1


@pytest.mark.unit
def test_chunked_put_4xx_non_retriable_raises_immediately(monkeypatch):
    """401（auth 失效）等 4xx 立即抛 PublishError，不重试。"""
    from app.services.publishing.adapters import youtube as yt
    from app.services.publishing.adapters.base import PublishError

    n = {"i": 0}

    def fake_put(url, headers=None, data=None, timeout=None, **_):
        n["i"] += 1
        return _FakeResponse(status_code=401, body=b"unauthorized")

    monkeypatch.setattr(yt.requests, "put", fake_put)

    with pytest.raises(PublishError) as exc_info:
        yt._chunked_put(
            upload_url="https://upload.test/session",
            video_bytes=b"hi",
            chunk_size=8,
            progress_cb=None,
            sleeper=lambda *_: None,
        )
    assert "401" in str(exc_info.value)
    assert n["i"] == 1, "401 must not retry"


# ── 6-7: _initiate_resumable_upload ─────────────────────────────────────────


@pytest.mark.unit
def test_initiate_resumable_upload_returns_session_uri(monkeypatch):
    """POST 200 + Location 头 → 返 session uri；headers 含 X-Upload-Content-Length。"""
    from app.services.publishing.adapters import youtube as yt

    captured: dict[str, Any] = {}

    def fake_post(url, params=None, headers=None, data=None, timeout=None, **_):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["data_len"] = len(data) if data else 0
        return _FakeResponse(
            status_code=200,
            headers={"Location": "https://upload.test/sess?upload_id=abc123"},
        )

    monkeypatch.setattr(yt.requests, "post", fake_post)

    uri = yt._initiate_resumable_upload(
        access_token="tk_xyz",
        metadata={"snippet": {"title": "hi"}, "status": {"privacyStatus": "private"}},
        total_bytes=1024,
    )
    assert uri == "https://upload.test/sess?upload_id=abc123"
    assert captured["params"]["uploadType"] == "resumable"
    assert captured["params"]["part"] == "snippet,status"
    assert captured["headers"]["X-Upload-Content-Length"] == "1024"
    assert captured["headers"]["Authorization"] == "Bearer tk_xyz"
    assert captured["data_len"] > 0


@pytest.mark.unit
def test_initiate_resumable_upload_5xx_raises(monkeypatch):
    """500 → PublishError；executor 翻成 DLQ。"""
    from app.services.publishing.adapters import youtube as yt
    from app.services.publishing.adapters.base import PublishError

    def fake_post(url, params=None, headers=None, data=None, timeout=None, **_):
        return _FakeResponse(status_code=500, body=b"boom")

    monkeypatch.setattr(yt.requests, "post", fake_post)

    with pytest.raises(PublishError):
        yt._initiate_resumable_upload(
            access_token="tk", metadata={}, total_bytes=10
        )


# ── 8: end-to-end adapter 走 chunked 路径 ───────────────────────────────────


@pytest.mark.unit
def test_youtube_adapter_uses_chunked_path_when_real_publish_on(monkeypatch):
    """confirm_real_publish=True + 完整 cred → adapter 走真发路径：

    - 下载 render_url
    - initiate session uri
    - 分片 PUT 直到 200 + id
    - 返 PublishOutcome(ok=True, external_id=video_id, meta.upload_mode=resumable_chunked)

    同时验证 progress_cb 在下载 + 上传阶段都被触发。
    """
    from app.services.publishing.adapters import youtube as yt
    from app.services.publishing.adapters.base import PublishRequest

    fake_settings = type(
        "S",
        (),
        {"google_client_id": "cid", "google_client_secret": "csec"},
    )()
    monkeypatch.setattr(yt, "get_settings", lambda: fake_settings)

    # 下载阶段：模拟一个 12 字节的视频
    def fake_get(url, timeout=None, stream=False, **_):
        return _FakeResponse(
            status_code=200,
            headers={"Content-Length": "12"},
            body=b"hello world!",
        )

    monkeypatch.setattr(yt.requests, "get", fake_get)

    # initiate
    def fake_post(url, params=None, headers=None, data=None, timeout=None, **_):
        return _FakeResponse(
            status_code=200,
            headers={"Location": "https://upload.test/sess"},
        )

    monkeypatch.setattr(yt.requests, "post", fake_post)

    # 分片 PUT：chunk_size=8 → 2 片（8 + 4）
    monkeypatch.setattr(yt, "DEFAULT_CHUNK_SIZE", 8, raising=True)

    put_seq: list[int] = []

    def fake_put(url, headers=None, data=None, timeout=None, **_):
        put_seq.append(len(data))
        if len(put_seq) == 1:
            return _FakeResponse(status_code=308)
        return _FakeResponse(status_code=200, json_payload={"id": "yt_real_id"})

    monkeypatch.setattr(yt.requests, "put", fake_put)

    progress_events: list[dict[str, Any]] = []

    req = PublishRequest(
        plan_id="plan_real_abc",
        user_id="u",
        platform="youtube",
        file_id="f",
        run_id=None,
        render_id=None,
        render_url="https://test.local/v.mp4",
        cover_url=None,
        title="t",
        description="d",
        tags=["x"],
        credential={
            "access_token": "tk",
            "refresh_token": "rk",
            "scope": [yt.YOUTUBE_REQUIRED_SCOPE],
        },
        confirm_real_publish=True,
        progress_cb=lambda info: progress_events.append(info),
    )

    out = yt.YouTubeAdapter().upload(req)
    assert out.ok is True
    assert out.external_id == "yt_real_id"
    assert out.external_url == "https://youtube.com/watch?v=yt_real_id"
    assert out.meta["upload_mode"] == "resumable_chunked"
    assert out.meta["total_bytes"] == 12
    # 2 chunks → 2 uploading events；下载阶段会另发 2 次（start + complete）
    uploading = [e for e in progress_events if e["phase"] == "uploading"]
    downloading = [e for e in progress_events if e["phase"] == "downloading"]
    assert len(uploading) == 2
    assert len(downloading) >= 1
    assert uploading[-1]["percent"] == 100.0
    assert uploading[-1]["bytes_uploaded"] == 12
    # PUT 实际分片大小：8 + 4
    assert put_seq == [8, 4]
