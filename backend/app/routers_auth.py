"""
Эндпоинты аутентификации, управления пользователями и просмотра audit_log
(этап 6, брейншторм ролей).

  POST /auth/login       — логин+пароль -> access-токен (30 мин) + refresh-токен (14 дней)
  POST /auth/refresh      — refresh-токен -> новая пара токенов (ротация, см. app/auth.py)
  POST /auth/logout       — отзывает конкретный refresh-токен (выход с этого устройства)

  POST   /users            — создать пользователя (только Admin, формы саморегистрации нет)
  GET    /users            — список пользователей (только Admin)
  PATCH  /users/{id}       — сменить роль/пароль/активность (только Admin)

  GET /audit-log           — журнал действий, самые новые сверху (Admin, Director)

Логин (username) — обычное имя пользователя, не email: компания решила не
привязываться к почтовым адресам (см. запрос пользователя), поэтому здесь
просто уникальная непустая строка без валидации формата.

Управление пользователями и /auth сознательно в одном файле: между ними
общий контекст (кто кого может логинить/создавать), и это два-три
эндпоинта на роль — разносить по отдельным роутерам пока избыточно.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import (
    _hash_token,
    create_access_token,
    consume_refresh_token,
    get_current_user,
    hash_password,
    issue_refresh_token,
    require_role,
    revoke_all_user_tokens,
    verify_password,
)
from app.db import get_session
from app.models import AuditLog, RefreshToken, User
from app.rate_limit import check_login_rate_limit, record_failed_login, record_successful_login
from app.roles import ADMIN, CAN_EXPORT, ROLES

auth_router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])
audit_router = APIRouter(prefix="/audit-log", tags=["audit"])


# =====================================================================
# /auth — вход, обновление токена, выход
# =====================================================================

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


@auth_router.post("/login", response_model=TokenPair)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_session)) -> TokenPair:
    ip = request.client.host if request.client else "unknown"

    retry_after = check_login_rate_limit(ip, body.username)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Слишком много неудачных попыток входа. Попробуйте позже.",
            headers={"Retry-After": str(retry_after)},
        )

    user = db.query(User).filter(User.username == body.username).first()

    # Намеренно один и тот же текст ошибки и для "нет такого логина", и для
    # "пароль неверный" — чтобы перебором нельзя было выяснить, какие логины
    # вообще зарегистрированы в системе.
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        record_failed_login(ip, body.username)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    record_successful_login(ip, body.username)
    access = create_access_token(user)
    refresh = issue_refresh_token(db, user)
    return TokenPair(access_token=access, refresh_token=refresh)


@auth_router.post("/refresh", response_model=TokenPair)
def refresh_token(body: RefreshRequest, db: Session = Depends(get_session)) -> TokenPair:
    record = consume_refresh_token(db, body.refresh_token)  # уже отозвал старый токен

    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Пользователь не найден или деактивирован")

    access = create_access_token(user)
    new_refresh = issue_refresh_token(db, user)
    return TokenPair(access_token=access, refresh_token=new_refresh)


@auth_router.post("/logout")
def logout(body: RefreshRequest, db: Session = Depends(get_session)) -> dict:
    """
    Отзывает конкретный refresh-токен. Не ошибка, если токен уже был
    отозван/не найден — logout должен быть идемпотентным с точки зрения
    клиента (повторный клик "выйти" не должен пугать пользователя ошибкой).
    """
    token_hash = _hash_token(body.refresh_token)
    record = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if record is not None and record.revoked_at is None:
        record.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return {"logged_out": True}


@auth_router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    """Кто я и с какой ролью — фронтенду нужно знать это сразу после логина,
    чтобы скрыть в интерфейсе кнопки действий, недоступных текущей роли."""
    return {"id": str(user.id), "username": user.username, "full_name": user.full_name, "role": user.role}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


@auth_router.post("/change-password", response_model=TokenPair)
def change_password(
    body: ChangePasswordRequest,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> TokenPair:
    """
    Смена СВОЕГО пароля — доступна любой роли, без прав администратора.

    Здесь, в /auth, а не в /users: это действие над собой, а не
    администрирование. PATCH /users/{id} для этого не годится — он требует
    роль Admin и НЕ спрашивает старый пароль (админ сбрасывает пароль
    забывшему, а не меняет свой).

    Старый пароль обязателен: без него любой, кто на минуту получил доступ
    к незаблокированному экрану или к украденному access-токену, менял бы
    пароль и запирал владельца снаружи.

    После смены все остальные сессии обрываются (revoke_all_user_tokens) —
    это и есть смысл смены пароля, если он утёк. Текущему клиенту сразу
    выдаём новую пару токенов, чтобы не разлогинивать того, кто только что
    сам всё это и сделал.
    """
    if not verify_password(body.current_password, current_user.password_hash):
        # Намеренно не уточняем, что неверен именно старый пароль в
        # деталях сверх этого — но и скрывать нечего: пользователь уже
        # аутентифицирован, это его собственная учётка.
        raise HTTPException(status_code=400, detail="Текущий пароль указан неверно")

    if body.new_password == body.current_password:
        raise HTTPException(status_code=400, detail="Новый пароль совпадает с текущим")

    current_user.password_hash = hash_password(body.new_password)
    db.commit()

    log_action(
        db, current_user, "user.change_password", entity_type="user", entity_id=current_user.id,
    )

    # Сначала отзываем ВСЕ refresh-токены (включая свой), затем выдаём
    # себе новый — порядок важен, иначе только что выданный тут же и
    # отозвался бы вместе с остальными.
    revoke_all_user_tokens(db, current_user.id)

    return TokenPair(
        access_token=create_access_token(current_user),
        refresh_token=issue_refresh_token(db, current_user),
    )


# =====================================================================
# /users — управление пользователями (только Admin)
# =====================================================================


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=8)
    full_name: str | None = None
    role: str


class UpdateUserRequest(BaseModel):
    full_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8)


def _validate_role(role: str) -> str:
    if role not in ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Недопустимая роль: {role!r}. Допустимые значения: {', '.join(ROLES)}",
        )
    return role


@users_router.post("", dependencies=[Depends(require_role(ADMIN))])
def create_user(
    body: CreateUserRequest,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    _validate_role(body.role)

    if db.query(User).filter(User.username == body.username).first() is not None:
        raise HTTPException(status_code=409, detail="Пользователь с таким логином уже существует")

    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
    )
    db.add(user)
    db.commit()

    log_action(
        db, current_user, "user.create", entity_type="user", entity_id=user.id,
        meta={"username": user.username, "role": user.role},
    )
    return {"id": str(user.id), "username": user.username, "role": user.role, "is_active": user.is_active}


@users_router.get("", dependencies=[Depends(require_role(ADMIN))])
def list_users(db: Session = Depends(get_session)) -> list[dict]:
    users = db.query(User).order_by(User.username).all()
    return [
        {
            "id": str(u.id),
            "username": u.username,
            "full_name": u.full_name,
            "role": u.role,
            "is_active": u.is_active,
        }
        for u in users
    ]


@users_router.patch("/{user_id}", dependencies=[Depends(require_role(ADMIN))])
def update_user(
    user_id: uuid.UUID,
    body: UpdateUserRequest,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Защита от самоблокировки: снять с себя роль Admin или деактивировать
    # себя же — билет в один конец. Восстановить будет нечем: POST /users
    # сам требует роль Admin, а bootstrap-админ создаётся только когда в
    # таблице нет ВООБЩЕ ни одного пользователя (см. ensure_bootstrap_admin),
    # то есть при живой базе он не поможет. Единственным выходом остался бы
    # ручной UPDATE в psql на сервере.
    # Сменить себе имя или пароль при этом можно — они доступ не отбирают.
    if user.id == current_user.id:
        if body.role is not None and body.role != user.role:
            raise HTTPException(
                status_code=400,
                detail="Нельзя менять роль самому себе — можно потерять доступ безвозвратно",
            )
        if body.is_active is False:
            raise HTTPException(status_code=400, detail="Нельзя деактивировать самого себя")

    changes = {}
    if body.full_name is not None:
        user.full_name = body.full_name
        changes["full_name"] = body.full_name
    if body.role is not None:
        _validate_role(body.role)
        changes["role"] = {"from": user.role, "to": body.role}
        user.role = body.role
    if body.password is not None:
        user.password_hash = hash_password(body.password)
        changes["password"] = "changed"
    if body.is_active is not None:
        user.is_active = body.is_active
        changes["is_active"] = body.is_active
        if not body.is_active:
            # деактивация обрывает и все текущие сессии — иначе уже
            # выданные access-токены (до 30 минут) и refresh-токены
            # продолжали бы работать до истечения TTL
            revoke_all_user_tokens(db, user.id)

    db.commit()
    log_action(db, current_user, "user.update", entity_type="user", entity_id=user.id, meta=changes)

    return {"id": str(user.id), "username": user.username, "role": user.role, "is_active": user.is_active}


# =====================================================================
# /audit-log — просмотр журнала (Admin, Director)
# =====================================================================

@audit_router.get("", dependencies=[Depends(require_role(*CAN_EXPORT))])
def list_audit_log(
    limit: int = Query(100, le=500),
    entity_type: str | None = None,
    db: Session = Depends(get_session),
) -> list[dict]:
    query = db.query(AuditLog)
    if entity_type is not None:
        query = query.filter(AuditLog.entity_type == entity_type)

    entries = query.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [
        {
            "id": str(e.id),
            "user_username": e.user_username,
            "action": e.action,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "meta": e.meta,
            "created_at": e.created_at.isoformat(),
        }
        for e in entries
    ]
