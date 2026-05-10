"""dump_summary.py — Produce a human-readable summary of ETL output.

Output:
  • output/etl_report_<timestamp>.md  — markdown report (~50 KB, push GitHub OK)
  • output/etl_state.json              — JSON for programmatic use

Sections:
  • Row counts per table
  • Top 10 sample records (with PII redacted)
  • Validation: orphan FK checks
  • Storage stats (Postgres + MinIO)

Usage: python scripts/dump_summary.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings, PROJECT_ROOT
from src.db import target_conn
from src.log import setup_logging, logger


def get_row_counts(conn) -> dict[str, int]:
    """Get exact row counts (slower than reltuples but accurate)."""
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        cur.execute("""
            SELECT n.nspname || '.' || c.relname AS qname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'p')
              AND n.nspname IN ('identity','master','hr','academic','student','files','audit')
            ORDER BY n.nspname, c.relname
        """)
        names = [r["qname"] for r in cur.fetchall()]
        for qname in names:
            try:
                cur.execute(f"SELECT COUNT(*) AS n FROM {qname}")
                counts[qname] = cur.fetchone()["n"]
            except Exception as e:
                counts[qname] = -1
                logger.warning(f"Cannot count {qname}: {e}")
    return counts


def get_db_size(conn) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_size_pretty(pg_database_size(current_database())) AS size")
        db_size = cur.fetchone()["size"]
        cur.execute("""
            SELECT n.nspname AS schema,
                   pg_size_pretty(SUM(pg_total_relation_size(c.oid))) AS size
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'p')
              AND n.nspname IN ('identity','master','hr','academic','student','files','audit')
            GROUP BY n.nspname
            ORDER BY n.nspname
        """)
        per_schema = {r["schema"]: r["size"] for r in cur.fetchall()}
    return {"total": db_size, **per_schema}


def get_validations(conn) -> list[dict]:
    checks = [
        ("districts orphan", "SELECT COUNT(*) AS n FROM master.districts d WHERE NOT EXISTS (SELECT 1 FROM master.provinces p WHERE p.id = d.province_id)"),
        ("wards orphan", "SELECT COUNT(*) AS n FROM master.wards w WHERE NOT EXISTS (SELECT 1 FROM master.districts d WHERE d.id = w.district_id)"),
        ("employees → dept", "SELECT COUNT(*) AS n FROM hr.employees e WHERE e.department_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM master.departments d WHERE d.id = e.department_id)"),
        ("students → program", "SELECT COUNT(*) AS n FROM student.students s WHERE s.program_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM academic.programs p WHERE p.id = s.program_id)"),
        ("course_classes → subject", "SELECT COUNT(*) AS n FROM academic.course_classes cc WHERE NOT EXISTS (SELECT 1 FROM academic.subjects s WHERE s.id = cc.subject_id)"),
        ("enrollments → student", "SELECT COUNT(*) AS n FROM student.enrollments e WHERE NOT EXISTS (SELECT 1 FROM student.students s WHERE s.id = e.student_id)"),
        ("grades → enrollment", "SELECT COUNT(*) AS n FROM student.grades g WHERE g.enrollment_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM student.enrollments e WHERE e.id = g.enrollment_id)"),
    ]
    results = []
    with conn.cursor() as cur:
        for name, sql in checks:
            try:
                cur.execute(sql)
                n = cur.fetchone()["n"]
                results.append({"check": name, "orphans": n, "status": "OK" if n == 0 else "FAIL"})
            except Exception as e:
                results.append({"check": name, "orphans": None, "status": f"ERR: {e}"})
    return results


def write_markdown(report: dict, out_file: Path) -> None:
    """Write Markdown report."""
    lines = [
        f"# ETL Output Summary — {report['timestamp']}",
        "",
        "## Database size",
        "",
        "| Schema | Size |",
        "|---|---:|",
    ]
    for k, v in report["db_size"].items():
        lines.append(f"| {k} | {v} |")
    lines += ["", "## Row counts", "", "| Table | Rows |", "|---|---:|"]
    for tbl, n in sorted(report["row_counts"].items()):
        lines.append(f"| `{tbl}` | {n:,} |")
    lines += ["", "## Validation", "", "| Check | Orphans | Status |", "|---|---:|---|"]
    for c in report["validations"]:
        emoji = "✅" if c["status"] == "OK" else "❌"
        orphan = c["orphans"] if c["orphans"] is not None else "?"
        lines.append(f"| {c['check']} | {orphan} | {emoji} {c['status']} |")

    out_file.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Wrote markdown report: {out_file}")


def main():
    setup_logging()
    out_dir = PROJECT_ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    md_file = out_dir / f"etl_report_{stamp}.md"
    json_file = out_dir / "etl_state.json"

    with target_conn() as conn:
        report = {
            "timestamp": datetime.now().isoformat(),
            "db_size": get_db_size(conn),
            "row_counts": get_row_counts(conn),
            "validations": get_validations(conn),
        }

    write_markdown(report, md_file)
    json_file.write_text(json.dumps(report, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Wrote JSON state: {json_file}")
    logger.success(f"Reports in {out_dir}/")


if __name__ == "__main__":
    main()
