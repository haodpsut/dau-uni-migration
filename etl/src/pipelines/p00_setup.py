"""Pipeline 00: Apply target_schema.sql lên Postgres trống.

Chạy 1 lần khi setup DB mới. Idempotent vì target_schema dùng `IF NOT EXISTS`.
"""

from __future__ import annotations

from pathlib import Path

from ..config import PROJECT_ROOT
from ..db import target_conn
from ..log import logger


SCHEMA_FILE = PROJECT_ROOT.parent / "target_schema.sql"


def run() -> None:
    """Execute target_schema.sql on the target Postgres."""
    if not SCHEMA_FILE.exists():
        raise FileNotFoundError(f"Cannot find {SCHEMA_FILE}")

    logger.info(f"Applying {SCHEMA_FILE} ...")
    sql = SCHEMA_FILE.read_text(encoding="utf-8")

    with target_conn(autocommit=True) as conn:
        # Split bằng dấu ; ngây thơ thì hỏng vì có ; trong CHECK constraints, etc.
        # Dùng psycopg execute trực tiếp toàn bộ file — psycopg3 hỗ trợ multi-statement
        with conn.cursor() as cur:
            cur.execute(sql)

    # Verify schemas tồn tại
    expected_schemas = {"identity", "master", "hr", "academic", "student", "files", "audit"}
    with target_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name = ANY(%s)",
                (list(expected_schemas),),
            )
            actual = {row["schema_name"] for row in cur.fetchall()}

    missing = expected_schemas - actual
    if missing:
        raise RuntimeError(f"Schemas missing after setup: {missing}")

    logger.success(f"✓ Setup complete. Schemas: {sorted(actual)}")


if __name__ == "__main__":
    from ..log import setup_logging
    setup_logging()
    run()
