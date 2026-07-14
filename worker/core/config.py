from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/postgres"
    DATABASE_HOST: str | None = None
    DATABASE_PORT: int = 5432
    DATABASE_USER: str | None = None
    DATABASE_PASS: str | None = None
    DATABASE_NAME: str | None = None
    DATABASE_LOCAL: bool = True
    JUNGBO_NARU_API_KEY: str = ""
    NL_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    VLM_API_KEY: str = ""
    VLM_API_BASE_URL: str = "https://api.openai.com/v1"
    VLM_MODEL: str = "gpt-4o-mini"
    VLM_IMAGE_MAX_EDGE: int = 2048
    VLM_IMAGE_JPEG_QUALITY: int = 80
    VLM_IMAGE_DETAIL: str = "high"
    VLM_MAX_TOKENS: int = 1500
    VLM_REQUEST_TIMEOUT_SECONDS: int = 45
    AWS_REGION: str = "ap-northeast-2"
    S3_BUCKET_NAME: str = ""
    SCAN_ARTIFACTS_ENABLED: bool = False
    SCAN_ARTIFACTS_PREFIX: str = "shelfalign/scans"
    SCAN_ARTIFACTS_SAVE_CROPS: bool = True
    OBB_CROP_PADDING_RATIO: float = 0.015
    OBB_CROP_MIN_WIDTH: int = 256
    OBB_CROP_MAX_EDGE: int = 3000
    
    @property
    def async_database_url(self) -> str:
        if all((self.DATABASE_HOST, self.DATABASE_USER, self.DATABASE_PASS, self.DATABASE_NAME)):
            username = quote(self.DATABASE_USER or "", safe="")
            password = quote(self.DATABASE_PASS or "", safe="")
            ssl_query = "" if self.DATABASE_LOCAL else "?sslmode=require"
            return (
                f"postgresql+psycopg://{username}:{password}"
                f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}{ssl_query}"
            )

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

    model_config = SettingsConfigDict(
        env_file=(".env", "web/apps/backend/.env"),
        extra="ignore",
    )

settings = Settings()
