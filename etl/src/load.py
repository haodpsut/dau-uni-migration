"""Bulk loader cho Postgres — dùng COPY (10x nhanh hơn INSERT)."""

from __future__ import annotations

from typing import Iterable, Sequence
from io import StringIO

import psycopg

from .log import logger


def truncate_table(conn: psycopg.Connection, qualified_table: str, restart_identity: bool = True) -> None:
    """TRUNCATE bảng, optionally reset BIGSERIAL."""
    cmd = f"TRUNCATE TABLE {qualified_table}"
    if restart_identity:
        cmd += " RESTART IDENTITY"
    cmd += " CASCADE"
    logger.debug(f"Executing: {cmd}")
    with conn.cursor() as cur:
        cur.execute(cmd)


def copy_rows(
    conn: psycopg.Connection,
    qualified_table: str,
    columns: Sequence[str],
    rows: Iterable[tuple],
) -> int:
    """Bulk load rows via COPY. Returns count loaded.

    Args:
        qualified_table: 'master.provinces' (must include schema)
        columns: ['code', 'name', 'legacy_id']
        rows: iterable of tuples matching columns order

    Example:
        copy_rows(conn, 'master.provinces', ['code', 'name', 'legacy_id'],
                  [('048', 'Đà Nẵng', 1), ('001', 'Hà Nội', 2)])
    """
    cols_sql = ", ".join(columns)
    sql = f"COPY {qualified_table} ({cols_sql}) FROM STDIN"

    count = 0
    with conn.cursor() as cur, cur.copy(sql) as copy:
        for row in rows:
            copy.write_row(row)
            count += 1

    logger.info(f"COPY → {qualified_table}: {count:,} rows")
    return count


def upsert_rows(
    conn: psycopg.Connection,
    qualified_table: str,
    columns: Sequence[str],
    rows: Sequence[tuple],
    conflict_column: str = "legacy_id",
    update_columns: Sequence[str] | None = None,
) -> int:
    """INSERT ... ON CONFLICT (legacy_id) DO UPDATE — idempotent re-runs.

    Slower than COPY but allows re-running without TRUNCATE.
    """
    if not rows:
        return 0

    cols_sql = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))

    if update_columns is None:
        update_columns = [c for c in columns if c != conflict_column]
    update_sql = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_columns)

    sql = (
        f"INSERT INTO {qualified_table} ({cols_sql}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_column}) DO UPDATE SET {update_sql}"
    )

    with conn.cursor() as cur:
        cur.executemany(sql, rows)
        count = cur.rowcount

    logger.info(f"UPSERT → {qualified_table}: {count:,} rows")
    return count


def get_id_by_legacy(conn: psycopg.Connection, qualified_table: str, legacy_id: int | None) -> int | None:
    """Lookup target ID from legacy_id. Cached version below for hot loops."""
    if legacy_id is None:
        return None
    with conn.cursor() as cur:
        cur.execute(f"SELECT id FROM {qualified_table} WHERE legacy_id = %s", (legacy_id,))
        row = cur.fetchone()
        return row["id"] if row else None


class LegacyIdMapper:
    """In-memory cache for legacy_id → new id lookups during ETL.

    Hai mode:
      • scalar (default): `legacy_id INTEGER` column. Quy ước cho hầu hết bảng.
      • JSONB: `legacy_ids JSONB` column với key cụ thể. Dùng cho student.students
        (vì merge 4 bảng nguồn — DT_HoSoSinhVien, DT_SinhVien, ...).

    Usage:
        # Scalar
        mapper = LegacyIdMapper(conn, 'master.provinces')

        # JSONB (student.students chứa {"DT_SinhVien": 12345, ...})
        mapper = LegacyIdMapper(conn, 'student.students', jsonb_key='DT_SinhVien')

        new_id = mapper.lookup(48)
    """

    def __init__(
        self,
        conn: psycopg.Connection,
        qualified_table: str,
        jsonb_key: str | None = None,
    ):
        self._cache: dict[int, int] = {}
        with conn.cursor() as cur:
            if jsonb_key:
                cur.execute(
                    f"SELECT (legacy_ids->>%s)::BIGINT AS source_id, id "
                    f"FROM {qualified_table} "
                    f"WHERE legacy_ids ? %s",
                    (jsonb_key, jsonb_key),
                )
            else:
                cur.execute(
                    f"SELECT legacy_id, id FROM {qualified_table} WHERE legacy_id IS NOT NULL"
                )
            for row in cur:
                key = row["source_id"] if jsonb_key else row["legacy_id"]
                if key is not None:
                    self._cache[int(key)] = row["id"]
        logger.debug(f"LegacyIdMapper for {qualified_table}: {len(self._cache):,} entries cached")

    def lookup(self, legacy_id: int | None) -> int | None:
        if legacy_id is None:
            return None
        return self._cache.get(legacy_id)

    def __len__(self) -> int:
        return len(self._cache)
