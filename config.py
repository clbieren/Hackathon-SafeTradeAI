from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Uygulama ayarları pydantic-settings ile .env dosyasından okunur.
    Ortam değişkenleri büyük/küçük harf duyarsızdır.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore", 
    )

    # PostgreSQL bağlantı URL'si (asyncpg sürücüsü ile)
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/eren_db"

    # Uygulama meta bilgileri
    app_name: str = "Eren API"
    app_version: str = "1.0.0"
    debug: bool = False

    # ---------------------------------------------------------------------------
    # Harici API Anahtarları — Eksikse servis devre dışı kalır, uygulama çökmez
    # ---------------------------------------------------------------------------

    # https://newsapi.org → ücretsiz developer key ile test edilebilir
    news_api_key: Optional[str] = None

    # https://finnhub.io → sandbox token: "sandbox_..." ile test edilebilir
    finnhub_api_key: Optional[str] = None

    # https://www.exchangerate-api.com → ücretsiz katman 1500 istek/ay
    exchange_rate_api_key: Optional[str] = None

    # https://aistudio.google.com → Gemini API anahtarı
    gemini_api_key: Optional[str] = None

    # https://developers.google.com/maps/documentation/places/web-service
    # Find Place + Place Details API'si için (MatcherService ve yorum fallback)
    google_places_api_key: str = ""

    # HTTP istemci zaman aşımı ayarları (saniye) — scraper ve external API timeout'larıyla tutarlı
    http_timeout_seconds: float = 7.0
    http_connect_timeout_seconds: float = 3.0

    # ---------------------------------------------------------------------------
    # JWT Kimlik Doğrulama Ayarları
    # ---------------------------------------------------------------------------
    secret_key: str = "change-me-in-production-use-a-long-random-string"
    access_token_expire_minutes: int = 60

    # ---------------------------------------------------------------------------
    # Email & Alert Sistemi
    # ---------------------------------------------------------------------------

    # https://resend.com — API key
    resend_api_key: Optional[str] = None

    # Unsubscribe linkinde kullanılacak frontend base URL
    frontend_base_url: str = "https://www.safeai.com.tr"


@lru_cache
def get_settings() -> Settings:
    """
    Settings örneğini önbelleğe alır. Uygulama boyunca tek bir instance kullanılır.
    FastAPI dependency injection ile kullanım için uygundur.
    """
    return Settings()

