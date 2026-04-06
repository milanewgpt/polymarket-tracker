from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    telegram_bot_token: str
    admin_chat_id: int = 0
    database_url: str = "sqlite+aiosqlite:///data/bot.db"
    default_check_interval_minutes: int = 10
    default_buffer_percent: float = 3.0
    default_buffer_enabled: bool = True
    error_rate_limit_hours: int = 6
    log_level: str = "INFO"

    polymarket_gamma_api_url: str = "https://gamma-api.polymarket.com"
    xtracker_base_url: str = "https://xtracker.polymarket.com"
    xtracker_source_url: str = "https://xtracker.polymarket.com/user/elonmusk"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
