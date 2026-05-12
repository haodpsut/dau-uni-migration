"""export_csv.py — Export all migrated Postgres tables to CSV files.

Uses Postgres COPY TO STDOUT (fastest export method, 10× faster than fetchall).
Skips partition children (data already in parent partitioned table).

Output: etl/output/csv/<schema>_<table>.csv
        + summary at output/csv/_INDEX.md

Usage:
    python scripts/export_csv.py             # export all
    python scripts/export_csv.py --schema student   # only one schema
    python scripts/export_csv.py --table student.students  # one table
    python scripts/export_csv.py --skip-audit   # skip audit (large JSONB)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import PROJECT_ROOT
from src.db import target_conn
from src.log import logger, setup_logging


SCHEMAS = ('master', 'hr', 'academic', 'student', 'files', 'audit', 'identity')


def list_tables(conn, schemas: tuple, table_filter: str | None = None):
    """List user tables in given schemas. Skip partition CHILDREN (export parents only)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT n.nspname AS schema,
                   c.relname AS name,
                   c.reltuples::BIGINT AS est_rows
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'p')
              AND n.nspname = ANY(%s)
              AND NOT EXISTS (
                  SELECT 1 FROM pg_inherits i WHERE i.inhrelid = c.oid
              )
            ORDER BY n.nspname, c.relname
        """, (list(schemas),))
        rows = cur.fetchall()

    if table_filter:
        if '.' not in table_filter:
            raise ValueError(f"--table must be schema.table format, got '{table_filter}'")
        sch, tbl = table_filter.split('.', 1)
        rows = [r for r in rows if r['schema'] == sch and r['name'] == tbl]
        if not rows:
            raise ValueError(f"Table {table_filter} not found")
    return rows


def export_table(conn, schema: str, table: str, out_path: Path) -> tuple[int, int]:
    """Export one table to CSV. Returns (size_bytes, exact_rows)."""
    qname = f'"{schema}"."{table}"'
    sql = f"COPY (SELECT * FROM {qname}) TO STDOUT WITH (FORMAT CSV, HEADER true, ENCODING 'UTF8')"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    bytes_written = 0
    with conn.cursor() as cur, open(out_path, 'wb') as f:
        with cur.copy(sql) as copy:
            for chunk in copy:
                f.write(chunk)
                bytes_written += len(chunk)

    # Count exact rows (subtract header)
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS n FROM {qname}")
        n_rows = cur.fetchone()['n']

    return bytes_written, n_rows


def write_index(out_dir: Path, results: list[dict]) -> None:
    """Write _INDEX.md summary."""
    total_size = sum(r['size'] for r in results)
    total_rows = sum(r['rows'] for r in results)

    lines = [
        f"# CSV Export Index — {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"**Total**: {len(results)} files, {total_rows:,} rows, {total_size / 1024 / 1024:.1f} MB",
        "",
        "| Schema | Table | Rows | Size | File |",
        "|---|---|---:|---:|---|",
    ]
    for r in sorted(results, key=lambda x: (x['schema'], x['table'])):
        size_str = f"{r['size'] / 1024 / 1024:.2f} MB" if r['size'] >= 1024 * 1024 else f"{r['size'] / 1024:.1f} KB"
        lines.append(
            f"| {r['schema']} | {r['table']} | {r['rows']:,} | {size_str} | `{r['file']}` |"
        )

    index_path = out_dir / "_INDEX.md"
    index_path.write_text("\n".join(lines), encoding='utf-8')
    logger.info(f"Wrote index: {index_path}")


def main():
    parser = argparse.ArgumentParser(description="Export Postgres tables to CSV")
    parser.add_argument('--schema', help="Only export this schema")
    parser.add_argument('--table', help="Only export this table (schema.table)")
    parser.add_argument('--skip-audit', action='store_true', help="Skip audit.audit_logs (large)")
    parser.add_argument('--out-dir', default=None, help="Output dir (default: output/csv/)")
    args = parser.parse_args()

    setup_logging()

    out_dir = Path(args.out_dir) if args.out_dir else (PROJECT_ROOT / 'output' / 'csv')
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output dir: {out_dir}")

    schemas = (args.schema,) if args.schema else SCHEMAS

    t_start = time.time()
    results = []

    with target_conn(autocommit=True) as conn:
        tables = list_tables(conn, schemas, table_filter=args.table)
        logger.info(f"Found {len(tables)} tables to export")

        for row in tables:
            schema = row['schema']
            table = row['name']
            qname = f"{schema}.{table}"

            if args.skip_audit and schema == 'audit':
                logger.info(f"⏭  Skipping {qname} (--skip-audit)")
                continue

            filename = f"{schema}_{table}.csv"
            out_path = out_dir / filename

            t0 = time.time()
            try:
                size_bytes, n_rows = export_table(conn, schema, table, out_path)
                elapsed = time.time() - t0
                size_mb = size_bytes / 1024 / 1024
                logger.success(
                    f"✓ {qname}: {n_rows:,} rows, {size_mb:.2f} MB in {elapsed:.1f}s"
                )
                results.append({
                    'schema': schema, 'table': table,
                    'rows': n_rows, 'size': size_bytes, 'file': filename,
                })
            except Exception as e:
                logger.error(f"✗ {qname} FAILED: {e}")

    write_index(out_dir, results)

    total_size = sum(r['size'] for r in results)
    total_rows = sum(r['rows'] for r in results)
    elapsed = time.time() - t_start
    logger.success(
        f"DONE: {len(results)} files, {total_rows:,} rows, "
        f"{total_size / 1024 / 1024:.1f} MB in {elapsed:.1f}s"
    )
    logger.info(f"Files in: {out_dir}")


if __name__ == '__main__':
    main()
