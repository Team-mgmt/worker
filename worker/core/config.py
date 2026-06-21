from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/postgres"
    JUNGBO_NARU_API_KEY: str = ""
    NL_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    VLM_API_KEY: str = ""
    VLM_API_BASE_URL: str = "https://api.openai.com/v1"
    VLM_MODEL: str = "gpt-4o-mini"
    
    @property
    def async_database_url(self) -> str:
        # Ensure we use psycopg driver
        if self.DATABASE_URL.startswith("postgresql://"):
            return self.DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
        elif self.DATABASE_URL.startswith("postgres://"):
            return self.DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
        return self.DATABASE_URL

    # Optional Sync URL for Alembic
    @property
    def sync_database_url(self) -> str:
        return self.async_database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
