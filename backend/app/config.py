from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./court_survivor.db"
    SECRET_KEY: str = "dev-secret-key-please-change"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 days
    ENV: str = "development"
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"
    ADMIN_SECRET: str = ""

    model_config = {"env_file": ".env"}


settings = Settings()
