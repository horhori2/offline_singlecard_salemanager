from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # 네이버 커머스 API
    naver_client_id: str = ""
    naver_client_secret: str = ""
    naver_account_id: str = ""  # 솔루션사가 판매자 대리 인증 시 필요 (type=SELLER). 본인 계정이면 빈칸
    naver_api_base: str = "https://api.commerce.naver.com/external"
    naver_auth_url: str = "https://api.commerce.naver.com/external/v1/oauth2/token"

    # 서버
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True

    # DB
    database_url: str = "sqlite+aiosqlite:///./inventory.db"

    # 재고
    low_stock_threshold: int = 10
    auto_sync_interval: int = 300  # 초


@lru_cache
def get_settings() -> Settings:
    return Settings()
