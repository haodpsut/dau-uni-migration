"""CLI entrypoint cho ETL pipeline.

Usage:
    python run.py setup              # apply target_schema.sql
    python run.py master             # 16 master lookup tables
    python run.py employees          # HR employees
    python run.py academic           # subjects + course_classes + student_classes
    python run.py students           # students (gộp 4 bảng) + graduations
    python run.py enrollments        # 2.3M đăng ký HP (partition)
    python run.py grades             # 2M điểm (slim 153→33, partition)
    python run.py files              # BLOB → MinIO
    python run.py audit              # XML → JSONB (3 năm gần nhất)
    python run.py all                # chạy tất cả theo thứ tự
    python run.py status             # row counts
    python run.py validate           # FK orphan checks
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import typer
from rich.console import Console
from rich.table import Table

from src.log import setup_logging, logger
from src.db import target_conn

app = typer.Typer(help="DAU University ETL pipeline")
console = Console()


def _run_pipeline(name: str, callable):
    setup_logging()
    t0 = time.time()
    result = callable()
    elapsed = time.time() - t0
    if isinstance(result, dict):
        table = Table(title=f"{name} pipeline — {elapsed:.1f}s")
        table.add_column("Table"); table.add_column("Rows", justify="right")
        for n, c in result.items():
            table.add_row(n, f"{c:,}")
        console.print(table)
    else:
        console.print(f"[green]✓[/green] {name}: {result:,} rows in {elapsed:.1f}s")


@app.command()
def setup():
    """Apply target_schema.sql lên Postgres."""
    from src.pipelines import p00_setup
    setup_logging()
    p00_setup.run()


@app.command()
def master():
    from src.pipelines import p01_master
    _run_pipeline("master", p01_master.run)


@app.command()
def employees():
    from src.pipelines import p02_employees
    _run_pipeline("employees", p02_employees.run)


@app.command()
def students():
    from src.pipelines import p03_students
    _run_pipeline("students", p03_students.run)


@app.command()
def graduations():
    """Sub-pipeline: load graduations (depends on students)."""
    setup_logging()
    from src.pipelines.p03_students import load_graduations
    with target_conn() as conn:
        n = load_graduations(conn)
    console.print(f"[green]✓[/green] graduations: {n:,} rows")


@app.command()
def academic():
    from src.pipelines import p04_academic
    _run_pipeline("academic", p04_academic.run)


@app.command()
def enrollments():
    from src.pipelines import p05_enrollments
    _run_pipeline("enrollments", p05_enrollments.run)


@app.command()
def grades():
    from src.pipelines import p06_grades
    _run_pipeline("grades", p06_grades.run)


@app.command()
def files():
    from src.pipelines import p07_files
    _run_pipeline("files", p07_files.run)


@app.command()
def audit():
    from src.pipelines import p08_audit
    _run_pipeline("audit", p08_audit.run)


@app.command()
def all():
    """Chạy toàn bộ pipelines theo thứ tự đúng (dependency order)."""
    setup_logging()
    setup()
    master()
    academic()           # academic_years/semesters/programs/subjects/course_classes/student_classes
    employees()
    students()
    graduations()
    enrollments()
    grades()
    files()
    audit()
    console.print("[bold green]✓ ALL PIPELINES COMPLETE[/bold green]")


@app.command()
def status():
    """Row counts per schema/table."""
    setup_logging()
    with target_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT n.nspname AS schema, c.relname AS table,
                       c.reltuples::BIGINT AS estimated_rows
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind IN ('r', 'p')
                  AND n.nspname IN ('identity','master','hr','academic','student','files','audit')
                ORDER BY n.nspname, c.relname
            """)
            rows = cur.fetchall()

    table = Table(title="Target DB row counts")
    table.add_column("Schema")
    table.add_column("Table")
    table.add_column("Est. rows", justify="right")
    for r in rows:
        table.add_row(r["schema"], r["table"], f"{r['estimated_rows']:,}")
    console.print(table)


@app.command()
def validate():
    """Sanity checks — orphan FKs, row count vs source."""
    setup_logging()
    checks = [
        ("districts → provinces",
         "SELECT COUNT(*) AS n FROM master.districts d "
         "WHERE NOT EXISTS (SELECT 1 FROM master.provinces p WHERE p.id = d.province_id)"),
        ("wards → districts",
         "SELECT COUNT(*) AS n FROM master.wards w "
         "WHERE NOT EXISTS (SELECT 1 FROM master.districts d WHERE d.id = w.district_id)"),
        ("employees → departments",
         "SELECT COUNT(*) AS n FROM hr.employees e WHERE e.department_id IS NOT NULL "
         "AND NOT EXISTS (SELECT 1 FROM master.departments d WHERE d.id = e.department_id)"),
        ("students → programs",
         "SELECT COUNT(*) AS n FROM student.students s WHERE s.program_id IS NOT NULL "
         "AND NOT EXISTS (SELECT 1 FROM academic.programs p WHERE p.id = s.program_id)"),
        ("course_classes → subjects",
         "SELECT COUNT(*) AS n FROM academic.course_classes cc "
         "WHERE NOT EXISTS (SELECT 1 FROM academic.subjects s WHERE s.id = cc.subject_id)"),
        ("enrollments → students",
         "SELECT COUNT(*) AS n FROM student.enrollments e "
         "WHERE NOT EXISTS (SELECT 1 FROM student.students s WHERE s.id = e.student_id)"),
        ("grades → enrollments link",
         "SELECT COUNT(*) AS n FROM student.grades g WHERE g.enrollment_id IS NOT NULL "
         "AND NOT EXISTS (SELECT 1 FROM student.enrollments e WHERE e.id = g.enrollment_id)"),
    ]
    table = Table(title="Validation — orphan FK checks")
    table.add_column("Check")
    table.add_column("Orphans", justify="right")
    table.add_column("Status")

    with target_conn() as conn:
        with conn.cursor() as cur:
            for name, sql in checks:
                try:
                    cur.execute(sql)
                    n = cur.fetchone()["n"]
                    status = "[green]✓ OK[/green]" if n == 0 else f"[red]✗ FAIL[/red]"
                    table.add_row(name, str(n), status)
                except Exception as e:
                    table.add_row(name, "?", f"[yellow]ERR: {e}[/yellow]")
    console.print(table)


if __name__ == "__main__":
    app()
