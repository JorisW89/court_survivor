from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./court_survivor.db"
    SECRET_KEY: str = "dev-secret-key-please-change"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 days
    ENV: str = "development"

    model_config = {"env_file": ".env"}


settings = Settings()
