"""Smoke test trước khi chạy ETL — kiểm tra connect được source + target.

Usage: python scripts/check_connections.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings
from src.db import source_conn, target_conn
from src.log import setup_logging, logger


def check_source():
    logger.info(f"Testing SOURCE: {settings.SOURCE_HOST}:{settings.SOURCE_PORT}")
    for db in (settings.SOURCE_DB_HRM, settings.SOURCE_DB_EDU, settings.SOURCE_DB_DATA):
        try:
            with source_conn(db) as conn:
                cur = conn.cursor()
                cur.execute("SELECT @@VERSION AS v, COUNT(*) AS n FROM sys.tables")
                row = cur.fetchone()
                logger.success(f"  ✓ {db}: tables={row[1]}")
        except Exception as e:
            logger.error(f"  ✗ {db}: {e}")


def check_target():
    logger.info(f"Testing TARGET: {settings.TARGET_HOST}:{settings.TARGET_PORT}/{settings.TARGET_DB}")
    try:
        with target_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version() AS v")
                row = cur.fetchone()
                logger.success(f"  ✓ Postgres: {row['v'][:60]}")

                cur.execute(
                    "SELECT COUNT(*) AS n FROM information_schema.schemata "
                    "WHERE schema_name IN ('identity','master','hr','academic','student','files','audit')"
                )
                schemas = cur.fetchone()["n"]
                logger.info(f"  Schemas already created: {schemas}/7")
    except Exception as e:
        logger.error(f"  ✗ Postgres: {e}")


def check_minio():
    from minio import Minio
    logger.info(f"Testing MINIO: {settings.MINIO_ENDPOINT}")
    try:
        client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        buckets = list(client.list_buckets())
        logger.success(f"  ✓ MinIO: {len(buckets)} buckets ({[b.name for b in buckets]})")
    except Exception as e:
        logger.error(f"  ✗ MinIO: {e}")


if __name__ == "__main__":
    setup_logging()
    check_source()
    check_target()
    check_minio()
