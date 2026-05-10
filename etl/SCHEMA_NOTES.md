# Schema notes — verified column names + caveats

Đây là tài liệu các điều chỉnh khi schema source khác giả định ban đầu. Verified trên DB
thật ngày 2026-05-08.

## ✅ Verified — chạy ngay được

### HRM_DAU (p01_master + p02_employees)

| Bảng | Note |
|---|---|
| DM_QuocGia | PK is `IDQuocGia`, không phải `Id` |
| DM_DanToc | PK `Id` ✓ |
| DM_TonGiao | PK `Id` ✓, có cả `MaTonGiao` |
| DM_PhongBan | PK `IDPhongBan`, KHÔNG có parent_id (dùng `IDPhongBanCu` cho khác mục đích) |
| DM_TinhThanh | PK `IDTinhThanh`, KHÔNG có cột "miền/region" |
| DM_Huyen | PK `Id`, FK `IDTinh` (NOT IDTinhThanh) |
| DM_BH_Xa | KHÔNG có FK ID đến DM_Huyen — chỉ có TEXT codes (MaTinh, MaHuyen, MaXa). Pipeline đã fix dùng MaHuyen lookup |
| DM_ChucVu | PK `IDChucVu` |
| DM_NgachCongChuc | PK `IDNgachCongChuc`, cols `MaNgachCongChuc`/`TenNgachCongChuc` |
| DM_LoaiHopDong | PK `IDLoaiHopDong` |
| DM_LoaiQuyetDinh | PK `IDLoaiQuyetDinh` |
| DM_ToBoMon | PK `ID` (uppercase!), `MaBoMon`/`TenBoMon` (NOT MaToBoMon) |
| NS_NhanSu | PK `IDNhanSu`, name = `HoDem`+`Ten` (riêng), FK fields = `HienTai*`/`DanToc`/`TonGiao` (không prefix `ID*`), `HocVi`/`HocHam`/`ChuyenNganh` cũng vậy |

### EDU_DAU (p03–p06)

| Bảng | Note |
|---|---|
| DM_NamHoc | PK `Id`, `NamHoc` (int = start year), `NienHoc` ("2008-2009") |
| DM_Dot | PK `Id`, `TenDot` ("HK1 - 2025-2026"), `IDNamHoc` FK, `TuThang`/`DenThang` |
| DM_Nganh | (instead of DT_NganhHoc) — pipeline tries flexible column names |
| TKB_MonHoc | PK `Id` (NOT IDMonHoc), FK `IDToBoMon` (NOT IDPhongBan). Subjects → divisions → departments chain |
| TKB_LopHoc | PK `Id`, `MaLopHoc`/`TenLopHoc` (NOT MaLop/TenLop). KHÔNG có NamVao — pipeline parse từ TenLopHoc regex `^\d{2}` |
| TKB_LopHocPhan | KHÔNG CÓ `NamHoc`/`HocKy` — dùng `IDDot` link đến DM_Dot. Pipeline đã build map dot→semester |
| DT_DangKyHocPhan | Status col = `IDTrangThaiDangKy` (NOT TrangThai). KHÔNG có NgayHuy/NguoiHuy/LyDoHuy riêng |
| DT_KetQuaHocTapMonHoc | Schema 153 cột — slim còn 33 (xem 05-grade-table-column-analysis.md) |
| DT_HoSoSinhVien | KHÔNG có `MaSinhVien` — link qua `IDSinhVien` đến DT_SinhVien |
| DT_DSSinhVienTotNghiep | Cột tốt nghiệp: `XepLoaiTotNghiep`, `SoHieuVanBang` (NOT SoBangCap), `NgayCapBang`, `NgayRaQD` (NOT NgayTotNghiep). KHÔNG có DiemTBChung/TongSoTinChi — chỉ có `DiemTotNghiep`/`DiemTotNghiepHe10` |

### EDU_DAU_DATA (p07_files + p08_audit) — đã verify ở Đợt 3

| Bảng | Note |
|---|---|
| EDU_DT_SinhVien | `Id`, `IDSinhVien`, `HinhAnh image` ✓ |
| HRM_HinhAnh | `Id`, `IDNhanSu`, `HinhAnh image` ✓ |
| EDU_NK_FileSuaDiem | `NoiDung varbinary(MAX)` ✓ |
| EDU_NK_TongHop | XML `History`, `TableName`, `PrimaryKey`, `NgayTao` ✓ |

---

## ⚠️ Pending — cần verify khi run lần đầu

| Bảng | Cần check |
|---|---|
| DM_Nganh | Tên cột chính xác (em dùng OR fallback nhiều names) — chạy `\d` trong psql sau load để xem |
| DT_NganhHoc | Có thể không tồn tại — em redirect sang DM_Nganh |
| DT_DSSinhVienTotNghiep | Em chỉ map cột cơ bản — nhiều cột chuyên biệt (KhoaHoanTat, ThuVien, NhanBang...) chưa map. Bổ sung khi cần |
| DT_MonHocTuongDuong | Schema phức tạp với IDChiTietKhungHocKy — pipeline skip, viết tay sau |
| TKB_LopHoc.IDKhoaHoc | Có thể link đến DM_KhoaHoc table — admission_year có thể derive chính xác hơn từ đây |
| DT_DangKyHocPhan IDTrangThaiDangKy | Mapping int→ENUM em dùng best-guess (1=registered, 2=completed, ...) — verify với DM_TrangThaiDangKy |

---

## 🔧 TODO sau khi chạy xong (low-priority)

1. **Programs/majors** — query `DM_Nganh` columns trước, chỉnh select rõ ràng
2. **Subject equivalences** — viết SQL custom dùng JOIN qua DT_ChiTietKhungHocKy
3. **Lecturer linkage** — TKB_LopHocPhan không có IDGiangVien trực tiếp. Cần JOIN qua TKB_LichHoc hoặc TKB_PhanCongGiangVien
4. **Marital status mapping** — `TinhTrangHonNhan int` chưa có lookup table tham chiếu. Cần load DM_TinhTrangHonNhan
5. **Address resolution** — students/employees có `HKTT_IDTinh/IDHuyen/IDPhuongXa` — resolve thành `permanent_ward_id` qua chain lookup
6. **Decision types categorization** — `DM_LoaiQuyetDinh.LoaiQuyetDinh` int — cần phân vào categories (tuyển dụng/bổ nhiệm/khen thưởng)
7. **Phone validation** — `phone` ở target schema NOT NULL nhưng source có thể NULL → cần fallback default

## Quick re-verify command

Sau khi cài deps, chạy:
```bash
python scripts/verify_source_schemas.py
```

Script này check tất cả expected columns vs actual và báo những cột thiếu.
