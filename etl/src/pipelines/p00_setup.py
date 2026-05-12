"""Pipeline 00: Apply target_schema.sql + make permissive for migration.

Strategy: legacy ASCVN data is dirty (NULL phones, dup codes, malformed emails,
inconsistent dates). Use permissive schema for MIGRATION PHASE:
  • Drop NOT NULL on all non-id columns
  • Drop all UNIQUE except identity.users (we control)
  • Drop all CHECK constraints (data-quality validations)

After ETL completes + data cleanup, re-add constraints via migration scripts.

Idempotent — safe to re-run.
"""

from __future__ import annotations

from pathlib import Path

from ..config import PROJECT_ROOT
from ..db import target_conn
from ..log import logger


SCHEMA_FILE = PROJECT_ROOT.parent / "target_schema.sql"


# Permissive migration patches — applied after target_schema.sql
PERMISSIVE_SQL = """
-- 1. Drop NOT NULL on all non-PK, non-created_at columns across migration schemas
DO $$ DECLARE r RECORD;
BEGIN
  FOR r IN
    SELECT n.nspname AS sch, c.relname AS tbl, a.attname AS col
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname IN ('master','hr','academic','student','files','audit','identity')
      AND a.attnotnull = TRUE
      AND a.attnum > 0
      AND a.attname NOT IN ('id', 'created_at')
      AND NOT EXISTS (
          SELECT 1 FROM pg_constraint
          WHERE conrelid = c.oid AND contype = 'p'
            AND a.attnum = ANY(conkey)
      )
  LOOP
    EXECUTE format('ALTER TABLE %I.%I ALTER COLUMN %I DROP NOT NULL', r.sch, r.tbl, r.col);
  END LOOP;
END $$;

-- 2. Drop UNIQUE constraints (except identity tables where uniqueness is logical)
DO $$ DECLARE r RECORD;
BEGIN
  FOR r IN
    SELECT n.nspname AS sch, c.relname AS tbl, con.conname
    FROM pg_constraint con
    JOIN pg_class c ON c.oid = con.conrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname IN ('master','hr','academic','student','files','audit')
      AND con.contype = 'u'
  LOOP
    EXECUTE format('ALTER TABLE %I.%I DROP CONSTRAINT %I', r.sch, r.tbl, r.conname);
  END LOOP;
END $$;

-- 3. Drop CHECK constraints (data-quality validations)
DO $$ DECLARE r RECORD;
BEGIN
  FOR r IN
    SELECT n.nspname AS sch, c.relname AS tbl, con.conname
    FROM pg_constraint con
    JOIN pg_class c ON c.oid = con.conrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname IN ('master','hr','academic','student','files','audit')
      AND con.contype = 'c'
      AND con.conname NOT LIKE '%_dummy'
      AND con.conname NOT IN ('chk_year', 'chk_not_self', 'chk_op')  -- keep logical
  LOOP
    EXECUTE format('ALTER TABLE %I.%I DROP CONSTRAINT %I', r.sch, r.tbl, r.conname);
  END LOOP;
END $$;
"""


def run() -> None:
    """Execute target_schema.sql + permissive patches on the target Postgres."""
    if not SCHEMA_FILE.exists():
        raise FileNotFoundError(f"Cannot find {SCHEMA_FILE}")

    logger.info(f"Applying {SCHEMA_FILE} ...")
    sql = SCHEMA_FILE.read_text(encoding="utf-8")

    with target_conn(autocommit=True) as conn:
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

    # Apply permissive patches for ASCVN dirty data migration
    logger.info("Applying permissive patches (drop NOT NULL/UNIQUE/CHECK) ...")
    with target_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(PERMISSIVE_SQL)
    logger.success(f"✓ Setup complete (permissive mode). Schemas: {sorted(actual)}")


if __name__ == "__main__":
    from ..log import setup_logging
    setup_logging()
    run()
