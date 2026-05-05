"""Track-09 (多角色锁定) × Track-10 (canary) 叠加行为冒烟。

只验证合并集成点：canary 命中/未命中时，多角色 anchor 字典是否正确流到 _generate_keyframes。
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import pytest


pytestmark = [pytest.mark.unit, pytest.mark.art]


LLM_OUT = json.dumps(
    {
        "style_board": {
            "aspect_ratio": "16:9",
            "style": "film",
            "palette": [],
            "lighting": "daylight",
        },
        "character_cards": [
            {"name": "Hero", "appearance": "tall", "wardrobe": "trench", "vibe": "cool"},
            {
                "name": "Villain",
                "appearance": "thin",
                "wardrobe": "black suit",
                "vibe": "menacing",
            },
        ],
        "shots": [
            {
                "index": 1,
                "description": "hero scene",
                "duration_s": 3,
                "camera": "wide",
                "focus_character": "Hero",
            },
            {
                "index": 2,
                "description": "villain scene",
                "duration_s": 3,
                "camera": "close",
                "focus_character": "Villain",
            },
        ],
    }
)


def _queue_responses(gw):
    from app.services.model_gateway.types import (
        CallStatus,
        ProviderName,
        RenderResult,
    )

    def llm_response(_req):
        return RenderResult(
            status=CallStatus.SUCCEEDED,
            provider=ProviderName.SILICONFLOW,
            output=LLM_OUT,
            cost_usd=0.001,
        )

    def image_response(req):
        prompt = (req.params or {}).get("prompt", "x")
        slug = "".join(c for c in prompt[:24] if c.isalnum() or c == "_") or "anchor"
        return RenderResult(
            status=CallStatus.SUCCEEDED,
            provider=ProviderName.SILICONFLOW,
            output={"image_url": f"https://anchor/{slug}.png"},
            cost_usd=0.005,
        )

    gw.queue(llm_response, image_response, image_response, image_response, image_response, image_response, image_response)


def _build_ctx(*, feature_flags: dict[str, Any]):
    from app.services.pipeline.types import PipelineContext

    return PipelineContext(
        run_id=f"canary-run-{uuid.uuid4().hex[:6]}",
        step_id="art",
        user_id="canary-user",
        file_id="canary-file",
        inputs={"brief": {"主题": "demo"}},
        upstream_outputs={
            "script": {
                "shots": [
                    {"index": 1, "focus_character": "Hero"},
                    {"index": 2, "focus_character": "Villain"},
                ]
            }
        },
        tenant_id="u:canary-tenant",
        tenant_plan="free",
        feature_flags=feature_flags,
    )


def _run(patch_gateway, *, flag_value):
    _queue_responses(patch_gateway)
    feature_flags: dict[str, Any] = {}
    if flag_value is not None:
        feature_flags["art_ipadapter_pct"] = flag_value
    from app.services.pipeline.agents.art import ArtAgent

    return ArtAgent().run(_build_ctx(feature_flags=feature_flags))


def test_canary_default_runs_v4_with_multichar_anchors(patch_gateway):
    res = _run(patch_gateway, flag_value=None)
    out = res.outputs
    assert out["canary_variant"] == "v4"
    anchors = out.get("character_anchors") or {}
    assert "Hero" in anchors


def test_canary_pct_zero_falls_back_to_prompt_only(patch_gateway):
    res = _run(patch_gateway, flag_value={"pct": 0})
    out = res.outputs
    assert out["canary_variant"] == "v3-prompt-only"
    image_calls = [c for c in patch_gateway.calls if c.action == "generate_image"]
    keyframe_calls = [c for c in image_calls if c.params.get("image_url")]
    assert keyframe_calls == [], "v3-prompt-only 路径不应给 keyframe 喂 image_url"


def test_canary_pct_full_keeps_v4(patch_gateway):
    res = _run(patch_gateway, flag_value={"pct": 100})
    out = res.outputs
    assert out["canary_variant"] == "v4"
    assert out["canary_flag_value"] == {"pct": 100}


def test_canary_enabled_false_falls_back(patch_gateway):
    res = _run(patch_gateway, flag_value={"enabled": False})
    out = res.outputs
    assert out["canary_variant"] == "v3-prompt-only"
