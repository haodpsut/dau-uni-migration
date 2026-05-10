"""DB connection helpers — SQL Server (source) + Postgres (target)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
import pymssql
from psycopg.rows import dict_row

from .config import settings
from .log import logger


@contextmanager
def source_conn(database: str | None = None) -> Iterator[pymssql.Connection]:
    """SQL Server connection. Pass database to override default HRM_DAU.

    Usage:
        with source_conn("EDU_DAU") as conn:
            cursor = conn.cursor(as_dict=True)
            cursor.execute("SELECT TOP 10 * FROM DT_SinhVien")
            rows = cursor.fetchall()
    """
    db = database or settings.SOURCE_DB_HRM
    logger.debug(f"Connecting source: {settings.SOURCE_HOST}:{settings.SOURCE_PORT}/{db}")
    conn = pymssql.connect(
        server=settings.SOURCE_HOST,
        port=settings.SOURCE_PORT,
        user=settings.SOURCE_USER,
        password=settings.SOURCE_PASSWORD,
        database=db,
        charset="UTF-8",
        tds_version="7.4",
        timeout=300,
    )
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def target_conn(autocommit: bool = False) -> Iterator[psycopg.Connection]:
    """Postgres connection (psycopg3) with dict_row default.

    Usage:
        with target_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS n")
                print(cur.fetchone())  # {'n': 1}
    """
    dsn = (
        f"host={settings.TARGET_HOST} port={settings.TARGET_PORT} "
        f"dbname={settings.TARGET_DB} user={settings.TARGET_USER} "
        f"password={settings.TARGET_PASSWORD}"
    )
    logger.debug(f"Connecting target: {settings.TARGET_HOST}:{settings.TARGET_PORT}/{settings.TARGET_DB}")
    conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=autocommit)
    try:
        yield conn
        if not autocommit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_all_dicts(database: str, sql: str, params: tuple = ()) -> list[dict]:
    """Convenience: SELECT all from source, return list[dict]."""
    with source_conn(database) as conn:
        cursor = conn.cursor(as_dict=True)
        cursor.execute(sql, params)
        return cursor.fetchall()


def stream_source(database: str, sql: str, batch_size: int = 10000) -> Iterator[list[dict]]:
    """Stream large source query in batches to avoid memory blow-up.

    Usage:
        for batch in stream_source("EDU_DAU", "SELECT * FROM DT_DangKyHocPhan", 10000):
            process(batch)
    """
    with source_conn(database) as conn:
        cursor = conn.cursor(as_dict=True)
        cursor.execute(sql)
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            yield rows
