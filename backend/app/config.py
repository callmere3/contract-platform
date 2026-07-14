"""
Настройки приложения читаются из переменных окружения (файл .env).
pydantic-settings сам находит .env, валидирует значения и приводит типы —
не нужно вручную писать os.environ.get() с дефолтами по всему коду.
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str

    minio_endpoint: str
    minio_root_user: str
    minio_root_password: str
    minio_bucket: str = "contracts"

    # Секрет для подписи JWT (HS256). Сгенерировать один раз командой
    # `openssl rand -hex 32` и положить в .env — при смене все выданные
    # токены (access и refresh) мгновенно станут недействительны, все
    # пользователи будут разлогинены.
    jwt_secret_key: str = "dev-insecure-secret-change-me"
    jwt_access_ttl_minutes: int = 30
    jwt_refresh_ttl_days: int = 14

    # Первый Admin создаётся автоматически при старте, ЕСЛИ в таблице users
    # ещё нет ни одного пользователя (см. app/auth.py: ensure_bootstrap_admin).
    # Без этого некому было бы создать первого Admin через POST /users —
    # этот эндпоинт сам требует роль Admin. Пусто = bootstrap выключен
    # (например, на сервере, где пользователи уже заведены).
    bootstrap_admin_username: str = ""
    bootstrap_admin_password: str = ""

    # адрес отдельного контейнера с LibreOffice headless (см. converter/) —
    # используется только эндпоинтом генерации при ?format=pdf, не нужен
    # для остального приложения, поэтому с дефолтом (не заставляем всех
    # существующих .env-файлов на сервере обязательно его знать)
    converter_url: str = "http://converter:8090"

    environment: str = "development"

    class Config:
        env_file = ".env"
        # переменные окружения регистронезависимы:
        # DATABASE_URL в .env совпадёт с полем database_url ниже
        case_sensitive = False


# создаётся один раз при импорте модуля и переиспользуется везде в приложении
settings = Settings()
