"""Track-09 v5 多角色锁定 — 端到端 + helper 烟测。

覆盖
----
1. ``test_select_relevant_characters_picks_referenced``
   helper：character_cards 有 3 张但只有 2 张被 shot focus 引用 → 返回 2 张（含主角）
2. ``test_inject_consistency_picks_per_shot_character``
   _inject_consistency_into_shots 接 characters_by_name 后，
   不同 focus_character 镜注入不同前缀 + locked_character 字段
3. ``test_art_run_multichar_creates_two_anchors``
   ArtAgent.run 端到端：mock LLM 返 2 角色，2 镜分别 focus 主角 / 配角，
   art outputs.character_anchors 含 2 个，character_anchor 单字段仍是主角的，
   不同 focus 镜注入不同 prefix，shot.locked_character 写对
4. ``test_art_run_multichar_back_compat_single_card``
   单 character_card 路径与 v3/v4 行为完全一致：character_anchors 只 1 个，
   character_anchor 等于该 anchor，无 focus_character 镜默认主角
5. ``test_video_select_ref_image_per_character``
   VideoAgent _select_ref_image 按 shot.locked_character 选对应 anchor，
   返回 (url, "anchor", role_name)
6. ``test_video_agent_uses_correct_anchor_per_shot``
   VideoAgent.run 集成：上游有 2 角色 anchors，2 镜分别 locked_character 主/配角
   → ref_image_source='anchor'，ref_anchor_role 各为主/配角名

注：所有 case 都用 mock gateway，全程 in-memory，无 DB 依赖。
"""
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.art


# ── helpers ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_select_relevant_characters_picks_referenced():
    """3 张卡 × 2 张被 focus 引用（含主角缺省镜）→ 返 2 张；不被 focus 的不出 anchor。"""
    from app.services.pipeline.agents.art import _select_relevant_characters

    cards = [
        {"name": "Hero", "appearance": "tall"},
        {"name": "Villain", "appearance": "bald"},
        {"name": "Sidekick", "appearance": "small"},  # 不被任何 shot focus
    ]
    shots = [
        {"index": 1, "focus_character": "Hero"},  # 主角
        {"index": 2},  # 缺省 → 默认主角
        {"index": 3, "focus_character": "Villain"},  # 配角
        # 没有任何 shot focus Sidekick
    ]
    out = _select_relevant_characters(character_cards=cards, shots=shots)
    names = [c["name"] for c in out]
    assert names == ["Hero", "Villain"], (
        f"应保留主角 + 被 focus 的配角，跳过 Sidekick；实际 {names}"
    )

    # 主角永远在第一位
    assert out[0]["name"] == "Hero"

    # 没角色卡 → 空 list
    assert _select_relevant_characters(character_cards=[], shots=shots) == []

    # 单角色卡 + 多镜（v3 行为兜底）→ 主角在
    single = _select_relevant_characters(
        character_cards=[cards[0]], shots=shots
    )
    assert [c["name"] for c in single] == ["Hero"]


@pytest.mark.unit
def test_inject_consistency_picks_per_shot_character():
    """v5 关键：传 characters_by_name 后，focus_character 命中其它角色卡 → 注入该角色前缀。"""
    from app.services.pipeline.agents.art import _inject_consistency_into_shots

    protagonist = {
        "name": "Hero",
        "appearance": "tall",
        "wardrobe": "trench coat",
        "vibe": "stoic",
    }
    villain = {
        "name": "Villain",
        "appearance": "bald, scar",
        "wardrobe": "black suit",
        "vibe": "cold",
    }
    characters_by_name = {"Hero": protagonist, "Villain": villain}

    shots = [
        {
            "index": 1,
            "enhanced_prompt": "city street at night",
            "negative_prompt": "blurry",
            # 缺 focus → 默认主角
        },
        {
            "index": 2,
            "enhanced_prompt": "office close-up",
            "negative_prompt": "blurry",
            "focus_character": "Villain",  # v5：命中配角卡 → 注入配角
        },
        {
            "index": 3,
            "enhanced_prompt": "crowd scene",
            "negative_prompt": "blurry",
            "focus_character": "Random",  # 没卡 → 不注入
        },
    ]

    out = _inject_consistency_into_shots(
        shots=shots,
        protagonist=protagonist,
        characters_by_name=characters_by_name,
    )

    # 镜 1：主角前缀
    assert out[0]["character_locked"] is True
    assert out[0]["locked_character"] == "Hero"
    assert "protagonist=Hero" in out[0]["enhanced_prompt"]
    assert "trench coat" in out[0]["enhanced_prompt"]
    assert "different face" in out[0]["negative_prompt"]

    # 镜 2：配角前缀
    assert out[1]["character_locked"] is True
    assert out[1]["locked_character"] == "Villain"
    assert "protagonist=Villain" in out[1]["enhanced_prompt"], (
        "v5 应注入 Villain 卡的描述（前缀 key 名仍叫 protagonist= 是稳定格式）"
    )
    assert "black suit" in out[1]["enhanced_prompt"]
    assert "trench coat" not in out[1]["enhanced_prompt"], (
        "v5 不能把主角的服装泼到配角镜"
    )

    # 镜 3：focus 没卡 → 不注入（v3 兜底）
    assert out[2]["character_locked"] is False
    assert out[2]["enhanced_prompt"] == "crowd scene"


# ── art.run() 端到端 ──────────────────────────────────────────────────────


_MOCK_LLM_MULTICHAR = json.dumps(
    {
        "style_board": {
            "palette": ["#1B1B3A"],
            "style_keywords": ["noir", "cinematic"],
            "lighting": "harsh shadows",
            "camera_language": ["dolly in"],
            "aspect_ratio": "16:9",
            "reference_notes": "",
        },
        "character_cards": [
            {
                "name": "Hero",
                "appearance": "tall, brown coat, weary",
                "wardrobe": "trench coat",
                "vibe": "stoic",
            },
            {
                "name": "Villain",
                "appearance": "bald, scar across left eye",
                "wardrobe": "black suit",
                "vibe": "cold",
            },
        ],
        "shots": [
            {
                "index": 1,
                "enhanced_prompt": "rainy alley wide shot",
                "negative_prompt": "watermark",
                "focus_character": "Hero",
            },
            {
                "index": 2,
                "enhanced_prompt": "office at night close-up",
                "negative_prompt": "watermark",
                "focus_character": "Villain",
            },
        ],
    },
    ensure_ascii=False,
)

_MOCK_LLM_SINGLE = json.dumps(
    {
        "style_board": {
            "palette": [],
            "style_keywords": ["soft"],
            "lighting": "warm",
            "camera_language": [],
            "aspect_ratio": "9:16",
        },
        "character_cards": [
            {
                "name": "Hero",
                "appearance": "tall",
                "wardrobe": "trench coat",
                "vibe": "stoic",
            }
        ],
        "shots": [
            {
                "index": 1,
                "enhanced_prompt": "subway",
                "negative_prompt": "blurry",
            },
            {
                "index": 2,
                "enhanced_prompt": "cafe",
                "negative_prompt": "blurry",
            },
        ],
    },
    ensure_ascii=False,
)


def _llm_result(content: str):
    from app.services.model_gateway.types import (
        CallStatus,
        ProviderName,
        RenderResult,
    )

    return RenderResult(
        status=CallStatus.SUCCEEDED,
        provider=ProviderName.SILICONFLOW,
        model="deepseek-mock",
        output=content,
        cost_usd=0.001,
    )


def _image_succ(url: str, cost: float = 0.005):
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


_BASE_UPSTREAM_SCRIPT = {
    "topic": {"title": "noir story"},
    "script": "alley then office",
    "shots": [
        {"index": 1, "duration_s": 5.0, "visual": "alley", "narration": "alley"},
        {"index": 2, "duration_s": 5.0, "visual": "office", "narration": "office"},
    ],
}


@pytest.mark.unit
def test_art_run_multichar_creates_two_anchors(patch_gateway, fake_gateway):
    """v5 端到端：mock LLM 返 2 角色 + 2 镜分别 focus → outputs.character_anchors 含 2 个；
    character_anchor 主角字段保留向后兼容；不同 focus 镜注入不同 prefix。

    队列：LLM → Hero anchor → Villain anchor → 镜1 keyframe → 镜2 keyframe
    """
    from app.services.pipeline.agents.art import ArtAgent
    from tests.conftest import make_ctx

    fake_gateway.queue(
        _llm_result(_MOCK_LLM_MULTICHAR),
        _image_succ("https://test.local/anchor-hero.png"),
        _image_succ("https://test.local/anchor-villain.png"),
        _image_succ("https://test.local/k1.png"),
        _image_succ("https://test.local/k2.png"),
    )

    ctx = make_ctx(
        inputs={"brief": {"platform": "youtube", "character_consistency": "auto"}},
        upstream={"script": _BASE_UPSTREAM_SCRIPT},
    )
    result = ArtAgent().run(ctx)
    out = result.outputs

    assert result.status.value == "succeeded"
    assert out["consistency_mode"] == "anchor"
    assert out["protagonist_name"] == "Hero"

    # v5 主断言：character_anchors 字典含 2 个
    anchors = out["character_anchors"]
    assert isinstance(anchors, dict)
    assert set(anchors.keys()) == {"Hero", "Villain"}, (
        f"应给 LLM 返回的 2 个角色各出 anchor；实际 {list(anchors.keys())}"
    )
    assert anchors["Hero"]["url"] == "https://test.local/anchor-hero.png"
    assert anchors["Villain"]["url"] == "https://test.local/anchor-villain.png"

    # v3 向后兼容：character_anchor 单字段 = 主角的 anchor
    assert out["character_anchor"] is not None
    assert out["character_anchor"]["url"] == "https://test.local/anchor-hero.png"
    assert out["character_anchor"]["name"] == "Hero"

    # v5 关键：不同 focus 镜注入不同 prefix
    shots = out["shots"]
    assert shots[0]["character_locked"] is True
    assert shots[0]["locked_character"] == "Hero"
    assert "protagonist=Hero" in shots[0]["enhanced_prompt"]
    assert "trench coat" in shots[0]["enhanced_prompt"]

    assert shots[1]["character_locked"] is True
    assert shots[1]["locked_character"] == "Villain"
    assert "protagonist=Villain" in shots[1]["enhanced_prompt"]
    assert "black suit" in shots[1]["enhanced_prompt"]
    # 关键反断言：配角镜不应混入主角的服装
    assert "trench coat" not in shots[1]["enhanced_prompt"]

    # 关键帧也应按角色喂对应 anchor 作 image_url（看 fake_gateway.calls）
    image_calls = [c for c in fake_gateway.calls if c.action == "generate_image"]
    # call 1 = Hero anchor / call 2 = Villain anchor / call 3 = 镜1 / call 4 = 镜2
    assert len(image_calls) == 4
    # 镜 1 应传 Hero 的 anchor 作 image_url
    shot1_call = image_calls[2]
    assert shot1_call.params.get("image_url") == "https://test.local/anchor-hero.png"
    # 镜 2 应传 Villain 的 anchor
    shot2_call = image_calls[3]
    assert shot2_call.params.get("image_url") == "https://test.local/anchor-villain.png"


@pytest.mark.unit
def test_art_run_multichar_back_compat_single_card(patch_gateway, fake_gateway):
    """单 character_card 时：v5 行为应与 v3/v4 完全一致，character_anchors 只 1 个。"""
    from app.services.pipeline.agents.art import ArtAgent
    from tests.conftest import make_ctx

    fake_gateway.queue(
        _llm_result(_MOCK_LLM_SINGLE),
        _image_succ("https://test.local/anchor.png"),
        _image_succ("https://test.local/k1.png"),
        _image_succ("https://test.local/k2.png"),
    )

    ctx = make_ctx(
        inputs={"brief": {"platform": "douyin", "character_consistency": "auto"}},
        upstream={"script": _BASE_UPSTREAM_SCRIPT},
    )
    result = ArtAgent().run(ctx)
    out = result.outputs

    assert out["consistency_mode"] == "anchor"
    assert set(out["character_anchors"].keys()) == {"Hero"}
    # 主角字段 = 主角 anchor（v3 老前端继续工作）
    assert out["character_anchor"]["url"] == "https://test.local/anchor.png"
    # 所有镜锁定主角（缺 focus → 默认主角）
    for s in out["shots"]:
        assert s["character_locked"] is True
        assert s["locked_character"] == "Hero"


# ── video.py：选 ref-image ──────────────────────────────────────────────────


@pytest.mark.unit
def test_video_select_ref_image_per_character():
    """_select_ref_image 按 shot.locked_character 选对应角色 anchor。"""
    from app.services.pipeline.agents.video import _select_ref_image

    anchors = {
        "Hero": "https://test.local/anchor-hero.png",
        "Villain": "https://test.local/anchor-villain.png",
    }

    # 主角镜
    url, src, role = _select_ref_image(
        shot={"character_locked": True, "locked_character": "Hero"},
        anchors_by_role=anchors,
        keyframe_url="https://test.local/k1.png",
    )
    assert url == anchors["Hero"]
    assert src == "anchor"
    assert role == "Hero"

    # 配角镜
    url, src, role = _select_ref_image(
        shot={"character_locked": True, "locked_character": "Villain"},
        anchors_by_role=anchors,
        keyframe_url="https://test.local/k2.png",
    )
    assert url == anchors["Villain"]
    assert src == "anchor"
    assert role == "Villain"

    # 大小写不敏感
    url, src, role = _select_ref_image(
        shot={"character_locked": True, "locked_character": "villain"},
        anchors_by_role=anchors,
        keyframe_url=None,
    )
    assert url == anchors["Villain"]
    assert role == "Villain"

    # locked_character 缺失时 fallback focus_character
    url, src, role = _select_ref_image(
        shot={"character_locked": True, "focus_character": "Hero"},
        anchors_by_role=anchors,
        keyframe_url=None,
    )
    assert role == "Hero"

    # character_locked=False → 退到 keyframe
    url, src, role = _select_ref_image(
        shot={"character_locked": False, "focus_character": "Random"},
        anchors_by_role=anchors,
        keyframe_url="https://test.local/kf.png",
    )
    assert url == "https://test.local/kf.png"
    assert src == "keyframe"
    assert role is None

    # locked=True 但都没命中 → 兜底取第一个 anchor（v3 老 run 兼容）
    url, src, role = _select_ref_image(
        shot={"character_locked": True},
        anchors_by_role=anchors,
        keyframe_url=None,
    )
    assert src == "anchor"
    assert role in ("Hero", "Villain")  # dict 顺序


@pytest.mark.unit
def test_video_agent_uses_correct_anchor_per_shot(monkeypatch, fake_gateway):
    """VideoAgent.run 集成：2 角色 anchors，2 镜分别锁主/配角 → ref_image_source='anchor'，
    ref_anchor_role 各为 'Hero' / 'Villain'，gateway 调用收到对应 ref_image。
    """
    import app.services.pipeline.agents.video as video_module
    from app.services.model_gateway.types import (
        CallStatus,
        ProviderName,
        RenderResult,
    )
    from app.services.pipeline.agents.video import VideoAgent
    from tests.conftest import make_ctx

    # patch_gateway fixture 不覆盖 video module；这里手动 patch
    monkeypatch.setattr(video_module, "get_gateway", lambda: fake_gateway, raising=True)

    fake_gateway.queue(
        RenderResult(
            status=CallStatus.SUCCEEDED,
            provider=ProviderName.KLING,
            model="kling-i2v",
            output={"video_url": "https://test.local/v1.mp4"},
            cost_usd=1.0,
            duration_ms=5000,
        ),
        RenderResult(
            status=CallStatus.SUCCEEDED,
            provider=ProviderName.KLING,
            model="kling-i2v",
            output={"video_url": "https://test.local/v2.mp4"},
            cost_usd=1.0,
            duration_ms=5000,
        ),
    )

    art_outputs = {
        "style_board": {"aspect_ratio": "16:9"},
        "protagonist_name": "Hero",
        # v5：character_anchors 字典
        "character_anchors": {
            "Hero": {
                "name": "Hero",
                "url": "https://test.local/anchor-hero.png",
            },
            "Villain": {
                "name": "Villain",
                "url": "https://test.local/anchor-villain.png",
            },
        },
        "character_anchor": {
            "name": "Hero",
            "url": "https://test.local/anchor-hero.png",
        },
        "shots": [
            {
                "index": 1,
                "duration_s": 5.0,
                "enhanced_prompt": "alley wide shot",
                "keyframe_url": "https://test.local/k1.png",
                "character_locked": True,
                "locked_character": "Hero",
                "focus_character": "Hero",
            },
            {
                "index": 2,
                "duration_s": 5.0,
                "enhanced_prompt": "villain office",
                "keyframe_url": "https://test.local/k2.png",
                "character_locked": True,
                "locked_character": "Villain",
                "focus_character": "Villain",
            },
        ],
    }

    ctx = make_ctx(upstream={"art": art_outputs})
    result = VideoAgent().run(ctx)
    out = result.outputs

    assert result.status.value == "awaiting_review"  # video 默认审批
    rows = out["shots"]
    assert len(rows) == 2

    # 关键断言：ref_image_source 全是 anchor，ref_anchor_role 分别对
    assert rows[0]["ref_image_source"] == "anchor"
    assert rows[0]["ref_anchor_role"] == "Hero"
    assert rows[0]["ref_image_url"] == "https://test.local/anchor-hero.png"

    assert rows[1]["ref_image_source"] == "anchor"
    assert rows[1]["ref_anchor_role"] == "Villain"
    assert rows[1]["ref_image_url"] == "https://test.local/anchor-villain.png"

    # gateway 收到的 ref_image 也对
    calls = fake_gateway.calls
    assert len(calls) == 2
    assert calls[0].params.get("ref_image") == "https://test.local/anchor-hero.png"
    assert calls[1].params.get("ref_image") == "https://test.local/anchor-villain.png"

    # 摘要：2 anchor / 0 keyframe / 0 none，by_role 含两个角色
    summary = out["ref_image_summary"]
    assert summary["anchor"] == 2
    assert summary["keyframe"] == 0
    assert summary["none"] == 0
    assert summary["by_role"] == {"Hero": 1, "Villain": 1}
