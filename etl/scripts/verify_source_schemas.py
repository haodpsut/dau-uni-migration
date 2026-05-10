"""Verify source table column names — chạy trước khi run ETL để tránh KeyError.

Output: list bảng + cột thiếu trong SQL Server source so với expectations.

Usage: python scripts/verify_source_schemas.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.table import Table

from src.config import settings
from src.db import source_conn
from src.log import setup_logging, logger


console = Console()


# Expectations: { db: { table: [required_cols] } }
EXPECTATIONS = {
    settings.SOURCE_DB_HRM: {
        "DM_QuocGia":      ["IDQuocGia", "MaQuocGia", "TenQuocGia"],
        "DM_DanToc":       ["Id", "MaDanToc", "TenDanToc"],
        "DM_TonGiao":      ["Id", "MaTonGiao", "TenTonGiao"],
        "DM_PhongBan":     ["IDPhongBan", "MaPhongBan", "TenPhongBan", "VietTat", "LoaiPhongBan"],
        "DM_TinhThanh":    ["IDTinhThanh", "MaTinhThanh", "TenTinhThanh"],
        "DM_Huyen":        ["Id", "IDTinh", "MaHuyen", "TenHuyen"],
        "DM_BH_Xa":        ["Id", "MaTinh", "MaHuyen", "MaXa", "TenXa"],
        "DM_ToBoMon":      ["ID", "MaBoMon", "TenBoMon", "IDPhongBan"],
        "DM_ChucVu":       ["IDChucVu", "MaChucVu", "TenChucVu"],
        "DM_ChucDanh":     ["Id", "MaChucDanh", "TenChucDanh"],
        "DM_HocVi":        ["Id", "MaHocVi", "TenHocVi"],
        "DM_HocHam":       ["Id", "MaHocHam", "TenHocHam"],
        "DM_NgachCongChuc": ["IDNgachCongChuc", "MaNgachCongChuc", "TenNgachCongChuc"],
        "DM_ChuyenNganh":  ["Id", "MaChuyenNganh", "TenChuyenNganh"],
        "DM_LoaiHopDong":  ["IDLoaiHopDong", "MaLoaiHopDong", "TenLoaiHopDong"],
        "DM_LoaiQuyetDinh": ["IDLoaiQuyetDinh", "MaLoaiQuyetDinh", "TenLoaiQuyetDinh"],
        "NS_NhanSu": [
            "IDNhanSu", "MaNhanSu", "HoDem", "Ten", "NgaySinh", "GioiTinh",
            "SoCMND", "SoDienThoai", "Email", "QuocTich", "DanToc", "TonGiao",
            "HienTaiPhongBan", "HienTaiChucVu", "IDChucDanh",
            "HocVi", "HocHam", "ChuyenNganh",
        ],
    },
    settings.SOURCE_DB_EDU: {
        "TKB_MonHoc":          ["IDMonHoc", "MaMonHoc", "TenMonHoc", "SoTinChi"],
        "TKB_LopHocPhan":      ["Id", "MaLopHocPhan", "IDMonHoc", "NamHoc", "HocKy"],
        "TKB_LopHoc":          ["Id", "MaLop", "TenLop", "IDNganh"],
        "DT_SinhVien":         ["Id", "MaSinhVien", "HoDem", "Ten", "GioiTinh",
                                "IDNganh", "IDLopHoc", "NamVao", "Email"],
        "DT_HoSoSinhVien":     ["Id", "MaSinhVien"],
        "DT_DangKyHocPhan":    ["Id", "IDSinhVien", "IDLopHocPhan", "NgayDangKy", "TrangThai"],
        "DT_KetQuaHocTapMonHoc": [
            "Id", "IDSinhVien", "IDLopHocPhan",
            "DiemThi", "DiemTongKet", "DiemTinChi", "DiemChu",
            "IsDat", "DuocDuThiKetThuc", "VangThi",
            "IsKhoaTH", "IsKhoaTL", "IsKhoaCK", "XepLoai_ENG",
        ],
        "DT_DSSinhVienTotNghiep": ["Id", "IDSinhVien", "NgayTotNghiep"],
        "DT_MonHocTuongDuong":  ["Id", "IDMonHoc", "IDMonHocTuongDuong"],
    },
    settings.SOURCE_DB_DATA: {
        "EDU_DT_SinhVien":     ["Id", "IDSinhVien", "HinhAnh"],
        "HRM_HinhAnh":         ["Id", "IDNhanSu", "HinhAnh"],
        "EDU_NK_FileSuaDiem":  ["Id", "IDSinhVien", "IDLopHocPhan", "NoiDung", "TenFile"],
        "EDU_NK_TongHop":      ["Id", "TableName", "PrimaryKey", "History", "NgayTao"],
    },
}


def get_columns(db: str, table: str) -> set[str]:
    try:
        with source_conn(db) as conn:
            cur = conn.cursor(as_dict=True)
            cur.execute(
                f"SELECT name FROM sys.columns WHERE object_id = OBJECT_ID('{table}')"
            )
            return {r["name"] for r in cur.fetchall()}
    except Exception as e:
        logger.error(f"Cannot query {db}.{table}: {e}")
        return set()


def main():
    setup_logging()
    table = Table(title="Source schema verification")
    table.add_column("DB")
    table.add_column("Table")
    table.add_column("Status")
    table.add_column("Missing cols", overflow="fold")

    has_failures = False
    for db, tables in EXPECTATIONS.items():
        for tbl, expected in tables.items():
            actual = get_columns(db, tbl)
            if not actual:
                table.add_row(db, tbl, "[red]✗ NOT FOUND[/red]", "(table missing)")
                has_failures = True
                continue
            missing = [c for c in expected if c not in actual]
            if missing:
                table.add_row(db, tbl, "[yellow]⚠ PARTIAL[/yellow]", ", ".join(missing))
                has_failures = True
            else:
                table.add_row(db, tbl, "[green]✓ OK[/green]", "")

    console.print(table)
    if has_failures:
        console.print("[bold red]Some schemas don't match expectations. "
                      "Update pipelines before running ETL.[/bold red]")
        sys.exit(1)
    console.print("[bold green]All source schemas verified.[/bold green]")


if __name__ == "__main__":
    main()
