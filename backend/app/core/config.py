from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://app:changeme@localhost:5432/novel_translator"
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = "changeme-secret-key-32chars-minimum"

    STORAGE_ENDPOINT: str = "http://localhost:9000"
    STORAGE_ACCESS_KEY: str = "minioadmin"
    STORAGE_SECRET_KEY: str = "minioadmin"
    STORAGE_BUCKET_SOURCE: str = "novel-source"
    STORAGE_BUCKET_OUTPUT: str = "novel-output"
    STORAGE_PRESIGNED_EXPIRY_SECONDS: int = 3600
    STORAGE_REGION: str = "us-east-1"

    MAX_FILE_SIZE_MB: int = 50
    CHUNK_SIZE_CHARS: int = 2000
    EXTRACTION_TIMEOUT_SECONDS: int = 600
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://frontend:3000"]

    class Config:
        env_file = ".env"


settings = Settings()
