"""
Клиент для MinIO.

MinIO S3-совместим, поэтому используем обычный boto3 (стандартный
S3-клиент из мира AWS) и просто указываем ему свой endpoint_url —
никакой отдельной библиотеки под MinIO не нужно. Это же значит,
что если однажды понадобится переехать на настоящий AWS S3 —
меняется только endpoint_url и креды, весь остальной код останется рабочим.
"""
import boto3
from botocore.client import Config

from app.config import settings

s3_client = boto3.client(
    "s3",
    endpoint_url=f"http://{settings.minio_endpoint}",
    aws_access_key_id=settings.minio_root_user,
    aws_secret_access_key=settings.minio_root_password,
    config=Config(signature_version="s3v4"),
    region_name="us-east-1",  # MinIO регион игнорирует, но boto3 требует непустое значение
)


def ensure_bucket_exists() -> None:
    """Создаёт бакет при первом запуске приложения, если его ещё нет."""
    existing = [b["Name"] for b in s3_client.list_buckets().get("Buckets", [])]
    if settings.minio_bucket not in existing:
        s3_client.create_bucket(Bucket=settings.minio_bucket)


def upload_test_file(key: str, content: bytes) -> None:
    s3_client.put_object(Bucket=settings.minio_bucket, Key=key, Body=content)


def download_test_file(key: str) -> bytes:
    obj = s3_client.get_object(Bucket=settings.minio_bucket, Key=key)
    return obj["Body"].read()
