"""
Точка входа FastAPI.

Задача этапа 1 — доказать, что три компонента системы (API, PostgreSQL,
MinIO) реально связаны друг с другом, а не просто одновременно запущены.
Для этого три эндпоинта:

  GET /health          — жив ли сам процесс API
  GET /health/db        — доходит ли API до PostgreSQL
  GET /health/storage    — доходит ли API до MinIO: кладём тестовый файл
                          и тут же читаем его обратно (тот самый "файл
                          руками кладётся в MinIO и читается обратно"
                          из критерия готовности этапа)
"""
from fastapi import FastAPI, HTTPException

from app.db import check_db_connection
from app.storage import download_test_file, ensure_bucket_exists, upload_test_file

app = FastAPI(title="Contract Platform API")


@app.on_event("startup")
def on_startup() -> None:
    # Бакет в MinIO должен существовать до первого запроса на загрузку файла —
    # создаём его один раз при старте приложения, а не при каждом обращении
    ensure_bucket_exists()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/health/db")
def health_db() -> dict:
    try:
        check_db_connection()
    except Exception as exc:
        # 503 Service Unavailable — правильный код для "зависимость недоступна",
        # в отличие от 500, который обычно означает баг в самом коде
        raise HTTPException(status_code=503, detail=f"db unavailable: {exc}") from exc
    return {"status": "ok"}


@app.get("/health/storage")
def health_storage() -> dict:
    test_key = "healthcheck/ping.txt"
    try:
        upload_test_file(test_key, b"ping")
        content = download_test_file(test_key)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"storage unavailable: {exc}") from exc
    return {"status": "ok", "roundtrip": content.decode()}
