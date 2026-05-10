"""Pipeline 06: Student grades — slim 153 cols → 33 cols.

Source: EDU_DAU.DT_KetQuaHocTapMonHoc (2,028,965 rows, 153 cols).
Schema verified 2026-05-08 (xem 05-grade-table-column-analysis.md).

Strategy:
  • Map TIER 1+2+3 cols (33 cols thiết yếu) sang student.grades
  • TIER 4 rare cols (~64 cols, <10% used) → extra_scores JSONB
  • TIER 5 dead cols (~50 cols, 0 used) → drop hoàn toàn
  • PARTITIONED by academic_year_id — phải tạo partition trước khi load

Phụ thuộc: students, course_classes, semesters, academic_years phải có sẵn.

Stream để không OOM với 2M rows.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from ..config import settings
from ..db import target_conn, stream_source
from ..load import truncate_table, copy_rows, LegacyIdMapper
from ..log import logger


# Tier 4 — cols rare → JSONB
RARE_SCORE_COLS = (
    [f"DiemHeSo{n}" for n in (12,13,14,15,16,17,18,19,
                              21,22,23,24,25,26,27,28,29,
                              31,32,33,34,35,36,37,38,39)] +
    [f"DiemTH{i}{j}" for i in (1,2,3) for j in (1,2,3,4,5)] +
    [f"DiemThuongKy{i}" for i in range(1, 10)] +
    [f"DiemThucHanh{i}" for i in range(1, 10)] +
    ["DiemChuyenCan2", "DiemTieuLuan2", "DiemThucHanh", "DiemGiuaMon1", "DiemGiuaMon2",
     "PhanTramVang", "DiemNoCu", "GhiChuSuaDiem",
     "DuocDuThiGiuaKy", "KhongDuocDuThiKetThucByGV"]
)


def _safe_decimal(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_str(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _safe_bool(v) -> bool | None:
    if v is None:
        return None
    if v in (1, True, "1", "True"):
        return True
    if v in (0, False, "0", "False"):
        return False
    return None


def _safe_dt(v) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime.combine(v, datetime.min.time())
    return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "__float__"):
        try:
            return float(value)
        except Exception:
            return str(value)
    return value


# =============================================================================
# Partition management
# =============================================================================

def ensure_partitions(conn, years: set[int]) -> None:
    """Tạo partition cho từng academic_year_id còn thiếu.

    Note: academic_year_id ở đây là Postgres ID, nhưng partition value cần là
    integer literal. Dùng academic_year.id của Postgres làm partition key.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM academic.academic_years")
        existing_year_ids = {r["id"] for r in cur.fetchall()}

        for ay_id in sorted(years):
            if ay_id not in existing_year_ids:
                logger.warning(f"academic_year id={ay_id} chưa có — tạo partition vẫn ok nhưng FK sẽ orphan")

            # Tạo partition cho enrollments + grades
            for tbl in ("student.enrollments", "student.grades"):
                schema, name = tbl.split(".")
                part_name = f"{name}_y{ay_id}"
                cur.execute(
                    f"SELECT to_regclass('{schema}.{part_name}') AS exists_check"
                )
                if cur.fetchone()["exists_check"] is None:
                    cur.execute(
                        f"CREATE TABLE {schema}.{part_name} "
                        f"PARTITION OF {tbl} FOR VALUES IN ({ay_id})"
                    )
                    logger.info(f"Created partition {schema}.{part_name}")


# =============================================================================
# Source query
# =============================================================================

GRADE_QUERY = """
    SELECT
        Id,
        IDSinhVien, IDLopHocPhan,
        DiemChuyenCan1, DiemHeSo11,
        DiemTBThuongKy, DiemTBThucHanh, DiemTieuLuan1,
        DiemThi, DiemThi1, DiemThi2,
        DiemTongKet, DiemTongKet1, DiemTongKet2,
        DiemChu, DiemChu2, XepLoai_ENG, XepLoai,
        DiemTinChi, DiemTinChi2,
        IsDat, IsDat1, DuocDuThiKetThuc, VangThi, IsVangThiGiuaKy,
        IsKhoaTH, IsKhoaTL, IsKhoaCK,
        GhiChu, GhiChuXetDuThi,
        NgayTao, NguoiTao, NgayCapNhat, NguoiCapNhat,
        -- Rare cols for JSONB (chỉ pull nếu cần — bỏ qua cho prototype để giảm I/O)
        DiemChuyenCan2, DiemTieuLuan2, PhanTramVang, DiemNoCu, GhiChuSuaDiem
    FROM DT_KetQuaHocTapMonHoc WITH(NOLOCK)
    ORDER BY Id
"""


GRADE_COLS = [
    "legacy_id",
    "student_id", "course_class_id",
    "academic_year_id",                     # MUST be set — partition key
    "semester_id",
    "attendance_score", "weighted_score_1",
    "regular_avg_score", "practice_avg", "essay_score",
    "final_exam_score", "final_exam_score_retake1", "final_exam_score_retake2",
    "overall_score", "overall_score_retake1", "overall_score_retake2",
    "letter_grade_native", "letter_grade_alt",
    "letter_grade_eng", "letter_grade_vn",
    "grade_point", "grade_point_alt",
    "is_passed", "is_passed_retake1", "is_eligible_for_final",
    "is_absent_from_exam", "is_absent_from_midterm",
    "is_practice_locked", "is_essay_locked", "is_final_locked",
    "notes", "eligibility_notes", "extra_scores",
    "created_at", "created_by", "updated_at", "updated_by",
]


def transform_grade(src: dict, mappers: dict[str, LegacyIdMapper],
                     course_class_to_year_semester: dict[int, tuple[int, int]]) -> tuple | None:
    """Returns tuple matching GRADE_COLS, or None nếu không resolve được FK."""
    student_id = mappers["students"].lookup(src.get("IDSinhVien"))
    course_class_id = mappers["course_classes"].lookup(src.get("IDLopHocPhan"))
    if not student_id or not course_class_id:
        return None

    ay_sem = course_class_to_year_semester.get(course_class_id)
    if not ay_sem:
        return None
    academic_year_id, semester_id = ay_sem

    # Build extra_scores JSONB từ rare cols (only non-null)
    extra: dict = {}
    for k in RARE_SCORE_COLS:
        v = src.get(k)
        if v is None:
            continue
        s = _json_safe(v)
        if s is None or (isinstance(s, str) and not s.strip()):
            continue
        extra[k] = s

    return (
        src["Id"],                                          # legacy_id
        student_id, course_class_id, academic_year_id, semester_id,
        _safe_decimal(src.get("DiemChuyenCan1")),
        _safe_decimal(src.get("DiemHeSo11")),
        _safe_decimal(src.get("DiemTBThuongKy")),
        _safe_decimal(src.get("DiemTBThucHanh")),
        _safe_decimal(src.get("DiemTieuLuan1")),
        _safe_decimal(src.get("DiemThi")),
        _safe_decimal(src.get("DiemThi1")),
        _safe_decimal(src.get("DiemThi2")),
        _safe_decimal(src.get("DiemTongKet")),
        _safe_decimal(src.get("DiemTongKet1")),
        _safe_decimal(src.get("DiemTongKet2")),
        _safe_str(src.get("DiemChu")),
        _safe_str(src.get("DiemChu2")),
        _safe_str(src.get("XepLoai_ENG")),
        _safe_str(src.get("XepLoai")),
        _safe_decimal(src.get("DiemTinChi")),
        _safe_decimal(src.get("DiemTinChi2")),
        _safe_bool(src.get("IsDat")) or False,
        _safe_bool(src.get("IsDat1")),
        _safe_bool(src.get("DuocDuThiKetThuc")),
        _safe_bool(src.get("VangThi")) or False,
        _safe_bool(src.get("IsVangThiGiuaKy")),
        _safe_bool(src.get("IsKhoaTH")) or False,
        _safe_bool(src.get("IsKhoaTL")) or False,
        _safe_bool(src.get("IsKhoaCK")) or False,
        _safe_str(src.get("GhiChu")),
        _safe_str(src.get("GhiChuXetDuThi")),
        json.dumps(extra, ensure_ascii=False) if extra else None,
        _safe_dt(src.get("NgayTao")) or datetime.now(),
        None,                                               # created_by - resolve sau
        _safe_dt(src.get("NgayCapNhat")) or _safe_dt(src.get("NgayTao")) or datetime.now(),
        None,
    )


def run() -> int:
    logger.info("Loading student.grades from EDU_DAU.DT_KetQuaHocTapMonHoc ...")

    with target_conn() as conn:
        # Build map course_class_id → (academic_year_id, semester_id)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT cc.id AS course_class_id, s.academic_year_id, cc.semester_id
                FROM academic.course_classes cc
                JOIN academic.semesters s ON s.id = cc.semester_id
            """)
            cc_map: dict[int, tuple[int, int]] = {
                r["course_class_id"]: (r["academic_year_id"], r["semester_id"])
                for r in cur.fetchall()
            }
        logger.info(f"Loaded {len(cc_map):,} course class → year/semester mappings")

        # Ensure partitions exist for all years
        years_in_use = {ay for ay, _ in cc_map.values()}
        ensure_partitions(conn, years_in_use)

        mappers = {
            "students":      LegacyIdMapper(conn, "student.students"),
            "course_classes": LegacyIdMapper(conn, "academic.course_classes"),
        }

        if settings.ETL_TRUNCATE_BEFORE_LOAD:
            truncate_table(conn, "student.grades")

        # Stream từ source theo batch
        total = 0
        skipped = 0
        for batch in stream_source(settings.SOURCE_DB_EDU, GRADE_QUERY, settings.ETL_BATCH_SIZE):
            rows = []
            for src in batch:
                t = transform_grade(src, mappers, cc_map)
                if t is None:
                    skipped += 1
                else:
                    rows.append(t)
            if rows:
                total += copy_rows(conn, "student.grades", GRADE_COLS, rows)
                conn.commit()
            logger.info(f"  ... batch loaded ({total:,} total, {skipped:,} skipped)")

    logger.success(f"✓ student.grades: {total:,} rows ({skipped:,} skipped due to missing FKs)")
    return total


if __name__ == "__main__":
    from ..log import setup_logging
    setup_logging()
    run()
