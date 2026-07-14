"""
Точка входа FastAPI.

Этап 1: health-эндпоинты (проверка связи с БД и MinIO).
Этап 2: подключены роутеры /folders (дерево папок произвольной глубины)
и /templates (загрузка шаблонов и генерация).
Этап 3: раздача HTML-интерфейса на корневом пути `/`.
Этап 6: авторизация — JWT с ролями (app/auth.py) вместо прежнего общего
Basic Auth. Проверка прав теперь не общим middleware на весь сервис, а
через Depends(require_role(...)) на каждом роуте отдельно (см. app/roles.py
и правки в routers_contragents.py/routers_templates.py) — у разных
эндпоинтов разные допустимые роли, общий "открыт/закрыт" такому больше
не соответствует.

Схема БД версионируется через Alembic (backend/alembic/) — на старте
приложение больше НЕ вызывает create_all(). Раньше вызывало, и это стало
причиной реального инцидента: при рестарте контейнера create_all() тихо
создал таблицы contragents/contragent_nicknames по свежим models.py ещё
ДО ручного запуска `alembic upgrade head`, из-за чего миграция упала на
"relation already exists". Накатывать схему теперь только командой
`docker compose exec api alembic upgrade head`.
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.auth import ensure_bootstrap_admin
from app.db import SessionLocal, check_db_connection
from app.routers_auth import audit_router, auth_router, users_router
from app.routers_contragents import contragents_router
from app.routers_tags import tags_router
from app.routers_templates import folders_router, templates_router
from app.storage import download_test_file, ensure_bucket_exists, upload_test_file

app = FastAPI(title="Contract Platform API")

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(audit_router)
app.include_router(folders_router)
app.include_router(templates_router)
app.include_router(contragents_router)
app.include_router(tags_router)

# статика лежит рядом с пакетом app: backend/static/index.html
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Интерфейс оператора. Открывается на http://<сервер>:8000/"""
    return FileResponse(STATIC_DIR / "index.html")


@app.on_event("startup")
def on_startup() -> None:
    ensure_bucket_exists()

    # Создаёт первого Admin из .env, если в users ещё вообще никого нет
    # (см. app/auth.py: ensure_bootstrap_admin) — иначе некому было бы
    # создать первого Admin через POST /users, который сам требует роль Admin.
    session = SessionLocal()
    try:
        ensure_bootstrap_admin(session)
    finally:
        session.close()


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
