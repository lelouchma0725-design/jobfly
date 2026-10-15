"""R2 對象存儲客戶端（S3 兼容）。"""
from __future__ import annotations

import boto3
from botocore.config import Config

from app.config import settings

_client = None


def r2_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )
    return _client


def upload_bytes(key: str, data: bytes, mime: str) -> None:
    r2_client().put_object(
        Bucket=settings.r2_bucket,
        Key=key,
        Body=data,
        ContentType=mime,
    )


def delete_object(key: str) -> None:
    r2_client().delete_object(Bucket=settings.r2_bucket, Key=key)


def object_url(key: str) -> str:
    if settings.r2_public_base_url:
        return f"{settings.r2_public_base_url.rstrip('/')}/{key}"
    return key


def presigned_url(key: str, expires: int = 3600) -> str:
    """私有桶的臨時訪問鏈接（無需公開桶）。"""
    return r2_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.r2_bucket, "Key": key},
        ExpiresIn=expires,
    )
