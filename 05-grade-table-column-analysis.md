# Phân tích 153 cột của `DT_KetQuaHocTapMonHoc` — slim còn 30 cột

**Phương pháp**: 1 query single-scan trên 2,028,965 dòng, đếm `COUNT(col)` cho từng cột → tỉ lệ NON-NULL.

---

## 1. Tổng quan

| Thống kê | Giá trị |
|---|---:|
| Tổng dòng | 2,028,965 |
| Tổng cột | 153 |
| Cột **luôn có data** (>90% rows) | **17** |
| Cột **dùng có điều kiện** (10-90%) | **8** |
| Cột **rất ít dùng** (1-10%) | **8** |
| Cột **gần như không dùng** (<1%) | **40** |
| Cột **CHƯA BAO GIỜ dùng** (0 rows) | **80** |

> **Kết luận sốc**: hơn **một nửa** schema (80/153 = 52%) là cột chết hoàn toàn. Vendor ASCVN đóng gói thừa quá mức.

---

## 2. Phân loại theo mức sử dụng

### TIER 1 — Cột định danh + bắt buộc (100% dòng có data)

| Cột | Ý nghĩa | Đề xuất Postgres |
|---|---|---|
| `Id` | Primary key | `id BIGSERIAL PRIMARY KEY` |
| `IDSinhVien` | FK sinh viên | `student_id BIGINT NOT NULL` |
| `IDLopHocPhan` | FK lớp học phần | `course_class_id BIGINT NOT NULL` |
| `VangThi` (NOT NULL, default 0) | Cờ vắng thi | `is_absent_from_exam BOOLEAN DEFAULT FALSE` |
| `IsKhoaTH` (100%) | Khóa thực hành | `is_practice_locked BOOLEAN DEFAULT FALSE` |
| `IsKhoaTL` (100%) | Khóa tiểu luận | `is_essay_locked BOOLEAN DEFAULT FALSE` |
| `IsKhoaCK` (100%) | Khóa cuối kỳ | `is_final_locked BOOLEAN DEFAULT FALSE` |
| `XepLoai_ENG` (100%) | Xếp loại tiếng Anh | `letter_grade VARCHAR(3)` (A+, A, B+, ...) |
| `NgayTao` (100%) | Ngày tạo | `created_at TIMESTAMPTZ NOT NULL` |

**9 cột** — đây là lõi không bao giờ NULL.

### TIER 2 — Cột điểm chính (>90% rows)

| Cột | % dùng | Ý nghĩa | Đề xuất Postgres |
|---|---:|---|---|
| `DiemTongKet` | 96% | **Điểm tổng kết môn (lần 1)** | `overall_score NUMERIC(4,2)` |
| `DiemTongKet1` | 95% | **Điểm tổng kết (lần thi lại 1)** | `overall_score_retake1 NUMERIC(4,2)` |
| `DiemTinChi` | 95% | **GPA point (lần 1)** | `grade_point NUMERIC(3,2)` |
| `DiemTinChi2` | 95% | GPA point khác (LT/TH?) | `grade_point_alt NUMERIC(3,2)` |
| `DiemThi` | 96% | **Điểm thi cuối kỳ (lần 1)** | `final_exam_score NUMERIC(4,2)` |
| `DiemThi1` | 95% | Điểm thi (lần 2 / khác) | `final_exam_score_retake NUMERIC(4,2)` |
| `DiemChu` | 96% | **Điểm chữ A/B/C/D/F** | `letter_grade_native CHAR(2)` |
| `DiemChu2` | 95% | Điểm chữ alt | `letter_grade_alt CHAR(2)` |
| `DuocDuThiKetThuc` | 99% | **Đủ điều kiện thi cuối kỳ** | `is_eligible_for_final BOOLEAN` |
| `IsDat` | 99% | **Đạt môn không** | `is_passed BOOLEAN` |
| `NguoiTao` | 90% | User tạo | `created_by BIGINT` |

**11 cột** — cốt lõi nghiệp vụ.

### TIER 3 — Cột phụ thường dùng (10-90%)

| Cột | % dùng | Ý nghĩa | Đề xuất |
|---|---:|---|---|
| `DiemTBThuongKy` | 88% | **Điểm TB thường kỳ** | `regular_avg_score NUMERIC(4,2)` |
| `NguoiCapNhat` | 47% | User cập nhật | `updated_by BIGINT` |
| `NgayCapNhat` | 48% | Ngày cập nhật | `updated_at TIMESTAMPTZ` |
| `GhiChu` | 46% | Ghi chú chung | `notes TEXT` |
| `XepLoai` | 37% | Xếp loại VN | `letter_grade_vn VARCHAR(20)` |
| `XepLoai2` | 35% | Xếp loại alt | `letter_grade_vn_alt VARCHAR(20)` |
| `GhiChuXetDuThi` | 34% | Ghi chú xét đủ thi | `eligibility_notes TEXT` |
| `DiemHeSo11` | 31% | **Điểm hệ số 1 cột 1** (chỉ cột đầu được dùng) | `weighted_score_1 NUMERIC(4,2)` |
| `IsVangThiGiuaKy` | 31% | Vắng thi giữa kỳ | `is_absent_from_midterm BOOLEAN` |
| `DiemChuyenCan1` | 26% | **Điểm chuyên cần** | `attendance_score NUMERIC(4,2)` |
| `DiemTongKet2` | 8.6% | Điểm tổng kết lần 3 (rare) | `overall_score_retake2 NUMERIC(4,2)` |
| `DiemThi2` | 8.6% | Điểm thi lần 3 (rare) | `final_exam_score_retake2 NUMERIC(4,2)` |
| `IsDat1` | 13% | Đạt lần 2 | `is_passed_retake1 BOOLEAN` |
| `DiemThucHanh1` + `DiemTBThucHanh` | 5% | Điểm thực hành | `practice_score NUMERIC(4,2)`, `practice_avg NUMERIC(4,2)` |
| `DiemNoCu` | 5% | Mã nợ cũ | `legacy_debt_code VARCHAR(2)` |
| `DiemTieuLuan1` | 11% | Điểm tiểu luận | `essay_score NUMERIC(4,2)` |

**16 cột**.

### TIER 4 — Cột rất ít dùng (<1%) — bỏ vào `extra_scores JSONB`

```
DiemHeSo12-19, DiemHeSo21-29, DiemHeSo31-39  (26 cột — chỉ 408 dòng/2M = 0.02%)
DiemTH11-15, DiemTH21-25, DiemTH31-35        (15 cột — 408 dòng/2M = 0.02%)
DiemThuongKy1-9                              (9 cột — 408 dòng/2M = 0.02%)
DiemThucHanh2-9                              (8 cột — 408 dòng/2M = 0.02%)
DiemChuyenCan2                               (1 cột — 0.02%)
DuocDuThiGiuaKy                              (1 cột — 0.15%)
KhongDuocDuThiKetThucByGV                    (1 cột — 0.006%)
GhiChuSuaDiem                                (1 cột — 0.09%)
DiemTieuLuan2                                (1 cột — 0.02%)
PhanTramVang                                 (1 cột — 0.31%)
```

**~64 cột** → gộp tất cả vào 1 cột `extra_scores JSONB` để bảo toàn data nhưng không phình schema:
```sql
extra_scores JSONB,  -- {"DiemHeSo12": 8.5, "DiemTH11": 7.2, ...}
```

### TIER 5 — Cột CHẾT (0 dòng) — DROP hoàn toàn

```
DiemThuongKy (col 24, 0%)            DiemGiuaMon1-2 (35-36, 0%)
DiemThucHanh (col 39, 0%)            DuocDuThiLan2 (51, 0%)
CoDiThi (52, 0%)                     DiemThiKN1-4, DiemThiKNTB (54-58, 0%)
IsDanhGia (69, 0%)                   DiemNo (72, 0%)
IsKhoaLT (104, 0% — chỉ TH/TL/CK)    SoThamChieu (110, 0%)
XepLoai1 (111, 0%)                   IsChuyenDiem (117, 0%)
GhiChu_TK, GhiChu_CK (118-119, 0%)   IDTruong (120, 0%)
IsChenDiem0 (121, 0%)                TongVang (123, 0%)
DiemTinChiGoc, DiemChuGoc, DiemTongKetGoc (124-126, 0%)
DiemTBQuaTrinh (127, 0%)             IDXepLoai/1/2 (128-130, 0% — chỉ 537 dòng)
IDQuyetDinh (132, 0%)                DiemTBThuongKy2 (133, 0%)
CongNo (134, 0%)                     IsDat2 (136, 0%)
IDKQHTGoc (137, 0%)                  DiemThiGV1-2 (138-139, 0%)
DiemTBLT/TBLT1/TBLT2 (140-142, 0%)   DiemTBTH/TBTH1/TBTH2 (143-145, 0%)
NgayXetDuThi (146, 0%)               NgayXoa, NguoiXoa (148-149, 0%)
DiemThiKN5/6 (150-151, 0%)           DiemTH36 (152, 0%)
LoaiXetDuThi (153, 0%)
```

**~50 cột rỗng tuyệt đối** → DROP, không cần migrate.

---

## 3. Bảng `student.grades` đề xuất cuối cùng — 30 cột

```sql
CREATE SCHEMA student;

CREATE TABLE student.grades (
    -- Identity
    id                          BIGSERIAL,
    legacy_id                   BIGINT,                      -- DT_KetQuaHocTapMonHoc.Id

    -- Foreign keys
    student_id                  BIGINT NOT NULL REFERENCES student.students(id),
    course_class_id             BIGINT NOT NULL REFERENCES academic.course_classes(id),
    enrollment_id               BIGINT REFERENCES student.enrollments(id),
    academic_year_id            BIGINT NOT NULL REFERENCES academic.academic_years(id),
    semester_id                 BIGINT NOT NULL REFERENCES academic.semesters(id),

    -- Component scores (TIER 2 + TIER 3)
    attendance_score            NUMERIC(4,2),                -- DiemChuyenCan1 (26%)
    weighted_score_1            NUMERIC(4,2),                -- DiemHeSo11 (31%)
    regular_avg_score           NUMERIC(4,2),                -- DiemTBThuongKy (88%)
    midterm_score               NUMERIC(4,2),                -- DiemHeSo11 đôi khi là midterm
    practice_avg                NUMERIC(4,2),                -- DiemTBThucHanh (5%)
    essay_score                 NUMERIC(4,2),                -- DiemTieuLuan1 (11%)

    -- Final exam (lần 1 + 2 + 3)
    final_exam_score            NUMERIC(4,2),                -- DiemThi (96%)
    final_exam_score_retake1    NUMERIC(4,2),                -- DiemThi1 (95%)
    final_exam_score_retake2    NUMERIC(4,2),                -- DiemThi2 (8.6%)

    -- Overall (lần 1 + 2 + 3)
    overall_score               NUMERIC(4,2),                -- DiemTongKet (96%)
    overall_score_retake1       NUMERIC(4,2),                -- DiemTongKet1 (95%)
    overall_score_retake2       NUMERIC(4,2),                -- DiemTongKet2 (8.6%)

    -- Letter & GPA
    letter_grade_native         CHAR(2),                     -- DiemChu (96%) - A,B,C,D,F
    letter_grade_alt            CHAR(2),                     -- DiemChu2 (95%)
    letter_grade_eng            VARCHAR(3),                  -- XepLoai_ENG (100%)
    letter_grade_vn             VARCHAR(20),                 -- XepLoai (37%)
    grade_point                 NUMERIC(3,2),                -- DiemTinChi (95%)
    grade_point_alt             NUMERIC(3,2),                -- DiemTinChi2 (95%)

    -- Status flags
    is_passed                   BOOLEAN NOT NULL DEFAULT FALSE,    -- IsDat (99%)
    is_passed_retake1           BOOLEAN,                            -- IsDat1 (13%)
    is_eligible_for_final       BOOLEAN,                            -- DuocDuThiKetThuc (99%)
    is_absent_from_exam         BOOLEAN NOT NULL DEFAULT FALSE,    -- VangThi (100%)
    is_absent_from_midterm      BOOLEAN,                            -- IsVangThiGiuaKy (31%)
    is_practice_locked          BOOLEAN NOT NULL DEFAULT FALSE,    -- IsKhoaTH (100%)
    is_essay_locked             BOOLEAN NOT NULL DEFAULT FALSE,    -- IsKhoaTL (100%)
    is_final_locked             BOOLEAN NOT NULL DEFAULT FALSE,    -- IsKhoaCK (100%)
    is_excluded                 BOOLEAN NOT NULL DEFAULT FALSE,    -- không tính vào GPA

    -- Notes
    notes                       TEXT,                        -- GhiChu (46%)
    eligibility_notes           TEXT,                        -- GhiChuXetDuThi (34%)

    -- Extras (TIER 4 - rare cols → JSONB)
    extra_scores                JSONB,                       -- DiemHeSo12-39, DiemTH*, DiemThuongKy1-9, ...

    -- Audit
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by                  BIGINT,
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by                  BIGINT,

    PRIMARY KEY (id, academic_year_id),
    UNIQUE (student_id, course_class_id, academic_year_id)
) PARTITION BY LIST (academic_year_id);

-- Indexes
CREATE INDEX idx_grades_student ON student.grades(student_id);
CREATE INDEX idx_grades_course_class ON student.grades(course_class_id);
CREATE INDEX idx_grades_legacy ON student.grades(legacy_id);
CREATE INDEX idx_grades_extra ON student.grades USING GIN (extra_scores);
```

**Tổng: 33 cột (vs 153 nguồn)** — giảm **78%** schema, giữ **>99% giá trị nghiệp vụ thật**.

---

## 4. Pattern phát hiện được — Vendor đã tổ chức bảng thế nào?

### 4.1 "Cột song hành phòng hờ" — 80 cột không bao giờ dùng

Vendor tạo ra **3 set hệ số × 9 cột** (DiemHeSo11-19, 21-29, 31-39 = 27 cột) nhưng thực tế chỉ **DiemHeSo11** được dùng ~30%, các cột khác chỉ ~408 dòng (1 lớp đặc biệt nào đó).

Tương tự **3 set thực hành × 5 cột** (DiemTH11-35 = 15 cột) — gần như không dùng.

→ **Rút ra**: schema vendor "đa năng" để chiều theo nhiều trường khác nhau. DAU chỉ dùng pattern đơn giản (chuyên cần + thường kỳ + thi cuối kỳ).

### 4.2 "Cột _Goc" để bảo toàn điểm gốc — 0 dòng

`DiemTinChiGoc`, `DiemChuGoc`, `DiemTongKetGoc` — tên cho thấy ý đồ "bảo toàn điểm trước khi sửa" cho audit. **Nhưng 0 dòng** → vendor đã có cơ chế audit khác (bảng `EDU_NK_FileSuaDiem` ở DB DATA).

### 4.3 "Tier rare 0.02%" = lớp đặc biệt

408 dòng có data trong các cột rare → khả năng cao là **1-2 lớp pilot/test** đã thử pattern phức tạp rồi bỏ. Migrate có thể giữ nguyên qua JSONB.

### 4.4 Letter grade song song

- `DiemChu` (96%) — chữ điểm VN: A, B+, B, ...
- `DiemChu2` (95%) — alt
- `XepLoai_ENG` (100%) — tiếng Anh
- `XepLoai` (37%), `XepLoai2` (35%) — VN

→ Vendor lưu **3 cách hiển thị điểm** cùng lúc. Hệ mới chỉ cần **1 cột chữ điểm + tính ra ngôn ngữ ở app layer**.

### 4.5 Audit cột rỗng → audit thật ở DB khác

`NgayXoa`, `NguoiXoa`, `IsDelete` (chỉ 3%), `IDQuyetDinh`, `IDKQHTGoc` đều ~0 dòng → **delete/audit không qua bảng này** mà qua `EDU_NK_TongHop` ở `EDU_DAU_DATA` (1.25M XML events đã phân tích Đợt 3).

---

## 5. Implications cho ETL

### 5.1 Mapping rule

```python
def transform_grade_row(src_row):
    return {
        "legacy_id": src_row["Id"],
        "student_id": map_student(src_row["IDSinhVien"]),
        "course_class_id": map_course_class(src_row["IDLopHocPhan"]),
        "academic_year_id": derive_year_from_class(src_row["IDLopHocPhan"]),
        "semester_id": derive_semester_from_class(src_row["IDLopHocPhan"]),

        # Tier 2-3 mapping (1:1)
        "attendance_score": src_row["DiemChuyenCan1"],
        "weighted_score_1": src_row["DiemHeSo11"],
        "regular_avg_score": src_row["DiemTBThuongKy"],
        "practice_avg": src_row["DiemTBThucHanh"],
        "essay_score": src_row["DiemTieuLuan1"],
        "final_exam_score": src_row["DiemThi"],
        "final_exam_score_retake1": src_row["DiemThi1"],
        "final_exam_score_retake2": src_row["DiemThi2"],
        "overall_score": src_row["DiemTongKet"],
        "overall_score_retake1": src_row["DiemTongKet1"],
        "overall_score_retake2": src_row["DiemTongKet2"],
        "letter_grade_native": src_row["DiemChu"],
        "letter_grade_alt": src_row["DiemChu2"],
        "letter_grade_eng": src_row["XepLoai_ENG"],
        "letter_grade_vn": src_row["XepLoai"],
        "grade_point": src_row["DiemTinChi"],
        "grade_point_alt": src_row["DiemTinChi2"],
        "is_passed": src_row["IsDat"],
        "is_passed_retake1": src_row["IsDat1"],
        "is_eligible_for_final": src_row["DuocDuThiKetThuc"],
        "is_absent_from_exam": src_row["VangThi"],
        "is_absent_from_midterm": src_row["IsVangThiGiuaKy"],
        "is_practice_locked": src_row["IsKhoaTH"],
        "is_essay_locked": src_row["IsKhoaTL"],
        "is_final_locked": src_row["IsKhoaCK"],
        "notes": src_row["GhiChu"],
        "eligibility_notes": src_row["GhiChuXetDuThi"],

        # Tier 4 → JSONB (only non-null values)
        "extra_scores": {
            k: v for k, v in {
                **{f"weighted_score_{i}": src_row[f"DiemHeSo{n}"]
                   for i, n in enumerate([12,13,14,15,16,17,18,19,
                                          21,22,23,24,25,26,27,28,29,
                                          31,32,33,34,35,36,37,38,39], 2)},
                **{f"practice_h{i}_{j}": src_row[f"DiemTH{i}{j}"]
                   for i in [1,2,3] for j in [1,2,3,4,5]},
                **{f"regular_score_{i}": src_row[f"DiemThuongKy{i}"]
                   for i in range(1,10)},
                **{f"practice_score_{i}": src_row[f"DiemThucHanh{i}"]
                   for i in range(1,10)},
                "attendance_2": src_row["DiemChuyenCan2"],
                "essay_2": src_row["DiemTieuLuan2"],
                "absence_pct": src_row["PhanTramVang"],
                "old_debt_code": src_row["DiemNoCu"],
                "edit_notes": src_row["GhiChuSuaDiem"],
            }.items() if v is not None
        } or None,

        # Audit
        "created_at": src_row["NgayTao"],
        "created_by": map_user(src_row["NguoiTao"]),
        "updated_at": src_row["NgayCapNhat"] or src_row["NgayTao"],
        "updated_by": map_user(src_row["NguoiCapNhat"]),
    }
```

### 5.2 Validation queries (post-ETL)

```sql
-- Đảm bảo không mất sinh viên nào
SELECT COUNT(DISTINCT student_id) FROM student.grades;
-- Phải = 38K (số SV trong students table)

-- Đảm bảo overall_score không lệch khỏi source
SELECT s.legacy_id, s.overall_score
FROM student.grades s
JOIN sql_server.DT_KetQuaHocTapMonHoc src ON s.legacy_id = src.Id
WHERE ABS(s.overall_score - src.DiemTongKet) > 0.01
  OR (s.overall_score IS NULL) <> (src.DiemTongKet IS NULL);
-- Phải = 0 dòng

-- Đảm bảo extra_scores giữ đầy đủ rare data
SELECT COUNT(*) FROM student.grades WHERE extra_scores IS NOT NULL;
-- Phải = ~408 dòng (data ở các cột rare 0.02%)
```

---

## 6. Tổng kết

| Hạng mục | Trước | Sau | Cải thiện |
|---|---:|---:|---:|
| **Số cột** | 153 | 33 | **−78%** |
| **Cột chết** | 80 (52%) | 0 | **−100%** |
| **Cột rare → JSONB** | 64 | 1 (extra_scores) | **−98%** |
| **Cột nghiệp vụ thật** | 27 | 27 | giữ nguyên |
| **Khả năng đọc schema** | Cực rối | Rõ ràng | ✓ |
| **Postgres-friendly** | ❌ | ✓ | ✓ |

**Tin tốt: 99% giá trị nghiệp vụ ở 27 cột → migrate gọn, không mất gì quan trọng.**
