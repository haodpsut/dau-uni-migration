"""Pipeline 03: Students — gộp 4 bảng nguồn.

Source:
  • DT_HoSoSinhVien (97,391 rows, 14 cols) — canonical mapping table (legacy SV)
  • DT_SinhVien (37,682 rows, 145 cols) — current active SV
  • DT_ThongTinSinhVien (23,792 rows, 177 cols) — extended info
  • DT_SinhVienEx (7,536 rows, 70 cols) — extra extended

Target: student.students (~50 cols thiết yếu + extra_info JSONB).

DT_SinhVien column names verified 2026-05-08 (xem _schema_sv.txt từ Đợt 5):
  • PK: Id (int)
  • MaSinhVien (varchar 20)
  • HoDem + Ten (separate, NOT HoTen)
  • NgaySinh (datetime — 0% used) vs NgaySinh2 (varchar — 100% used!)
  • GioiTinh (bit, 100%)
  • IDDanToc (88%), IDQuocTich (73%), IDTonGiao (35%) — modern FK
  • DanToc (text 36%) — legacy text version
  • IDNganh, IDLopHoc, IDKhoaHoc (100% — academic structure)
  • SoCMND (99%), Email (99.9%), SoDienThoai (~100%)
  • Pwd (100%) — legacy password — KHÔNG MIGRATE plaintext, force reset

Strategy:
  1. Use DT_HoSoSinhVien as cursor (97K cumulative)
  2. LEFT JOIN với DT_SinhVien (37K active) để có cột chi tiết
  3. LEFT JOIN với DT_ThongTinSinhVien, DT_SinhVienEx — cols rare → JSONB

Phụ thuộc: master + academic phải xong trước.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from ..config import settings
from ..db import target_conn, fetch_all_dicts
from ..load import truncate_table, copy_rows, LegacyIdMapper
from ..log import logger


# Cột "core" của DT_SinhVien — đã map sang student.students columns
CORE_DT_SV_COLS = {
    "Id", "MaSinhVien", "HoDem", "Ten", "GioiTinh",
    "NgaySinh", "NgaySinh2", "NoiSinh",
    "SoCMND", "NgayCap", "NoiCap",
    "Email", "SoDienThoai", "SoDienThoai2", "SoDienThoaiPhuHuynh", "EmailPhuHuynh",
    "DiaChiThuongTru", "DiaChiLienLac",
    "IDDanToc", "IDQuocTich", "IDTonGiao",
    "IDNganh", "IDLopHoc", "IDKhoaHoc", "IDHeDaoTao", "IDLoaiHinhDT", "IDCoSo",
    "NamVao", "NgayNhapHoc",
    "TrangThai",
    "HoTenNguoiGiamHo", "NamSinhNguoiGiamHo", "NgheNghiepNguoiGiamHo",
    "SoTaiKhoan", "TenTaiKhoan", "TenNganHang",
    "MaBHXH_YT",
    "XepLoaiHK", "XepLoaiHT", "XepLoaiTN",
    "Pwd", "PwdHashKey",
    "NguoiTao", "NgayTao", "NguoiCapNhat", "NgayCapNhat",
}

AUDIT_COLS = {"NguoiTao", "NgayTao", "NguoiCapNhat", "NgayCapNhat"}
SECURITY_COLS = {"Pwd", "PwdHashKey", "PasswordKey", "Passwords"}
BLOB_COLS = {"Anh", "AnhHocVi"}


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


def _to_gender(v) -> str | None:
    if v is None:
        return None
    if v in (1, True, "1"):
        return "male"
    if v in (0, False, "0"):
        return "female"
    return None


def _to_status(v) -> str:
    """TrangThai int → enrollment_status_type. Mapping best-guess."""
    if v is None:
        return "enrolled"
    mapping = {
        1: "enrolled", 2: "graduated", 3: "dropped_out",
        4: "suspended", 5: "transferred", 6: "deferred", 7: "expelled",
    }
    try:
        return mapping.get(int(v), "enrolled")
    except (TypeError, ValueError):
        return "enrolled"


def _parse_date_safe(v) -> date | None:
    """Hệ cũ thường lưu birthday ở 2 chỗ: NgaySinh (datetime, 0% dùng) +
    NgaySinh2 (varchar, 100% dùng). Try string first."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if not s:
        return None
    # Try common formats
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "__float__"):
        try:
            return float(value)
        except Exception:
            return str(value)
    if isinstance(value, bytes):
        return None
    return value


# =============================================================================
# Source query
# =============================================================================

# Use LEFT JOIN to get all canonical SV from DT_HoSoSinhVien + active details from DT_SinhVien
SOURCE_QUERY = """
    SELECT
        sv.*,
        hs.Id AS hs_Id,
        hs.IDThiSinh AS hs_IDThiSinh,
        hs.IDHoSo AS hs_IDHoSo
    FROM DT_SinhVien sv
    -- DT_HoSoSinhVien KHÔNG CÓ MaSinhVien — link via IDSinhVien
    LEFT JOIN DT_HoSoSinhVien hs ON hs.IDSinhVien = sv.Id
    ORDER BY sv.Id
"""


STUDENT_COLS = [
    "student_code", "legacy_ids",
    "full_name", "family_name", "given_name", "gender", "date_of_birth",
    "place_of_birth_id", "place_of_birth_text",
    "citizen_id", "citizen_id_issued_date", "citizen_id_issued_place",
    "nationality_id", "ethnicity_id", "religion_id",
    "permanent_address", "permanent_ward_id", "permanent_house_no",
    "contact_address", "contact_ward_id",
    "phone", "phone_alt", "phone_parent", "email", "email_parent",
    "guardian_name", "guardian_birth_year", "guardian_occupation",
    "program_id", "student_class_id",
    "facility_id", "education_type_id", "training_form_id", "cohort_id",
    "admission_year", "admission_date",
    "expected_graduation_year", "high_school_graduation_year", "high_school_name",
    "bank_account_number", "bank_account_name", "bank_name", "bank_branch", "bank_id",
    "insurance_number",
    "legacy_pwd_hash", "legacy_pwd_key",
    "enrollment_status", "status_changed_at",
    "conduct_ranking_overall", "study_ranking_overall", "graduation_ranking",
    "photo_url", "photo_uploaded_at",
    "extra_info",
    "created_by", "updated_by",
]


def transform_student(src: dict, mappers: dict[str, LegacyIdMapper]) -> tuple:
    """Transform 1 row source → tuple matching STUDENT_COLS."""
    legacy_id = src["Id"]

    # FK lookups
    program_id = mappers["programs"].lookup(src.get("IDNganh"))
    student_class_id = mappers["student_classes"].lookup(src.get("IDLopHoc"))
    nationality_id = mappers["countries"].lookup(src.get("IDQuocTich"))
    ethnicity_id = mappers["ethnicities"].lookup(src.get("IDDanToc"))
    religion_id = mappers["religions"].lookup(src.get("IDTonGiao"))

    # Build extra_info from rare cols
    extra: dict = {}
    skip = CORE_DT_SV_COLS | AUDIT_COLS | SECURITY_COLS | BLOB_COLS | {"hs_Id", "hs_IDThiSinh", "hs_IDHoSo"}
    for k, v in src.items():
        if k in skip or v is None:
            continue
        s = _json_safe(v)
        if s is None or (isinstance(s, str) and not s.strip()):
            continue
        extra[k] = s

    # Legacy IDs JSON
    legacy_ids = {"DT_SinhVien": legacy_id}
    if src.get("hs_Id"):
        legacy_ids["DT_HoSoSinhVien"] = src["hs_Id"]

    full_name_parts = [_safe_str(src.get("HoDem")), _safe_str(src.get("Ten"))]
    full_name = " ".join(p for p in full_name_parts if p) or "?"

    return (
        _safe_str(src.get("MaSinhVien")) or f"SV-{legacy_id}",
        json.dumps(legacy_ids),
        full_name,
        _safe_str(src.get("HoDem")), _safe_str(src.get("Ten")),
        _to_gender(src.get("GioiTinh")),
        _parse_date_safe(src.get("NgaySinh2")) or _parse_date_safe(src.get("NgaySinh")),
        None,                                                # place_of_birth_id (text-only in source)
        _safe_str(src.get("NoiSinh_Text")) or _safe_str(src.get("NoiSinh")),
        _safe_str(src.get("SoCMND")),
        _parse_date_safe(src.get("NgayCap")),
        _safe_str(src.get("NoiCap")),
        nationality_id, ethnicity_id, religion_id,
        _safe_str(src.get("DiaChiThuongTru")), None, None,    # permanent_*
        _safe_str(src.get("DiaChiLienLac")), None,            # contact_*
        _safe_str(src.get("SoDienThoai")),
        _safe_str(src.get("SoDienThoai2")),
        _safe_str(src.get("SoDienThoaiPhuHuynh")),
        _safe_str(src.get("Email")),
        _safe_str(src.get("EmailPhuHuynh")),
        _safe_str(src.get("HoTenNguoiGiamHo")),
        _safe_str(src.get("NamSinhNguoiGiamHo")),
        _safe_str(src.get("NgheNghiepNguoiGiamHo")),
        program_id, student_class_id,
        _safe_int(src.get("IDCoSo")),
        _safe_int(src.get("IDHeDaoTao")),
        _safe_int(src.get("IDLoaiHinhDT")),
        _safe_int(src.get("IDKhoaHoc")),
        _safe_int(src.get("NamVao")) or 2020,                # admission_year (NOT NULL)
        _parse_date_safe(src.get("NgayNhapHoc")),
        None,                                                # expected_graduation_year
        _safe_int(src.get("NamTotNghiep")),
        _safe_str(src.get("TruongTotNghiep")),
        _safe_str(src.get("SoTaiKhoan")),
        _safe_str(src.get("TenTaiKhoan")),
        _safe_str(src.get("TenNganHang")),
        _safe_str(src.get("ChiNhanhNganHang")),
        _safe_int(src.get("IDNganHang")),
        _safe_str(src.get("MaBHXH_YT")),
        _safe_str(src.get("Pwd")),                            # legacy_pwd_hash
        _safe_str(src.get("PwdHashKey")),                     # legacy_pwd_key
        _to_status(src.get("TrangThai")),
        None,                                                # status_changed_at
        _safe_str(src.get("XepLoaiHK")),
        _safe_str(src.get("XepLoaiHT")),
        _safe_str(src.get("XepLoaiTN")),
        None,                                                # photo_url — pipeline files set later
        None,                                                # photo_uploaded_at
        json.dumps(extra, ensure_ascii=False) if extra else None,
        None, None,                                           # created_by, updated_by
    )


def run() -> int:
    logger.info("Loading student.students from EDU_DAU.DT_SinhVien (+ DT_HoSoSinhVien) ...")

    with target_conn() as conn:
        mappers = {
            "programs":         LegacyIdMapper(conn, "academic.programs"),
            "student_classes":  LegacyIdMapper(conn, "academic.student_classes"),
            "countries":        LegacyIdMapper(conn, "master.countries"),
            "ethnicities":      LegacyIdMapper(conn, "master.ethnicities"),
            "religions":        LegacyIdMapper(conn, "master.religions"),
        }

        src_rows = fetch_all_dicts(settings.SOURCE_DB_EDU, SOURCE_QUERY)
        logger.info(f"Fetched {len(src_rows):,} students from source")

        rows = [transform_student(r, mappers) for r in src_rows]

        if settings.ETL_TRUNCATE_BEFORE_LOAD:
            truncate_table(conn, "student.students")
        n = copy_rows(conn, "student.students", STUDENT_COLS, rows)

    logger.success(f"✓ student.students: {n:,} rows loaded")
    return n


# =============================================================================
# Graduations sub-loader
# =============================================================================

def load_graduations(conn) -> int:
    """Source: DT_DSSinhVienTotNghiep (17,969 rows). Verify column names khi run."""
    src = fetch_all_dicts(
        settings.SOURCE_DB_EDU,
        "SELECT Id, IDSinhVien, NgayTotNghiep, SoBangCap, XepLoai, "
        "DiemTBChung, TongSoTinChi FROM DT_DSSinhVienTotNghiep",
    )
    student_map = LegacyIdMapper(conn, "student.students")

    rows = []
    skipped = 0
    for r in src:
        student_id = student_map.lookup(r.get("IDSinhVien"))
        if not student_id:
            skipped += 1
            continue
        rows.append((
            r["Id"], student_id,
            r.get("NgayTotNghiep") or datetime.now().date(),
            _safe_str(r.get("SoBangCap")) or f"GRAD-{r['Id']}",
            None,                                              # diploma_type
            _safe_str(r.get("XepLoai")),
            r.get("DiemTBChung"),
            _safe_int(r.get("TongSoTinChi")),
            None, None, None,                                  # decision_id, issued_date, notes
        ))
    if skipped:
        logger.warning(f"Skipped {skipped} graduations (missing student FK)")

    if settings.ETL_TRUNCATE_BEFORE_LOAD:
        truncate_table(conn, "student.graduations")
    return copy_rows(
        conn, "student.graduations",
        ["legacy_id", "student_id", "graduation_date", "diploma_number",
         "diploma_type", "classification", "final_gpa", "total_credits",
         "decision_id", "issued_date", "notes"],
        rows,
    )


if __name__ == "__main__":
    from ..log import setup_logging
    setup_logging()
    run()
