"""
Точка входа FastAPI.

Этап 1: health-эндпоинты (проверка связи с БД и MinIO).
Этап 2: подключён роутер /templates (загрузка шаблонов и генерация),
на старте создаются таблицы БД.
"""
from fastapi import FastAPI, HTTPException

from app.db import check_db_connection, init_db
from app.routers_templates import router as templates_router
from app.storage import download_test_file, ensure_bucket_exists, upload_test_file

app = FastAPI(title="Contract Platform API")

app.include_router(templates_router)


@app.on_event("startup")
def on_startup() -> None:
    ensure_bucket_exists()
    init_db()  # создаёт таблицы templates и template_fields, если их ещё нет


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/health/db")
def health_db() -> dict:
    try:
        check_db_connection()
    except Exception as exc:
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
