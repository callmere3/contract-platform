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

    environment: str = "development"

    class Config:
        env_file = ".env"
        # переменные окружения регистронезависимы:
        # DATABASE_URL в .env совпадёт с полем database_url ниже
        case_sensitive = False


# создаётся один раз при импорте модуля и переиспользуется везде в приложении
settings = Settings()
