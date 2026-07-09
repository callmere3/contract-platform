"""
Точка входа FastAPI.

Этап 1: health-эндпоинты (проверка связи с БД и MinIO).
Этап 2: подключены роутеры /folders (дерево папок произвольной глубины)
и /templates (загрузка шаблонов и генерация), на старте создаются таблицы БД.
Этап 3: раздача HTML-интерфейса на корневом пути `/`.
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.db import check_db_connection, init_db
from app.routers_templates import folders_router, templates_router
from app.storage import download_test_file, ensure_bucket_exists, upload_test_file

app = FastAPI(title="Contract Platform API")

app.include_router(folders_router)
app.include_router(templates_router)

# статика лежит рядом с пакетом app: backend/static/index.html
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Интерфейс оператора. Открывается на http://<сервер>:8000/"""
    return FileResponse(STATIC_DIR / "index.html")


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
