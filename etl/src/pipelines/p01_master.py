"""Pipeline 01: Master data.

Load thứ tự (do FK chain): countries/ethnicities/religions/depts (no deps) →
provinces → districts → wards → divisions/positions/titles/degrees/ranks/specs/
contract_types/decision_types.

Source: HRM_DAU.DM_* — column names verified against actual schema 2026-05-08.

Note quan trọng:
  • Vendor ASCVN dùng cả 2 PK pattern: 'Id' (DM_DanToc, DM_HocVi, ...) và
    'ID*' (IDQuocGia, IDChucVu, IDPhongBan, ...). Phải check từng bảng.
  • DM_BH_Xa KHÔNG có IDHuyen FK — chỉ có text codes (MaTinh, MaHuyen, MaXa).
    Phải join qua text code khi resolve FK.
  • DM_PhongBan KHÔNG có column parent — không có cấu trúc cây trong source.
"""

from __future__ import annotations

from typing import Callable

from ..config import settings
from ..db import target_conn, fetch_all_dicts
from ..load import truncate_table, copy_rows, LegacyIdMapper
from ..log import logger


# =============================================================================
# Helpers
# =============================================================================

def _safe_str(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _gen_code(prefix: str, legacy_id: int) -> str:
    return f"{prefix}-{legacy_id}"


# =============================================================================
# Independent tables (no FK)
# =============================================================================

def load_countries(conn) -> int:
    """HRM_DAU.DM_QuocGia → master.countries.

    Source: IDQuocGia, MaQuocGia, TenQuocGia, VietTat
    """
    src = fetch_all_dicts(
        settings.SOURCE_DB_HRM,
        "SELECT IDQuocGia, MaQuocGia, TenQuocGia FROM DM_QuocGia ORDER BY IDQuocGia",
    )
    rows = [
        (
            _safe_str(r.get("MaQuocGia")) or _gen_code("Q", r["IDQuocGia"]),
            _safe_str(r.get("TenQuocGia")) or "?",
            None,                                            # name_native
            r["IDQuocGia"],
        )
        for r in src
    ]
    if settings.ETL_TRUNCATE_BEFORE_LOAD:
        truncate_table(conn, "master.countries")
    return copy_rows(conn, "master.countries", ["code", "name", "name_native", "legacy_id"], rows)


def load_ethnicities(conn) -> int:
    """HRM_DAU.DM_DanToc → master.ethnicities. PK is 'Id'."""
    src = fetch_all_dicts(
        settings.SOURCE_DB_HRM,
        "SELECT Id, MaDanToc, TenDanToc FROM DM_DanToc ORDER BY Id",
    )
    rows = [
        (
            _safe_str(r.get("MaDanToc")) or _gen_code("D", r["Id"]),
            _safe_str(r.get("TenDanToc")) or "?",
            r["Id"],
        )
        for r in src
    ]
    if settings.ETL_TRUNCATE_BEFORE_LOAD:
        truncate_table(conn, "master.ethnicities")
    return copy_rows(conn, "master.ethnicities", ["code", "name", "legacy_id"], rows)


def load_religions(conn) -> int:
    """HRM_DAU.DM_TonGiao → master.religions. PK is 'Id'."""
    src = fetch_all_dicts(
        settings.SOURCE_DB_HRM,
        "SELECT Id, MaTonGiao, TenTonGiao FROM DM_TonGiao ORDER BY Id",
    )
    rows = [(_safe_str(r.get("TenTonGiao")) or f"?-{r['Id']}", r["Id"]) for r in src]
    if settings.ETL_TRUNCATE_BEFORE_LOAD:
        truncate_table(conn, "master.religions")
    return copy_rows(conn, "master.religions", ["name", "legacy_id"], rows)


def load_departments(conn) -> int:
    """HRM_DAU.DM_PhongBan → master.departments.

    Source: IDPhongBan (PK), MaPhongBan, TenPhongBan, VietTat, LoaiPhongBan, IDPhongBanCu.
    Source KHÔNG CÓ parent_id — flat list. Set department_type from LoaiPhongBan.
    """
    src = fetch_all_dicts(
        settings.SOURCE_DB_HRM,
        "SELECT IDPhongBan, MaPhongBan, TenPhongBan, VietTat, LoaiPhongBan "
        "FROM DM_PhongBan ORDER BY IDPhongBan",
    )
    # Map LoaiPhongBan int → readable string
    type_map = {1: "khoa", 2: "phong", 3: "trung_tam", 4: "vien", 5: "ban"}

    rows = [
        (
            _safe_str(r.get("MaPhongBan")) or _gen_code("P", r["IDPhongBan"]),
            _safe_str(r.get("TenPhongBan")) or "?",
            _safe_str(r.get("VietTat")),
            None,                                            # parent_id (no source data)
            type_map.get(r.get("LoaiPhongBan")),
            r["IDPhongBan"],
        )
        for r in src
    ]
    if settings.ETL_TRUNCATE_BEFORE_LOAD:
        truncate_table(conn, "master.departments")
    return copy_rows(
        conn, "master.departments",
        ["code", "name", "name_short", "parent_id", "department_type", "legacy_id"],
        rows,
    )


# =============================================================================
# Provinces → districts → wards (FK chain — DM_BH_Xa via TEXT code, not ID!)
# =============================================================================

def load_provinces(conn) -> int:
    """HRM_DAU.DM_TinhThanh → master.provinces.

    Source: IDTinhThanh, MaTinhThanh, TenTinhThanh, VietTat, GhiChu.
    KHÔNG có cột "miền" (region) — set NULL, derive sau.
    """
    src = fetch_all_dicts(
        settings.SOURCE_DB_HRM,
        "SELECT IDTinhThanh, MaTinhThanh, TenTinhThanh FROM DM_TinhThanh ORDER BY IDTinhThanh",
    )
    rows = [
        (
            _safe_str(r.get("MaTinhThanh")) or _gen_code("T", r["IDTinhThanh"]),
            _safe_str(r.get("TenTinhThanh")) or "?",
            None,                                            # region — NULL for now
            r["IDTinhThanh"],
        )
        for r in src
    ]
    if settings.ETL_TRUNCATE_BEFORE_LOAD:
        truncate_table(conn, "master.provinces")
    return copy_rows(conn, "master.provinces", ["code", "name", "region", "legacy_id"], rows)


def load_districts(conn) -> int:
    """HRM_DAU.DM_Huyen → master.districts.

    Source: Id (PK), IDTinh (FK to DM_TinhThanh.IDTinhThanh), MaHuyen, TenHuyen.
    """
    src = fetch_all_dicts(
        settings.SOURCE_DB_HRM,
        "SELECT Id, IDTinh, MaHuyen, TenHuyen FROM DM_Huyen ORDER BY Id",
    )
    province_map = LegacyIdMapper(conn, "master.provinces")

    rows = []
    skipped = 0
    for r in src:
        province_id = province_map.lookup(r.get("IDTinh"))
        if not province_id:
            skipped += 1
            continue
        rows.append((
            _safe_str(r.get("MaHuyen")) or _gen_code("H", r["Id"]),
            _safe_str(r.get("TenHuyen")) or "?",
            province_id,
            r["Id"],
        ))

    if skipped:
        logger.warning(f"Skipped {skipped} districts with missing province FK")

    if settings.ETL_TRUNCATE_BEFORE_LOAD:
        truncate_table(conn, "master.districts")
    return copy_rows(conn, "master.districts", ["code", "name", "province_id", "legacy_id"], rows)


def load_wards(conn) -> int:
    """HRM_DAU.DM_BH_Xa → master.wards.

    QUAN TRỌNG: Source CHỈ CÓ text codes — no FK ID to DM_Huyen.
    Schema source: Id, MaTinh, MaHuyen, MaXa, TenXa.

    `MaHuyen` không unique toàn quốc (cùng code dùng ở nhiều tỉnh).
    Phải resolve qua **(MaTinh, MaHuyen) composite** để chính xác district.
    """
    # 1. Build (MaTinhThanh → IDTinhThanh) map
    tinh_codes = fetch_all_dicts(
        settings.SOURCE_DB_HRM,
        "SELECT IDTinhThanh, MaTinhThanh FROM DM_TinhThanh WHERE MaTinhThanh IS NOT NULL",
    )
    tinh_id_by_code: dict[str, int] = {
        r["MaTinhThanh"].strip(): r["IDTinhThanh"]
        for r in tinh_codes
        if r.get("MaTinhThanh") and r["MaTinhThanh"].strip()
    }

    # 2. Build ((IDTinh, MaHuyen) → DM_Huyen.Id) composite map
    huyen_records = fetch_all_dicts(
        settings.SOURCE_DB_HRM,
        "SELECT Id, IDTinh, MaHuyen FROM DM_Huyen WHERE MaHuyen IS NOT NULL",
    )
    huyen_id_by_tinh_huyen: dict[tuple[int, str], int] = {}
    for r in huyen_records:
        if r.get("IDTinh") and r.get("MaHuyen"):
            huyen_id_by_tinh_huyen[(r["IDTinh"], r["MaHuyen"].strip())] = r["Id"]

    # 3. Mapper từ legacy district Id → target district id
    district_map = LegacyIdMapper(conn, "master.districts")

    src = fetch_all_dicts(
        settings.SOURCE_DB_HRM,
        "SELECT Id, MaTinh, MaHuyen, MaXa, TenXa FROM DM_BH_Xa ORDER BY Id",
    )

    rows = []
    skipped_orphan = 0
    skipped_dup = 0
    seen: set[tuple[str, int]] = set()  # dedup (code, district_id) within batch

    for r in src:
        ma_tinh = _safe_str(r.get("MaTinh"))
        ma_huyen = _safe_str(r.get("MaHuyen"))
        if not (ma_tinh and ma_huyen):
            skipped_orphan += 1
            continue

        # Resolve province via MaTinh text → IDTinhThanh
        tinh_id = tinh_id_by_code.get(ma_tinh)
        if not tinh_id:
            skipped_orphan += 1
            continue

        # Resolve district via (IDTinh, MaHuyen) → DM_Huyen.Id
        huyen_legacy_id = huyen_id_by_tinh_huyen.get((tinh_id, ma_huyen))
        district_id = district_map.lookup(huyen_legacy_id)
        if not district_id:
            skipped_orphan += 1
            continue

        ma_xa = _safe_str(r.get("MaXa")) or _gen_code("W", r["Id"])

        # Dedup within batch — source có thể có duplicate (rare)
        key = (ma_xa, district_id)
        if key in seen:
            skipped_dup += 1
            continue
        seen.add(key)

        rows.append((
            ma_xa,
            _safe_str(r.get("TenXa")) or "?",
            district_id,
            r["Id"],
        ))

    if skipped_orphan:
        logger.warning(f"Skipped {skipped_orphan:,} wards: missing district FK")
    if skipped_dup:
        logger.warning(f"Skipped {skipped_dup:,} wards: duplicate (code, district_id)")

    if settings.ETL_TRUNCATE_BEFORE_LOAD:
        truncate_table(conn, "master.wards")
    return copy_rows(conn, "master.wards", ["code", "name", "district_id", "legacy_id"], rows)


# =============================================================================
# Lookup tables — generic helper
# =============================================================================

def _load_simple_lookup(
    conn,
    src_query: str,
    id_col: str,
    code_col: str,
    name_col: str,
    target_table: str,
    code_prefix: str = "X",
) -> int:
    """Generic loader (Id, code, name, legacy_id)."""
    src = fetch_all_dicts(settings.SOURCE_DB_HRM, src_query)
    rows = [
        (
            _safe_str(r.get(code_col)) or _gen_code(code_prefix, r[id_col]),
            _safe_str(r.get(name_col)) or "?",
            r[id_col],
        )
        for r in src
    ]
    if settings.ETL_TRUNCATE_BEFORE_LOAD:
        truncate_table(conn, target_table)
    return copy_rows(conn, target_table, ["code", "name", "legacy_id"], rows)


def load_positions(conn) -> int:
    """DM_ChucVu — PK is IDChucVu (not Id)."""
    return _load_simple_lookup(
        conn,
        "SELECT IDChucVu, MaChucVu, TenChucVu FROM DM_ChucVu ORDER BY IDChucVu",
        "IDChucVu", "MaChucVu", "TenChucVu", "master.positions", "CV",
    )


def load_titles(conn) -> int:
    """DM_ChucDanh — PK is Id."""
    return _load_simple_lookup(
        conn,
        "SELECT Id, MaChucDanh, TenChucDanh FROM DM_ChucDanh ORDER BY Id",
        "Id", "MaChucDanh", "TenChucDanh", "master.titles", "CD",
    )


def load_degrees(conn) -> int:
    """DM_HocVi — PK is Id."""
    return _load_simple_lookup(
        conn,
        "SELECT Id, MaHocVi, TenHocVi FROM DM_HocVi ORDER BY Id",
        "Id", "MaHocVi", "TenHocVi", "master.degrees", "HV",
    )


def load_academic_ranks(conn) -> int:
    """DM_HocHam — PK is Id."""
    return _load_simple_lookup(
        conn,
        "SELECT Id, MaHocHam, TenHocHam FROM DM_HocHam ORDER BY Id",
        "Id", "MaHocHam", "TenHocHam", "master.academic_ranks", "HH",
    )


def load_civil_ranks(conn) -> int:
    """DM_NgachCongChuc — PK is IDNgachCongChuc, cols MaNgachCongChuc/TenNgachCongChuc."""
    return _load_simple_lookup(
        conn,
        "SELECT IDNgachCongChuc, MaNgachCongChuc, TenNgachCongChuc FROM DM_NgachCongChuc ORDER BY IDNgachCongChuc",
        "IDNgachCongChuc", "MaNgachCongChuc", "TenNgachCongChuc", "master.civil_ranks", "NG",
    )


def load_specializations(conn) -> int:
    """DM_ChuyenNganh — PK is Id."""
    return _load_simple_lookup(
        conn,
        "SELECT Id, MaChuyenNganh, TenChuyenNganh FROM DM_ChuyenNganh ORDER BY Id",
        "Id", "MaChuyenNganh", "TenChuyenNganh", "master.specializations", "SP",
    )


def load_contract_types(conn) -> int:
    """DM_LoaiHopDong — PK is IDLoaiHopDong."""
    return _load_simple_lookup(
        conn,
        "SELECT IDLoaiHopDong, MaLoaiHopDong, TenLoaiHopDong FROM DM_LoaiHopDong ORDER BY IDLoaiHopDong",
        "IDLoaiHopDong", "MaLoaiHopDong", "TenLoaiHopDong", "master.contract_types", "LH",
    )


def load_decision_types(conn) -> int:
    """DM_LoaiQuyetDinh — PK is IDLoaiQuyetDinh."""
    return _load_simple_lookup(
        conn,
        "SELECT IDLoaiQuyetDinh, MaLoaiQuyetDinh, TenLoaiQuyetDinh FROM DM_LoaiQuyetDinh ORDER BY IDLoaiQuyetDinh",
        "IDLoaiQuyetDinh", "MaLoaiQuyetDinh", "TenLoaiQuyetDinh", "master.decision_types", "QD",
    )


def load_divisions(conn) -> int:
    """DM_ToBoMon — PK is **ID** (uppercase!), cols MaBoMon/TenBoMon."""
    src = fetch_all_dicts(
        settings.SOURCE_DB_HRM,
        "SELECT ID, MaBoMon, TenBoMon, IDPhongBan FROM DM_ToBoMon ORDER BY ID",
    )
    dept_map = LegacyIdMapper(conn, "master.departments")

    rows = []
    skipped = 0
    for r in src:
        dept_id = dept_map.lookup(r.get("IDPhongBan"))
        if not dept_id:
            skipped += 1
            continue
        rows.append((
            _safe_str(r.get("MaBoMon")) or _gen_code("BM", r["ID"]),
            _safe_str(r.get("TenBoMon")) or "?",
            dept_id,
            r["ID"],
        ))

    if skipped:
        logger.warning(f"Skipped {skipped} divisions with missing department FK")

    if settings.ETL_TRUNCATE_BEFORE_LOAD:
        truncate_table(conn, "master.divisions")
    return copy_rows(conn, "master.divisions", ["code", "name", "department_id", "legacy_id"], rows)


# =============================================================================
# Orchestrator
# =============================================================================

PIPELINE_STEPS: list[tuple[str, Callable]] = [
    ("countries", load_countries),
    ("ethnicities", load_ethnicities),
    ("religions", load_religions),
    ("departments", load_departments),

    ("provinces", load_provinces),
    ("districts", load_districts),
    ("wards", load_wards),

    ("positions", load_positions),
    ("titles", load_titles),
    ("degrees", load_degrees),
    ("academic_ranks", load_academic_ranks),
    ("civil_ranks", load_civil_ranks),
    ("specializations", load_specializations),
    ("contract_types", load_contract_types),
    ("decision_types", load_decision_types),

    ("divisions", load_divisions),  # depends on departments
]


def run() -> dict[str, int]:
    """Run all loaders in dependency order."""
    results: dict[str, int] = {}
    with target_conn(autocommit=False) as conn:
        for name, loader in PIPELINE_STEPS:
            try:
                logger.info(f"Loading master.{name} ...")
                results[name] = loader(conn)
            except Exception as e:
                logger.exception(f"Failed loading {name}: {e}")
                raise

    total = sum(results.values())
    logger.success(f"✓ Master pipeline complete. Total {total:,} rows across {len(results)} tables")
    for name, count in results.items():
        logger.info(f"  {name}: {count:,}")
    return results


if __name__ == "__main__":
    from ..log import setup_logging
    setup_logging()
    run()
