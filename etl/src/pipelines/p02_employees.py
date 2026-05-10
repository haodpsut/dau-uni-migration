"""Pipeline 02: HR Employees.

Source: HRM_DAU.NS_NhanSu (1024 rows, 238 cột) → hr.employees (~30 cột thiết yếu).

Phụ thuộc: master pipeline (p01) phải xong trước.

Schema thực tế của NS_NhanSu (verified 2026-05-08):
  • PK: IDNhanSu
  • Tên: HoDem + Ten (riêng) → ghép thành full_name
  • Date of birth: NgaySinh
  • Gender: GioiTinh (bit: 1=nam, 0=nữ)
  • CCCD: SoCMND, NgayCapCMND, NoiCapCMND
  • Phones: SoDienThoai, SoDiDong
  • Emails: Email, Email2
  • Addresses: HoKhau (text), NoiOHienTai (text), HKTT_IDTinh/IDHuyen/IDPhuongXa, DCLH_*
  • Refs: DanToc (int), TonGiao (int), QuocTich (int), TinhTrangHonNhan (int)
  • Work: HienTaiPhongBan, HienTaiChucVu, IDChucDanh, HienTaiLoaiHopDong
  • Education: HocVi, HocHam, ChuyenNganh
  • Status flags: DaChamDutHopDong, DaVeHuu, IsThoiViec
  • Dates: NgayBatDauGiangDay, NgayChamDutHopDong, NgayKyHDLD
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from ..config import settings
from ..db import target_conn, fetch_all_dicts
from ..load import truncate_table, copy_rows, LegacyIdMapper
from ..log import logger


# Cột "core" — đã map vào column riêng của hr.employees
CORE_COLS = {
    "IDNhanSu", "MaNhanSu", "HoDem", "Ten", "NgaySinh", "NoiSinh", "GioiTinh",
    "SoCMND", "NgayCapCMND", "NoiCapCMND", "SoDienThoai", "SoDiDong", "Email",
    "Email2", "HoKhau", "NoiOHienTai", "HKTT_IDTinh", "HKTT_IDHuyen",
    "HKTT_IDPhuongXa", "HKTT_ThonXom", "DanToc", "TonGiao", "QuocTich",
    "TinhTrangHonNhan", "HienTaiPhongBan", "HienTaiChucVu", "IDChucDanh",
    "HienTaiLoaiHopDong", "HocVi", "HocHam", "ChuyenNganh",
    "NgayBatDauGiangDay", "NgayChamDutHopDong", "NgayKyHDLD",
    "DaChamDutHopDong", "DaVeHuu", "IsThoiViec",
}

AUDIT_COLS = {"NguoiTao", "NgayTao", "NguoiCapNhat", "NgayCapNhat"}

# Cột BLOB / nhị phân — không bỏ vào JSONB
BLOB_COLS = {"Anh", "AnhHocVi", "CCKhuonMat", "CCNgon1", "CCNgon2"}

# Cột password — KHÔNG bỏ vào JSONB (security)
SECURITY_COLS = {"Passwords", "Passwords2", "PasswordKey", "CCMatKhau"}


# =============================================================================
# Helpers
# =============================================================================

def _safe_str(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _to_gender(v) -> str | None:
    """GioiTinh: bit. 1=nam, 0=nữ."""
    if v is None:
        return None
    if v in (1, True, "1", "True"):
        return "male"
    if v in (0, False, "0", "False"):
        return "female"
    return None


def _to_marital(v) -> str | None:
    """TinhTrangHonNhan int. Vendor lookup table không có sẵn — best-guess."""
    if v is None:
        return None
    mapping = {1: "single", 2: "married", 3: "divorced", 4: "widowed"}
    try:
        return mapping.get(int(v))
    except (ValueError, TypeError):
        return None


def _to_date(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
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
        return None  # skip BLOB
    return value


def _join_name(ho_dem: str | None, ten: str | None) -> str:
    parts = [_safe_str(ho_dem), _safe_str(ten)]
    return " ".join(p for p in parts if p) or "?"


# =============================================================================
# Source query — verbose để dễ debug
# =============================================================================

NS_NHAN_SU_QUERY = """
    SELECT *
    FROM NS_NhanSu
    ORDER BY IDNhanSu
"""


def fetch_employees() -> list[dict]:
    return fetch_all_dicts(settings.SOURCE_DB_HRM, NS_NHAN_SU_QUERY)


def transform_employee(src: dict, mappers: dict[str, LegacyIdMapper]) -> tuple:
    legacy_id = src["IDNhanSu"]

    # Resolve FKs
    department_id = mappers["departments"].lookup(src.get("HienTaiPhongBan"))
    position_id = mappers["positions"].lookup(src.get("HienTaiChucVu"))
    title_id = mappers["titles"].lookup(src.get("IDChucDanh"))
    degree_id = mappers["degrees"].lookup(src.get("HocVi"))
    academic_rank_id = mappers["academic_ranks"].lookup(src.get("HocHam"))
    specialization_id = mappers["specializations"].lookup(src.get("ChuyenNganh"))
    nationality_id = mappers["countries"].lookup(src.get("QuocTich"))
    ethnicity_id = mappers["ethnicities"].lookup(src.get("DanToc"))
    religion_id = mappers["religions"].lookup(src.get("TonGiao"))

    # Build extra_info from non-core, non-audit, non-blob, non-security cols
    extra: dict = {}
    skip = CORE_COLS | AUDIT_COLS | BLOB_COLS | SECURITY_COLS
    for k, v in src.items():
        if k in skip or v is None:
            continue
        s = _json_safe(v)
        if s is None or (isinstance(s, str) and not s.strip()):
            continue
        extra[k] = s

    return (
        # employee_code, legacy_id
        _safe_str(src.get("MaNhanSu")) or f"NS-{legacy_id}",
        legacy_id,

        # Personal
        _join_name(src.get("HoDem"), src.get("Ten")),
        _to_gender(src.get("GioiTinh")),
        _to_date(src.get("NgaySinh")),
        None,                                                # place_of_birth_id (text-only in source)
        _safe_str(src.get("SoCMND")),
        _to_date(src.get("NgayCapCMND")),
        _safe_str(src.get("NoiCapCMND")),

        # Refs
        nationality_id,
        ethnicity_id,
        religion_id,
        _to_marital(src.get("TinhTrangHonNhan")),

        # Contact
        _safe_str(src.get("Email")),
        _safe_str(src.get("Email2")),
        _safe_str(src.get("SoDienThoai")),
        _safe_str(src.get("SoDiDong")),

        # Address
        _safe_str(src.get("HoKhau")),
        None,                                                # permanent_ward_id (resolve later)
        _safe_str(src.get("NoiOHienTai")),
        None,                                                # current_ward_id (resolve later)

        # Work
        department_id,
        None,                                                # division_id (NS_NhanSu không có cột bộ môn rõ)
        position_id,
        title_id,
        None,                                                # civil_rank_id (NS_NhanSu không có)
        None,                                                # employment_type (derive từ HienTaiLoaiHopDong)

        # Education
        degree_id,
        academic_rank_id,
        specialization_id,

        # Employment dates
        _to_date(src.get("NgayBatDauGiangDay")) or _to_date(src.get("NgayKyHDLD")),
        _to_date(src.get("NgayChamDutHopDong")),

        # Photo
        None,                                                # photo_url — pipeline files sẽ set
        None,                                                # photo_uploaded_at

        # Extras
        json.dumps(extra, ensure_ascii=False) if extra else None,

        # Audit
        None,                                                # created_by
        None,                                                # updated_by
    )


EMPLOYEE_COLS = [
    "employee_code", "legacy_id",
    "full_name", "gender", "date_of_birth", "place_of_birth_id",
    "citizen_id", "citizen_id_issued_date", "citizen_id_issued_place",
    "nationality_id", "ethnicity_id", "religion_id", "marital_status",
    "email", "email_personal", "phone", "phone_alt",
    "permanent_address", "permanent_ward_id", "current_address", "current_ward_id",
    "department_id", "division_id", "position_id", "title_id", "civil_rank_id",
    "employment_type",
    "highest_degree_id", "academic_rank_id", "primary_specialization_id",
    "join_date", "leave_date",
    "photo_url", "photo_uploaded_at",
    "extra_info",
    "created_by", "updated_by",
]


def run() -> int:
    logger.info("Loading hr.employees from HRM_DAU.NS_NhanSu ...")

    with target_conn() as conn:
        mappers = {
            "departments":     LegacyIdMapper(conn, "master.departments"),
            "positions":       LegacyIdMapper(conn, "master.positions"),
            "titles":          LegacyIdMapper(conn, "master.titles"),
            "degrees":         LegacyIdMapper(conn, "master.degrees"),
            "academic_ranks":  LegacyIdMapper(conn, "master.academic_ranks"),
            "specializations": LegacyIdMapper(conn, "master.specializations"),
            "countries":       LegacyIdMapper(conn, "master.countries"),
            "ethnicities":     LegacyIdMapper(conn, "master.ethnicities"),
            "religions":       LegacyIdMapper(conn, "master.religions"),
        }

        src_rows = fetch_employees()
        logger.info(f"Fetched {len(src_rows):,} employees from source")

        rows = [transform_employee(r, mappers) for r in src_rows]

        if settings.ETL_TRUNCATE_BEFORE_LOAD:
            truncate_table(conn, "hr.employees")
        n = copy_rows(conn, "hr.employees", EMPLOYEE_COLS, rows)

    logger.success(f"✓ hr.employees: {n:,} rows loaded")
    return n


if __name__ == "__main__":
    from ..log import setup_logging
    setup_logging()
    run()
