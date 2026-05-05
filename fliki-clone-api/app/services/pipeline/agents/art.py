"""ArtAgent v3 / v4 — 风格 + 关键帧 + 角色一致性 + IP-Adapter 真接入

输入：上游 ScriptAgent 的 outputs（topic / script / shots）+ Brief 中的可选视觉偏好
输出：
- `style_board`：全片视觉调性（色板、风格关键词、光线、镜头语汇、aspect_ratio）
- `character_cards`：脚本里出现的主要角色卡（外形/服装/神态/语气）
- `character_anchor`（v3 新）：主角的锚点参考图：`{name, appearance, url, error?, cost_usd}`
- `consistency_mode`（v3 新）：`anchor` / `prompt-only` / `disabled` —— 实际启用模式
- `shots`：在 ScriptAgent shots 上叠加 `enhanced_prompt` / `negative_prompt` / `style_ref`
  / `keyframe_url`（v2：调 GENERATE_IMAGE 的产物，作为 IMAGE_TO_VIDEO 的参考帧）
  / `character_locked`（v3：该镜是否真把角色描述拼到 prompt 前缀）
  / `ip_adapter_used`（v4：该镜出关键帧时是否真把锚点参考图喂给了 image provider）

v3 角色一致性策略
-----------------
v2 痛点：每镜独立出图，主角脸/发型/服装跨镜漂。

v3 双层方案（**任何 image provider 都生效，不依赖 IP-Adapter**）：

1. **锚点首镜**（默认开启，可关）：在生成各镜关键帧之前，先单独调一次
   GENERATE_IMAGE 为主角出一张「角色参考板」（1:1，neutral background，
   portrait/hero shot），URL 保存到 `outputs.character_anchor.url`，
   同时挂到 brief 上后续 VideoAgent / EditAgent / 前端可复用。

2. **prompt 锁定**（默认开启）：把主角的 `appearance / wardrobe / vibe`
   组装成稳定前缀 `[Consistent character: ...]`，**强制**注入到每镜
   `enhanced_prompt` 头部；negative_prompt 追加防漂关键词
   `different face, different person, inconsistent character, multiple people`。

3. 二者独立可关：`brief.character_consistency`：
   - `auto`（默认）：有 character_cards 就启用 anchor + prompt-only；都没角色卡时降到 disabled
   - `prompt-only`：强制只走 prompt 模式（省锚点钱）
   - `anchor`：强制要锚点；锚点失败则保留 prompt-only 并写 warning
   - `off`：v2 行为完全恢复

v4 IP-Adapter 真接入（在 v3 之上）
---------------------------------
v3 已生成 `outputs.character_anchor.url`，但只是放着没真喂回 image provider。v4
让 `_generate_keyframes` 对 `character_locked=true` 的镜传 `image_url=anchor.url` 入
`RenderRequest.params`：

- 主角镜（character_locked=true）+ anchor.url 存在 → 传 image_url；
  provider 真用了（Kolors-IP 或兼容路径）→ 该镜 outputs `ip_adapter_used=true`
- 非主角镜（character_locked=false）→ 不传 image_url（避免污染聚焦的角色脸）→
  `ip_adapter_used=false`
- provider 不支持 image_url（返 400 / unknown parameter）→ siliconflow_image.py
  自动剥离重试，本镜 `ip_adapter_used=false` + 写 `ip_adapter_degrade_reason`；
  不影响 keyframe 生成（v3 prompt-only 兜底依然生效）

激活方式：env `SILICONFLOW_KOLORS_IP_MODEL=<官方上线后的 model id>` 把 IP 模型
路由到主选；缺省时仍尝试给现有 Kolors / FLUX 模型塞 image_url，由 provider 自决降级。

设计取舍（v2 沿用）：
- 默认为每镜出 1 张关键帧（约 $0.005/张，6 镜 ≈ $0.03，远小于视频生成成本）
- `brief.skip_keyframes=true` 可关闭；适用于纯文字 prompt 的快速测试
- 单镜关键帧失败时仅警告，不阻塞整个 step；VideoAgent 检测不到 keyframe_url 自动回退 GENERATE_VIDEO
- 强制 awaiting_review 留给 script 节点；ArtAgent 默认放行
- 输出尽量 self-contained，便于前端独立渲染（不需要 join script 输出）
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.services.model_gateway import (
    CallStatus,
    ModelAction,
    RenderRequest,
    get_gateway,
)

from .. import feature_flags as pipeline_feature_flags
from ..types import PipelineContext, Step, StepResult, StepStatus, register_agent

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "你是一位短视频美术指导 + 提示词工程师。"
    " 给定 Brief、选题、口播脚本与初版分镜，请输出一个 JSON 对象，描述全片视觉风格 + 角色卡 + 每镜增强提示词。"
    " 字段如下：\n"
    "{\n"
    "  \"style_board\": {\n"
    "    \"palette\": [\"色板关键词，3-5 个，可以是 #FF6B6B 或 'warm orange'\"],\n"
    "    \"style_keywords\": [\"画风关键词，3-6 个，英文，例如 cinematic, neon, retro, anime, photoreal\"],\n"
    "    \"lighting\": \"光线描述，英文，如 soft window light, harsh neon\",\n"
    "    \"camera_language\": [\"机位/运动关键词，2-4 个，英文，例如 slow push-in, handheld\"],\n"
    "    \"aspect_ratio\": \"按平台推断：抖音/快手 9:16；YouTube/B 站 16:9；小红书 4:5\",\n"
    "    \"reference_notes\": \"对调色 / 质感的额外说明，1 句，英文\"\n"
    "  },\n"
    "  \"character_cards\": [\n"
    "    {\n"
    "      \"name\": \"角色代号，如 protagonist / coworker_A；**主角必须放在数组第一位**，使下游能稳定锁定一致性\",\n"
    "      \"appearance\": \"外形描述，英文，含发型/年龄/体态/性别等具体特征，越具体越能跨镜锁定\",\n"
    "      \"wardrobe\": \"服装描述，英文，主角的衣着应在所有镜里一致（除非脚本明确换装）\",\n"
    "      \"vibe\": \"气质 / 表情 / 神态，英文\"\n"
    "    }\n"
    "  ],\n"
    "  \"shots\": [\n"
    "    {\n"
    "      \"index\": 1,\n"
    "      \"enhanced_prompt\": \"详细英文 prompt：subject + scene + lighting + camera + style_keywords + aspect。"
    "**不需要重复 character 描述**（下游会自动注入主角一致性前缀），聚焦本镜的场景 / 动作 / 镜头\",\n"
    "      \"negative_prompt\": \"避免内容（英文，含 distorted hands, watermark, text overlay 等）\",\n"
    "      \"focus_character\": \"该镜画面焦点的角色代号；缺省视为主角\"\n"
    "    }\n"
    "  ]\n"
    "}\n"
    " 严格输出合法 JSON 对象，不要包含 markdown 围栏或多余文字。"
    " 必须保持 shots 数组的长度与上游分镜一致；index 与上游一一对应。"
    " character_cards 至少给出主角 1 张；多角色脚本主角放第一位。"
)


# 一致性模式：brief.character_consistency 取值
CONSISTENCY_MODES = ("auto", "prompt-only", "anchor", "off")
DEFAULT_CONSISTENCY_MODE = "auto"

# 注入到每镜 enhanced_prompt 前缀的固定包裹格式（保持稳定，便于跨调用复现）
_CHAR_PROMPT_PREFIX = "[Consistent character: {body}] "
# negative prompt 防漂关键词（追加到原有 negative 后）
_CHAR_NEGATIVE_HINT = (
    "different face, different person, inconsistent character, multiple people"
)


@register_agent("art")
class ArtAgent(Step):
    def estimate_cost_usd(self, ctx: PipelineContext) -> float:
        script_out = ctx.upstream_outputs.get("script") or {}
        shots = script_out.get("shots") or []
        brief = (ctx.inputs or {}).get("brief") or {}
        # 1 次 LLM 提示词增强 + 每镜一张关键帧（默认开启）+ v3 角色锚点 1 张
        skip = bool(brief.get("skip_keyframes"))
        keyframe_cost = 0.0 if skip else 0.005 * len(shots)
        # 锚点：mode != off 且不是显式 prompt-only 时多算 1 张图
        mode = str(brief.get("character_consistency") or DEFAULT_CONSISTENCY_MODE).lower()
        anchor_cost = 0.005 if mode in ("auto", "anchor") and not skip else 0.0
        return 0.003 + keyframe_cost + anchor_cost

    def run(self, ctx: PipelineContext) -> StepResult:  # noqa: D401
        brief = (ctx.inputs or {}).get("brief") or {}
        script_out = ctx.upstream_outputs.get("script") or {}
        shots = [s for s in (script_out.get("shots") or []) if isinstance(s, dict)]

        if not shots:
            return StepResult(
                status=StepStatus.FAILED,
                error="art: missing shots from upstream script outputs",
            )

        user_msg = (
            "Brief：\n"
            + json.dumps(brief, ensure_ascii=False, indent=2)
            + "\n\n选题：\n"
            + json.dumps(script_out.get("topic") or {}, ensure_ascii=False, indent=2)
            + "\n\n口播稿：\n"
            + str(script_out.get("script") or "")
            + "\n\n初版分镜：\n"
            + json.dumps(shots, ensure_ascii=False, indent=2)
        )

        gateway = get_gateway()
        result = gateway.run(
            RenderRequest(
                action=ModelAction.LLM,
                params={
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": 0.5,
                    "max_tokens": 2200,
                    "approx_tokens": 3000,
                },
                user_id=ctx.user_id,
                file_id=ctx.file_id,
                pipeline_step_id=ctx.step_id,
            )
        )

        if not result.ok or not isinstance(result.output, str):
            return StepResult(
                status=StepStatus.FAILED,
                error=result.error or "art: invalid LLM output",
                cost_usd=result.cost_usd,
            )

        parsed = _parse_json_object(result.output)
        if not parsed:
            return StepResult(
                status=StepStatus.FAILED,
                error="art: cannot parse LLM JSON object",
                cost_usd=result.cost_usd,
            )

        style_board = _normalise_style_board(parsed.get("style_board") or {}, brief)
        character_cards = _normalise_character_cards(parsed.get("character_cards") or [])
        enriched_shots = _enrich_shots(shots, parsed.get("shots") or [], style_board)

        total_cost = float(result.cost_usd or 0.0)
        keyframe_failures = 0

        # ── v3：决定一致性模式 + 选主角 + （可选）出锚点 ──────────────────
        consistency_mode = _resolve_consistency_mode(brief, character_cards)
        protagonist = _select_protagonist(brief, character_cards)
        character_anchor: dict[str, Any] | None = None
        anchor_warning: str | None = None

        if consistency_mode in ("auto", "anchor") and protagonist:
            anchor_aspect = "1:1"  # 锚点参考板用 1:1，便于复用 / IP-Adapter 友好
            anchor_result = _generate_character_anchor(
                protagonist=protagonist,
                style_board=style_board,
                ctx=ctx,
                gateway=gateway,
                aspect=anchor_aspect,
            )
            total_cost += float(anchor_result.get("cost_usd") or 0.0)
            character_anchor = anchor_result
            if not anchor_result.get("url"):
                if consistency_mode == "anchor":
                    anchor_warning = (
                        "character_anchor failed; downgraded to prompt-only mode: "
                        + str(anchor_result.get("error") or "unknown")
                    )[:300]
                # 锚点失败：mode=auto 时静默降到 prompt-only；mode=anchor 时也降级 + warning
                consistency_mode = "prompt-only" if character_cards else "disabled"

        # ── v3：把角色描述注入每镜 enhanced_prompt + 防漂 negative ─────────
        if consistency_mode in ("auto", "anchor", "prompt-only") and protagonist:
            enriched_shots = _inject_consistency_into_shots(
                shots=enriched_shots, protagonist=protagonist
            )
            # auto + 锚点成功 → mode 提升为 anchor；auto + 无锚点 → prompt-only
            if consistency_mode == "auto":
                consistency_mode = (
                    "anchor"
                    if character_anchor and character_anchor.get("url")
                    else "prompt-only"
                )
        elif consistency_mode == "auto":
            # auto 但没角色卡 → 真正退回 disabled
            consistency_mode = "disabled"

        skip_keyframes = bool(brief.get("skip_keyframes"))
        # ── Track-10 灰度：通过 art_ipadapter_pct flag 决定本 run 是否启用 v4 IP-Adapter ──
        # value 形态约定：{"pct": 0..100} / {"enabled": bool} / {"variant": "v4"/"v3"}。
        # is_enabled 命中（True）→ 喂 anchor 给 _generate_keyframes 走 v4 IP-Adapter；
        # 不命中 → anchor_url 置 None，主角镜降到 v3 prompt-only（前缀注入仍生效）。
        # 缺省（tenant 没设过 flag）→ 保持当前默认行为（v4），向后兼容。
        # key=ctx.run_id 让同 tenant 不同 run 之间也按 pct 分流（pct=50 → 一半 run 走 v4）。
        canary_value = (ctx.feature_flags or {}).get("art_ipadapter_pct")
        if canary_value is None:
            canary_v4 = True  # flag 缺省 → 默认 v4
        else:
            canary_v4 = pipeline_feature_flags.is_enabled(
                ctx.tenant_id or "",
                "art_ipadapter_pct",
                key=ctx.run_id,
                flags=ctx.feature_flags,
            )
        canary_variant = "v4" if canary_v4 else "v3-prompt-only"

        anchor_url_for_keyframes: str | None = None
        if (
            canary_v4
            and character_anchor
            and isinstance(character_anchor.get("url"), str)
        ):
            anchor_url_for_keyframes = character_anchor["url"]
        if not skip_keyframes:
            enriched_shots, kf_cost, keyframe_failures = _generate_keyframes(
                enriched_shots,
                style_board=style_board,
                ctx=ctx,
                gateway=gateway,
                character_anchor_url=anchor_url_for_keyframes,
            )
            total_cost += kf_cost

        outputs: dict[str, Any] = {
            "style_board": style_board,
            "character_cards": character_cards,
            "shots": enriched_shots,
            "keyframes_enabled": not skip_keyframes,
            "keyframe_failures": keyframe_failures,
            # v3 字段
            "consistency_mode": consistency_mode,
            "character_anchor": character_anchor,
            "protagonist_name": protagonist.get("name") if protagonist else None,
            # Track-10 灰度可观测：让前端 / 调试能知道本 run 实际走了哪一档
            "canary_variant": canary_variant,
            "canary_flag_value": canary_value,
        }
        if anchor_warning:
            outputs["consistency_warning"] = anchor_warning
        if skip_keyframes:
            outputs["note"] = "skip_keyframes=true; VideoAgent 将走 GENERATE_VIDEO（无 ref image 一致性）"

        return StepResult(
            status=StepStatus.SUCCEEDED,
            outputs=outputs,
            cost_usd=total_cost,
        )


def _generate_keyframes(
    shots: list[dict[str, Any]],
    *,
    style_board: dict[str, Any],
    ctx: PipelineContext,
    gateway: Any,
    character_anchor_url: str | None = None,
) -> tuple[list[dict[str, Any]], float, int]:
    """为每个 shot 调一次 GENERATE_IMAGE，写入 shots[i].keyframe_url。

    v4：当 `character_anchor_url` 提供且本镜 `character_locked=True` 时，把它作为
    `image_url` 传入 RenderRequest.params，让 image provider 走 IP-Adapter 路径
    锁定主角脸。每镜在 outputs 里加：

    - `ip_adapter_used: bool`         provider 写回（True 表 image_url 真喂上去了）
    - `ip_adapter_degrade_reason: str | None`  provider 剥离 image_url 时填这里

    非主角镜（character_locked=False）不传 image_url，避免污染聚焦角色脸。

    单镜失败（含 IP-Adapter 不支持后的 v3 兜底降级）仅记 warning + 留 keyframe_error
    字段；不影响其它镜与下游回退路径。返回 (shots, total_cost, failure_count)。
    """

    aspect = str(style_board.get("aspect_ratio") or "16:9")
    total_cost = 0.0
    failures = 0

    out: list[dict[str, Any]] = []
    for shot in shots:
        merged = dict(shot)
        prompt = str(shot.get("enhanced_prompt") or shot.get("visual") or "").strip()
        if not prompt:
            merged["keyframe_url"] = None
            merged["keyframe_error"] = "empty prompt"
            merged["ip_adapter_used"] = False
            failures += 1
            out.append(merged)
            continue

        # v4：只对「锁了主角」的镜传 anchor 作为 IP-Adapter 输入
        is_protagonist_shot = bool(shot.get("character_locked"))
        ref_image_url = (
            character_anchor_url if (is_protagonist_shot and character_anchor_url) else None
        )

        params: dict[str, Any] = {
            "prompt": prompt,
            "negative_prompt": shot.get("negative_prompt"),
            "aspect_ratio": shot.get("aspect_ratio") or aspect,
            "n": 1,
        }
        if ref_image_url:
            params["image_url"] = ref_image_url

        result = gateway.run(
            RenderRequest(
                action=ModelAction.GENERATE_IMAGE,
                params=params,
                user_id=ctx.user_id,
                file_id=ctx.file_id,
                pipeline_step_id=ctx.step_id,
                timeout_s=120.0,
            )
        )

        total_cost += float(result.cost_usd or 0.0)

        # 默认 False；只有 provider 在 output 里写回 True 时才认为 IP-Adapter 真生效
        merged["ip_adapter_used"] = False

        if result.ok and isinstance(result.output, dict):
            merged["keyframe_url"] = result.output.get("image_url")
            merged["keyframe_provider"] = (
                result.provider.value if result.provider else None
            )
            merged["keyframe_model"] = result.model
            merged["keyframe_size"] = result.output.get("image_size")
            merged["keyframe_error"] = None
            ip_used = bool(result.output.get("ip_adapter_used"))
            merged["ip_adapter_used"] = ip_used
            degrade = result.output.get("ip_adapter_degrade_reason")
            if degrade:
                merged["ip_adapter_degrade_reason"] = str(degrade)[:300]
            elif ref_image_url and not ip_used:
                # 我们传了 anchor 但 provider 没标 used 也没标 degrade（兜底）
                merged["ip_adapter_degrade_reason"] = (
                    "image_url passed but provider did not confirm IP-Adapter usage"
                )
        else:
            merged["keyframe_url"] = None
            merged["keyframe_error"] = result.error or "image generation failed"
            if ref_image_url:
                merged["ip_adapter_degrade_reason"] = (
                    f"keyframe call failed with image_url: {merged['keyframe_error']}"
                )[:300]
            failures += 1
            logger.warning(
                "art: keyframe failed for shot %s: %s",
                shot.get("index"),
                merged["keyframe_error"],
            )

        out.append(merged)

    return out, total_cost, failures


# ── v3 helpers：角色一致性 ───────────────────────────────────────────────────


def _resolve_consistency_mode(
    brief: dict[str, Any], character_cards: list[dict[str, Any]]
) -> str:
    """读 brief.character_consistency；不合法值兜底 auto；off / 无 cards 返 disabled。"""
    raw = str(brief.get("character_consistency") or DEFAULT_CONSISTENCY_MODE).lower().strip()
    if raw not in CONSISTENCY_MODES:
        raw = DEFAULT_CONSISTENCY_MODE
    if raw == "off":
        return "disabled"
    if not character_cards:
        # auto / prompt-only / anchor 都依赖至少 1 张 character_card；缺失 → disabled
        return "disabled"
    return raw


def _select_protagonist(
    brief: dict[str, Any], character_cards: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """选主角：brief.protagonist_role 命中名字时优先；否则取 character_cards[0]。"""
    if not character_cards:
        return None
    target = str(brief.get("protagonist_role") or "").strip().lower()
    if target:
        for card in character_cards:
            if str(card.get("name", "")).strip().lower() == target:
                return card
    return character_cards[0]


def _build_anchor_prompt(protagonist: dict[str, Any], style_board: dict[str, Any]) -> str:
    """组装锚点参考板 prompt：portrait + 角色卡 + 全片风格 + 中性背景。"""
    name = str(protagonist.get("name") or "protagonist")
    appearance = str(protagonist.get("appearance") or "").strip()
    wardrobe = str(protagonist.get("wardrobe") or "").strip()
    vibe = str(protagonist.get("vibe") or "").strip()
    style_kw = ", ".join(style_board.get("style_keywords") or [])
    parts = [
        f"character reference sheet of {name}",
        appearance,
        f"wearing {wardrobe}" if wardrobe else "",
        vibe,
        style_kw,
        "front portrait, hero shot, neutral gray background",
        "consistent appearance, single subject, full face visible",
        "high detail, professional studio lighting",
    ]
    prompt = ", ".join(p for p in parts if p)
    return prompt[:800]


def _generate_character_anchor(
    *,
    protagonist: dict[str, Any],
    style_board: dict[str, Any],
    ctx: PipelineContext,
    gateway: Any,
    aspect: str,
) -> dict[str, Any]:
    """单独调一次 GENERATE_IMAGE 出主角参考板；返回 {name, appearance, prompt, url, error, cost_usd, aspect}。"""
    prompt = _build_anchor_prompt(protagonist, style_board)
    result = gateway.run(
        RenderRequest(
            action=ModelAction.GENERATE_IMAGE,
            params={
                "prompt": prompt,
                "negative_prompt": _DEFAULT_NEGATIVE + ", multiple people",
                "aspect_ratio": aspect,
                "n": 1,
            },
            user_id=ctx.user_id,
            file_id=ctx.file_id,
            pipeline_step_id=ctx.step_id,
            timeout_s=120.0,
        )
    )
    out: dict[str, Any] = {
        "name": protagonist.get("name"),
        "appearance": protagonist.get("appearance"),
        "wardrobe": protagonist.get("wardrobe"),
        "vibe": protagonist.get("vibe"),
        "prompt": prompt,
        "aspect": aspect,
        "url": None,
        "provider": result.provider.value if result.provider else None,
        "model": result.model,
        "error": None,
        "cost_usd": float(result.cost_usd or 0.0),
    }
    if result.status == CallStatus.SUCCEEDED and isinstance(result.output, dict):
        out["url"] = result.output.get("image_url")
    elif result.status == CallStatus.DEGRADED and isinstance(result.output, dict):
        out["url"] = result.output.get("image_url")
        out["fallback_used"] = True
    else:
        out["error"] = result.error or "anchor generation failed"
        logger.warning(
            "art: character anchor failed for %s: %s",
            protagonist.get("name"),
            out["error"],
        )
    return out


def _inject_consistency_into_shots(
    *,
    shots: list[dict[str, Any]],
    protagonist: dict[str, Any],
) -> list[dict[str, Any]]:
    """把 protagonist 的 appearance/wardrobe/vibe 拼成稳定前缀，注入到每镜 enhanced_prompt 头。

    标记 `character_locked=true` 让前端 / 调试可观察哪些镜真正注入了一致性 prompt。
    negative_prompt 追加防漂关键词，避免模型擅自换人。
    """
    name = str(protagonist.get("name") or "protagonist")
    appearance = str(protagonist.get("appearance") or "").strip()
    wardrobe = str(protagonist.get("wardrobe") or "").strip()
    vibe = str(protagonist.get("vibe") or "").strip()
    body_parts = [
        f"protagonist={name}",
        appearance,
        f"wardrobe={wardrobe}" if wardrobe else "",
        f"vibe={vibe}" if vibe else "",
    ]
    body = "; ".join(p for p in body_parts if p)
    prefix = _CHAR_PROMPT_PREFIX.format(body=body)

    out: list[dict[str, Any]] = []
    for shot in shots:
        merged = dict(shot)
        # focus_character 显式标了别人 → 跳过该镜（只锁主角，不强加到非主角镜）
        focus = str(shot.get("focus_character") or "").strip().lower()
        focus_is_protagonist = (not focus) or (focus == name.lower())
        if not focus_is_protagonist:
            merged["character_locked"] = False
            out.append(merged)
            continue

        original = str(merged.get("enhanced_prompt") or "").strip()
        # 已经包含相同前缀（重跑场景）就不重复注入
        if original.startswith("[Consistent character:"):
            merged["character_locked"] = True
            out.append(merged)
            continue
        merged["enhanced_prompt"] = (prefix + original)[:1200]

        # negative：追加防漂关键词，去重避免重叠
        neg = str(merged.get("negative_prompt") or "").strip()
        if _CHAR_NEGATIVE_HINT not in neg:
            sep = ", " if neg else ""
            merged["negative_prompt"] = (neg + sep + _CHAR_NEGATIVE_HINT)[:600]
        merged["character_locked"] = True
        out.append(merged)
    return out


# ── helpers ──────────────────────────────────────────────────────────────────


def _parse_json_object(content: str) -> dict[str, Any] | None:
    """从 LLM 响应里抓出第一个 JSON 对象，容忍 ```json``` 围栏与前后噪声。"""

    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
        if text.endswith("```"):
            text = text[:-3].strip()

    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                snippet = text[start : i + 1]
                try:
                    parsed = json.loads(snippet)
                except Exception:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def _platform_aspect(brief: dict[str, Any]) -> str:
    platform = str(brief.get("platform", "")).strip().lower()
    if any(k in platform for k in ("douyin", "抖音", "tiktok", "kuaishou", "快手", "shorts", "reels")):
        return "9:16"
    if any(k in platform for k in ("youtube", "bilibili", "b 站", "b站", "youku", "西瓜")):
        return "16:9"
    if any(k in platform for k in ("xhs", "小红书", "instagram feed", "feed")):
        return "4:5"
    return "16:9"


def _normalise_style_board(raw: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any]:
    palette = [str(x).strip()[:40] for x in (raw.get("palette") or []) if str(x).strip()]
    style_keywords = [
        str(x).strip()[:40] for x in (raw.get("style_keywords") or []) if str(x).strip()
    ]
    camera_language = [
        str(x).strip()[:40] for x in (raw.get("camera_language") or []) if str(x).strip()
    ]
    aspect = str(raw.get("aspect_ratio") or "").strip()
    if aspect not in ("16:9", "9:16", "1:1", "4:5", "4:3"):
        aspect = _platform_aspect(brief)

    return {
        "palette": palette[:6],
        "style_keywords": style_keywords[:8],
        "lighting": str(raw.get("lighting", "")).strip()[:200],
        "camera_language": camera_language[:6],
        "aspect_ratio": aspect,
        "reference_notes": str(raw.get("reference_notes", "")).strip()[:300],
    }


def _normalise_character_cards(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for item in items[:6]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()[:40]
        if not name:
            continue
        out.append(
            {
                "name": name,
                "appearance": str(item.get("appearance", "")).strip()[:300],
                "wardrobe": str(item.get("wardrobe", "")).strip()[:200],
                "vibe": str(item.get("vibe", "")).strip()[:200],
            }
        )
    return out


_DEFAULT_NEGATIVE = (
    "distorted hands, extra fingers, watermark, text overlay, low quality, "
    "blurry, deformed face, lowres"
)


def _enrich_shots(
    base_shots: list[dict[str, Any]],
    art_shots: list[Any],
    style_board: dict[str, Any],
) -> list[dict[str, Any]]:
    """把 LLM 生成的 enhanced_prompt 合到 ScriptAgent 的 shots 上；缺失项做 graceful fallback。"""

    art_by_index: dict[int, dict[str, Any]] = {}
    for item in art_shots:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("index"))
        except Exception:
            continue
        art_by_index[idx] = item

    style_suffix_parts = []
    if style_board.get("style_keywords"):
        style_suffix_parts.append(", ".join(style_board["style_keywords"]))
    if style_board.get("lighting"):
        style_suffix_parts.append(style_board["lighting"])
    if style_board.get("aspect_ratio"):
        style_suffix_parts.append(f"aspect {style_board['aspect_ratio']}")
    style_suffix = ", ".join([p for p in style_suffix_parts if p])

    out: list[dict[str, Any]] = []
    for shot in base_shots:
        index = int(shot.get("index") or len(out) + 1)
        art_item = art_by_index.get(index, {})
        enhanced = str(art_item.get("enhanced_prompt", "")).strip()
        if not enhanced:
            base_visual = str(shot.get("visual") or shot.get("narration") or "").strip()
            enhanced = f"{base_visual}. {style_suffix}".strip(". ")
        negative = str(art_item.get("negative_prompt", "")).strip() or _DEFAULT_NEGATIVE
        focus = str(art_item.get("focus_character", "")).strip()[:40]

        merged = dict(shot)
        merged.update(
            {
                "enhanced_prompt": enhanced[:800],
                "negative_prompt": negative[:400],
                "style_ref": ", ".join(style_board.get("style_keywords") or []),
                "aspect_ratio": style_board.get("aspect_ratio") or "16:9",
            }
        )
        if focus:
            merged["focus_character"] = focus
        out.append(merged)
    return out
