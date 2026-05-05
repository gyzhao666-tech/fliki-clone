"""百度智能云 ASR provider 单元测试。

单元测试不发真实网络请求；mock requests.post 覆盖：
- token 拿取 + 缓存 + 过期刷新
- 短语音识别成功 / 失败 / 错误码 3302（鉴权失败）触发 token invalidate + retry
- audio_bytes 缺失 / 太大兜底
- dev_pid 默认 1537 / 语言映射英文 1737 / 显式覆盖
- 输出格式与其他 ASR provider 一致（segments=[], words=[]，让 voice.py 健康检查降级）
- gateway routing 包含 BAIDU + provider 注册成功

不依赖 PG / Redis / 真 baidu 端点；CI 默认门禁可跑。
"""
from __future__ import annotations

import base64
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.model_gateway.providers.baidu_asr import (
    BaiduASRProvider,
    _build_asr_payload,
    _clear_token_cache,
    _get_access_token,
)
from app.services.model_gateway.types import (
    CallStatus,
    ModelAction,
    ProviderName,
    RenderRequest,
)


@pytest.fixture(autouse=True)
def _reset_token_cache():
    """每个 case 隔离：清空 token 缓存避免相互污染。"""
    _clear_token_cache()
    yield
    _clear_token_cache()


@pytest.fixture
def baidu_settings(monkeypatch):
    """注入 fake baidu key 让 is_available()=True；不真发请求。"""
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "baidu_asr_api_key", "fake-api-key", raising=False)
    monkeypatch.setattr(s, "baidu_asr_secret_key", "fake-secret-key", raising=False)
    monkeypatch.setattr(s, "baidu_asr_app_id", "fake-app-id", raising=False)
    monkeypatch.setattr(s, "baidu_asr_dev_pid", 1537, raising=False)
    monkeypatch.setattr(s, "baidu_asr_cuid", "test-cuid", raising=False)
    return s


def _make_token_response(token: str = "fake-token-xyz", expires: int = 2592000):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"access_token": token, "expires_in": expires}
    r.text = "{}"
    return r


def _make_asr_response(text: str = "你好世界", err_no: int = 0, err_msg: str = "success."):
    r = MagicMock()
    r.status_code = 200
    body: dict[str, Any] = {
        "err_no": err_no,
        "err_msg": err_msg,
        "sn": "fake-sn-123",
        "corpus_no": "fake-corpus-456",
    }
    if err_no == 0:
        body["result"] = [text]
    r.json.return_value = body
    r.text = str(body)
    return r


# ── 1. is_available 行为 ─────────────────────────────────────────────────────


def test_is_available_false_without_keys(monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "baidu_asr_api_key", "", raising=False)
    monkeypatch.setattr(s, "baidu_asr_secret_key", "", raising=False)
    p = BaiduASRProvider()
    assert p.is_available() is False


def test_is_available_true_when_both_keys_set(baidu_settings):
    p = BaiduASRProvider()
    assert p.is_available() is True


def test_supports_only_asr():
    p = BaiduASRProvider()
    assert p.supports(ModelAction.ASR) is True
    assert p.supports(ModelAction.LLM) is False
    assert p.supports(ModelAction.TTS) is False


# ── 2. token 缓存行为 ────────────────────────────────────────────────────────


def test_get_access_token_caches_within_window():
    """同一 (api_key, secret_key) 第二次调用走缓存，不发第二次请求。"""
    with patch("app.services.model_gateway.providers.baidu_asr.requests.post") as mock_post:
        mock_post.return_value = _make_token_response("token-A")
        t1 = _get_access_token("k", "s")
        t2 = _get_access_token("k", "s")
        assert t1 == "token-A"
        assert t2 == "token-A"
        assert mock_post.call_count == 1  # 只调一次


def test_get_access_token_different_keys_isolated():
    with patch("app.services.model_gateway.providers.baidu_asr.requests.post") as mock_post:
        mock_post.side_effect = [_make_token_response("A"), _make_token_response("B")]
        a = _get_access_token("k1", "s1")
        b = _get_access_token("k2", "s2")
        assert a == "A" and b == "B"
        assert mock_post.call_count == 2


def test_get_access_token_invalid_response_raises():
    """expires_in <= 0 或 access_token 缺失抛 _BaiduTokenError。"""
    from app.services.model_gateway.providers.baidu_asr import _BaiduTokenError

    with patch("app.services.model_gateway.providers.baidu_asr.requests.post") as mock_post:
        bad = MagicMock()
        bad.status_code = 200
        bad.json.return_value = {"error": "invalid_client"}
        bad.text = "{}"
        mock_post.return_value = bad
        with pytest.raises(_BaiduTokenError):
            _get_access_token("k", "s")


# ── 3. payload 构造 ──────────────────────────────────────────────────────────


def test_build_payload_base64_encodes_audio():
    audio = b"\x00\x01\x02\x03"
    payload = _build_asr_payload(
        audio_bytes=audio,
        audio_format="mp3",
        token="tok",
        dev_pid=1537,
        cuid="me",
    )
    assert payload["format"] == "mp3"
    assert payload["rate"] == 16000
    assert payload["channel"] == 1
    assert payload["dev_pid"] == 1537
    assert payload["cuid"] == "me"
    assert payload["token"] == "tok"
    assert payload["len"] == 4
    assert payload["speech"] == base64.b64encode(audio).decode("ascii")


# ── 4. call() 完整路径 ───────────────────────────────────────────────────────


def test_call_succeeds_and_normalises_output(baidu_settings):
    p = BaiduASRProvider()
    request = RenderRequest(
        action=ModelAction.ASR,
        params={"audio_bytes": b"fake-mp3-bytes", "audio_format": "mp3"},
    )
    with patch("app.services.model_gateway.providers.baidu_asr.requests.post") as mock_post:
        mock_post.side_effect = [
            _make_token_response("tk"),
            _make_asr_response("识别出来的文本"),
        ]
        result = p.call(request)
    assert result.status == CallStatus.SUCCEEDED
    assert result.provider == ProviderName.BAIDU
    assert result.output["text"] == "识别出来的文本"
    # 关键：与其他 ASR provider 严格一致的 segments=[] / words=[]
    # voice.py v4 健康检查会因 words 太少自动降到 v3 行级
    assert result.output["segments"] == []
    assert result.output["words"] == []
    assert result.output["language"] == "zh-CN"
    assert result.output["duration_s"] is None  # 百度不返；caller ffprobe 兜底


def test_call_missing_audio_returns_failed(baidu_settings):
    p = BaiduASRProvider()
    request = RenderRequest(action=ModelAction.ASR, params={})
    result = p.call(request)
    assert result.status == CallStatus.FAILED
    assert "missing audio_bytes" in (result.error or "")


def test_call_audio_too_large_returns_failed(baidu_settings):
    p = BaiduASRProvider()
    big = b"\x00" * (10 * 1024 * 1024 + 1)
    request = RenderRequest(action=ModelAction.ASR, params={"audio_bytes": big})
    result = p.call(request)
    assert result.status == CallStatus.FAILED
    assert "too large" in (result.error or "")


def test_call_missing_keys_returns_failed(monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "baidu_asr_api_key", "", raising=False)
    monkeypatch.setattr(s, "baidu_asr_secret_key", "", raising=False)
    p = BaiduASRProvider()
    request = RenderRequest(action=ModelAction.ASR, params={"audio_bytes": b"x"})
    result = p.call(request)
    assert result.status == CallStatus.FAILED
    assert "missing baidu_asr" in (result.error or "")


def test_call_baidu_err_no_returns_failed_with_detail(baidu_settings):
    """err_no=3308 音频时长超过 60s 应翻成 FAILED + 含 err_no 的错误描述。"""
    p = BaiduASRProvider()
    request = RenderRequest(
        action=ModelAction.ASR, params={"audio_bytes": b"audio"}
    )
    with patch("app.services.model_gateway.providers.baidu_asr.requests.post") as mock_post:
        mock_post.side_effect = [
            _make_token_response("tk"),
            _make_asr_response(err_no=3308, err_msg="audio too long"),
        ]
        result = p.call(request)
    assert result.status == CallStatus.FAILED
    assert "3308" in (result.error or "")
    assert "audio too long" in (result.error or "")


def test_call_err_no_3302_triggers_token_retry(baidu_settings):
    """err_no=3302 鉴权失败应 invalidate token + retry 一次。"""
    p = BaiduASRProvider()
    request = RenderRequest(
        action=ModelAction.ASR, params={"audio_bytes": b"audio"}
    )
    with patch("app.services.model_gateway.providers.baidu_asr.requests.post") as mock_post:
        mock_post.side_effect = [
            _make_token_response("token-1"),                    # 首次拿 token
            _make_asr_response(err_no=3302, err_msg="auth"),    # 第一次 ASR 鉴权失败
            _make_token_response("token-2"),                    # 强制刷新 token
            _make_asr_response("终于成功了"),                    # 第二次 ASR 成功
        ]
        result = p.call(request)
    assert result.status == CallStatus.SUCCEEDED
    assert result.output["text"] == "终于成功了"
    assert mock_post.call_count == 4


def test_call_dev_pid_defaults_to_1537(baidu_settings):
    p = BaiduASRProvider()
    request = RenderRequest(action=ModelAction.ASR, params={"audio_bytes": b"x"})
    with patch("app.services.model_gateway.providers.baidu_asr.requests.post") as mock_post:
        mock_post.side_effect = [_make_token_response("tk"), _make_asr_response("hi")]
        p.call(request)
    asr_call_kwargs = mock_post.call_args_list[1].kwargs
    sent_payload = asr_call_kwargs["json"]
    assert sent_payload["dev_pid"] == 1537


def test_call_dev_pid_overridable_via_language_english(baidu_settings):
    p = BaiduASRProvider()
    request = RenderRequest(
        action=ModelAction.ASR,
        params={"audio_bytes": b"x", "language": "en"},
    )
    with patch("app.services.model_gateway.providers.baidu_asr.requests.post") as mock_post:
        mock_post.side_effect = [_make_token_response("tk"), _make_asr_response("hi")]
        result = p.call(request)
    asr_call_kwargs = mock_post.call_args_list[1].kwargs
    assert asr_call_kwargs["json"]["dev_pid"] == 1737
    assert result.output["language"] == "en"


def test_call_dev_pid_explicit_param_wins(baidu_settings):
    """显式 params['dev_pid'] 优先级最高。"""
    p = BaiduASRProvider()
    request = RenderRequest(
        action=ModelAction.ASR,
        params={"audio_bytes": b"x", "dev_pid": 1837, "language": "en"},
    )
    with patch("app.services.model_gateway.providers.baidu_asr.requests.post") as mock_post:
        mock_post.side_effect = [_make_token_response("tk"), _make_asr_response("hi")]
        p.call(request)
    asr_call_kwargs = mock_post.call_args_list[1].kwargs
    assert asr_call_kwargs["json"]["dev_pid"] == 1837


# ── 5. gateway 集成（路由 + 注册）─────────────────────────────────────────────


def test_gateway_routing_includes_baidu_between_local_and_siliconflow():
    """ASR 路由必须是 [OPENAI, FASTER_WHISPER_LOCAL, BAIDU, SILICONFLOW] 顺序。"""
    from app.services.model_gateway.gateway import Gateway

    gw = Gateway()
    routing = gw._default_routing[ModelAction.ASR]
    assert routing == [
        ProviderName.OPENAI,
        ProviderName.FASTER_WHISPER_LOCAL,
        ProviderName.BAIDU,
        ProviderName.SILICONFLOW,
    ]


def test_gateway_factory_registers_baidu_provider(baidu_settings):
    """get_gateway() 启动时必须注册 BaiduASRProvider。"""
    # 强制重建 gateway 单例（factory 用 lazy init + 模块级缓存）
    from app.services.model_gateway import gateway as gw_module

    gw_module._gateway = None  # type: ignore[attr-defined]
    gw = gw_module.get_gateway()
    assert gw.has_provider(ProviderName.BAIDU)
    selected = gw.select_provider(ModelAction.ASR, hint=ProviderName.BAIDU)
    assert isinstance(selected, BaiduASRProvider)
