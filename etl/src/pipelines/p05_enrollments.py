"""Pipeline 05: Student enrollments (đăng ký học phần).

Source: EDU_DAU.DT_DangKyHocPhan (2,300,818 rows).
Target: student.enrollments (PARTITIONED by academic_year_id).

Common cols (verify khi run): Id, IDSinhVien, IDLopHocPhan, NgayDangKy, TrangThai,
IDNguoiDangKy, NgayHuy, NguoiHuy, LyDoHuy.

Stream để không OOM với 2.3M rows.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ..config import settings
from ..db import target_conn, stream_source
from ..load import truncate_table, copy_rows, LegacyIdMapper
from ..log import logger


# Map TrangThai int → enrollment_state ENUM
STATE_MAP = {
    1: "registered",
    2: "completed",
    3: "cancelled",
    4: "failed",
    5: "in_progress",
    6: "withdrew",
}


def _safe_str(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _safe_dt(v) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime.combine(v, datetime.min.time())
    return None


def _state(v) -> str:
    if v is None:
        return "registered"
    try:
        return STATE_MAP.get(int(v), "registered")
    except (TypeError, ValueError):
        return "registered"


# =============================================================================

ENROLLMENT_QUERY = """
    SELECT
        Id, IDSinhVien, IDLopHocPhan,
        NgayDangKy, IDTrangThaiDangKy, NguoiTao,
        GhiChu, GhiChuKTC, NgayTao
    FROM DT_DangKyHocPhan WITH(NOLOCK)
    ORDER BY Id
"""

ENROLLMENT_COLS = [
    "legacy_id",
    "student_id", "course_class_id",
    "academic_year_id", "semester_id",
    "enrolled_at", "enrolled_by_id", "state",
    "cancelled_at", "cancelled_by_id", "cancel_reason",
    "notes",
]


def transform(src: dict, mappers: dict[str, LegacyIdMapper],
              cc_to_year_sem: dict[int, tuple[int, int]]) -> tuple | None:
    student_id = mappers["students"].lookup(src.get("IDSinhVien"))
    course_class_id = mappers["course_classes"].lookup(src.get("IDLopHocPhan"))
    if not student_id or not course_class_id:
        return None
    ay_sem = cc_to_year_sem.get(course_class_id)
    if not ay_sem:
        return None
    academic_year_id, semester_id = ay_sem

    return (
        src["Id"],
        student_id, course_class_id,
        academic_year_id, semester_id,
        _safe_dt(src.get("NgayDangKy")) or _safe_dt(src.get("NgayTao")) or datetime.now(),
        None,                                                # enrolled_by_id — resolve via NguoiTao + identity.users (sau)
        _state(src.get("IDTrangThaiDangKy")),
        None,                                                # cancelled_at — không có cột riêng
        None,                                                # cancelled_by_id
        None,                                                # cancel_reason
        _safe_str(src.get("GhiChu")) or _safe_str(src.get("GhiChuKTC")),
    )


def run() -> int:
    logger.info("Loading student.enrollments from EDU_DAU.DT_DangKyHocPhan ...")

    with target_conn() as conn:
        # Map course_class → (year, semester)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT cc.id AS course_class_id, s.academic_year_id, cc.semester_id
                FROM academic.course_classes cc
                JOIN academic.semesters s ON s.id = cc.semester_id
            """)
            cc_map = {r["course_class_id"]: (r["academic_year_id"], r["semester_id"])
                      for r in cur.fetchall()}
        logger.info(f"Loaded {len(cc_map):,} course_class mappings")

        # Ensure partitions
        from .p06_grades import ensure_partitions
        years_in_use = {ay for ay, _ in cc_map.values()}
        ensure_partitions(conn, years_in_use)

        mappers = {
            "students":        LegacyIdMapper(conn, "student.students"),
            "course_classes":  LegacyIdMapper(conn, "academic.course_classes"),
        }

        if settings.ETL_TRUNCATE_BEFORE_LOAD:
            truncate_table(conn, "student.enrollments")

        total = 0
        skipped = 0
        for batch in stream_source(settings.SOURCE_DB_EDU, ENROLLMENT_QUERY, settings.ETL_BATCH_SIZE):
            rows = []
            for src in batch:
                t = transform(src, mappers, cc_map)
                if t is None:
                    skipped += 1
                else:
                    rows.append(t)
            if rows:
                total += copy_rows(conn, "student.enrollments", ENROLLMENT_COLS, rows)
                conn.commit()
            logger.info(f"  ... batch loaded ({total:,} total, {skipped:,} skipped)")

    logger.success(f"✓ student.enrollments: {total:,} rows ({skipped:,} skipped)")
    return total


if __name__ == "__main__":
    from ..log import setup_logging
    setup_logging()
    run()
