from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PM_", env_file=".env", extra="ignore")

    app_name: str = "Process Mining Platform"
    # SQLAlchemy database URL. SQLite by default for dev; set PM_DATABASE_URL
    # to a postgresql+psycopg2://... URL in production (schema is portable).
    database_url: str = "sqlite:///./process_mining.db"
    jwt_secret: str = "dev-only-insecure-secret-change-me-in-production-0000"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720
    cors_origins: str = "http://localhost:3000"
    # Seed an initial admin user on startup (dev convenience).
    seed_admin_email: str = "admin@example.com"
    seed_admin_password: str = "admin12345"
    # Discovery runs on aggregated variants; this caps the materialized rows
    # used to build the pm4py event log for miners/conformance.
    max_discovery_events: int = 2_000_000
    upload_max_bytes: int = 200 * 1024 * 1024  # 200 MB

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
