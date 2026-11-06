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
    # Дневной лимит запросов Checko (бесплатный тариф 100) и запас на ручные действия
    checko_daily_limit: int = 100
    checko_reserve: int = 5
    # Час ежедневной проверки по часовому поясу пользователя
    monitor_hour: int = 9
    telegram_api_base: str = "https://api.telegram.org"
    webapp_url: str = ""
    # Swagger-документация API (/api/docs). В пилоте выключена
    api_docs: bool = False
    # Папка резервных копий SQLite и сколько дней их хранить
    backup_dir: str = ""
    backup_keep: int = 7
    # Корневой сертификат Минцифры (PEM): нужен только для GigaChat API
    gigachat_ca_file: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
