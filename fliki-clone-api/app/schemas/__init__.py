from datetime import datetime
from typing import Any, Optional, List
from pydantic import BaseModel, EmailStr


# ── Auth ──────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str = ""


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── User / Me ─────────────────────────────────────────
class CreditsInfo(BaseModel):
    used: int
    total: int
    unit: str = "minutes"


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    plan: str
    credits: CreditsInfo
    youtube_channel_ids: List[str] = []

    class Config:
        from_attributes = True


class UpdateMeRequest(BaseModel):
    name: Optional[str] = None
    youtube_channel_ids: Optional[List[str]] = None


class UpdatePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class UpdateNotificationsRequest(BaseModel):
    email_notifications: bool


# ── File ──────────────────────────────────────────────
class FileOut(BaseModel):
    id: str
    title: str
    thumbnail_url: Optional[str] = None
    preview_url: Optional[str] = None
    duration: Optional[str] = None
    status: str
    updated_at: datetime
    scene_count: int
    type: str
    template_id: Optional[str] = None
    project_type: str = "story_video"
    product_name: Optional[str] = None
    target_market: Optional[str] = None
    selling_points: List[str] = []
    brand_terms: Optional[str] = None
    avoid_terms: Optional[str] = None
    aspect_ratio: str = "16:9"
    copyright_confirmed: bool = False

    class Config:
        from_attributes = True


class FileListResponse(BaseModel):
    items: List[FileOut]
    total: int
    next_cursor: Optional[str] = None


class CreateFileRequest(BaseModel):
    title: str
    script: Optional[str] = None
    template_id: Optional[str] = None
    template_slot_values: dict[str, Any] = {}
    voice_id: Optional[str] = None
    language: str = "English"
    folder_id: Optional[str] = None
    scene_duration: Optional[float] = None  # 每个场景的目标时长（秒），由 aiDuration/段落数 计算
    project_type: str = "story_video"
    product_name: Optional[str] = None
    target_market: Optional[str] = None
    selling_points: List[str] = []
    brand_terms: Optional[str] = None
    avoid_terms: Optional[str] = None
    aspect_ratio: str = "16:9"
    asset_ids: List[str] = []
    copyright_confirmed: bool = False


class PatchFileRequest(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
    folder_id: Optional[str] = None
    product_name: Optional[str] = None
    target_market: Optional[str] = None
    selling_points: Optional[List[str]] = None
    brand_terms: Optional[str] = None
    avoid_terms: Optional[str] = None
    aspect_ratio: Optional[str] = None
    copyright_confirmed: Optional[bool] = None


# ── Folder ────────────────────────────────────────────
class FolderOut(BaseModel):
    id: str
    name: str
    created_at: datetime

    class Config:
        from_attributes = True


class CreateFolderRequest(BaseModel):
    name: str
    parent_id: Optional[str] = None


class PatchFolderRequest(BaseModel):
    name: str


# ── Scene ─────────────────────────────────────────────
class SceneOut(BaseModel):
    id: str
    file_id: str
    order_index: int
    title: Optional[str] = None
    script: Optional[str] = None
    voice_id: Optional[str] = None
    media_url: Optional[str] = None
    media_type: Optional[str] = None
    character_id: Optional[str] = None
    scene_goal: Optional[str] = None
    selling_point: Optional[str] = None
    asset_id: Optional[str] = None
    duration: Optional[float] = None
    # 视频生成相关
    video_prompt: Optional[str] = None    # LLM 转换后的视觉提示词
    video_url: Optional[str] = None       # 该分镜对应的视频片段 URL
    video_status: Optional[str] = None    # pending|generating|done|error

    class Config:
        from_attributes = True


class CreateSceneRequest(BaseModel):
    title: Optional[str] = None
    script: Optional[str] = None
    voice_id: Optional[str] = None
    scene_goal: Optional[str] = None
    selling_point: Optional[str] = None
    asset_id: Optional[str] = None


class PatchSceneRequest(BaseModel):
    title: Optional[str] = None
    script: Optional[str] = None
    voice_id: Optional[str] = None
    media_url: Optional[str] = None
    media_type: Optional[str] = None
    character_id: Optional[str] = None
    scene_goal: Optional[str] = None
    selling_point: Optional[str] = None
    asset_id: Optional[str] = None
    order_index: Optional[int] = None
    duration: Optional[float] = None
    video_prompt: Optional[str] = None  # 用户可编辑的视觉提示词（单镜重生成前保存）


class RegenerateSceneVideoRequest(BaseModel):
    """单镜重生成：可选覆盖提示词，或仅根据 script 用 LLM 刷新提示词。"""

    video_prompt: Optional[str] = None
    refresh_prompt_from_script: bool = False
    prevent_style_drift: bool = True
    default_scene_duration: float = 5.0


class ReorderSceneRequest(BaseModel):
    new_index: int


# ── Generate ──────────────────────────────────────────
class GenerateRequest(BaseModel):
    duration: int = 5                    # 与 default_scene_duration 同为 5 时作为 per-scene 默认（秒）
    scenes_per_batch: int = 3            # 兼容保留；可灵/硅基均为逐镜生成
    # False：分镜可并行生成，总耗时更短；True：镜头间风格延续（可灵 I2V），更慢（默认开，产品更连贯）
    prevent_style_drift: bool = True
    default_scene_duration: float = 5.0  # 分镜未写 duration 时每镜目标时长（秒）；项目页与 duration 同传


class GenerateResponse(BaseModel):
    job_id: str
    estimated_seconds: int = 30


class GenerateStatusResponse(BaseModel):
    status: str
    progress: int = 0
    job_id: Optional[str] = None
    preview_url: Optional[str] = None
    error: Optional[str] = None


# ── Export ────────────────────────────────────────────
class ExportRequest(BaseModel):
    format: str = "mp4"  # mp4|mp3|mov


class ExportJobOut(BaseModel):
    id: str
    file_id: str
    title: str = ""
    format: str
    status: str
    file_url: Optional[str] = None
    file_size: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ── Template ──────────────────────────────────────────
class TemplateOut(BaseModel):
    id: str
    title: str
    category: str
    thumbnail_url: Optional[str] = None
    preview_url: Optional[str] = None
    duration: Optional[str] = None
    lang: str
    uses_count: int
    is_premium: bool
    config_json: Optional[dict[str, Any]] = None

    class Config:
        from_attributes = True


# ── Voice ─────────────────────────────────────────────
class VoiceOut(BaseModel):
    id: str
    name: str
    lang: str
    accent: Optional[str] = None
    style: Optional[str] = None
    gender: Optional[str] = None
    tags: List[str] = []
    preview_url: Optional[str] = None
    is_premium: bool

    class Config:
        from_attributes = True


class VoiceCloneOut(BaseModel):
    id: str
    name: str
    status: str
    audio_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class CreateVoiceCustomRequest(BaseModel):
    prompt: str
    name: str


class VoiceCustomOut(BaseModel):
    id: str
    name: str
    prompt: str
    status: str
    preview_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ── Character ─────────────────────────────────────────
class CharacterOut(BaseModel):
    id: str
    name: str
    style: Optional[str] = None
    image_url: Optional[str] = None
    is_default: bool

    class Config:
        from_attributes = True


class CreateCharacterRequest(BaseModel):
    name: str
    style: Optional[str] = None
    prompt: Optional[str] = None


# ── Asset ─────────────────────────────────────────────
class AssetOut(BaseModel):
    id: str
    type: str
    name: str
    url: str
    thumbnail_url: Optional[str] = None
    duration: Optional[str] = None
    is_stock: bool
    project_id: Optional[str] = None
    asset_role: Optional[str] = None
    sort_order: int = 0

    class Config:
        from_attributes = True


# ── Brand Kit ─────────────────────────────────────────
class BrandKitOut(BaseModel):
    id: str
    name: str
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    font: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class CreateBrandKitRequest(BaseModel):
    name: str
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    font: Optional[str] = None


class PatchBrandKitRequest(BaseModel):
    name: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    font: Optional[str] = None


# ── Team ──────────────────────────────────────────────
class TeamMemberOut(BaseModel):
    id: str
    email: str
    role: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: str = "editor"


class PatchMemberRequest(BaseModel):
    role: str


# ── Billing ───────────────────────────────────────────
class BillingPlanOut(BaseModel):
    plan: str
    status: str
    credits_used: int
    credits_total: int
    current_period_end: Optional[datetime] = None
    stripe_customer_id: Optional[str] = None


class CheckoutRequest(BaseModel):
    plan: str  # standard|premium
    # success_url / cancel_url 可选；前端不传时 router 用 settings.frontend_url + /app/billing 兜底，
    # 让前端调用方更省事（Track-11）。
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


class CheckoutResponse(BaseModel):
    checkout_url: str


class PortalResponse(BaseModel):
    portal_url: str


# ── Rewards & Referrals ───────────────────────────────
class RewardTaskOut(BaseModel):
    id: str
    task_type: str
    status: str
    credits_awarded: int
    submitted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SubmitRewardRequest(BaseModel):
    task_type: str
    screenshot_url: Optional[str] = None


class ReferralStatsOut(BaseModel):
    total_referred: int
    credits_earned: int
    referral_link: str


# ── Playground ────────────────────────────────────────
class PlaygroundImageRequest(BaseModel):
    prompt: str
    model: str = "z-turbo"
    ratio: str = "16:9"
    style: Optional[str] = None


class PlaygroundGenOut(BaseModel):
    id: str
    prompt: str
    model: str
    ratio: str
    style: Optional[str] = None
    result_url: Optional[str] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── AI ────────────────────────────────────────────────
class AIScriptRequest(BaseModel):
    topic: str
    duration: Optional[int] = 60  # seconds
    tone: Optional[str] = "professional"
    language: str = "English"


class AIScriptResponse(BaseModel):
    script: str


class AIRewriteRequest(BaseModel):
    text: str
    instruction: Optional[str] = "Make it more engaging"


class AIRewriteResponse(BaseModel):
    result: str


class AITranslateRequest(BaseModel):
    text: str
    target_language: str


class AITranslateResponse(BaseModel):
    result: str


# ── Generic ───────────────────────────────────────────
class MessageResponse(BaseModel):
    message: str
