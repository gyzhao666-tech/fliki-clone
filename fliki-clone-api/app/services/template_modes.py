from __future__ import annotations

from copy import deepcopy
import re
from typing import Any


def _scene(
    scene_id: str,
    name: str,
    goal: str,
    duration: float,
    slots: list[str],
    prompt: str,
) -> dict[str, Any]:
    return {
        "id": scene_id,
        "name": name,
        "goal": goal,
        "duration": duration,
        "slots": slots,
        "prompt_template": prompt,
    }


def _mode(
    *,
    mode_id: str,
    name: str,
    project_type: str,
    best_for: list[str],
    replacement_scope: str,
    required_inputs: list[dict[str, str]],
    slots: list[dict[str, str]],
    scenes: list[dict[str, Any]],
    visual_style: dict[str, Any],
    prompt_rules: list[str],
    quality_rules: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mode_id": mode_id,
        "mode_name": name,
        "project_type": project_type,
        "best_for": best_for,
        "replacement_scope": replacement_scope,
        "required_inputs": required_inputs,
        "slots": slots,
        "scenes": scenes,
        "visual_style": visual_style,
        "prompt_rules": prompt_rules,
        "quality_rules": quality_rules,
    }


TEMPLATE_MODES: dict[str, dict[str, Any]] = {
    "t-01": _mode(
        mode_id="product_launch_replace",
        name="产品发布替换模式",
        project_type="template_replace",
        best_for=["新品发布", "产品亮点", "电商首发", "SaaS 功能上线"],
        replacement_scope="替换产品名称、主视觉、核心卖点、价格/权益和 CTA，保留发布节奏与商业广告构图。",
        required_inputs=[
            {"key": "product_name", "label": "产品名称"},
            {"key": "product_visual", "label": "产品图片或视频"},
            {"key": "top_benefits", "label": "3 个核心卖点"},
            {"key": "cta", "label": "行动号召"},
        ],
        slots=[
            {"key": "hook", "type": "text", "description": "开场吸睛文案"},
            {"key": "product_visual", "type": "media", "description": "产品主视觉"},
            {"key": "benefit_1", "type": "text", "description": "核心卖点一"},
            {"key": "benefit_2", "type": "text", "description": "核心卖点二"},
            {"key": "benefit_3", "type": "text", "description": "核心卖点三"},
            {"key": "cta", "type": "text", "description": "结尾引导"},
        ],
        scenes=[
            _scene("hook", "开场亮相", "用一句话定义新品价值", 4, ["hook", "product_visual"], "竖屏新品发布广告开场，展示 {{product_name}}，标题为 {{hook}}，高级商业质感，干净背景。"),
            _scene("problem", "需求痛点", "说明用户为什么需要这个产品", 5, ["target_pain"], "表现目标用户的典型痛点：{{target_pain}}，镜头简洁，有生活化真实感。"),
            _scene("benefits", "卖点连击", "连续展示 3 个核心卖点", 8, ["benefit_1", "benefit_2", "benefit_3"], "用三段快速镜头展示 {{product_name}} 的卖点：{{benefit_1}}、{{benefit_2}}、{{benefit_3}}。"),
            _scene("proof", "信任背书", "用数据或场景强化可信度", 5, ["proof"], "产品使用场景特写，叠加可信背书：{{proof}}，画面稳定、现代。"),
            _scene("cta", "购买引导", "明确下一步行动", 4, ["cta", "product_visual"], "结尾展示 {{product_name}} 和行动号召 {{cta}}，突出品牌感和购买欲。"),
        ],
        visual_style={"aspect_ratio": "9:16", "pace": "fast", "tone": "premium commercial", "subtitle": "bold bottom"},
        prompt_rules=["保持产品始终清晰可见", "优先使用用户上传素材", "卖点镜头不要发散成剧情片"],
        quality_rules=["每个镜头只表达一个卖点", "CTA 必须出现在最后 3 秒", "避免虚构价格、认证或功效"],
    ),
    "t-02": _mode(
        mode_id="tutorial_steps_replace",
        name="教程步骤替换模式",
        project_type="template_replace",
        best_for=["操作指南", "工具教程", "软件功能教学", "DIY 步骤"],
        replacement_scope="替换教程主题、步骤说明、关键截图/画面和注意事项，保留分步讲解结构。",
        required_inputs=[
            {"key": "tutorial_topic", "label": "教程主题"},
            {"key": "steps", "label": "3-5 个操作步骤"},
            {"key": "screen_or_demo_media", "label": "截图或演示素材"},
        ],
        slots=[
            {"key": "tutorial_topic", "type": "text", "description": "教程标题"},
            {"key": "step_1", "type": "text", "description": "步骤一"},
            {"key": "step_2", "type": "text", "description": "步骤二"},
            {"key": "step_3", "type": "text", "description": "步骤三"},
            {"key": "tip", "type": "text", "description": "关键提示"},
        ],
        scenes=[
            _scene("intro", "说明结果", "先展示学完能做到什么", 4, ["tutorial_topic"], "教程视频开场，标题为 {{tutorial_topic}}，展示最终效果，画面清晰。"),
            _scene("step_1", "步骤一", "演示第一步操作", 6, ["step_1", "screen_or_demo_media"], "分步教程画面，突出步骤 1：{{step_1}}，使用清晰箭头和编号。"),
            _scene("step_2", "步骤二", "演示第二步操作", 6, ["step_2", "screen_or_demo_media"], "分步教程画面，突出步骤 2：{{step_2}}，画面干净，重点明确。"),
            _scene("step_3", "步骤三", "演示第三步操作", 6, ["step_3", "screen_or_demo_media"], "分步教程画面，突出步骤 3：{{step_3}}，保留教程一致风格。"),
            _scene("tip", "注意事项", "提醒容易踩坑的点", 4, ["tip"], "教程总结画面，强调关键提示：{{tip}}。"),
        ],
        visual_style={"aspect_ratio": "9:16", "pace": "medium", "tone": "clear instructional", "subtitle": "step labels"},
        prompt_rules=["每段只讲一个步骤", "编号、箭头、重点框要统一", "不要加入无关剧情"],
        quality_rules=["步骤顺序不能被改写", "关键术语保持用户原文", "如果缺截图，用抽象 UI 示意图替代"],
    ),
    "t-03": _mode(
        mode_id="social_promo_replace",
        name="社媒促销替换模式",
        project_type="template_replace",
        best_for=["限时优惠", "活动预告", "社媒广告", "拉新促销"],
        replacement_scope="替换活动主题、优惠利益点、倒计时、商品/服务素材和 CTA，保留高节奏社媒广告风格。",
        required_inputs=[
            {"key": "offer", "label": "优惠或活动利益点"},
            {"key": "product_name", "label": "商品/服务名称"},
            {"key": "deadline", "label": "截止时间"},
            {"key": "cta", "label": "行动号召"},
        ],
        slots=[
            {"key": "offer", "type": "text", "description": "促销利益点"},
            {"key": "deadline", "type": "text", "description": "截止时间"},
            {"key": "social_proof", "type": "text", "description": "热度或口碑"},
            {"key": "cta", "type": "text", "description": "行动号召"},
        ],
        scenes=[
            _scene("flash_hook", "强钩子", "快速抛出优惠", 3, ["offer"], "快节奏社媒广告开场，大字突出 {{offer}}，高对比色彩。"),
            _scene("product", "产品展示", "展示商品或服务", 5, ["product_name", "product_visual"], "动态展示 {{product_name}}，社媒短视频风格，镜头快速切换。"),
            _scene("value", "价值说明", "解释为什么值得立刻行动", 5, ["social_proof", "top_benefit"], "突出 {{top_benefit}} 和 {{social_proof}}，节奏紧凑。"),
            _scene("urgency", "限时紧迫感", "强化截止时间", 4, ["deadline"], "倒计时促销画面，强调截止时间：{{deadline}}。"),
            _scene("cta", "转化收口", "引导点击或购买", 3, ["cta"], "结尾强 CTA：{{cta}}，按钮感设计，适合社媒广告。"),
        ],
        visual_style={"aspect_ratio": "9:16", "pace": "very fast", "tone": "energetic social ad", "subtitle": "kinetic captions"},
        prompt_rules=["前 2 秒必须出现优惠点", "字幕短促有冲击力", "优先高饱和视觉和动态转场"],
        quality_rules=["不要虚构优惠条件", "截止时间必须和用户输入一致", "不要超过 5 个主要信息点"],
    ),
    "t-04": _mode(
        mode_id="corporate_deck_replace",
        name="企业介绍替换模式",
        project_type="template_replace",
        best_for=["企业宣传", "招商介绍", "B2B 服务介绍", "年度概览"],
        replacement_scope="替换公司名称、业务领域、核心能力、数据背书和合作 CTA，保留稳重商务叙事。",
        required_inputs=[
            {"key": "company_name", "label": "公司名称"},
            {"key": "business_scope", "label": "业务范围"},
            {"key": "proof_points", "label": "数据或案例背书"},
            {"key": "cta", "label": "合作引导"},
        ],
        slots=[
            {"key": "company_name", "type": "text", "description": "企业名称"},
            {"key": "mission", "type": "text", "description": "一句话定位"},
            {"key": "capability_1", "type": "text", "description": "核心能力一"},
            {"key": "capability_2", "type": "text", "description": "核心能力二"},
            {"key": "proof", "type": "text", "description": "可信背书"},
        ],
        scenes=[
            _scene("brand_open", "品牌开场", "建立企业专业感", 5, ["company_name", "mission"], "企业宣传片开场，展示 {{company_name}}，定位为 {{mission}}，稳重高级商务风。"),
            _scene("scope", "业务范围", "说明服务对象和领域", 6, ["business_scope"], "展示企业业务范围：{{business_scope}}，现代办公和行业场景。"),
            _scene("capabilities", "能力展示", "展示核心能力", 8, ["capability_1", "capability_2"], "用商务信息图展示能力：{{capability_1}}、{{capability_2}}。"),
            _scene("proof", "数据背书", "增强可信度", 6, ["proof"], "商务数据可视化画面，突出背书：{{proof}}，避免夸张。"),
            _scene("cta", "合作引导", "引导咨询合作", 4, ["cta"], "企业宣传片结尾，展示合作 CTA：{{cta}}，专业可信。"),
        ],
        visual_style={"aspect_ratio": "16:9", "pace": "medium slow", "tone": "corporate premium", "subtitle": "minimal lower third"},
        prompt_rules=["保持正式、克制、可信", "优先信息图和商务场景", "不要使用娱乐化动效"],
        quality_rules=["数据必须来自用户输入", "避免绝对化宣传词", "适合横屏和官网展示"],
    ),
    "t-05": _mode(
        mode_id="creator_intro_replace",
        name="频道片头替换模式",
        project_type="template_replace",
        best_for=["YouTube 片头", "播客片头", "栏目包装", "创作者品牌开场"],
        replacement_scope="替换频道名、栏目口号、头像/logo 和主题关键词，保留短片头包装节奏。",
        required_inputs=[
            {"key": "channel_name", "label": "频道或栏目名"},
            {"key": "tagline", "label": "频道口号"},
            {"key": "brand_visual", "label": "头像或 Logo"},
        ],
        slots=[
            {"key": "channel_name", "type": "text", "description": "频道名称"},
            {"key": "tagline", "type": "text", "description": "栏目口号"},
            {"key": "brand_visual", "type": "media", "description": "头像或 Logo"},
            {"key": "topic_keywords", "type": "text", "description": "内容关键词"},
        ],
        scenes=[
            _scene("logo_reveal", "Logo 亮相", "建立频道识别", 3, ["brand_visual"], "创作者频道片头，Logo 或头像 {{brand_visual}} 动态亮相。"),
            _scene("name", "频道名", "展示频道名称", 3, ["channel_name"], "大字展示频道名 {{channel_name}}，动效干净有冲击力。"),
            _scene("keywords", "内容关键词", "说明频道内容方向", 4, ["topic_keywords"], "快速闪现频道关键词：{{topic_keywords}}，适合 YouTube 片头。"),
            _scene("tagline", "口号收尾", "强化记忆点", 3, ["tagline"], "结尾展示口号 {{tagline}}，音乐节奏感强。"),
        ],
        visual_style={"aspect_ratio": "16:9", "pace": "fast", "tone": "creator branding", "subtitle": "none or minimal"},
        prompt_rules=["总时长保持短", "重点是品牌识别而非完整叙事", "适合反复复用"],
        quality_rules=["频道名必须清晰居中", "不要生成冗长旁白", "Logo 不要被复杂背景遮挡"],
    ),
    "t-06": _mode(
        mode_id="news_report_replace",
        name="新闻播报替换模式",
        project_type="template_replace",
        best_for=["新闻摘要", "行业快讯", "财经资讯", "事件播报"],
        replacement_scope="替换新闻标题、事实要点、地点/时间、背景资料和总结，不替换成娱乐化表达。",
        required_inputs=[
            {"key": "headline", "label": "新闻标题"},
            {"key": "facts", "label": "3-5 条事实要点"},
            {"key": "location_time", "label": "地点和时间"},
        ],
        slots=[
            {"key": "headline", "type": "text", "description": "新闻标题"},
            {"key": "fact_1", "type": "text", "description": "事实一"},
            {"key": "fact_2", "type": "text", "description": "事实二"},
            {"key": "fact_3", "type": "text", "description": "事实三"},
            {"key": "summary", "type": "text", "description": "总结"},
        ],
        scenes=[
            _scene("headline", "头条", "明确新闻主题", 4, ["headline", "location_time"], "新闻播报开场，标题 {{headline}}，地点时间 {{location_time}}，演播室或新闻图文风。"),
            _scene("context", "背景", "交代事件背景", 6, ["context"], "新闻背景画面，客观呈现 {{context}}，避免戏剧化。"),
            _scene("facts", "事实要点", "按顺序陈述事实", 10, ["fact_1", "fact_2", "fact_3"], "新闻信息图，按顺序展示事实：{{fact_1}}、{{fact_2}}、{{fact_3}}。"),
            _scene("impact", "影响", "说明影响或后续", 6, ["impact"], "展示事件影响：{{impact}}，保持中立客观。"),
            _scene("summary", "总结", "收束报道", 4, ["summary"], "新闻播报结尾，总结 {{summary}}，正式可信。"),
        ],
        visual_style={"aspect_ratio": "16:9", "pace": "medium", "tone": "neutral news", "subtitle": "news lower third"},
        prompt_rules=["只基于用户提供事实", "保持中立、不煽动", "用新闻图文和演播室视觉"],
        quality_rules=["禁止编造事实、数据和来源", "事实顺序不可打乱", "敏感事件避免夸张镜头"],
    ),
    "t-07": _mode(
        mode_id="recipe_replace",
        name="食谱步骤替换模式",
        project_type="template_replace",
        best_for=["美食制作", "菜谱教程", "餐饮营销", "厨房技巧"],
        replacement_scope="替换菜名、食材、步骤、成品图和小贴士，保留美食教程节奏。",
        required_inputs=[
            {"key": "recipe_name", "label": "菜名"},
            {"key": "ingredients", "label": "食材清单"},
            {"key": "steps", "label": "制作步骤"},
            {"key": "final_dish_visual", "label": "成品图"},
        ],
        slots=[
            {"key": "recipe_name", "type": "text", "description": "菜名"},
            {"key": "ingredients", "type": "text", "description": "食材"},
            {"key": "step_1", "type": "text", "description": "步骤一"},
            {"key": "step_2", "type": "text", "description": "步骤二"},
            {"key": "tip", "type": "text", "description": "烹饪技巧"},
        ],
        scenes=[
            _scene("dish_open", "成品诱惑", "先展示成品吸引食欲", 4, ["recipe_name", "final_dish_visual"], "美食视频开场，展示 {{recipe_name}} 成品，食物特写，诱人光泽。"),
            _scene("ingredients", "食材准备", "展示食材清单", 5, ["ingredients"], "厨房台面俯拍，整齐展示食材：{{ingredients}}。"),
            _scene("cook_1", "制作步骤一", "演示第一步", 6, ["step_1"], "美食制作过程，步骤一：{{step_1}}，手部操作清晰。"),
            _scene("cook_2", "制作步骤二", "演示第二步", 6, ["step_2"], "美食制作过程，步骤二：{{step_2}}，蒸汽和细节自然。"),
            _scene("serve", "摆盘收尾", "展示成品和技巧", 5, ["tip", "final_dish_visual"], "成品摆盘特写，提示 {{tip}}，温暖美食风格。"),
        ],
        visual_style={"aspect_ratio": "9:16", "pace": "medium", "tone": "warm appetizing", "subtitle": "recipe step labels"},
        prompt_rules=["突出食物质感", "步骤镜头以手部操作为主", "不要加入无关人物剧情"],
        quality_rules=["食材和步骤不能乱改", "缺成品图时生成同菜品合理画面", "避免夸张功效描述"],
    ),
    "t-08": _mode(
        mode_id="travel_vlog_replace",
        name="旅行 Vlog 替换模式",
        project_type="template_replace",
        best_for=["旅行记录", "目的地种草", "酒店/景点推广", "路线推荐"],
        replacement_scope="替换目的地、路线、亮点、素材和出行建议，保留 Vlog 情绪和镜头结构。",
        required_inputs=[
            {"key": "destination", "label": "目的地"},
            {"key": "highlights", "label": "3 个旅行亮点"},
            {"key": "travel_media", "label": "旅行图片或视频"},
            {"key": "tip", "label": "出行建议"},
        ],
        slots=[
            {"key": "destination", "type": "text", "description": "目的地"},
            {"key": "highlight_1", "type": "text", "description": "亮点一"},
            {"key": "highlight_2", "type": "text", "description": "亮点二"},
            {"key": "highlight_3", "type": "text", "description": "亮点三"},
            {"key": "tip", "type": "text", "description": "旅行建议"},
        ],
        scenes=[
            _scene("arrival", "抵达目的地", "建立旅行期待", 4, ["destination", "travel_media"], "旅行 Vlog 开场，抵达 {{destination}}，自然光，手持真实感。"),
            _scene("highlight_1", "亮点一", "展示第一个景点或体验", 6, ["highlight_1"], "旅行镜头展示亮点：{{highlight_1}}，轻松治愈风格。"),
            _scene("highlight_2", "亮点二", "展示第二个景点或体验", 6, ["highlight_2"], "旅行镜头展示亮点：{{highlight_2}}，自然转场。"),
            _scene("highlight_3", "亮点三", "展示第三个景点或体验", 6, ["highlight_3"], "旅行镜头展示亮点：{{highlight_3}}，保留 Vlog 真实感。"),
            _scene("tip", "路线建议", "给出实用建议", 4, ["tip"], "旅行总结画面，给出建议：{{tip}}，温暖轻松。"),
        ],
        visual_style={"aspect_ratio": "9:16", "pace": "medium", "tone": "cinematic vlog", "subtitle": "small travel captions"},
        prompt_rules=["优先使用真实旅行素材", "镜头情绪轻松自然", "不要把 Vlog 做成硬广"],
        quality_rules=["目的地名称必须准确", "缺素材时用风格一致的目的地画面", "不要虚构不可验证的交通/价格信息"],
    ),
}

TEMPLATE_TITLE_ALIASES: dict[str, str] = {
    "product launch": "t-01",
    "产品亮点": "t-01",
    "品牌故事": "t-04",
    "tutorial walkthrough": "t-02",
    "操作指南": "t-02",
    "知识分享": "t-02",
    "social media promo": "t-03",
    "限时优惠": "t-03",
    "短视频封面": "t-03",
    "热门话题": "t-03",
    "互动投票": "t-03",
    "corporate presentation": "t-04",
    "企业简介": "t-04",
    "年度报告": "t-04",
    "youtube intro": "t-05",
    "搞笑日常": "t-05",
    "news report": "t-06",
    "工具测评": "t-06",
    "recipe video": "t-07",
    "美食制作": "t-07",
    "travel vlog": "t-08",
    "开箱体验": "t-01",
    "健身打卡": "t-08",
}


def get_template_mode(template_id: str, title: str | None = None) -> dict[str, Any] | None:
    mode = TEMPLATE_MODES.get(template_id)
    if mode is None and title:
        normalized = title.strip().lower()
        alias_id = TEMPLATE_TITLE_ALIASES.get(normalized) or TEMPLATE_TITLE_ALIASES.get(title.strip())
        if alias_id:
            mode = TEMPLATE_MODES.get(alias_id)
    return deepcopy(mode) if mode else None


def _split_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r"[\n,，;；]+", text) if part.strip()]


def _render_template(text: str, values: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        value = values.get(key)
        if isinstance(value, list):
            return "、".join(str(item) for item in value if str(item).strip())
        if value is None or str(value).strip() == "":
            return f"[{key}]"
        return str(value).strip()

    return re.sub(r"\{\{\s*([\w_]+)\s*\}\}", replace, text)


def normalize_template_slot_values(
    mode: dict[str, Any],
    *,
    slot_values: dict[str, Any] | None,
    title: str,
    script: str | None,
    product_name: str | None = None,
    selling_points: list[str] | None = None,
    target_market: str | None = None,
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    values.update(slot_values or {})
    values.setdefault("project_title", title)
    values.setdefault("product_name", product_name or values.get("product_name") or title)
    values.setdefault("company_name", values.get("company_name") or title)
    values.setdefault("channel_name", values.get("channel_name") or title)
    values.setdefault("tutorial_topic", values.get("tutorial_topic") or title)
    values.setdefault("recipe_name", values.get("recipe_name") or title)
    values.setdefault("destination", values.get("destination") or title)
    values.setdefault("headline", values.get("headline") or title)
    values.setdefault("target_market", target_market or values.get("target_market") or "")
    values.setdefault("user_script", script or "")

    points = selling_points or _split_values(values.get("top_benefits")) or _split_values(values.get("benefits"))
    steps = _split_values(values.get("steps"))
    facts = _split_values(values.get("facts"))
    highlights = _split_values(values.get("highlights"))
    ingredients = _split_values(values.get("ingredients"))
    keywords = _split_values(values.get("topic_keywords"))

    for index, item in enumerate(points[:5], start=1):
        values.setdefault(f"benefit_{index}", item)
        values.setdefault(f"capability_{index}", item)
    for index, item in enumerate(steps[:5], start=1):
        values.setdefault(f"step_{index}", item)
    for index, item in enumerate(facts[:5], start=1):
        values.setdefault(f"fact_{index}", item)
    for index, item in enumerate(highlights[:5], start=1):
        values.setdefault(f"highlight_{index}", item)

    if points:
        values.setdefault("top_benefit", points[0])
        values.setdefault("top_benefits", points)
    if ingredients:
        values["ingredients"] = ingredients
    if keywords:
        values["topic_keywords"] = keywords
    values.setdefault("hook", values.get("offer") or values.get("headline") or values.get("product_name") or title)
    values.setdefault("cta", values.get("cta") or "立即了解更多")
    values.setdefault("proof", values.get("proof") or values.get("social_proof") or "真实使用场景与用户反馈")
    values.setdefault("target_pain", values.get("target_pain") or "用户当前遇到的关键问题")
    values.setdefault("tip", values.get("tip") or "保存收藏，按步骤操作")
    values.setdefault("summary", values.get("summary") or script or title)
    values.setdefault("context", values.get("context") or script or title)
    values.setdefault("impact", values.get("impact") or values.get("summary") or script or title)
    values.setdefault("mission", values.get("mission") or values.get("business_scope") or title)
    values.setdefault("tagline", values.get("tagline") or values.get("cta") or title)

    for slot in mode.get("slots") or []:
        key = slot.get("key")
        if key and key not in values:
            values[key] = ""
    return values


def build_template_scenes(
    mode: dict[str, Any],
    values: dict[str, Any],
    *,
    fallback_script: str | None = None,
) -> list[dict[str, Any]]:
    visual_style = mode.get("visual_style") or {}
    prompt_rules = "；".join(mode.get("prompt_rules") or [])
    quality_rules = "；".join(mode.get("quality_rules") or [])
    scenes: list[dict[str, Any]] = []

    for index, scene in enumerate(mode.get("scenes") or []):
        prompt = _render_template(str(scene.get("prompt_template") or ""), values)
        slot_summary = []
        for key in scene.get("slots") or []:
            value = values.get(key)
            if isinstance(value, list):
                value = "、".join(str(item) for item in value if str(item).strip())
            if value:
                slot_summary.append(f"{key}: {value}")

        style_suffix = (
            f" Visual style: {visual_style}. "
            f"Prompt rules: {prompt_rules}. Quality rules: {quality_rules}."
        )
        scenes.append(
            {
                "title": scene.get("name") or f"Scene {index + 1}",
                "script": "\n".join(
                    part
                    for part in [
                        str(scene.get("goal") or "").strip(),
                        "；".join(slot_summary),
                        fallback_script or "",
                    ]
                    if part
                ),
                "scene_goal": scene.get("goal"),
                "selling_point": slot_summary[0][:1024] if slot_summary else None,
                "duration": scene.get("duration"),
                "video_prompt": (prompt + style_suffix).strip(),
            }
        )
    return scenes
