import boto3
from botocore.config import Config
from app.core.config import settings

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=settings.STORAGE_ENDPOINT,
            aws_access_key_id=settings.STORAGE_ACCESS_KEY,
            aws_secret_access_key=settings.STORAGE_SECRET_KEY,
            region_name=settings.STORAGE_REGION,
            config=Config(signature_version="s3v4"),
        )
        for bucket in [settings.STORAGE_BUCKET_SOURCE, settings.STORAGE_BUCKET_OUTPUT]:
            try:
                _client.head_bucket(Bucket=bucket)
            except Exception:
                try:
                    _client.create_bucket(Bucket=bucket)
                except Exception:
                    pass
    return _client


def upload_file(bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream"):
    _get_client().put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)


def download_file(bucket: str, key: str) -> bytes:
    response = _get_client().get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def generate_presigned_url(bucket: str, key: str, expiry: int = 3600) -> str:
    return _get_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expiry,
    )
