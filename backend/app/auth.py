"""
JWT-авторизация с ролями (этап 6) — заменяет прежний общий Basic Auth
(один список логин/пароль без различия прав, см. git-историю файла).

Схема:
  - пароли хранятся только как argon2-хэш (passlib), не в открытом виде;
  - access-токен — короткоживущий (settings.jwt_access_ttl_minutes),
    в нём зашита роль (claim "role") — не нужно лезть в БД на каждый
    запрос, чтобы узнать права пользователя;
  - refresh-токен — долгоживущий (settings.jwt_refresh_ttl_days), хранится
    в БД как хэш (см. models.RefreshToken) — это позволяет реально отозвать
    сессию (logout, деактивация пользователя), а не просто «ждать, пока
    сам истечёт»;
  - Depends(get_current_user) — кто угодно залогиненный;
    Depends(require_role(*roles)) — только перечисленные роли (см. app/roles.py).

Middleware намеренно НЕТ (в отличие от прежнего BasicAuthMiddleware) —
у /auth/login и /health не должно быть проверки токена, а у остальных
роутов права разные (Admin/Director/Manager), поэтому проверка вешается
явно через Depends на каждый роут — это чуть более многословно, зато
видно прямо в сигнатуре функции, кому она доступна, без необходимости
лезть в отдельный список "публичных путей".
"""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.models import RefreshToken, User

_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

_bearer_scheme = HTTPBearer(auto_error=False)

ALGORITHM = "HS256"


# ---------------------------------------------------------------------
# Пароли
# ---------------------------------------------------------------------

def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd_context.verify(password, password_hash)


# ---------------------------------------------------------------------
# JWT access-токен
# ---------------------------------------------------------------------

def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "username": user.username,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Токен истёк, требуется /auth/refresh")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Недействительный токен")


# ---------------------------------------------------------------------
# Refresh-токен — непрозрачная случайная строка, не JWT. В БД хранится
# только sha256-хэш (см. models.RefreshToken) — сам токен нигде не
# восстановить из базы, как и с паролем.
# ---------------------------------------------------------------------

def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def issue_refresh_token(db: Session, user: User) -> str:
    raw_token = uuid.uuid4().hex + uuid.uuid4().hex  # 64 случайных hex-символа
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=_hash_token(raw_token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_ttl_days),
        )
    )
    db.commit()
    return raw_token


def consume_refresh_token(db: Session, raw_token: str) -> RefreshToken:
    """
    Проверяет refresh-токен (существует, не отозван, не истёк) и сразу
    отзывает его (revoked_at) — ротация при каждом /auth/refresh: если
    один и тот же refresh-токен вдруг "выстрелит" второй раз (например,
    его украли и используют параллельно с легитимным клиентом), это будет
    видно по попытке применить уже отозванный токен, а не тихо продолжит
    работать вечно на одном и том же значении.
    """
    token_hash = _hash_token(raw_token)
    record = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    if record is None or record.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Refresh-токен недействителен, войдите заново")

    now = datetime.now(timezone.utc)
    if record.expires_at.replace(tzinfo=timezone.utc) < now:
        raise HTTPException(status_code=401, detail="Refresh-токен истёк, войдите заново")

    record.revoked_at = now
    db.commit()
    return record


def revoke_all_user_tokens(db: Session, user_id: uuid.UUID) -> None:
    """Отзывает все refresh-токены пользователя — logout со всех устройств
    сразу, и то, что дергаем при деактивации пользователя (PATCH /users/{id})."""
    now = datetime.now(timezone.utc)
    (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .update({"revoked_at": now})
    )
    db.commit()


# ---------------------------------------------------------------------
# FastAPI-зависимости
# ---------------------------------------------------------------------

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(_bearer_scheme),
    db: Session = Depends(get_session),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Не авторизован")

    payload = decode_token(credentials.credentials)
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Ожидался access-токен")

    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Пользователь не найден или деактивирован")

    _touch_last_seen(db, user)
    return user


# Как часто обновляем last_seen_at: чаще писать в БД на каждый запрос
# незачем — статус "в сети" считается с порогом 5 минут, точность до минуты
# избыточна. 60с — компромисс между свежестью и нагрузкой на запись.
_LAST_SEEN_THROTTLE_SECONDS = 60


def _touch_last_seen(db: Session, user: User) -> None:
    """
    Обновляет user.last_seen_at (не чаще раза в минуту). Best-effort: если
    запись не удалась, глотаем ошибку и откатываем — статус "в сети" не
    настолько важен, чтобы из-за него падал реальный запрос пользователя
    (тот же принцип, что и у audit_log).
    """
    now = datetime.now(timezone.utc)
    last = user.last_seen_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if last is not None and (now - last).total_seconds() < _LAST_SEEN_THROTTLE_SECONDS:
        return
    try:
        user.last_seen_at = now
        db.commit()
    except Exception:
        db.rollback()


def require_role(*allowed_roles: str):
    """
    Depends(require_role(ADMIN, DIRECTOR)) — доступ только перечисленным
    ролям. Роль проверяется по значению из JWT-claim текущего пользователя
    (get_current_user уже дополнительно проверил, что пользователь активен
    прямо сейчас, а не просто когда-то получил токен).
    """
    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            # Ответ НЕ перечисляет допустимые роли (раньше перечислял:
            # "Требуется роль: admin, director, ..."). Состав ролей — не то,
            # что стоит показывать пользователю: человеку это ничем не
            # поможет (роль себе он всё равно не выдаст), а постороннему
            # выдаёт карту прав целиком, по одному запросу к любому
            # закрытому эндпоинту. Кому именно доступно действие — знает
            # администратор, а не сообщение об ошибке.
            raise HTTPException(
                status_code=403,
                detail="Недостаточно прав для этого действия",
            )
        return user

    return _check


def ensure_bootstrap_admin(db: Session) -> None:
    """
    Создаёт первого Admin из .env (BOOTSTRAP_ADMIN_USERNAME/PASSWORD), если в
    таблице users ещё нет ни одного пользователя. Вызывается один раз на
    старте приложения (см. main.py: on_startup).

    Без этого механизма первого Admin некому было бы создать: POST /users
    сам требует роль Admin — классическая проблема курицы и яйца при
    переходе с общего Basic Auth на персональные аккаунты с ролями.

    Если BOOTSTRAP_ADMIN_* не заданы в .env — просто ничего не делает
    (не мешает серверу, где пользователи уже заведены руками).
    """
    if not settings.bootstrap_admin_username or not settings.bootstrap_admin_password:
        return
    if db.query(User).first() is not None:
        return  # хотя бы один пользователь уже есть — bootstrap не нужен

    from app.roles import ADMIN  # локальный импорт: избегаем цикла auth<->roles

    db.add(
        User(
            username=settings.bootstrap_admin_username,
            password_hash=hash_password(settings.bootstrap_admin_password),
            full_name="Администратор",
            role=ADMIN,
        )
    )
    db.commit()
