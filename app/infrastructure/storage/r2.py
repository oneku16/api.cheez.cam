import asyncio
from functools import lru_cache

import boto3
from botocore.client import Config

from app.core.config import get_settings


@lru_cache
def _sync_client():
    settings = get_settings()
    if not settings.r2_access_key_id or not settings.r2_secret_access_key:
        raise RuntimeError("R2 credentials are not configured (R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY).")
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
    )


class StorageService:
    def __init__(self):
        self.settings = get_settings()
        self.client = _sync_client()
        self.bucket = self.settings.r2_bucket_name

    def create_presigned_upload_url(self, object_key: str, expires_in: int = 900) -> str:
        return self.client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": object_key,
            },
            ExpiresIn=expires_in,
            HttpMethod="PUT",
        )

    def create_presigned_read_url(self, object_key: str, expires_in: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": object_key},
            ExpiresIn=expires_in,
        )

    def head_object(self, object_key: str) -> dict:
        return self.client.head_object(Bucket=self.bucket, Key=object_key)

    def download_object(self, object_key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=object_key)
        return response["Body"].read()

    def upload_bytes(self, object_key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=object_key,
            Body=data,
            ContentType=content_type,
        )

    def delete_object(self, object_key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=object_key)

    def delete_objects(self, object_keys: list[str]) -> None:
        keys = list(dict.fromkeys(k for k in object_keys if k))
        if not keys:
            return
        for i in range(0, len(keys), 1000):
            batch = keys[i : i + 1000]
            self.client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
            )

    async def head_object_async(self, object_key: str) -> dict:
        return await asyncio.to_thread(self.head_object, object_key)

    async def create_presigned_upload_url_async(
        self, object_key: str, expires_in: int = 900
    ) -> str:
        return await asyncio.to_thread(
            self.create_presigned_upload_url, object_key, expires_in
        )

    async def create_presigned_read_url_async(
        self, object_key: str, expires_in: int = 3600
    ) -> str:
        return await asyncio.to_thread(self.create_presigned_read_url, object_key, expires_in)
