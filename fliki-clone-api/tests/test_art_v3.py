"""ArtAgent v3 角色一致性 helpers + 集成测试。

覆盖
----
helpers (5):
1. ``test_resolve_consistency_mode_off_branch``                ``off`` 直接返 ``disabled``
2. ``test_resolve_consistency_mode_no_cards_returns_disabled`` 无 character_cards 也降到 ``disabled``
3. ``test_select_protagonist_explicit_match``                  brief.protagonist_role 命中
4. ``test_build_anchor_prompt_assembly``                       portrait + 风格 + 中性背景拼接
5. ``test_inject_consistency_into_shots_skips_non_protagonist``focus_character != 主角时不注入

集成 (3):
6. ``test_art_run_anchor_mode_success``        anchor 成功 + 注入 + 每镜 character_locked=True
7. ``test_art_run_anchor_failure_falls_back``  锚点 GENERATE_IMAGE 失败 → 退到 prompt-only + warning
8. ``test_art_run_off_mode_disables_consistency``
                                               brief.character_consistency='off' → mode=disabled

注：依赖 ``patch_gateway`` fixture mock LLM/Image，全程 in-memory，无 DB。
"""
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.art


# ── helpers ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_resolve_consistency_mode_off_branch():
    """``character_consistency='off'`` → 一律返 disabled，即使有 character_cards。"""
    from app.services.pipeline.agents.art import _resolve_consistency_mode

    cards = [{"name": "protagonist", "appearance": "tall"}]
    assert _resolve_consistency_mode({"character_consistency": "off"}, cards) == "disabled"

    # 不合法值兜底 auto，再走 disabled 当无 cards
    assert _resolve_consistency_mode({"character_consistency": "weird"}, cards) == "auto"


@pytest.mark.unit
def test_resolve_consistency_mode_no_cards_returns_disabled():
    """没有 character_cards 时所有模式都退到 disabled（依赖 cards 才能注入 prompt）。"""
    from app.services.pipeline.agents.art import _resolve_consistency_mode

    for mode in ("auto", "anchor", "prompt-only", "off", "weird"):
        assert (
            _resolve_consistency_mode({"character_consistency": mode}, []) == "disabled"
        ), f"mode={mode} 无 cards 时应该 disabled"


@pytest.mark.unit
def test_select_protagonist_explicit_match():
    """brief.protagonist_role 显式给名字 → 命中该卡；否则取 cards[0]。"""
    from app.services.pipeline.agents.art import _select_protagonist

    cards = [
        {"name": "side_kick", "appearance": "small"},
        {"name": "protagonist", "appearance": "tall"},
        {"name": "boss", "appearance": "old"},
    ]
    # 显式命中（大小写不敏感）
    p = _select_protagonist({"protagonist_role": "PROTAGONIST"}, cards)
    assert p["name"] == "protagonist"

    # 未命中（拼写错误）→ fallback cards[0]
    p2 = _select_protagonist({"protagonist_role": "ghost"}, cards)
    assert p2["name"] == "side_kick"

    # 没指定 → cards[0]
    p3 = _select_protagonist({}, cards)
    assert p3["name"] == "side_kick"

    # 空 cards → None（不抛）
    assert _select_protagonist({}, []) is None


@pytest.mark.unit
def test_build_anchor_prompt_assembly():
    """portrait + 角色卡 + style_keywords + 中性背景应拼接到一起，且不超 800 字符。"""
    from app.services.pipeline.agents.art import _build_anchor_prompt

    protagonist = {
        "name": "Alice",
        "appearance": "young woman, brown hair, freckles",
        "wardrobe": "casual hoodie",
        "vibe": "curious",
    }
    style_board = {"style_keywords": ["cinematic", "photoreal"]}
    prompt = _build_anchor_prompt(protagonist, style_board)
    # 结构断言：包含必要片段
    assert "Alice" in prompt
    assert "brown hair" in prompt
    assert "wearing casual hoodie" in prompt
    assert "curious" in prompt
    assert "cinematic" in prompt
    assert "neutral gray background" in prompt
    assert "front portrait" in prompt
    assert len(prompt) <= 800

    # wardrobe 缺失时不应出现 "wearing "
    minimal = _build_anchor_prompt({"name": "Bob"}, {"style_keywords": []})
    assert "Bob" in minimal
    assert "wearing" not in minimal


@pytest.mark.unit
def test_inject_consistency_into_shots_skips_non_protagonist():
    """focus_character 显式标其它角色时不注入；标主角 / 缺省 → 注入并加 negative。"""
    from app.services.pipeline.agents.art import _inject_consistency_into_shots

    protagonist = {
        "name": "Hero",
        "appearance": "tall",
        "wardrobe": "trench coat",
        "vibe": "stoic",
    }
    shots = [
        {
            "index": 1,
            "enhanced_prompt": "city street at night",
            "negative_prompt": "blurry",
            # 不写 focus_character → 默认主角
        },
        {
            "index": 2,
            "enhanced_prompt": "office close-up of villain",
            "negative_prompt": "blurry",
            "focus_character": "Villain",
        },
        {
            "index": 3,
            "enhanced_prompt": "[Consistent character: 老镜头, ...] hero strolls back",
            "negative_prompt": "blurry, different face",
            # 模拟重跑：原 prompt 已有前缀 + negative 已含防漂关键词 → 不重复
        },
    ]
    out = _inject_consistency_into_shots(shots=shots, protagonist=protagonist)
    # 镜 1：注入前缀 + negative 追加防漂
    assert out[0]["character_locked"] is True
    assert out[0]["enhanced_prompt"].startswith("[Consistent character: protagonist=Hero")
    assert "different face" in out[0]["negative_prompt"]
    # 镜 2：focus_character != Hero → 跳过
    assert out[1]["character_locked"] is False
    assert out[1]["enhanced_prompt"] == "office close-up of villain"
    assert out[1]["negative_prompt"] == "blurry"
    # 镜 3：已有前缀不重复（仍标 locked=True 让前端正确显示）
    assert out[2]["character_locked"] is True
    # 不二次 prepend [Consistent ...]
    assert out[2]["enhanced_prompt"].count("[Consistent character:") == 1


# ── 集成：ArtAgent.run() ─────────────────────────────────────────────────────

# LLM 增强 step 通常返 JSON 串；下面三个 case 共用一个 mock LLM 输出结构
_MOCK_LLM_JSON = json.dumps(
    {
        "style_board": {
            "palette": ["#FF6B6B", "warm orange"],
            "style_keywords": ["cinematic", "neon"],
            "lighting": "soft window light",
            "camera_language": ["slow push-in"],
            "aspect_ratio": "9:16",
            "reference_notes": "clean composition",
        },
        "character_cards": [
            {
                "name": "protagonist",
                "appearance": "young woman, short black hair",
                "wardrobe": "navy blazer",
                "vibe": "confident",
            }
        ],
        "shots": [
            {
                "index": 1,
                "enhanced_prompt": "subway platform morning rush",
                "negative_prompt": "watermark, blurry",
                "focus_character": "protagonist",
            },
            {
                "index": 2,
                "enhanced_prompt": "cafe counter with steam",
                "negative_prompt": "watermark",
            },
        ],
    },
    ensure_ascii=False,
)


def _llm_result():
    from app.services.model_gateway.types import (
        CallStatus,
        ProviderName,
        RenderResult,
    )

    return RenderResult(
        status=CallStatus.SUCCEEDED,
        provider=ProviderName.SILICONFLOW,
        model="deepseek-mock",
        output=_MOCK_LLM_JSON,
        cost_usd=0.001,
    )


def _image_succ(url: str = "https://test.local/img.png", cost: float = 0.005):
    from app.services.model_gateway.types import (
        CallStatus,
        ProviderName,
        RenderResult,
    )

    return RenderResult(
        status=CallStatus.SUCCEEDED,
        provider=ProviderName.SILICONFLOW,
        model="kolors-mock",
        output={"image_url": url, "image_size": "1024x1024"},
        cost_usd=cost,
    )


def _image_fail(err: str = "image gen failed"):
    from app.services.model_gateway.types import (
        CallStatus,
        ProviderName,
        RenderResult,
    )

    return RenderResult(
        status=CallStatus.FAILED,
        provider=ProviderName.SILICONFLOW,
        error=err,
        cost_usd=0.0,
    )


def _base_inputs(consistency_mode: str = "auto", skip_keyframes: bool = False):
    return {
        "brief": {
            "platform": "douyin",
            "character_consistency": consistency_mode,
            **({"skip_keyframes": True} if skip_keyframes else {}),
        }
    }


_BASE_UPSTREAM_SCRIPT = {
    "topic": {"title": "morning rush"},
    "script": "subway then coffee",
    "shots": [
        {
            "index": 1,
            "duration_s": 4.0,
            "visual": "subway",
            "narration": "subway",
        },
        {
            "index": 2,
            "duration_s": 4.0,
            "visual": "cafe",
            "narration": "cafe",
        },
    ],
}


@pytest.mark.unit
def test_art_run_anchor_mode_success(patch_gateway, fake_gateway):
    """auto + 锚点 + 关键帧全部成功：consistency_mode='anchor'，每镜 character_locked。

    队列：LLM → 锚点 GENERATE_IMAGE → 镜1 GENERATE_IMAGE → 镜2 GENERATE_IMAGE
    """
    from app.services.pipeline.agents.art import ArtAgent
    from tests.conftest import make_ctx

    fake_gateway.queue(
        _llm_result(),
        _image_succ(url="https://test.local/anchor.png", cost=0.005),
        _image_succ(url="https://test.local/keyframe-1.png", cost=0.005),
        _image_succ(url="https://test.local/keyframe-2.png", cost=0.005),
    )

    ctx = make_ctx(
        inputs=_base_inputs("auto"),
        upstream={"script": _BASE_UPSTREAM_SCRIPT},
    )
    result = ArtAgent().run(ctx)
    out = result.outputs

    assert result.status.value == "succeeded"
    assert out["consistency_mode"] == "anchor"
    assert out["character_anchor"] is not None
    assert out["character_anchor"]["url"] == "https://test.local/anchor.png"
    assert out["protagonist_name"] == "protagonist"
    # 每镜应 character_locked=True（focus 都默认主角）
    assert all(s["character_locked"] for s in out["shots"])
    # 关键帧全成功
    assert out["keyframe_failures"] == 0
    assert out["shots"][0]["keyframe_url"] == "https://test.local/keyframe-1.png"
    # 累加成本：LLM 0.001 + 锚点 0.005 + 2 张 keyframe 0.005*2 = 0.016
    assert result.cost_usd == pytest.approx(0.016, abs=0.0001)
    # 调用次数：1 + 1 + 2 = 4
    assert len(fake_gateway.calls) == 4
    assert fake_gateway.calls[0].action == "llm"
    assert all(c.action == "generate_image" for c in fake_gateway.calls[1:])


@pytest.mark.unit
def test_art_run_anchor_failure_falls_back(patch_gateway, fake_gateway):
    """显式 mode='anchor' 但锚点 GENERATE_IMAGE 失败 → mode 降到 prompt-only +
    输出 consistency_warning；prompt 锁定仍生效（character_locked=True）。
    """
    from app.services.pipeline.agents.art import ArtAgent
    from tests.conftest import make_ctx

    fake_gateway.queue(
        _llm_result(),
        _image_fail("anchor down"),
        _image_succ(url="https://test.local/k1.png"),
        _image_succ(url="https://test.local/k2.png"),
    )

    ctx = make_ctx(
        inputs=_base_inputs("anchor"),
        upstream={"script": _BASE_UPSTREAM_SCRIPT},
    )
    result = ArtAgent().run(ctx)
    out = result.outputs

    assert result.status.value == "succeeded"
    assert out["consistency_mode"] == "prompt-only", (
        f"锚点失败 + 有 cards 时应降到 prompt-only；实际 {out['consistency_mode']}"
    )
    assert "consistency_warning" in out
    assert "anchor down" in out["consistency_warning"]
    # anchor 行返回但 url=None
    assert out["character_anchor"] is not None
    assert out["character_anchor"]["url"] is None
    # prompt 锁定仍生效
    assert all(s["character_locked"] for s in out["shots"])


@pytest.mark.unit
def test_art_run_off_mode_disables_consistency(patch_gateway, fake_gateway):
    """brief.character_consistency='off' → 不调锚点 + 不注入 prompt + mode='disabled'。

    队列：LLM → 镜1 keyframe → 镜2 keyframe（无锚点调用）
    """
    from app.services.pipeline.agents.art import ArtAgent
    from tests.conftest import make_ctx

    fake_gateway.queue(
        _llm_result(),
        _image_succ(url="https://test.local/k1.png"),
        _image_succ(url="https://test.local/k2.png"),
    )

    ctx = make_ctx(
        inputs=_base_inputs("off"),
        upstream={"script": _BASE_UPSTREAM_SCRIPT},
    )
    result = ArtAgent().run(ctx)
    out = result.outputs

    assert out["consistency_mode"] == "disabled"
    assert out["character_anchor"] is None
    # off 时 enhanced_prompt 不应被注入 [Consistent ...]
    for s in out["shots"]:
        assert not s.get("enhanced_prompt", "").startswith("[Consistent character:")
        # character_locked 字段在 off 模式下根本不会被设置 → 这里允许缺失
        assert "character_locked" not in s or s["character_locked"] is False
    # 调用次数：1 LLM + 2 keyframe = 3，没有锚点
    assert len(fake_gateway.calls) == 3
