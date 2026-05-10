# Discovery EDU_DAU_DATA — DB chia sẻ chứa file + audit log (Đợt 3)

**Nguồn dữ liệu**: `EDU_DAU_DATA_backup_2026_03_02_000001_6915565.bak` (5.7 GB)
**Phiên bản DB**: SQL Server (logical name `EDU_BTU_DATA`, vendor **ASCVN**)
**Restore time**: 2.2 phút (149 MB/sec)
**Dung lượng sau restore**: MDF 20 GB, LDF 1 MB (đã shrink)

---

## 1. Phát hiện cốt lõi

> **EDU_DAU_DATA KHÔNG phải bản sao của EDU_DAU.** Đây là **DB phụ chia sẻ** cho cả `HRM_DAU` và `EDU_DAU`, chuyên chứa:
>
> 1. **File đính kèm dạng BLOB** (ảnh sinh viên, ảnh nhân sự, PDF biên nhận)
> 2. **Audit log dạng XML** (lưu trữ snapshot before/after của mọi thay đổi trong các DB chính)
>
> Vendor ASCVN tách DB này ra để: (a) DB chính (HRM_DAU, EDU_DAU) gọn nhẹ, không bị lẫn BLOB nặng; (b) audit log không làm chậm OLTP.

### Bằng chứng kiến trúc shared

Trong `EDU_DAU_DATA` có các bảng prefix `HRM_*`:
- `HRM_HinhAnh` (652 dòng × 8 cột × 29 MB) — ảnh nhân sự
- `HRM_HinhAnh_HopDong`, `HRM_HinhAnh_QuyetDinh`, `HRM_HinhAnhBoSung` (rỗng)
- `HRM_NK_TongHop` (158 dòng × 9 cột) — audit log riêng cho HRM
- `HRM_DM_LoaiHinhAnh` (rỗng)

→ **Khi nhân sự upload ảnh trong HRM_DAU, ảnh thực tế được ghi vào `EDU_DAU_DATA.HRM_HinhAnh`** (chứ không phải HRM_DAU). DB nào ghi/đọc xuyên DB là vấn đề migration cần lưu ý.

---

## 2. Tổng quan kỹ thuật

| Hạng mục | EDU_DAU_DATA | So với EDU_DAU |
|---|---:|---:|
| **Tables** | **65** | 22× ít hơn |
| **Stored procedures** | **42** | 162× ít hơn |
| Views | 1 | — |
| Scalar functions | 3 | — |
| Foreign keys | 0 | — |
| **MDF** | **20 GB** | 50% size of EDU_DAU |
| **LDF** | 1 MB | (đã shrink) |

> Tỉ lệ "tables : storage" của EDU_DAU_DATA là **20 GB / 65 bảng = ~310 MB/bảng** (rất nặng), trong khi EDU_DAU là 39.6 GB / 1465 = ~27 MB/bảng. Khẳng định EDU_DAU_DATA chứa BLOB.

---

## 3. Phân loại 65 bảng theo 4 pattern

### Pattern 1: BLOB images (ảnh) — `image` type

| Bảng | Dòng | Size | Vai trò |
|---|---:|---:|---|
| `EDU_DT_SinhVien` | 19,964 | **2,769 MB** | Ảnh thẻ sinh viên (`HinhAnh image`) |
| `HRM_HinhAnh` | 652 | 29 MB | Ảnh nhân sự (`HinhAnh image`) |
| `HRM_HinhAnh_HopDong` | 0 | — | Ảnh hợp đồng (rỗng) |
| `HRM_HinhAnh_QuyetDinh` | 0 | — | Ảnh quyết định (rỗng) |
| `HRM_HinhAnh_HopDongKhac` | 0 | — | Ảnh hợp đồng khác |
| `HRM_HinhAnhBoSung` | 0 | — | Ảnh bổ sung |
| `EDU_HinhAnh_PhieuToDiem` | 0 | — | Ảnh phiếu tô điểm thi |
| `EDU_DT_HinhSinhVienDeXuat` | 0 | — | Ảnh SV đề xuất chỉnh sửa |
| `EX_EXT_ThiSinhHinhAnh` | 0 | — | Ảnh thí sinh thi tuyển |
| `EDU_TC_HinhAnhKhoanThu` | 0 | — | Ảnh khoản thu |

> **Trường có ~20K ảnh sinh viên** trong DB (không phải file system). Khi migrate Postgres, có 2 lựa chọn: (a) dùng `bytea` giữ nguyên, (b) export ra object storage (S3/MinIO) và lưu URL.

### Pattern 2: File đính kèm (PDF/binary) — `varbinary(MAX)` type

| Bảng | Dòng | Size | Vai trò |
|---|---:|---:|---|
| `EDU_KT_BienNhanNhapHoc` | 3,023 | 821 MB | Biên nhận nhập học PDF (`BienNhanFile varbinary(MAX)`) |
| `EDU_NK_FileSuaDiem` | 1,346 | 1,000 MB | Biên bản sửa điểm (file đính kèm) |
| `EDU_DT_FileDinhKem` | 0 | — | File đính kèm chung |
| `CC_ChungChiSinhVienFile` | 0 | — | File chứng chỉ SV |
| `EX_FileDapAn`, `ES_BaiThiNgoaiFileDapAn` | 0 | — | File đáp án/bài thi |
| `HT_V2_FileAttach` | 0 | — | File attach generic |

> Bảng `EDU_NK_FileSuaDiem` **đặc biệt quan trọng**: schema bao gồm `LoaiSuaDiem`, `DiemThiCu`, `DiemTongKetCu`, `DiemThiMoi`, `DiemTongKetMoi`, `LoaiFile`, `NoiDung varbinary(MAX)`, `TenFile`, `GhiChu`, `DuLieu ntext` → **business rule rút ra**: GV sửa điểm phải kèm biên bản (PDF) làm chứng từ. Quan trọng cho compliance/kiểm định.

### Pattern 3: XML audit log — `History xml` type

| Bảng | Dòng | Size | Audit cho gì |
|---|---:|---:|---|
| **`EDU_NK_TongHop`** | **1,248,820** | **3,520 MB** | Audit log tổng hợp cho mọi bảng EDU_DAU |
| `EDU_NK_DT_KetQuaHocTap` | 739,423 | 4,890 MB | Audit chuyên cho điểm môn học |
| `EDU_NK_TKB_LichHoc` | 228,736 | 842 MB | Audit lịch học |
| `EDU_NK_TKB_ChamCongLichHoc` | 154,788 | 311 MB | Audit chấm công lịch học |
| `EDU_NK_InBieuMauSinhVien` | 88,960 | 12 MB | Log in biểu mẫu SV |
| `EDU_NK_HeThong` | 26,253 | 6.3 MB | Log hệ thống |
| `EDU_NK_TKB_LichThi` | 19,623 | 102 MB | Audit lịch thi |
| `EDU_NK_TKB_ChamCongLichThi` | 20,272 | 45 MB | Audit chấm công thi |
| `EDU_NK_CongNoSinhVien` | 8,252 | 62 MB | Audit công nợ SV |
| `EDU_NK_TS_XacNhanNguyenVong` | 7,496 | 0.5 MB | Audit xác nhận NV TS |
| `EDU_NK_ChuongTrinhKhung` | 16,734 | 4.7 MB | Audit chương trình khung |
| `EDU_NK_TS_InGBTT` | 1,262 | 0.3 MB | Audit in GBTT |
| `HRM_NK_TongHop` | 158 | 0.8 MB | Audit log riêng HRM |

### Pattern 4: Audit + File evidence (kết hợp 2 và 3)

| Bảng | Dòng | Vai trò |
|---|---:|---|
| `EDU_NK_FileSuaDiem` | 1,346 | Mỗi lần sửa điểm: lưu cả XML history + file biên bản đính kèm |

---

## 4. Cấu trúc audit log XML — phân tích deep

### 4.1 Schema bảng `EDU_NK_TongHop` (audit chung)

```sql
Id           bigint
TableName    varchar(50)    -- Tên bảng bị thay đổi (trong EDU_DAU)
PrimaryKey   int            -- ID của dòng bị thay đổi
History      xml            -- Snapshot XML before/after
NguoiTao     int            -- User ID (FK đến NS_NhanSu hoặc DT_SinhVien)
NgayTao      datetime
NguoiCapNhat int
NgayCapNhat  datetime
```

### 4.2 Format XML — từ một mẫu thực tế

```xml
<row Id="46020" IDLopHocPhan="141981" NgayDiemDanh="2026-02-05T00:00:00"
     IDLichHoc="227357"
     NhanXet="* Module 01: Principles of Interior Design (cont'd)..."
     NguoiTao="858" NgayTao="2026-03-01T14:48:21.523"
     NguoiGhiNhatKy="858" NgayGhiNhatKy="2026-03-01T14:48:21.530"/>
<row Id="46020" IDLopHocPhan="141981" NgayDiemDanh="2026-02-05T00:00:00"
     IDLichHoc="227357"
     NhanXet="* Module 01: Principles of Interior Design (cont'd)..."
     NguoiTao="858" NgayTao="2026-03-01T14:48:21.523"
     NguoiCapNhat="858" NgayCapNhat="2026-03-01T14:48:26.900"
     NguoiGhiNhatKy="858" NgayGhiNhatKy="2026-03-01T14:48:26.900"/>
```

**Cấu trúc**: 2 phần tử `<row>` — phần 1 là state **before**, phần 2 là state **after**. Mọi cột của bảng nguồn được attribute hóa.

> **Đây là pattern "shadow audit"** rất tốt cho compliance: mọi thay đổi được lưu nguyên trạng. Tuy nhiên tốn dung lượng (3.5 GB chỉ cho audit log tổng hợp). Khi migrate Postgres có thể dùng:
> - `pgaudit` extension (built-in)
> - Hoặc temporal tables (system-versioned)
> - Hoặc trigger-based JSON audit (giữ pattern hiện tại nhưng JSON thay XML)

### 4.3 Phạm vi thời gian audit

| Hạng mục | Giá trị |
|---|---|
| **Earliest event** | 2018-09-28 15:21:07 |
| **Latest event** | 2026-03-01 14:48:21 |
| **Span** | **7.4 năm (2,711 ngày)** |
| **Total events** | 1,248,820 |
| **Avg events/day** | ~460 |

> Audit log có dữ liệu liên tục từ tháng 9/2018 → 3/2026 (đến thời điểm sao lưu). Trong 7.4 năm vận hành đã ghi 1.25 triệu thay đổi.

### 4.4 Top 25 bảng được audit nhiều nhất

| # | TableName (in EDU_DAU) | Audit events |
|---:|---|---:|
| 1 | `DT_KetQuaHocTapMonHoc` | 210,385 |
| 2 | `TS_ThiSinhOnlineDiemMonThi` | 125,189 |
| 3 | `DT_DiemDanhSinhVien` | 114,202 |
| 4 | `DT_TongKetDot` | 86,003 |
| 5 | `DT_HanhKiemSinhVien` | 85,739 |
| 6 | `TS_ThiSinhOnlineNguyenVong` | 50,240 |
| 7 | `TS_ThiSinhOnline` | 45,923 |
| 8 | `KT_SoThuHocPhi` | 39,917 |
| 9 | `DT_HanhKiemSinhVienTheoNamHoc` | 39,690 |
| 10 | `DT_NhanXetDiemDanh` | 38,791 |
| 11 | `DT_DangKyHocPhan` | 37,182 |
| 12 | `TKB_LopHocPhan` | 34,910 |
| 13 | `EX_DeThiChiTiet` | 32,381 |
| 14 | `TS_ThiSinhTrungTuyen` | 26,875 |
| 15 | `DT_TongKetNamHoc` | 26,014 |
| 16 | `DT_XTN_ChiTietNoMon` | 23,101 |
| 17 | `DT_TC_XetTotNghiep` | 22,417 |
| 18 | `DT_LichThiSinhVien` | 21,206 |
| 19 | `TKB_MonHoc` | 20,419 |
| 20 | `KT_SoThuKhac` | 17,835 |
| 21 | `DT_XetHocBongNamHoc` | 15,979 |
| 22 | `EX_CauTraLoi` | 14,032 |
| 23 | `DT_SinhVien` | 13,638 |
| 24 | `EX_CauHoi` | 12,818 |
| 25 | `DM_ChiTietSinhVienDotDeXuatThongTinSV` | 11,717 |

### Insights từ top 25

- **Điểm môn học bị sửa 210K lần** — phản ánh quy trình thực tế: GV nhập điểm → nhập sai → sửa nhiều lần
- **Điểm danh được audit 114K lần** — cường độ giảng dạy + hệ thống chấm công online
- **Tuyển sinh online (TS_*)** chiếm 4/10 top → **trường có hệ thống tuyển sinh online phát triển**
- **DT_TongKetDot, DT_TongKetNamHoc** (totals) — bị tính lại nhiều lần qua các đợt
- **EX_CauHoi, EX_CauTraLoi** (đề thi, đáp án) — có thay đổi nhưng ở mức vừa → đề thi có quản lý phiên bản

---

## 5. Đề xuất phạm vi migrate cho EDU_DAU_DATA

### 5.1 BẮT BUỘC migrate

| Bảng | Đề xuất xử lý |
|---|---|
| `EDU_DT_SinhVien.HinhAnh` (20K ảnh, 2.8GB) | Export ra **MinIO/S3** → URL trong Postgres `students.photo_url` |
| `HRM_HinhAnh` (652 ảnh) | Tương tự — export → URL trong `employees.photo_url` |
| `EDU_KT_BienNhanNhapHoc` (3K biên nhận, 821MB) | Export PDF ra storage, giữ metadata (`receipts.file_url`) |
| `EDU_NK_FileSuaDiem` (1.3K biên bản, 1GB) | Quan trọng cho audit/kiểm định → giữ metadata, export file |

### 5.2 NÊN migrate (audit log có chọn lọc)

| Bảng | Đề xuất |
|---|---|
| `EDU_NK_TongHop` (1.25M events) | Migrate **3 năm gần nhất** (~500K events). Phần cũ archive vào cold storage hoặc data lake |
| `EDU_NK_DT_KetQuaHocTap` (739K) | Tương tự — top bảng về size (4.9GB) |

### 5.3 KHÔNG migrate

- 50+ bảng rỗng (BLOB tables chưa dùng) — schema vendor đóng gói thừa
- Audit log nhỏ (< 10K events) — value/size thấp
- Bảng `sysdiagrams` (system table)

→ **Phạm vi thực tế: ~10 bảng cần migrate**, kèm export blob ra storage.

### 5.4 Strategy migration cho audit log

**Option A: Giữ pattern XML history** (compatible nhất)
- Postgres bảng `audit_logs(table_name, primary_key, history jsonb, ...)`
- Convert XML → JSON khi import

**Option B: Dùng temporal tables (Postgres 17+)** hoặc extension `temporal_tables`
- Trigger-based, transparent
- Mỗi bảng OLTP có shadow `*_history` table
- Phù hợp khi migrate hệ thống mới

**Option C: pgaudit extension**
- Log mọi DML statement
- Không lưu data, chỉ log SQL
- Phù hợp khi audit chỉ cần biết "ai đã chạy gì khi nào"

→ **Recommendation: Option A** (giữ pattern hiện tại, convert XML → JSON) để không break legacy compatibility.

---

## 6. Kiến trúc hệ thống tổng thể (rút ra từ 3 DB)

```
┌─────────────────────────────────────────────────────────────────┐
│                     ASCVN University Suite                      │
│                                                                 │
│  ┌────────────────┐         ┌────────────────┐                  │
│  │   HRM_DAU      │         │   EDU_DAU      │                  │
│  │ (HR module)    │         │ (Academic)     │                  │
│  │                │         │                │                  │
│  │ 586 tables     │         │ 1,465 tables   │                  │
│  │ 1,139 SPs      │         │ 6,796 SPs      │                  │
│  │ 18 FKs         │         │ 59 FKs         │                  │
│  │ 178 MB         │         │ 39.6 GB        │                  │
│  │                │         │                │                  │
│  │ ~1,024 NS      │         │ ~97K SV (cum)  │                  │
│  │ ~316 HĐ        │         │ ~75K MH        │                  │
│  └────────┬───────┘         └────────┬───────┘                  │
│           │                          │                          │
│           │  Cross-DB writes         │ Cross-DB writes          │
│           │  (BLOB + audit)          │ (BLOB + audit)           │
│           │                          │                          │
│           ▼                          ▼                          │
│  ┌──────────────────────────────────────────────┐               │
│  │            EDU_DAU_DATA                      │               │
│  │            (shared blob + audit)             │               │
│  │                                              │               │
│  │ 65 tables, 42 SPs, 20 GB                     │               │
│  │                                              │               │
│  │ • BLOB: HRM_HinhAnh, EDU_DT_SinhVien.HinhAnh │               │
│  │ • PDF:  EDU_KT_BienNhanNhapHoc, FileSuaDiem  │               │
│  │ • XML audit: 1.25M events (2018-2026)        │               │
│  └──────────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────────┘
```

### Đặc điểm quan trọng

1. **3 DB chia sẻ**, business logic xuyên DB qua stored procedures
2. **Tất cả thay đổi lớn được audit** vào EDU_DAU_DATA (compliance level cao)
3. **Tách BLOB ra DB riêng** giúp DB chính nhẹ và backup nhanh
4. **DAU đã vận hành hệ thống ASCVN từ ít nhất 2018** (audit log có từ tháng 9/2018)

---

## 7. Câu hỏi cần thầy xác nhận trước khi sang Đợt 4

1. **Lưu trữ ảnh khi migrate**: Postgres `bytea` (giữ nguyên cách) hay tách ra **MinIO/S3** (best practice)?
2. **Audit retention**: Giữ bao lâu audit log của hệ mới?
   - **(a)** 1 năm (compliance tối thiểu)
   - **(b)** 3 năm (kiểm định ABET cần 3 chu kỳ)
   - **(c)** All (giữ nguyên 7.4 năm)
3. **Migration audit log lịch sử**: Có cần import 1.25M events cũ vào hệ mới? Hay chỉ start audit từ thời điểm cutover?
4. **Trường còn dùng "EDU_NK_FileSuaDiem"** (1.3K biên bản sửa điểm) — pattern này có giữ trong hệ mới không? (Em recommend GIỮ vì rất quan trọng cho kiểm định AUN-QA / ABET).

---

## 8. Trạng thái hệ thống hiện tại

- ✅ Container `mssql-edu` đang chạy (port 1433, password `YourStrong@Pass1`)
- ✅ DB `EDU_DAU_DATA` ONLINE — có thể connect SSMS/DBeaver để khám phá
- ✅ LDF đã shrink xuống 1MB (không còn lo disk full)
- ✅ Ổ C: free ~95GB sau restore (đủ chỗ restore thêm HRM_DAU + EDU_DAU sau này)
- ❌ HRM_DAU và EDU_DAU chưa restore lại — cần Đợt 4 nếu muốn cross-query

### Đề xuất cho Đợt 4 (khi thầy sẵn sàng)

**Lựa chọn A — Phân tích sâu EDU_DAU_DATA hiện tại**:
- Sample BLOB data, đọc XML audit cho các vụ sửa điểm cụ thể
- Reconstruct timeline thay đổi của 1 sinh viên cụ thể
- Đánh giá quality dữ liệu

**Lựa chọn B — Restore lại HRM + EDU full**:
- Có cả 3 DB online cùng lúc
- Cross-query: "tìm SV X có ảnh ở đâu", "audit log của SV này"
- Cần ~85GB disk → vẫn an toàn

**Lựa chọn C — Bắt đầu thiết kế Postgres target schema**:
- Đã đủ dữ liệu để vẽ ERD đích
- Bỏ qua restore tiếp, sang phase migration design
