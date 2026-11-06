from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str
    session_secret: str
    database_url: str = "postgresql+asyncpg://radar:radar@db:5432/radar"
    # Сколько секунд initData от Telegram считается свежим
    init_data_max_age: int = 24 * 3600
    # Срок жизни сессии Mini App
    session_ttl: int = 12 * 3600
    default_timezone: str = "Europe/Moscow"
    # Папка со сборкой Mini App. Если задана, backend сам отдаёт кабинет (режим «всё в одном» для Mac)
    static_dir: str = ""
    # Мастер-ключ шифрования пользовательских ключей (base64, 32 байта)
    encryption_master_key: str = ""
    checko_base_url: str = "https://api.checko.ru/v2"


@lru_cache
def get_settings() -> Settings:
    return Settings()
