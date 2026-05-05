from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "Fliki Clone API"
    debug: bool = False
    api_prefix: str = "/api"
    frontend_url: str = "http://localhost:3000"
    # Browser-accessible backend root URL for local static video URLs.
    api_public_base_url: str = "http://localhost:8000"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/fliki"
    database_url_sync: str = "postgresql://postgres:postgres@localhost:5432/fliki"

    # JWT
    jwt_secret: str = "changeme-super-secret"
    jwt_algorithm: str = "HS256"
    jwt_expires_days: int = 7

    # S3 / Cloudflare R2
    s3_bucket: str = "fliki-media"
    s3_region: str = "auto"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_endpoint: str = ""

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_standard: str = ""
    stripe_price_premium: str = ""

    # SiliconFlow
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"

    @field_validator("siliconflow_api_key", mode="before")
    @classmethod
    def normalize_siliconflow_key(cls, v: object) -> object:
        if not isinstance(v, str):
            return v
        s = v.strip()
        if s.lower().startswith("bearer "):
            s = s[7:].strip()
        return s

    # Kling AI video generation
    kling_access_key: str = ""
    kling_secret_key: str = ""
    kling_base_url: str = "https://openapi.klingai.com"
    kling_model: str = "kling-v1-6"
    kling_max_duration: int = 10

    # Scene video generation
    video_scenes_per_batch: int = 3
    llm_model: str = "deepseek-ai/DeepSeek-V3"
    tts_model: str = "FishAudio/fish-speech-1.5"
    # ASR：用于 VoiceAgent v2 字幕对齐（拿真实音频时长 + 可选 segments）
    asr_model: str = "FunAudioLLM/SenseVoiceSmall"
    image_model: str = "black-forest-labs/FLUX.1-schnell"
    video_model: str = "Wan-AI/Wan2.1-T2V-14B"
    siliconflow_wan_num_frames: int = 81
    video_api_poll_interval_sec: float = 2.0
    kling_parallel_max_workers: int = 3
    siliconflow_parallel_max_workers: int = 2

    # Legacy / integrations
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    # OpenAI ASR 模型；用户配了 openai_api_key 时 VoiceAgent 会优先走这个拿 word-level
    openai_asr_model: str = "whisper-1"
    google_client_id: str = ""
    google_client_secret: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""

    # Email
    mail_username: str = ""
    mail_password: str = ""
    mail_from: str = "noreply@yourdomain.com"
    mail_port: int = 587
    mail_server: str = "smtp.gmail.com"
    mail_starttls: bool = True
    mail_ssl_tls: bool = False

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    # 当 worker 在跑时打开，让 pipeline 调度走 Celery；False 时回退到 BackgroundTasks
    # （dev / 单机测试 / 没起 redis 都能继续工作）。
    celery_enabled: bool = False

    # Publishing 凭证 Fernet 对称加密 KEY（Track-01）。
    # url-safe base64 编码的 32-byte key（Fernet.generate_key() 输出格式）；
    # 留空时 credentials.py 会 fallback 到 plain text 写库（向后兼容老库）+ 启动 logger.warning。
    publish_credential_fernet_key: str = ""

    @field_validator("publish_credential_fernet_key", mode="before")
    @classmethod
    def normalize_publish_credential_fernet_key(cls, v: object) -> object:
        if not isinstance(v, str):
            return v
        s = v.strip()
        if not s:
            return ""
        # 校验：base64 解出来必须是 32 字节，不然 Fernet 会在调用时炸；
        # 这里早 fail，避免后端能起来但每次写库都 500。
        try:
            import base64

            raw = base64.urlsafe_b64decode(s.encode("ascii"))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(
                "PUBLISH_CREDENTIAL_FERNET_KEY 必须是 url-safe base64 编码"
            ) from exc
        if len(raw) != 32:
            raise ValueError(
                "PUBLISH_CREDENTIAL_FERNET_KEY 解码后必须是 32 字节 "
                "（用 Fernet.generate_key() 生成）"
            )
        return s

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
