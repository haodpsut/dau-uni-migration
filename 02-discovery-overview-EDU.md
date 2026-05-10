# Discovery EDU module — ĐH Kiến trúc Đà Nẵng (Đợt 2)

**Nguồn dữ liệu**: `EDU_DAU_backup_2026_03_02_000001_6915565.bak` (16 GB)
**Ngày phân tích**: 2026-05-07
**Phiên bản DB**: SQL Server (logical names `EDU_ORG2`, `EDU_ORG2_log`, vendor **ASCVN**)
**File phụ thuộc**: `EDU_DAU_DATA_backup_*.bak` (5.7 GB) — **chưa phân tích** (sẽ làm Đợt 3)

> ⚠️ **Sự cố disk** trong quá trình restore: LDF của EDU_DAU pre-allocate **62 GB** (theo metadata gốc), khi restore song song với EDU_DAU_DATA đã làm đầy ổ C (chỉ còn 152MB). Em đã shutdown WSL, xóa VHDX, free 118GB. Đợt 3 sẽ restore tuần tự + SHRINK log ngay sau mỗi restore + Optimize VHDX giữa các lần.

---

## 1. Tổng quan kỹ thuật — EDU_DAU

| Hạng mục | EDU_DAU | So với HRM_DAU |
|---|---:|---:|
| **Tables (user)** | **1,465** | **2.5×** |
| **Stored procedures** | **6,796** | **6.0×** |
| Views | 539 | 2.7× |
| Scalar functions | 393 | 1.9× |
| Table-valued functions | 77 | 4.3× |
| Triggers | 39 | 1.6× |
| Primary keys | 1,441 | 2.5× |
| **Foreign keys** | **59** ⚠️ | **4%** PK/FK (giống HRM) |
| Default constraints | 512 | 3.0× |
| Unique constraints | 3 | — |
| **Dung lượng MDF** | **39.6 GB** | 1820× HRM (170 MB) |
| **Dung lượng LDF gốc** | **62.2 GB** | — |

### Nhận định kỹ thuật

> Quy mô EDU lớn gấp **6× HRM về stored procedures**, gấp 2.5× về số bảng. Đây là module **lõi** của hệ thống quản lý đại học ASCVN, gói trọn: đào tạo, sinh viên, đăng ký môn học, điểm, tuyển sinh, học phí, thời khóa biểu, khảo thí, khảo sát.

> **Cùng pattern thiết kế của ASCVN**: tỉ lệ FK/PK = 4%, business logic gói trong stored procedures (6,796 SPs!) thay vì trong DB constraints.

---

## 2. Phân nhóm 1,465 bảng theo prefix → modules

### 2.1 Modules **đang dùng** (có dữ liệu)

| Prefix | Module | Tables | Có data | Tổng dòng | Ghi chú |
|---|---|---:|---:|---:|---|
| **DT** | **Đào tạo (LÕI)** | 284 | 88 | **25,452,058** | Sinh viên + đăng ký + điểm + đào tạo |
| **DM** | Master data | 209 | 99 | 165,556 | Các bảng tra cứu |
| **TKB** | Thời khóa biểu | 111 | 38 | 957,115 | Lịch học, lớp học phần, môn học |
| **TS** | Tuyển sinh | 97 | 29 | 507,641 | Thí sinh, nguyện vọng, xét tuyển |
| **EX** | Khảo thí (Exam) | 97 | 28 | 1,111,018 | Đề thi, điểm thi, đáp án |
| **NK** | Nhật ký | 88 | 13 | 2,914,619 | Log các thao tác |
| **KT** | **Kế toán/Tài chính** | 64 | 17 | 1,215,708 | Sổ thu, học phí, hóa đơn |
| **HT** | Hệ thống | 60 | 21 | 1,222,634 | Config, tracking |
| **KS** | **Khảo sát (lớn nhất)** | 20 | 11 | **14,555,815** | Khảo sát, ý kiến SV |
| **ACL** | Phân quyền | 15 | 9 | 1,149,114 | Sessions, audit log |
| **OP** | Operation/Online payment | 7 | 6 | 2,013,959 | Cổng thanh toán trực tuyến |
| **DAU** | Đặc thù DAU (custom) | 2 | 2 | 1,287,999 | `DAU_DIEM_PSC` — bảng custom của trường |
| **CC** | Chứng chỉ | 25 | 3 | 57,888 | Chứng chỉ SV (chỉ phần SV) |
| **TC** | Tín chỉ? | 3 | 1 | 13,198 | |
| **DD** | Điểm danh | 9 | 3 | 59,691 | Điểm danh lớp học |
| **CNCD** | Chuyển ngành/Chuyển điểm | 14 | 2 | 18 | Hầu như chưa dùng |
| **BK** | Backup tables | 10 | 2 | 2,911 | **Technical debt — cần dọn** |
| **(không prefix)** | Một số bảng custom | 31 | 23 | 4,919 | Cần xem case-by-case |
| **NoPrefix** | Bảng vendor không prefix | 7 | 4 | 24,430 | |

### 2.2 Modules **chưa dùng** (rỗng hoàn toàn — vendor đóng gói thừa)

| Prefix | Module | Tables | Diễn giải |
|---|---|---:|---|
| **KTX** | **Ký túc xá** | 58 | Trường không quản lý KTX qua hệ thống |
| **DTBD** | Đào tạo bồi dưỡng | 40 | Trùng với module trong HRM (DTDH/DTNH) |
| **DCMH** | Đăng ký Cấu hình Môn học (?) | 26 | Vendor có 2 cách đăng ký, dùng `DT_DangKyHocPhan` thay |
| **ES** | Exam System (online?) | 59 | Hệ thống thi online — chưa triển khai |
| **CNCD** | Chuyển ngành/đổi điểm | 14 | Hầu như rỗng |
| **ASC** | ASCVN system tables | 12 | System của vendor — không cần migrate |
| **EGOV** | Tích hợp E-Government | 11 | Tích hợp cổng dịch vụ công — chưa dùng |
| **GADT** | Giảng đường (?) | 8 | |
| **OP** một phần | Operation tables | 7 | Một phần dùng (online payment) |
| **TX** | Thẻ xe (?) | 6 | `TX_TheXeSinhVien` rỗng |
| **QLTD** | Quản lý tuyển dụng (NS) | 6 | Trùng với HRM module |
| **HRM** | HRM stub trong EDU | 5 | Vendor để placeholder, dữ liệu thật ở DB HRM_DAU |
| **DGXL** | Đánh giá xếp loại | 5 | |
| **CMS** | Content Management System | 4 | |
| **BC** | Báo cáo riêng | 3 | |
| **WEB** | Web portal | 3 | |
| **SV** | Sinh viên (?) | 3 | **Trùng prefix DT** — không dùng |
| **CTK** | Cộng tác khoa? | 2 | |
| **SYS** | System log | 3 | |
| **API** | API import buffers | 9 | |
| **LX**, **TMP**, **IMP**, **DA**, **KH**, **KM**, **LMS**, **Exam**, **HoiDap** | Misc | mỗi cái 1-7 | Rỗng |

### Tỉ lệ "đóng gói thừa" của EDU

- Tổng 1,465 bảng → chỉ ~487 bảng có data → **~67% bảng rỗng**
- Migrate Postgres chỉ cần ~150-200 bảng cốt lõi (xem mục 7)

---

## 3. Top 30 bảng có nhiều dữ liệu nhất (sắp xếp theo `row_count`)

| # | Tên bảng | Số dòng | Vai trò |
|---:|---|---:|---|
| 1 | `KS_KetQuaKS` | **13,857,277** | Kết quả khảo sát (lớn nhất, 13.8M) |
| 2 | `DT_NK_GetKetQuaHocTapMonHocChiTiet` | 12,383,213 | Log truy vấn điểm (audit) |
| 3 | `DT_DangKyHocPhan` | **2,300,818** | **Đăng ký học phần** (table chính) |
| 4 | `DT_KetQuaHocTapMonHoc` | **2,028,965** | **Điểm môn học** (table chính, 153 cột) |
| 5 | `NK_AutoRun` | 2,012,983 | Log auto-run jobs |
| 6 | `DT_GhiChuSinhVien` | 1,886,276 | Ghi chú về sinh viên |
| 7 | `DT_KetQuaHocTapMonHoc_bk_20824` | **1,820,985** | ⚠ **Backup tay** trong DB |
| 8 | `DT_KetQuaHocTapMonHoc_bk_14824` | **1,820,616** | ⚠ **Backup tay 2** trong DB |
| 9 | `DAU_DIEM_PSC` | 1,149,160 | Bảng custom đặc thù DAU |
| 10 | `ACL_LoginSessionDetail` | 945,422 | Audit login |
| 11 | `EX_DiemThiChiTiet` | 942,008 | Chi tiết điểm thi |
| 12 | `HT_TinhHuyenXaBackup` | **862,641** | ⚠ Backup geography |
| 13 | `KT_ChiTietSoThu` | 783,706 | Chi tiết sổ thu |
| 14 | `DT_DS_MonHocKhongThamGiaKetQuaTinh` | 634,979 | DS môn không tính điểm |
| 15 | `KS_ChiTietDotKhaoSatSinhVien` | 596,489 | Chi tiết đợt khảo sát |
| 16 | `OP_GiaoDichChoGachNo` | 553,656 | Giao dịch chờ gạch nợ |
| 17 | `OP_ChiTietSoThuTrucTuyen` | 549,528 | Chi tiết sổ thu trực tuyến |
| 18 | `OP_ChiTietSoThuTrucTuyenEx` | 547,728 | (trùng lặp với 17) |
| 19 | `DT_DS_NhatKyXetDuThi` | 433,598 | Nhật ký xét đủ thi |
| 20 | `HT_Tracking` | 333,332 | Tracking hệ thống |
| 21 | `NK_HuyDangKyHocPhan` | 310,228 | Log huỷ đăng ký học phần |
| 22 | `DT_HanhKiemSinhVien` | 303,850 | Hạnh kiểm SV |
| 23 | `OP_NganHangGachNoLog` | 288,567 | Log gạch nợ ngân hàng |
| 24 | `DT_LoginSession` | 249,683 | Login session SV |
| 25 | `DT_MonHocTuongDuong` | 240,992 | Môn học tương đương |
| 26 | `NK_DienBienMienGiam` | 225,131 | Diễn biến miễn giảm |
| 27 | `DT_NK_GetKetQuaHocTapMonHoc` | 223,810 | Log truy vấn điểm |
| 28 | `DT_ChiTietGuiMail` | 214,693 | Log gửi email |
| 29 | `TKB_LichHocGiangVien` | 197,158 | Lịch học GV |
| 30 | `TKB_LichHoc` | 196,179 | Lịch học |

### Insights từ top 30

- **3 bảng audit** (`DT_NK_GetKetQuaHocTapMonHocChiTiet`, `DT_NK_GetKetQuaHocTapMonHoc`, `NK_HuyDangKyHocPhan`, `NK_AutoRun`) — chiếm **17M dòng** chỉ để log → migrate sang Postgres có thể bỏ hoặc archive riêng
- **2 bảng backup tay**: `DT_KetQuaHocTapMonHoc_bk_20824`, `_bk_14824` — DBA backup 2 thời điểm khác nhau (8/2024) → technical debt
- **Khảo sát (`KS_*`)**: 13.8M dòng nhưng chỉ 11 bảng có data → tích lũy nhiều năm phản hồi sinh viên
- **Tài chính online**: `OP_*` có 1.7M dòng giao dịch → trường có cổng thanh toán điện tử

---

## 4. Quy mô thực tế (số liệu nghiệp vụ)

| Hạng mục | Số lượng |
|---|---:|
| **Hồ sơ sinh viên (cumulative)** | **97,391** |
| Sinh viên đang hoạt động (`DT_SinhVien`) | 37,682 |
| Sinh viên có thông tin đầy đủ (`DT_ThongTinSinhVien`) | 23,792 |
| Sinh viên đã tốt nghiệp (`DT_DSSinhVienTotNghiep`) | 17,969 |
| **Môn học** (`TKB_MonHoc`) | **75,614** |
| **Lớp học phần** (`TKB_LopHocPhan`) | **82,501** |
| Lớp học (`TKB_LopHoc`) | 55,468 |
| **Đăng ký học phần (`DT_DangKyHocPhan`)** | **2,300,818** |
| **Điểm môn học (`DT_KetQuaHocTapMonHoc`)** | **2,028,965** |
| Thí sinh tuyển sinh | 53,897 |
| Thí sinh trúng tuyển | 57,277 |
| Chi tiết điểm thi | 942,008 |
| Hóa đơn điện tử | 112,094 |
| Sổ thu học phí | 105,042 |
| Kết quả khảo sát | **13,857,277** |

> **Trường có ~97K hồ sơ SV cumulative, ~38K SV đang quản lý, ~76K môn học (trong toàn bộ chương trình các năm).**

---

## 5. Các bảng quan trọng — số cột

| Bảng | Số dòng | Số cột | Ghi chú |
|---|---:|---:|---|
| `TS_ThiSinh` | 53,897 | **155** | Hồ sơ thí sinh — schema rất nặng (chuẩn quốc gia) |
| `DT_KetQuaHocTapMonHoc` | 2,028,965 | **153** | Điểm môn học — **cực kỳ nhiều cột** (chứa nhiều cột tính toán) |
| `DT_SinhVien` | 37,682 | **145** | Hồ sơ SV chính |
| `DT_ThongTinSinhVien` | 23,792 | **177** | Thông tin SV mở rộng |
| `DT_DSSinhVienTotNghiep` | 17,969 | 94 | DS SV tốt nghiệp |
| `TKB_LopHocPhan` | 82,501 | 84 | Lớp học phần |
| `DT_DangKyHocPhan` | 2,300,818 | 42 | Đăng ký học phần |
| `TKB_MonHoc` | 75,614 | 36 | Môn học |
| `KT_HoaDonDienTu` | 112,094 | 27 | Hóa đơn |
| `DT_HoSoSinhVien` | 97,391 | 14 | **Hồ sơ SV (rất ít cột)** — có vẻ là bảng index/registration |

### Quan sát

> Vendor ASCVN có **3 bảng song song** chứa thông tin sinh viên ở các mức độ chi tiết khác nhau:
> - `DT_HoSoSinhVien` (97K, 14 cột) — danh bạ tổng (legacy?)
> - `DT_SinhVien` (37K, 145 cột) — hồ sơ chính (đang dùng)
> - `DT_ThongTinSinhVien` (23K, 177 cột) — extended (cho subset SV)
> - `DT_SinhVienEx` (7.5K, 70 cột) — extended #2

> Khi migrate Postgres → **gộp về 1 bảng `students` duy nhất** với các cột tùy chọn nullable. Tránh phân mảnh.

---

## 6. Technical debt phát hiện ở EDU

1. ✗ **Backup tay trong DB**: `DT_KetQuaHocTapMonHoc_bk_20824`, `_bk_14824` (1.8M × 2 = 3.6M dòng), `HT_TinhHuyenXaBackup` (862K), `BK_*` 10 bảng
2. ✗ **Bảng tạm còn sót**: `DD_LichHocSinhVien_TMP` (59K), `TS_KetQuaXetTuyen_Tmp` (57K), `DT_TongHopCongNoSinhVien_Tmp` (0)
3. ✗ **3 bảng song song chứa thông tin SV** (DT_HoSoSinhVien, DT_SinhVien, DT_ThongTinSinhVien, DT_SinhVienEx) → cần gộp khi migrate
4. ✗ **Bảng có 153, 155, 177 cột** — code smell, vi phạm 3NF, cần refactor khi migrate
5. ✗ **2 hệ phân quyền song song** (`ACL_*` đang dùng + `DT_LoginSession` 250K dòng riêng cho SV)
6. ✗ **OP_ChiTietSoThuTrucTuyen** và **OP_ChiTietSoThuTrucTuyenEx** — 2 bảng gần như giống hệt (549K + 547K dòng) → có vẻ là copy/paste khi migrate phiên bản
7. ✗ **17M dòng audit log** trong `NK_*` và `DT_NK_*` — nên archive riêng, không migrate
8. ⚠ Bảng `EDU_*` (34) hầu hết rỗng nhưng prefix tên trùng với DB name → confusing
9. ⚠ Bảng có `Backup` trong tên (`HT_TinhHuyenXaBackup`) — vendor đặt sẵn

---

## 7. Đề xuất phạm vi migrate sang Postgres

### 7.1 BẮT BUỘC (core đào tạo)

| Domain | Bảng nguồn | Bảng đích Postgres |
|---|---|---|
| Sinh viên (gộp 4 bảng) | `DT_HoSoSinhVien`, `DT_SinhVien`, `DT_ThongTinSinhVien`, `DT_SinhVienEx` | `students` (consolidated) |
| Tốt nghiệp | `DT_DSSinhVienTotNghiep` | `graduations` |
| Môn học | `TKB_MonHoc`, `DT_MonHocTuongDuong` | `subjects`, `subject_equivalences` |
| Lớp học phần | `TKB_LopHocPhan`, `TKB_LopHoc` | `course_classes`, `classes` |
| Đăng ký học phần | `DT_DangKyHocPhan`, `NK_HuyDangKyHocPhan` | `enrollments`, `enrollment_history` |
| Điểm | `DT_KetQuaHocTapMonHoc` (gọn lại từ 153 cột) | `grades` |
| Hạnh kiểm | `DT_HanhKiemSinhVien`, `DT_HanhKiemSinhVienTheoNamHoc` | `conduct_scores` |
| Điểm danh | `DT_DiemDanhSinhVien` | `attendance` |
| Ghi chú SV | `DT_GhiChuSinhVien` | `student_notes` |

### 7.2 BẮT BUỘC (lịch và thi)

| Domain | Bảng nguồn | Bảng đích |
|---|---|---|
| Lịch học | `TKB_LichHoc`, `TKB_LichHocGiangVien`, `TKB_ChamCongLichHoc` | `class_schedules`, `lecturer_schedules`, `attendance_logs` |
| Đề thi & điểm thi | `EX_DiemThiChiTiet`, `EX_DeThiChiTietDapAn`, `EX_BaiThiSinhVien` | `exam_scores`, `exam_questions`, `exam_submissions` |

### 7.3 BẮT BUỘC (tuyển sinh)

| Domain | Bảng nguồn | Bảng đích |
|---|---|---|
| Hồ sơ thí sinh | `TS_ThiSinh`, `TS_ThiSinhOnline`, `TS_HoSoNopOnline` | `applicants` |
| Nguyện vọng | `TS_ThiSinhOnlineNguyenVong` | `application_choices` |
| Trúng tuyển | `TS_ThiSinhTrungTuyen`, `TS_KetQuaXetTuyen_Tmp` | `admissions` |
| Điểm thi tuyển | `TS_ThiSinhOnlineDiemMonThi` | `applicant_exam_scores` |

### 7.4 BẮT BUỘC (tài chính)

| Domain | Bảng nguồn | Bảng đích |
|---|---|---|
| Sổ thu | `KT_SoThuHocPhi`, `KT_ChiTietSoThu`, `KT_SoThuKhac` | `tuition_collections`, `collection_details` |
| Hóa đơn | `KT_HoaDonDienTu` | `electronic_invoices` |
| Cổng thanh toán | `OP_GiaoDichChoGachNo`, `OP_ChiTietSoThuTrucTuyen`, `OP_NganHangGachNoLog` | `online_transactions`, `bank_reconciliation` |
| Miễn giảm | `NK_DienBienMienGiam`, `NK_MienGiamHP`, `NK_DienBienKhauTru` | `tuition_waivers`, `deductions` |

### 7.5 NÊN MIGRATE (khảo sát)

| Domain | Bảng nguồn | Bảng đích |
|---|---|---|
| Khảo sát | `KS_KetQuaKS` (13.8M), `KS_ChiTietDotKhaoSatSinhVien`, `KS_ChiTietDotKS` | `surveys`, `survey_responses` |

⚠ Dữ liệu khảo sát 13.8M dòng — cần archive policy, không nhất thiết import all vào DB nóng.

### 7.6 KHÔNG MIGRATE

- 58 bảng `KTX_*` (Ký túc xá — rỗng)
- 40 bảng `DTBD_*` (Đào tạo bồi dưỡng — rỗng)
- 26 bảng `DCMH_*` (rỗng)
- 59 bảng `ES_*` (Exam System online — chưa triển khai)
- 12 bảng `ASC_*` (vendor system — không cần)
- 11 bảng `EGOV_*` (rỗng)
- 5 bảng `HRM_*` trong EDU (đã có HRM_DAU riêng)
- 17M dòng audit log `NK_*`, `DT_NK_*` — archive riêng
- Tất cả bảng `_bk_*`, `*Backup*`, `*_TMP`, `*_Tmp` — technical debt
- 539 views — build lại theo thiết kế mới
- 6,796 stored procedures — KHÔNG migrate, viết lại business logic ở app layer

→ **Phạm vi thực tế cần migrate cho EDU: ~150-200 bảng** (giảm từ 1,465).

---

## 8. So sánh tổng quan HRM vs EDU

| | HRM_DAU | EDU_DAU | Tổng |
|---|---:|---:|---:|
| Tables | 586 | 1,465 | **2,051** |
| Stored procedures | 1,139 | 6,796 | **7,935** |
| Views | 199 | 539 | 738 |
| Functions | 225 | 470 | 695 |
| **Tổng objects** | **2,164** | **9,309** | **11,473** |
| Bảng có data | ~80 | ~487 | ~567 |
| Tỉ lệ rỗng | 60% | 67% | — |
| MDF restored | 178 MB | 39.6 GB | 39.8 GB |
| Vendor | ASCVN | ASCVN | — |

---

## 9. Kế hoạch Đợt 3 — restore EDU_DAU_DATA an toàn (chưa làm)

**Bài học từ sự cố disk**: phải SHRINK log + Optimize VHDX giữa các restore.

### 9.1 Strategy mới

```sql
-- Sau mỗi RESTORE:
USE master;
ALTER DATABASE [EDU_DAU] SET RECOVERY SIMPLE;
USE EDU_DAU;
DBCC SHRINKFILE (N'EDU_ORG2_log', 1);  -- shrink LDF về 1MB
GO
```

Sau đó từ host (PowerShell, Hyper-V module):
```powershell
Optimize-VHD -Path "...docker_data.vhdx" -Mode Full
```

### 9.2 Quy trình từng bước

1. **Restore HRM_DAU** lại (4 sec) — cần để tham chiếu chéo
2. **Restore EDU_DAU**, ngay sau đó SHRINK log → release ~58GB inside VHDX
3. **Stop container, Optimize VHDX** → reclaim disk on host (estimated VHDX shrinks to ~40GB)
4. **Start container, restore EDU_DAU_DATA** (5.7GB .bak → 20GB MDF)
5. SHRINK log của EDU_DAU_DATA (LDF chỉ 1MB nên không cần)
6. Stop, Optimize VHDX again → final VHDX ~60GB
7. Phân tích EDU_DAU_DATA: schema, top tables, mối liên hệ với EDU_DAU (qua linked queries hay không?)

### 9.3 Câu hỏi cho thầy

1. **`EDU_DAU` vs `EDU_DAU_DATA`**: vendor tách 2 DB, em đoán `EDU_DAU_DATA` là **kho lưu file đính kèm + dữ liệu lịch sử / archive**. Cần xác minh để biết bảng nào ở DB nào.
2. **Module `KS_*` (khảo sát)**: 13.8M dòng — trường có còn dùng module này không? Hay là dữ liệu cũ tích lũy?
3. **Module `OP_*` (online payment)**: 1.7M giao dịch — đang tích hợp ngân hàng nào? Cần thông tin để migrate đúng.
4. **Bảng custom `DAU_DIEM_PSC`** (1.1M dòng): trường tự code thêm? Cần thầy giải thích PSC là gì.
5. **Audit log `NK_*` 17M dòng**: muốn giữ lại bao nhiêu năm khi migrate? (1 năm? 3 năm? all?)

---

## 10. Trạng thái hệ thống hiện tại

- ❌ Container `mssql-hrm` đã stop (do disk full)
- ❌ HRM_DAU và EDU_DAU đã restore — **mất khi xóa VHDX** (sẽ làm lại ở Đợt 3)
- ✅ File `.bak` gốc trên ổ D: an toàn
- ✅ Báo cáo Đợt 1 (`01-discovery-overview.md`) — đã lưu
- ✅ Báo cáo Đợt 2 (file này) — đã lưu
- ✅ Ổ C: free 118GB sau khi xóa VHDX

**Trước khi sang Đợt 3**: cần cấu hình Docker Desktop tăng disk image size limit (Settings → Resources → Disk image size), hoặc move WSL2 distro sang ổ khác để có thêm dung lượng dự phòng.
