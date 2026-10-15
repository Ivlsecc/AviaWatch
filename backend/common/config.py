from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    # Telegram
    bot_token: str = ""
    admin_tg_ids: list[int] = []

    # Travelpayouts (Aviasales Data API)
    travelpayouts_token: str = ""
    travelpayouts_marker: str = ""

    # Хранилища. По умолчанию SQLite, чтобы запускаться без Docker.
    database_url: str = "sqlite+aiosqlite:///./aviawatch.db"
    redis_url: str = ""

    # Глобальный прокси (переопределяется в конфиге конкретного источника)
    http_proxy: str = ""
    # Прокси до api.telegram.org. Пусто — берётся системный (VPN-клиент), если он есть
    telegram_proxy: str = ""

    # Поиск
    search_cache_ttl_s: int = 15 * 60
    source_failure_threshold: int = 5
    source_cooldown_min: int = 30

    # Подписки: как часто перепроверять цены (минуты)
    subscription_check_minutes: int = 60

    # Метрики Prometheus (0 — не поднимать HTTP-сервер)
    metrics_port: int = 0

    # Веб-админка
    admin_username: str = "admin"
    admin_password: str = ""
    jwt_secret: str = ""
    api_port: int = 8000

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
