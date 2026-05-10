"""Config loaded from .env via pydantic-settings."""

from __future__ import annotations

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # SOURCE
    SOURCE_HOST: str = "localhost"
    SOURCE_PORT: int = 1433
    SOURCE_USER: str = "sa"
    SOURCE_PASSWORD: str
    SOURCE_DB_HRM: str = "HRM_DAU"
    SOURCE_DB_EDU: str = "EDU_DAU"
    SOURCE_DB_DATA: str = "EDU_DAU_DATA"

    # TARGET
    TARGET_HOST: str = "localhost"
    TARGET_PORT: int = 5432
    TARGET_DB: str = "dau_university"
    TARGET_USER: str = "dau_admin"
    TARGET_PASSWORD: str

    # MinIO
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str
    MINIO_SECRET_KEY: str
    MINIO_SECURE: bool = False
    MINIO_BUCKET_STUDENTS: str = "students"
    MINIO_BUCKET_EMPLOYEES: str = "employees"
    MINIO_BUCKET_DOCUMENTS: str = "documents"
    MINIO_BUCKET_GRADE_CHANGES: str = "grade-changes"

    # ETL
    ETL_BATCH_SIZE: int = 10000
    ETL_TRUNCATE_BEFORE_LOAD: bool = True
    ETL_AUDIT_KEEP_YEARS: int = 3

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/etl.log"


settings = Settings()  # singleton
PROJECT_ROOT = Path(__file__).resolve().parent.parent
