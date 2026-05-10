# Phân tích phần mềm HRM của ĐH Kiến trúc Đà Nẵng — Báo cáo Discovery (Đợt 1)

**Nguồn dữ liệu**: `HRM_DAU_backup_2026_03_02_000001_6915565.bak` (21.5 MB)
**Ngày phân tích**: 2026-05-07
**Người thực hiện**: TS. Đỗ Phúc Hảo (với hỗ trợ Claude Code)
**Phiên bản DB**: SQL Server (logical name `HRM_ORG2`, vendor **ASCVN**)

---

## 1. Tổng quan kỹ thuật

| Hạng mục | Số lượng | Ghi chú |
|---|---:|---|
| Tables (user) | **586** | Toàn bộ ở schema `dbo` |
| Stored procedures | **1139** | Logic nghiệp vụ chủ yếu nằm ở đây |
| Views | 199 | |
| Scalar functions | 203 | |
| Table-valued functions | 18 | |
| Triggers | 25 | |
| **Primary keys** | **578** | Hầu như bảng nào cũng có PK |
| **Foreign keys** | **18** ⚠️ | Bất thường — DB không enforce quan hệ qua FK |
| Default constraints | 173 | |

### Nhận định kỹ thuật cốt lõi

> **Đây là phần mềm thương mại đóng gói** của vendor **ASCVN** (`D:\ASCVN\DATA\HRM_DAU_2.mdf`), không phải phần mềm tự xây. Schema thiết kế cho mọi nghiệp vụ HR đại học có thể có (586 bảng), nhưng ĐH Kiến trúc Đà Nẵng **chỉ dùng một phần nhỏ**.

> **Business logic dày trong stored procedures**, không trong DB constraints. Tỉ lệ FK/PK = 18/578 = **3%** — gần như không có FK, nghĩa là khi migrate sang Postgres phải **suy quan hệ từ tên cột** (ví dụ `MaNhanSu` ở mọi bảng đều ám chỉ `NS_NhanSu.MaNhanSu`).

---

## 2. Phân nhóm 586 bảng theo prefix → module nghiệp vụ

| Prefix | Module nghiệp vụ | Số bảng (ước) | Tình trạng dữ liệu |
|---|---|---:|---|
| `_*` | Bảng nội bộ / temp | 5 | Rỗng |
| `ACL_*` | Access Control + Phiên đăng nhập | 11 | **Đang dùng** (1.8K sessions, 8.4K session details) |
| `API_*` | Buffer import API | 1 | Rỗng |
| `BC_*` | Báo cáo cán bộ giảng viên | 5 | Hầu hết rỗng (chỉ `BC_Field` 56 dòng — config) |
| `BH_*` | Bảo hiểm tăng/giảm | 1 | Rỗng |
| `bk_*` | **Ad-hoc backup table** ⚠️ | 1 | `bk_NS_LUONG_20231218` (899 dòng) — DBA backup tay |
| `BL_*` | **Bảng lương / Payroll** | 32 | **Đang dùng** (BL_TinhLuong 35K dòng, các bảng khác config) |
| `BNCB_*` | Bổ nhiệm cán bộ | 3 | Rỗng (chưa dùng) |
| `CC_*` | **Chấm công** | 33 | **CHƯA DÙNG — toàn bộ rỗng** |
| `DBNS_*` | Định biên nhân sự | 2 | Rỗng |
| `DM_*` | **Danh mục / Master data** | 155 | Một phần đang dùng (xem mục 3) |
| `DM_BH_*` | Master data Bảo hiểm Việt Nam | 8 | **Đầy đủ** (xã/huyện/tỉnh/dân tộc/quốc gia) |
| `DM_KPI_*` | Master KPI | 8 | Rỗng |
| `DM_TD_*` | Master Tuyển dụng | 4 | Rỗng |
| `DTDH_*` | Đào tạo dài hạn | 4 | Rỗng |
| `DTNH_*` | Đào tạo ngắn hạn | 2 | Rỗng |
| `HRM_*`, `HT_*` | System config | 11 | Một phần dùng (`HT_MapColName` 210 dòng — mapping import) |
| `IMP_*` | Import wizard | 2 | Rỗng |
| `NBL_*` | Nâng bậc lương | 4 | Rỗng |
| `NK_*` | Nhật ký quyết định / hợp đồng | 10 | **Đang dùng** (`NK_HopDong` 994, `NK_QuyetDinh` 108) |
| `NS_*` | **Nhân sự — module chính** | 90+ | **Đang dùng đậm** (xem mục 4) |
| `NS_KPI_*` | KPI nhân sự | 2 | Rỗng |
| `P_*` | Phân quyền (legacy?) | 2 | `P_Quyen` 1958 dòng, `P_HeThong` 4 |
| `PT_*` | **Phụ trội (giảng dạy vượt giờ)** | 50+ | Một phần (`PT_NS_SoTietChuan` 969) |
| `QH_*`, `QHCB_*` | Quy hoạch cán bộ | 13 | Rỗng |
| `QL_*` | Quản lý quyền (mới?) | 4 | Rỗng |
| `SYS_*` | Nhật ký hệ thống | 1 | Rỗng |
| `TD_*` | Tuyển dụng | 14 | Rỗng |
| `TG_*` | **Thỉnh giảng** | 24 | **Đang dùng** (`TG_HopDong` 257, `TG_HopDongChinh` 59) |
| `UV_*` | Ứng viên tuyển dụng | 9 | Rỗng |
| `VanBan*` | Văn bản thông qua | 2 | Rỗng |

### 2 quan sát chiến lược

1. **~60% bảng rỗng** = 350+ bảng vendor đóng gói nhưng chưa dùng. Khi migrate, **không cần migrate hết** — chỉ những module thực sự đang dùng.
2. **Modules đang dùng thật**: HR core (NS_*), Lương (BL_TinhLuong), Hợp đồng (NS_HopDong, NK_HopDong), Thỉnh giảng (TG_*), Bảo hiểm (NS_QuaTrinhDongBaoHiem), ACL.
3. **Modules có schema nhưng chưa dùng**: Chấm công, Tuyển dụng, KPI, Quy hoạch, Đào tạo bồi dưỡng, Định biên — có thể: (a) trường mua nhưng chưa triển khai, hoặc (b) gói cơ sở của vendor có sẵn.

---

## 3. Master data đang dùng (bảng `DM_*` có dữ liệu)

Đây là cơ sở rất quan trọng để migrate sang DB mới — các giá trị enum/lookup này phải được giữ nguyên ID để không vỡ tham chiếu.

### 3.1 Master data hành chính Việt Nam (đầy đủ)

| Bảng | Số dòng | Nội dung |
|---|---:|---|
| `DM_BH_QuocGia` | 240 | Quốc gia (chuẩn BHXH) |
| `DM_QuocGia` | 33 | Quốc gia (rút gọn — trùng lặp với `DM_BH_*`?) |
| `DM_TinhThanh` | 65 | 63 tỉnh thành VN + 2 dự phòng |
| `DM_BH_Tinh` | 64 | Tỉnh (BHXH) — **trùng lặp** |
| `DM_Huyen` | 760 | Huyện |
| `DM_BH_Huyen` | 715 | Huyện (BHXH) — **trùng lặp** |
| `DM_BH_Xa` | 11706 | Xã/Phường |
| `DM_BH_Vung` | 777 | Vùng địa lý BHXH |
| `DM_DanToc` | 57 | Dân tộc |
| `DM_BH_DanToc` | 55 | Dân tộc (BHXH) — **trùng lặp** |
| `DM_TonGiao` | 14 | Tôn giáo |

⚠️ **Trùng lặp rõ rệt**: vendor có 2 hệ master geography (`DM_*` cho UI và `DM_BH_*` cho khai báo BHXH). Khi migrate Postgres → **gộp thành 1 bảng** với mã chuẩn quốc gia VN.

### 3.2 Master data đào tạo (đầy đủ)

| Bảng | Số dòng | Nội dung |
|---|---:|---|
| `DM_HocVan` | 7 | Trình độ học vấn |
| `DM_HocVi` | 7 | Học vị (Cử nhân, Thạc sĩ, TS, TSKH...) |
| `DM_HocHam` | 4 | Học hàm (PGS, GS) |
| `DM_TrinhDoNgoaiNgu` | 18 | Trình độ ngoại ngữ |
| `DM_NgoaiNgu` | 9 | Ngoại ngữ |
| `DM_ChuyenMon` | 113 | Chuyên môn |
| `DM_ChuyenNganh` | 474 | Chuyên ngành |
| `DM_BacDaoTao` | 2 | Bậc đào tạo |
| `DM_CapDaoTao` | 3 | Cấp đào tạo |
| `DM_HinhThucDaoTao` | 3 | Hình thức đào tạo |
| `DM_TrinhDoChinhTri` | 6 | Trình độ chính trị |
| `DM_TrinhDoNhaNuoc` | 3 | Trình độ QLNN |
| `DM_TrinhDoGiaoDuc` | 3 | Trình độ giáo dục |
| `DM_ChungChi` | 12 | Chứng chỉ |

### 3.3 Master data tổ chức / nhân sự

| Bảng | Số dòng | Nội dung |
|---|---:|---|
| `DM_DonVi` | 1 | Đơn vị (chỉ 1 — tức là DAU) |
| `DM_PhongBan` | 31 | Phòng/Ban/Khoa |
| `DM_ToBoMon` | 20 | Tổ bộ môn |
| `DM_LoaiPhongBan` | 5 | Loại phòng ban |
| `DM_ChucDanh` | 7 | Chức danh |
| `DM_ChucVu` | 33 | Chức vụ |
| `DM_LoaiChucVu` | 7 | Loại chức vụ |
| `DM_LoaiNhanSu` | 2 | Loại nhân sự |
| `DM_QuanHam` | 15 | Quân hàm (cho cán bộ có gốc quân đội) |
| `DM_NgachCongChuc` | 7 | Ngạch công chức |
| `DM_LoaiNgach` | 6 | Loại ngạch |
| `DM_ChiTietNgachCongChuc` | 75 | Chi tiết ngạch (mã ngạch nhà nước) |

### 3.4 Master data quan hệ / đặc điểm cá nhân

| Bảng | Số dòng | Nội dung |
|---|---:|---|
| `DM_QuanHeGiaDinh` | 16 | Quan hệ gia đình |
| `DM_ThanhPhanGiaDinh` | 16 | Thành phần gia đình |
| `DM_ThanhPhanBanThan` | 9 | Thành phần bản thân |
| `DM_TinhTrangHonNhan` | 3 | Tình trạng hôn nhân |
| `DM_HangThuongBinh` | 4 | Hạng thương binh |
| `DM_DanhHieu` | 8 | Danh hiệu |

### 3.5 Master data quyết định / hợp đồng

| Bảng | Số dòng | Nội dung |
|---|---:|---|
| `DM_LoaiQuyetDinh` | 81 | Loại quyết định (rất phong phú) |
| `DM_LoaiHopDong` | 9 | Loại hợp đồng |
| `DM_HinhThucKTKL` | 15 | Hình thức Khen thưởng/Kỷ luật |
| `DM_BieuMau` | 58 | Biểu mẫu |
| `DM_NguonTuyen` | 8 | Nguồn tuyển |

### 3.6 Master data lương / bảo hiểm

| Bảng | Số dòng | Nội dung |
|---|---:|---|
| `DM_BaoHiemThang` | 177 | Bảo hiểm theo tháng |
| `DM_BHYT` | 16 | Mã BHYT |
| `DM_BH_LoaiTangGiam` | 18 | Loại tăng/giảm BHXH |
| `DM_BH_DonViKCB` | 202 | Đơn vị khám chữa bệnh |
| `DM_PhuCapKhac` | 4 | Phụ cấp khác |
| `DM_ABC` | 6 | Xếp loại ABC |

### 3.7 Master data hệ thống UI (vendor-specific)

| Bảng | Số dòng | Mục đích |
|---|---:|---|
| `DM_DanhMucCauHinhCotHienThi` | 2014 | Cấu hình cột hiển thị grid (UI legacy) |
| `DM_LoaiDanhMucCauHinhCotHienThi` | 95 | Loại cấu hình cột |
| `DM_DanhMucCauHinhCotExport` | 146 | Cấu hình cột khi export Excel |
| `HT_MapColName` | 210 | Map tên cột import |
| `HT_ThongSo` | 56 | Thông số hệ thống |

⚠️ **Khi migrate sang Postgres**: 4 bảng UI trên KHÔNG cần migrate — chúng là cấu hình của UI cũ ASCVN, hệ thống mới sẽ có UI riêng.

---

## 4. Module Nhân sự (`NS_*`) — Trái tim của HRM

### 4.1 Bảng có dữ liệu thật

| Bảng | Số dòng | Vai trò suy đoán (cần xác minh) |
|---|---:|---|
| **`NS_NhanSu`** | **1024** | **Bảng chính — hồ sơ nhân sự** |
| `NS_QuaTrinhDongBaoHiem` | 39231 | Quá trình đóng BHXH (lịch sử nhiều năm) |
| `NS_Luong_Details` | 39935 | Chi tiết lương (theo từng kỳ × người) |
| `NS_XetTinhLuong` | 2798 | Xét điều kiện tính lương |
| `NS_QuanHeGiaDinh` | 1228 | Quan hệ gia đình (1.2 dòng / nhân sự) |
| `NS_Luong` | 914 | Bảng lương hiện hành |
| `NS_QuaTrinhDaoTao` | 872 | Lịch sử đào tạo (0.85 dòng / nhân sự) |
| `NS_HeSoLuong` | 364 | Hệ số lương |
| `NS_BaoHiem` | 351 | Bảo hiểm hiện tại |
| `NS_PhuCap` | 339 | Phụ cấp |
| `NS_HopDong` | 316 | Hợp đồng lao động |
| `NS_ToBoMon` | 287 | Phân công tổ bộ môn (lịch sử?) |
| `NS_ThamGiaBaoHiem` | 279 | Tham gia BHXH/BHYT |
| `NS_NhanSu_DeXuatThongTin` | 263 | Đề xuất sửa thông tin (workflow duyệt) |
| `NS_QuyetDinh` | 118 | Quyết định liên quan nhân sự |
| `NS_LuongDongBaoHiem` | 107 | Lương đóng BH |
| `NS_HienTaiQD` | 105 | QĐ hiện tại của mỗi nhân sự (snapshot) |
| `NS_QuaTrinhNghienCuu` | 69 | Quá trình NCKH |
| `NS_ThongTinKhac` | 29 | Thông tin khác |
| `NS_DaoTao` | 30 | Đào tạo |
| `NS_PhuLucHopDong` | 17 | Phụ lục hợp đồng |
| `NS_QuaTrinhCongTacChuyenMon` | 11 | Quá trình công tác chuyên môn |
| `NS_ThieuSot` | 4 | Thiếu sót |
| `NS_CauHinhThe` | 3 | Cấu hình thẻ |
| Còn lại (~70 bảng) | 0 | Rỗng |

### 4.2 Tỉ lệ "đầy đủ" của hồ sơ 1024 nhân sự

- **100%**: Có ở `NS_NhanSu` (chắc chắn — bảng chính)
- **31%**: Có hợp đồng (`NS_HopDong`/1024)
- **89%**: Có lịch sử đào tạo
- **35%**: Có bảo hiểm hiện tại
- **27%**: Có phụ cấp
- **120%**: Quan hệ gia đình (1228 dòng) — mỗi người trung bình có 1.2 quan hệ
- **~10%**: Có quá trình nghiên cứu (chỉ giảng viên)

### 4.3 Bảng cần phân tích sâu (Đợt 2)

- `NS_NhanSu` — bao nhiêu cột? Dữ liệu thật ra sao?
- `NS_HopDong` + `NS_PhuLucHopDong` — luồng hợp đồng
- `NS_Luong` + `NS_Luong_Details` + `BL_TinhLuong` — luồng tính lương
- `NS_QuyetDinh` + `NS_HienTaiQD` + `NK_QuyetDinh` — luồng quyết định
- `NS_QuaTrinhDongBaoHiem` (39K dòng) — sơ đồ thời gian đóng BH

---

## 5. Module có nghi vấn / cần xác minh

### 5.1 Module Chấm công (33 bảng `CC_*` — TẤT CẢ RỖNG)

→ Khả năng cao **trường KHÔNG dùng phân hệ chấm công của ASCVN**. Có thể vì:
- Trường dùng phần mềm chấm công khác (máy quẹt thẻ độc lập)
- Chưa triển khai
- Hoặc dùng phương thức thủ công

**Hành động**: Hỏi thầy → nếu xác nhận không dùng, **bỏ luôn module này** trong DB mới.

### 5.2 Module Tuyển dụng (14 `TD_*` + 9 `UV_*` — RỖNG)

→ Trường có thể tuyển dụng qua quy trình ngoài hệ thống (form Google, email...).

### 5.3 Module Phụ trội/Thỉnh giảng (`PT_*`, `TG_*`)

- `TG_*` (thỉnh giảng): có dữ liệu (`TG_HopDong` 257, `TG_HopDongChinh` 59) → **đang dùng**
- `PT_*` (phụ trội): chỉ một vài bảng có data (`PT_NS_SoTietChuan` 969) → có thể dùng một phần

### 5.4 Hai hệ phân quyền song song

- `ACL_*` (mới): có data (sessions, NhatKy, PhanQuyenHT)
- `P_Quyen` + `P_HeThong` (cũ): có data (1958, 4)
- `QL_NhomNguoiDung`, `QL_Quyen`, `QL_NhomNguoiDung_Quyen` (mới hơn?): rỗng

→ Vendor có **3 thế hệ phân quyền** đan xen. Migrate cần hợp nhất.

---

## 6. Technical debt phát hiện

1. ✗ **18/578 PK có FK** — DB không enforce quan hệ
2. ✗ **`bk_NS_LUONG_20231218`** — bảng backup tay trong DB production
3. ✗ **350+ bảng rỗng** chiếm chỗ trong schema, tăng độ phức tạp khi đọc
4. ✗ **Master data trùng lặp** (`DM_QuocGia` vs `DM_BH_QuocGia`, `DM_DanToc` vs `DM_BH_DanToc`, `DM_Tinh` vs `DM_BH_Tinh`...)
5. ✗ **3 hệ phân quyền song song** (P_*, ACL_*, QL_*)
6. ⚠ Tên cột tiếng Việt không dấu, không nhất quán: `MaNhanSu`, `IdNhanSu`, `NhanSuId` — cần xem chi tiết
7. ⚠ Có bảng tên `_DM_BangKyTu`, `_updateluong` (leading underscore) — temp/internal, không nên migrate

---

## 7. Đề xuất phạm vi migrate sang Postgres

### Bắt buộc (core HR)

| Domain | Bảng nguồn | Bảng đích Postgres (gợi ý) |
|---|---|---|
| Nhân sự | `NS_NhanSu` (+ FileAttach) | `employees` |
| Master tổ chức | `DM_DonVi`, `DM_PhongBan`, `DM_ToBoMon` | `organizations`, `departments`, `divisions` |
| Master nhân sự | `DM_ChucVu`, `DM_ChucDanh`, `DM_HocVi`, `DM_HocHam`, `DM_NgachCongChuc`, `DM_ChuyenNganh` | `positions`, `titles`, `degrees`, `academic_ranks`, `civil_ranks`, `specializations` |
| Master VN | `DM_TinhThanh`, `DM_Huyen`, `DM_BH_Xa`, `DM_DanToc`, `DM_TonGiao`, `DM_QuocGia` | `provinces`, `districts`, `wards`, `ethnicities`, `religions`, `countries` |
| Quan hệ gia đình | `NS_QuanHeGiaDinh` + `DM_QuanHeGiaDinh` | `family_relations` |
| Quá trình đào tạo | `NS_QuaTrinhDaoTao` | `training_history` |
| Quá trình NCKH | `NS_QuaTrinhNghienCuu` | `research_history` |
| Quá trình công tác | `NS_QuaTrinhCongTacChuyenMon` | `career_history` |

### Bắt buộc (lương & hợp đồng)

| Domain | Bảng nguồn | Bảng đích |
|---|---|---|
| Hợp đồng | `NS_HopDong`, `NS_PhuLucHopDong`, `NK_HopDong`, `DM_LoaiHopDong` | `contracts`, `contract_addendums`, `contract_history` |
| Lương | `NS_Luong`, `NS_Luong_Details`, `NS_HeSoLuong`, `BL_TinhLuong`, `BL_NgayCongTinhLuong` | `salaries`, `salary_details`, `salary_calculations` |
| Phụ cấp | `NS_PhuCap` + `DM_PhuCapKhac` | `allowances` |
| Bảo hiểm | `NS_BaoHiem`, `NS_QuaTrinhDongBaoHiem`, `NS_ThamGiaBaoHiem`, `DM_BHYT` | `insurances`, `insurance_history` |
| Quyết định | `NS_QuyetDinh`, `NS_HienTaiQD`, `NK_QuyetDinh` + `DM_LoaiQuyetDinh` | `decisions`, `current_decisions` |
| Khen thưởng/Kỷ luật | `NS_KhenThuongKyLuat` (rỗng?) | `rewards_disciplines` (nếu có data) |

### Bắt buộc nếu trường có dùng

| Domain | Khi nào? | Bảng nguồn |
|---|---|---|
| Thỉnh giảng | Có (đang dùng) | `TG_HopDong`, `TG_HopDongChinh`, `TG_DonGiaTiet`, `TG_DonGiaThinhGiang` |
| Phụ trội giảng dạy | Một phần | `PT_NS_SoTietChuan`, `PT_NS_SoTietTinhPhuTroi`, `PT_DM_LoaiTietChuan` |
| ACL (đăng nhập) | Có | `ACL_NhatKyHT` (audit log) — phần khác build mới |

### Không cần migrate

- 33 bảng `CC_*` (Chấm công) — rỗng hết
- 23 bảng `TD_*` + `UV_*` (Tuyển dụng + Ứng viên) — rỗng
- 13 bảng `QH_*`, `QHCB_*` (Quy hoạch) — rỗng
- 8 bảng `DM_KPI_*` + 2 bảng `NS_KPI_*` — rỗng
- 6 bảng `DTDH_*`, `DTNH_*` (Đào tạo bồi dưỡng) — rỗng
- 4 bảng `NBL_*` (Nâng bậc lương) — rỗng
- 2 bảng `DBNS_*` (Định biên) — rỗng
- 5 bảng `_*` (internal/temp)
- 1 bảng `bk_NS_LUONG_20231218` (backup ad-hoc)
- 4 bảng `HRM_ResourceColumns`, `HT_GridForm`, `HT_ImportData`, các UI config — sẽ build UI mới
- 199 views — build lại theo thiết kế mới
- 1139 stored procedures — KHÔNG migrate, **viết lại business logic ở application layer**

→ **Phạm vi thực tế cần migrate: ~80–100 bảng** (giảm từ 586).

---

## 8. Kế hoạch các đợt phân tích tiếp theo

| Đợt | Mục tiêu | Output |
|---|---|---|
| ✅ Đợt 1 | Discovery overview (bảng này) | `01-discovery-overview.md` |
| Đợt 2 | Đặc tả chi tiết module Nhân sự (`NS_NhanSu` + FileAttach) | `02-spec-NhanSu.md` + ERD |
| Đợt 3 | Đặc tả module Hợp đồng (NS_HopDong, NS_PhuLucHopDong, NK_HopDong) | `03-spec-HopDong.md` |
| Đợt 4 | Đặc tả module Lương (luồng từ `BL_*` → `NS_Luong*`) | `04-spec-Luong.md` |
| Đợt 5 | Đặc tả Bảo hiểm + Quyết định + Đào tạo | `05-spec-BaoHiem-QuyetDinh-DaoTao.md` |
| Đợt 6 | Đặc tả Thỉnh giảng + Phụ trội (nếu giữ) | `06-spec-ThinhGiang-PhuTroi.md` |
| Đợt 7 | Phân tích stored procedures lõi | `07-business-rules-from-SPs.md` |
| Đợt 8 | Schema Postgres đề xuất + script migrate | `08-postgres-target-schema.sql` + `08-migration-plan.md` |

---

## 9. Các câu hỏi cần thầy xác nhận trước Đợt 2

1. **Module Chấm công**: trường có dùng phần mềm khác để chấm công không? (toàn bộ `CC_*` rỗng)
2. **Module Tuyển dụng**: trường có dùng module tuyển dụng của ASCVN không? (toàn bộ `TD_*`, `UV_*` rỗng)
3. **Module Phụ trội** (`PT_*`): trường có thanh toán giờ vượt giảng dạy qua hệ thống ASCVN không, hay làm Excel ngoài?
4. **Module Quy hoạch cán bộ** (`QH_*`, `QHCB_*`): có sử dụng không?
5. **Naming convention DB Postgres mới**:
   - **(A)** `snake_case` + tiếng Anh (`employees`, `contracts`, `salary_details`)
   - **(B)** `snake_case` + tiếng Việt không dấu (`nhan_su`, `hop_dong`, `chi_tiet_luong`)
   - **(C)** Giữ nguyên PascalCase + tiếng Việt như cũ (`NhanSu`, `HopDong`)
6. **Có file `.bak` của các module khác** (Đào tạo, Sinh viên, Tài chính)? Hay chỉ HRM?

---

**Trạng thái container**: SQL Server 2022 đang chạy ở Docker container `mssql-hrm`, port 1433, password `YourStrong@Pass1`. Có thể connect bằng SSMS hoặc DBeaver để khám phá tay.
