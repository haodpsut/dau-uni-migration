"""Pipeline 04: Academic catalog.

Source schemas verified 2026-05-08:
  • DM_NamHoc — academic year (Id, NamHoc int, NienHoc "2008-2009", MaNamHoc)
  • DM_Dot — semester period (Id, TenDot "HK1 - 2025-2026", IDNamHoc, TuThang, DenThang)
  • DM_Nganh — program/major (NOT DT_NganhHoc!)
  • TKB_MonHoc — subject (PK is Id, MaMonHoc, TenMonHoc, SoTinChi, IDToBoMon)
  • TKB_LopHoc — student class (Id, MaLopHoc, TenLopHoc, IDNganh, IDKhoa)
  • TKB_LopHocPhan — course class (Id, MaLopHocPhan, IDMonHoc, IDDot, IDKhoaChuQuan)
  • DT_MonHocTuongDuong — has IDMonHocTuongDuong + IDChiTietKhungHocKy (no direct IDMonHoc)
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from ..config import settings
from ..db import target_conn, fetch_all_dicts, stream_source
from ..load import truncate_table, copy_rows, LegacyIdMapper
from ..log import logger


def _safe_str(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _safe_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# =============================================================================
# Academic years from DM_NamHoc
# =============================================================================

def load_academic_years(conn) -> int:
    src = fetch_all_dicts(
        settings.SOURCE_DB_EDU,
        "SELECT Id, NamHoc, NienHoc, MaNamHoc, TuNgay, DenNgay FROM DM_NamHoc "
        "WHERE IsDelete IS NULL OR IsDelete = 0 ORDER BY NamHoc",
    )
    rows = []
    for r in src:
        nh = _safe_int(r.get("NamHoc"))
        if not nh:
            continue
        rows.append((
            _safe_str(r.get("NienHoc")) or f"{nh}-{nh+1}",
            nh, nh + 1,
            r.get("TuNgay"), r.get("DenNgay"),
            False,
            r["Id"],                                    # legacy_id
        ))
    if settings.ETL_TRUNCATE_BEFORE_LOAD:
        truncate_table(conn, "academic.academic_years")
    # Note: target_schema không có legacy_id ở academic_years — bỏ ra hoặc thêm
    # Để tương thích, ta dùng start_year làm khóa lookup thay legacy_id
    return copy_rows(
        conn, "academic.academic_years",
        ["code", "start_year", "end_year", "start_date", "end_date", "is_current"],
        [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows],
    )


# =============================================================================
# Semesters from DM_Dot
# =============================================================================

# Parse semester number from TenDot like "HK1 - 2025-2026"
_HK_PATTERN = re.compile(r"HK\s*(\d+)", re.IGNORECASE)


def _derive_semester_type(ten_dot: str | None, tu_thang: int | None) -> tuple[str, int]:
    """Returns (semester_type, semester_number)."""
    if ten_dot:
        m = _HK_PATTERN.search(ten_dot)
        if m:
            n = int(m.group(1))
            type_map = {1: "fall", 2: "spring", 3: "summer", 4: "extra"}
            return type_map.get(n, "extra"), n
    # Fallback: derive from TuThang
    if tu_thang:
        if 8 <= tu_thang <= 12:
            return "fall", 1
        if 1 <= tu_thang <= 5:
            return "spring", 2
        if 6 <= tu_thang <= 7:
            return "summer", 3
    return "extra", 4


def load_semesters(conn) -> int:
    src = fetch_all_dicts(
        settings.SOURCE_DB_EDU,
        "SELECT Id, MaDot, TenDot, IDNamHoc, TuThang, DenThang, TuNgay, DenNgay "
        "FROM DM_Dot WHERE (IsDelete IS NULL OR IsDelete = 0) "
        "ORDER BY IDNamHoc, TuThang",
    )
    # Map source IDNamHoc → target academic_year_id (via NamHoc int as key)
    namhoc_src = fetch_all_dicts(
        settings.SOURCE_DB_EDU,
        "SELECT Id, NamHoc FROM DM_NamHoc",
    )
    namhoc_to_year_int = {r["Id"]: r["NamHoc"] for r in namhoc_src if r.get("NamHoc")}
    with conn.cursor() as cur:
        cur.execute("SELECT id, start_year FROM academic.academic_years")
        year_id_by_start = {r["start_year"]: r["id"] for r in cur.fetchall()}

    rows = []
    skipped = 0
    for r in src:
        src_namhoc_id = r.get("IDNamHoc")
        nh_int = namhoc_to_year_int.get(src_namhoc_id)
        ay_id = year_id_by_start.get(nh_int) if nh_int else None
        if not ay_id:
            skipped += 1
            continue
        sem_type, sem_n = _derive_semester_type(r.get("TenDot"), r.get("TuThang"))
        rows.append((
            ay_id, sem_type,
            _safe_str(r.get("MaDot")) or f"HK{sem_n}-{nh_int}",
            _safe_str(r.get("TenDot")) or f"Học kỳ {sem_n}, năm {nh_int}-{nh_int+1}",
            r.get("TuNgay"), r.get("DenNgay"),
            False,
        ))

    if skipped:
        logger.warning(f"Skipped {skipped} semesters with missing year FK")

    if settings.ETL_TRUNCATE_BEFORE_LOAD:
        truncate_table(conn, "academic.semesters")
    n = copy_rows(
        conn, "academic.semesters",
        ["academic_year_id", "semester_type", "code", "name",
         "start_date", "end_date", "is_current"],
        rows,
    )
    # Build legacy_dot_id → semester_id map cached in connection-local table
    # (We can't add a column to academic.semesters without altering schema)
    # Use a temp lookup: semester.code unique per year+type, plus DM_Dot.Id mapping
    return n


def build_dot_to_semester_map(conn) -> dict[int, int]:
    """Map source DM_Dot.Id → target academic.semesters.id by (code, year)."""
    # Re-fetch DM_Dot
    src = fetch_all_dicts(
        settings.SOURCE_DB_EDU,
        "SELECT Id, MaDot, TenDot, IDNamHoc, TuThang FROM DM_Dot",
    )
    namhoc_src = fetch_all_dicts(settings.SOURCE_DB_EDU, "SELECT Id, NamHoc FROM DM_NamHoc")
    namhoc_to_year_int = {r["Id"]: r["NamHoc"] for r in namhoc_src if r.get("NamHoc")}

    # Build target-side map: (start_year, semester_type) → semester.id
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.id AS sem_id, ay.start_year, s.semester_type
            FROM academic.semesters s
            JOIN academic.academic_years ay ON ay.id = s.academic_year_id
        """)
        target_map = {(r["start_year"], r["semester_type"]): r["sem_id"]
                      for r in cur.fetchall()}

    result: dict[int, int] = {}
    for r in src:
        nh_int = namhoc_to_year_int.get(r.get("IDNamHoc"))
        if not nh_int:
            continue
        sem_type, _ = _derive_semester_type(r.get("TenDot"), r.get("TuThang"))
        target_id = target_map.get((nh_int, sem_type))
        if target_id:
            result[r["Id"]] = target_id
    logger.info(f"Built {len(result):,} DM_Dot → semester_id mappings")
    return result


# =============================================================================
# Programs from DM_Nganh
# =============================================================================

def load_programs(conn) -> int:
    """DM_Nganh — verify columns when running. Common: Id, MaNganh, TenNganh, IDKhoa."""
    try:
        src = fetch_all_dicts(
            settings.SOURCE_DB_EDU,
            "SELECT * FROM DM_Nganh WHERE IsDelete IS NULL OR IsDelete = 0",
        )
    except Exception as e:
        logger.warning(f"DM_Nganh query failed: {e}")
        return 0

    dept_map = LegacyIdMapper(conn, "master.departments")

    rows = []
    for r in src:
        # Try multiple possible column names
        legacy_id = r.get("Id") or r.get("IDNganh")
        if not legacy_id:
            continue
        code = _safe_str(r.get("MaNganh")) or _safe_str(r.get("MaCN")) or f"PRG-{legacy_id}"
        name = _safe_str(r.get("TenNganh")) or _safe_str(r.get("Ten")) or "?"
        dept_legacy = r.get("IDKhoa") or r.get("IDPhongBan")
        rows.append((
            code, name,
            _safe_str(r.get("TenNganhTiengAnh")),
            dept_map.lookup(dept_legacy),
            None, None,                                  # specialization, degree
            None, None,                                  # duration, credits
            legacy_id,
        ))

    if settings.ETL_TRUNCATE_BEFORE_LOAD:
        truncate_table(conn, "academic.programs")
    return copy_rows(
        conn, "academic.programs",
        ["code", "name", "name_eng", "department_id", "specialization_id",
         "degree_id", "duration_years", "total_credits", "legacy_id"],
        rows,
    )


# =============================================================================
# Subjects from TKB_MonHoc
# =============================================================================

def load_subjects(conn) -> int:
    """TKB_MonHoc — PK is Id, FK to division via IDToBoMon (NOT IDPhongBan)."""
    src = fetch_all_dicts(
        settings.SOURCE_DB_EDU,
        "SELECT Id, MaMonHoc, MaHocPhan, TenMonHoc, TenVietTatMonHoc, "
        "SoTinChi, SoTinChiLT, SoTinChiTH, IDToBoMon FROM TKB_MonHoc",
    )
    # Subjects FK to divisions, not departments. Adjust target_schema or use NULL here.
    division_map = LegacyIdMapper(conn, "master.divisions")

    rows = []
    skipped = 0
    for r in src:
        credits = _safe_int(r.get("SoTinChi"))
        if not credits or credits < 0:
            skipped += 1
            continue

        # Get department via division → department chain
        division_id = division_map.lookup(r.get("IDToBoMon"))
        department_id = None
        if division_id:
            with conn.cursor() as cur:
                cur.execute("SELECT department_id FROM master.divisions WHERE id = %s", (division_id,))
                row = cur.fetchone()
                department_id = row["department_id"] if row else None

        rows.append((
            _safe_str(r.get("MaMonHoc")) or _safe_str(r.get("MaHocPhan")) or f"SUB-{r['Id']}",
            _safe_str(r.get("TenMonHoc")) or "?",
            None,                                         # name_eng
            credits,
            _safe_int(r.get("SoTinChiLT")),
            _safe_int(r.get("SoTinChiTH")),
            department_id,
            None, True,
            r["Id"],
        ))

    if skipped:
        logger.warning(f"Skipped {skipped} subjects with invalid credits")

    if settings.ETL_TRUNCATE_BEFORE_LOAD:
        truncate_table(conn, "academic.subjects")
    return copy_rows(
        conn, "academic.subjects",
        ["code", "name", "name_eng", "credits_total", "credits_theory", "credits_practice",
         "department_id", "description", "is_active", "legacy_id"],
        rows,
    )


# =============================================================================
# Subject equivalences — schema mismatch — defer to manual SQL post-load
# =============================================================================

def load_subject_equivalences(conn) -> int:
    """DT_MonHocTuongDuong dùng IDChiTietKhungHocKy (FK lạ) thay IDMonHoc trực tiếp.

    Cần JOIN qua DT_ChiTietKhungHocKy.IDMonHoc để biết môn nguồn. Skip ở prototype —
    user có thể viết custom SQL post-load.
    """
    logger.warning("subject_equivalences: defer — schema phức tạp, viết tay sau")
    return 0


# =============================================================================
# Student classes from TKB_LopHoc
# =============================================================================

def load_student_classes(conn) -> int:
    """TKB_LopHoc: Id, MaLopHoc, TenLopHoc, IDNganh, IDKhoa, IDKhoaHoc.

    NO NamVao directly — derive from IDKhoaHoc (cohort).
    """
    src = fetch_all_dicts(
        settings.SOURCE_DB_EDU,
        "SELECT Id, MaLopHoc, TenLopHoc, IDNganh, IDKhoa, IDKhoaHoc "
        "FROM TKB_LopHoc WHERE (IsDelete IS NULL OR IsDelete = 0)",
    )
    program_map = LegacyIdMapper(conn, "academic.programs")
    dept_map = LegacyIdMapper(conn, "master.departments")

    rows = []
    for r in src:
        # admission_year: derive từ IDKhoaHoc nếu có DM_KhoaHoc table riêng,
        # tạm dùng best-guess year hiện tại 2020 (TODO: parse từ TenLopHoc regex)
        # E.g., "21KTPM01" → 2021 = admission_year
        admission_year = 2020
        ten_lop = _safe_str(r.get("TenLopHoc")) or _safe_str(r.get("MaLopHoc")) or ""
        m = re.search(r"^(\d{2})", ten_lop)
        if m:
            yy = int(m.group(1))
            admission_year = 2000 + yy if yy < 50 else 1900 + yy

        rows.append((
            _safe_str(r.get("MaLopHoc")) or f"CLS-{r['Id']}",
            _safe_str(r.get("TenLopHoc")) or "?",
            program_map.lookup(r.get("IDNganh")),
            admission_year,
            None,                                          # advisor_id
            dept_map.lookup(r.get("IDKhoa")),
            True,
            r["Id"],
        ))

    if settings.ETL_TRUNCATE_BEFORE_LOAD:
        truncate_table(conn, "academic.student_classes")
    return copy_rows(
        conn, "academic.student_classes",
        ["code", "name", "program_id", "admission_year", "advisor_id",
         "department_id", "is_active", "legacy_id"],
        rows,
    )


# =============================================================================
# Course classes from TKB_LopHocPhan
# =============================================================================

def load_course_classes(conn) -> int:
    """TKB_LopHocPhan: Id, MaLopHocPhan, IDMonHoc, IDDot, IDKhoaChuQuan, SiSoToiDa.

    Resolve semester via IDDot → DM_Dot → academic_year.
    Lecturer: NS_NhanSu chưa có cột FK trực tiếp — dùng TKB_LichHoc nếu cần.
    """
    if settings.ETL_TRUNCATE_BEFORE_LOAD:
        truncate_table(conn, "academic.course_classes")

    subject_map = LegacyIdMapper(conn, "academic.subjects")
    dot_to_semester = build_dot_to_semester_map(conn)

    total = 0
    skipped = 0
    for batch in stream_source(
        settings.SOURCE_DB_EDU,
        "SELECT Id, MaLopHocPhan, IDMonHoc, IDDot, IDKhoaChuQuan, "
        "SiSoToiDa, SiSoDangKy, GhiChu FROM TKB_LopHocPhan",
        settings.ETL_BATCH_SIZE,
    ):
        rows = []
        for r in batch:
            subject_id = subject_map.lookup(r.get("IDMonHoc"))
            if not subject_id:
                skipped += 1
                continue
            sem_id = dot_to_semester.get(r.get("IDDot"))
            if not sem_id:
                skipped += 1
                continue
            rows.append((
                _safe_str(r.get("MaLopHocPhan")) or f"CC-{r['Id']}",
                subject_id, sem_id,
                None,                                       # primary_lecturer_id
                _safe_int(r.get("SiSoToiDa")),
                _safe_int(r.get("SiSoDangKy")) or 0,
                None, None, False,
                _safe_str(r.get("GhiChu")),
                r["Id"],
            ))
        if rows:
            total += copy_rows(
                conn, "academic.course_classes",
                ["code", "subject_id", "semester_id", "primary_lecturer_id",
                 "capacity", "enrolled_count", "classroom", "schedule_pattern",
                 "is_locked", "notes", "legacy_id"],
                rows,
            )

    logger.info(f"  course_classes: skipped {skipped:,} (orphan FK)")
    return total


# =============================================================================
# Orchestrator
# =============================================================================

def run() -> dict[str, int]:
    results: dict[str, int] = {}
    with target_conn(autocommit=False) as conn:
        for name, fn in [
            ("academic_years", load_academic_years),
            ("semesters", load_semesters),
            ("programs", load_programs),
            ("subjects", load_subjects),
            ("student_classes", load_student_classes),
            ("course_classes", load_course_classes),
            ("subject_equivalences", load_subject_equivalences),
        ]:
            logger.info(f"Loading academic.{name} ...")
            results[name] = fn(conn)

    total = sum(results.values())
    logger.success(f"✓ Academic pipeline complete. Total {total:,} rows")
    for name, count in results.items():
        logger.info(f"  {name}: {count:,}")
    return results


if __name__ == "__main__":
    from ..log import setup_logging
    setup_logging()
    run()
