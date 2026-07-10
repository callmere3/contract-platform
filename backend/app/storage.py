"""
Клиент для MinIO (S3-совместимый через boto3).

Этап 1: healthcheck-функции (upload/download_test_file).
Этап 2: добавлены put_file / get_file для работы с реальными шаблонами
и сгенерированными документами. Ключи (пути внутри бакета) строятся с
префиксами, чтобы файлы лежали организованно:
    templates/<template_id>.docx      — исходные шаблоны
    generated/<document_id>.docx      — сгенерированные документы
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
    region_name="us-east-1",
)


def ensure_bucket_exists() -> None:
    existing = [b["Name"] for b in s3_client.list_buckets().get("Buckets", [])]
    if settings.minio_bucket not in existing:
        s3_client.create_bucket(Bucket=settings.minio_bucket)


def put_file(key: str, content: bytes) -> None:
    """Кладёт файл в MinIO по указанному ключу (пути внутри бакета)."""
    s3_client.put_object(Bucket=settings.minio_bucket, Key=key, Body=content)


def get_file(key: str) -> bytes:
    """Читает файл из MinIO по ключу."""
    obj = s3_client.get_object(Bucket=settings.minio_bucket, Key=key)
    return obj["Body"].read()


def delete_file(key: str) -> None:
    """
    Удаляет файл из MinIO по ключу. Не бросает ошибку, если ключа уже
    нет (delete_object в S3-совместимом API идемпотентен) — так удаление
    шаблона не падает, даже если файл в хранилище уже отсутствовал.
    """
    s3_client.delete_object(Bucket=settings.minio_bucket, Key=key)


# --- healthcheck-функции этапа 1 (оставлены для /health/storage) ---

def upload_test_file(key: str, content: bytes) -> None:
    put_file(key, content)


def download_test_file(key: str) -> bytes:
    return get_file(key)
