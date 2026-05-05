from typing import Optional
import os
import boto3
from botocore.config import Config
from app.config import get_settings

settings = get_settings()

_s3_client = None

# 本地静态文件目录（S3 未配置时使用）
_LOCAL_STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "videos")


def _s3_configured() -> bool:
    return bool(settings.s3_access_key and settings.s3_secret_key)


def get_s3_client():
    global _s3_client
    if _s3_client is None:
        kwargs = dict(
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=Config(signature_version="s3v4"),
        )
        if settings.s3_endpoint:
            kwargs["endpoint_url"] = settings.s3_endpoint
        _s3_client = boto3.client("s3", **kwargs)
    return _s3_client


def generate_presigned_upload_url(key: str, content_type: str, expires: int = 300) -> str:
    """Generate a presigned PUT URL for direct browser upload."""
    client = get_s3_client()
    return client.generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.s3_bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=expires,
    )


def generate_presigned_download_url(key: str, expires: int = 3600) -> str:
    """Generate a presigned GET URL for file download."""
    client = get_s3_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=expires,
    )


def upload_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload raw bytes to S3 (or local static dir if S3 not configured) and return the public URL."""
    if not _s3_configured():
        # 本地文件兜底：保存到 static/videos/ 并返回可访问的 URL
        os.makedirs(_LOCAL_STATIC_DIR, exist_ok=True)
        filename = os.path.basename(key)
        local_path = os.path.join(_LOCAL_STATIC_DIR, filename)
        with open(local_path, "wb") as f:
            f.write(data)
        base_url = settings.api_public_base_url.rstrip("/")
        return f"{base_url}/static/videos/{filename}"

    client = get_s3_client()
    client.put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    if settings.s3_endpoint:
        return f"{settings.s3_endpoint}/{settings.s3_bucket}/{key}"
    return f"https://{settings.s3_bucket}.s3.{settings.s3_region}.amazonaws.com/{key}"


def delete_object(key: str) -> None:
    if not _s3_configured():
        return
    client = get_s3_client()
    client.delete_object(Bucket=settings.s3_bucket, Key=key)


def public_url(key: str) -> Optional[str]:
    """Return the public URL for an object (only works if bucket is public)."""
    if not key:
        return None
    if not _s3_configured():
        filename = os.path.basename(key)
        base_url = settings.api_public_base_url.rstrip("/")
        return f"{base_url}/static/videos/{filename}"
    if settings.s3_endpoint:
        return f"{settings.s3_endpoint}/{settings.s3_bucket}/{key}"
    return f"https://{settings.s3_bucket}.s3.{settings.s3_region}.amazonaws.com/{key}"
