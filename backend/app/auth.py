"""
Базовая HTTP Basic Auth защита всего сервиса.

Зачем: сервис хранит и генерирует документы с паспортными данными, ИНН,
банковскими реквизитами — это чувствительные персональные данные. До этого
момента порт был открыт без единой проверки. Полноценные роли/JWT (этап 7)
избыточны для пары человек без разницы в правах — здесь минимальный
барьер: общий список логин/пароль, доступ либо есть, либо нет.

Список пользователей — в .env, формат "логин:пароль,логин2:пароль2"
(AUTH_USERS). Пароли сравниваются через secrets.compare_digest — обычное
"==" на строках уязвимо к timing-атаке (утечка пароля по времени сравнения).
"""
import base64
import secrets

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import settings

# пути, не требующие авторизации: health-checks дергает сам Docker изнутри
# сети контейнеров, наружу они не отдают ничего чувствительного (только
# {"status": "ok"})
PUBLIC_PATHS = {"/health", "/health/db", "/health/storage"}


def _parse_users(raw: str) -> dict[str, str]:
    users = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        login, password = pair.split(":", 1)
        users[login.strip()] = password.strip()
    return users


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        users = _parse_users(settings.auth_users)
        if not users:
            # AUTH_USERS не задан в .env — не блокируем (иначе сервис
            # перестанет работать без явной настройки после деплоя)
            return await call_next(request)

        header = request.headers.get("authorization", "")
        if header.startswith("Basic "):
            try:
                decoded = base64.b64decode(header[6:]).decode("utf-8")
                login, _, password = decoded.partition(":")
            except Exception:
                login, password = "", ""

            expected = users.get(login)
            if expected is not None and secrets.compare_digest(password, expected):
                return await call_next(request)

        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Contract Platform"'},
        )
