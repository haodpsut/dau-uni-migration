# Thiết kế DB đích & Kế hoạch Migration sang Postgres / Ubuntu

**Ngày**: 2026-05-08
**Phạm vi**: Core only — ~50 bảng phủ Sinh viên + Nhân sự + Đào tạo + Môn học + Điểm + Hợp đồng
**Mục tiêu**: Bóc tách dữ liệu từ 3 DB SQL Server (HRM_DAU + EDU_DAU + EDU_DAU_DATA) → 1 Postgres DB hiện đại trên Ubuntu, có thể tự control hoàn toàn.

---

## 0. Quyết định nền tảng (đã chốt)

| Quyết định | Lựa chọn |
|---|---|
| **Naming** | `snake_case` tiếng Anh (`students`, `enrollments`, `grades`) |
| **Primary key** | `BIGSERIAL` (auto-increment, dễ migrate INT IDENTITY của hệ cũ) |
| **BLOB storage** | **MinIO** trên Ubuntu (S3-compatible, self-hosted, Postgres chỉ giữ URL) |
| **Scope đợt đầu** | Core ~50 bảng (sau này mở rộng) |
| **Postgres version** | 16 LTS (2026 còn được support ít nhất tới 2028) |
| **OS** | Ubuntu 24.04 LTS |
| **Charset** | UTF-8, collation `vi-VN-x-icu` |
| **Timezone** | `Asia/Ho_Chi_Minh` |

---

## 1. Triết lý thiết kế (10 nguyên tắc)

1. **Foreign keys ENFORCED** — hệ cũ chỉ 18-59 FK, hệ mới mọi quan hệ đều có FK. Đảm bảo không có orphan rows.
2. **3NF + selective denormalization** — không tạo bảng 153 cột như hệ cũ. Tách ra `students` + `student_extended_info` nếu cần.
3. **JSONB cho dữ liệu bán cấu trúc** — thay XML audit, thay các bảng "settings" linh hoạt.
4. **CHECK constraints + ENUM types** — không tin app validate, DB tự enforce. Ví dụ `gender CHECK (gender IN ('M','F','O'))`.
5. **Soft delete bằng `deleted_at TIMESTAMPTZ`** — không xóa thật, chỉ mark.
6. **Audit cột chuẩn**: `created_at`, `created_by`, `updated_at`, `updated_by`, `deleted_at` cho mọi bảng nghiệp vụ.
7. **TIMESTAMPTZ thay DATETIME** — luôn có timezone, tránh confusion khi deploy multi-region sau này.
8. **Indexes có chủ đích** — chỉ index trên FK, cột tìm kiếm thật. Hệ cũ over-index gấp 3-5 lần cần thiết.
9. **Partitioning cho bảng lớn** — `enrollments`, `grades` partition theo `academic_year_id` để query năm cụ thể nhanh.
10. **Row-level security (RLS) cho data nhạy cảm** — Postgres RLS policy cho `salary_history`, `grades` (chỉ owner + admin xem).

---

## 2. Data triage — Phải lấy gì, bỏ gì

### 2.1 Từ `HRM_DAU` (586 bảng → giữ ~12 bảng có data thật)

| Source table (SQL Server) | Số dòng | Giữ? | Đích Postgres |
|---|---:|---|---|
| `NS_NhanSu` | 1,024 | ✅ Core | `employees` (gộp với NhanSuEx) |
| `NS_HopDong` | 316 | ✅ Core | `contracts` |
| `NS_PhuLucHopDong` | 17 | ✅ Core | `contract_addendums` |
| `NS_QuaTrinhDaoTao` | 872 | ✅ Core | `employee_training_history` |
| `NS_QuaTrinhCongTacChuyenMon` | 11 | ✅ Core | `employee_career_history` |
| `NS_QuaTrinhNghienCuu` | 69 | ✅ Core | `employee_research_history` |
| `NS_QuanHeGiaDinh` | 1,228 | ✅ Core | `employee_family_relations` |
| `NS_HeSoLuong` | 364 | ✅ Core | `salary_grades` |
| `NS_PhuCap` | 339 | ✅ Core | `allowances` |
| `NS_BaoHiem` + `NS_QuaTrinhDongBaoHiem` | 39,582 | ✅ Core | `insurance_history` |
| `NS_QuyetDinh` + `NS_HienTaiQD` + `NK_QuyetDinh` | 331 | ✅ Core | `decisions` (gộp 3 bảng) |
| `DM_PhongBan`, `DM_ToBoMon`, `DM_ChucVu`, `DM_ChucDanh` | <100 | ✅ Master | `departments`, `divisions`, `positions`, `titles` |
| `DM_TinhThanh`, `DM_Huyen`, `DM_BH_Xa`, `DM_DanToc`, `DM_TonGiao` | ~12K | ✅ Master | `provinces`, `districts`, `wards`, `ethnicities`, `religions` |
| `DM_HocVi`, `DM_HocHam`, `DM_NgachCongChuc` | ~25 | ✅ Master | `degrees`, `academic_ranks`, `civil_ranks` |
| 350+ bảng rỗng (KPI, Quy hoạch, Chấm công, Tuyển dụng…) | 0 | ❌ Bỏ | — |
| `BL_TinhLuong` (35K dòng) | 35,432 | ⏳ Không core | Đợt 2: `payroll_calculations` |
| `bk_NS_LUONG_20231218` | 899 | ❌ Bỏ | Backup tay |
| Stored procedures (1,139) | — | ❌ Bỏ | Viết lại ở app layer |

### 2.2 Từ `EDU_DAU` (1,465 bảng → giữ ~30 bảng có data thật)

| Source | Số dòng | Giữ? | Đích Postgres |
|---|---:|---|---|
| `DT_HoSoSinhVien` + `DT_SinhVien` + `DT_ThongTinSinhVien` + `DT_SinhVienEx` | 4 bảng | ✅ Core (GỘP) | `students` (1 bảng duy nhất, các cột optional nullable) |
| `DT_DSSinhVienTotNghiep` | 17,969 | ✅ Core | `graduations` |
| `TKB_MonHoc` | 75,614 | ✅ Core | `subjects` |
| `DT_MonHocTuongDuong` | 240,992 | ✅ Core | `subject_equivalences` |
| `TKB_LopHocPhan` | 82,501 | ✅ Core | `course_classes` |
| `TKB_LopHoc` | 55,468 | ✅ Core | `student_classes` |
| `TKB_LichHoc` + `TKB_LichHocGiangVien` | 393K | ⏳ Không core | Đợt 2: `class_schedules` |
| `DT_DangKyHocPhan` | 2,300,818 | ✅ Core | `enrollments` (partition theo year) |
| `NK_HuyDangKyHocPhan` | 310,228 | ⏳ Không core | Đợt 2: archive log |
| `DT_KetQuaHocTapMonHoc` (153 cột!) | 2,028,965 | ✅ Core | `grades` (slim ~30 cột) |
| `DT_HanhKiemSinhVien` | 303,850 | ⏳ Không core | Đợt 2: `conduct_scores` |
| `DT_GhiChuSinhVien` | 1,886,276 | ❌ Bỏ | Đa phần là note linh tinh, không value cao |
| `DT_DiemDanhSinhVien` | 93,057 | ⏳ Không core | Đợt 2 |
| `EX_DiemThiChiTiet` | 942,008 | ⏳ Không core | Đợt 2: `exam_scores` |
| `TS_*` (Tuyển sinh, ~500K dòng) | 500K | ⏳ Không core | Đợt 3 (nếu giữ module TS) |
| `KT_*` (Tài chính, ~1M dòng) | 1M | ⏳ Không core | Đợt 3 (nếu giữ module finance) |
| `OP_*` (Online payment, 1.7M) | 1.7M | ⏳ Không core | Đợt 3 |
| `KS_*` (Khảo sát, 13.8M) | 13.8M | ❌ Bỏ | Quá legacy, value/size thấp |
| `DT_KetQuaHocTapMonHoc_bk_*` (3.6M) | 3.6M | ❌ Bỏ | Backup tay |
| 6,796 stored procedures | — | ❌ Bỏ | Viết lại |
| 539 views | — | ❌ Bỏ | Viết lại |

### 2.3 Từ `EDU_DAU_DATA` (65 bảng → giữ ~5 bảng)

| Source | Số dòng | Giữ? | Đích |
|---|---:|---|---|
| `EDU_DT_SinhVien.HinhAnh` (BLOB) | 19,964 ảnh | ✅ Core | Export ra MinIO bucket `students/photos/{student_id}.jpg`, lưu URL trong `students.photo_url` |
| `HRM_HinhAnh` (BLOB ảnh NS) | 652 ảnh | ✅ Core | Export ra MinIO `employees/photos/{employee_id}.jpg`, lưu URL trong `employees.photo_url` |
| `EDU_KT_BienNhanNhapHoc` (PDF) | 3,023 PDF | ⏳ Không core | Đợt 3: MinIO `receipts/{id}.pdf` |
| `EDU_NK_FileSuaDiem` (PDF biên bản) | 1,346 PDF | ✅ Core (compliance) | MinIO + bảng `grade_change_records` (rất quan trọng cho kiểm định) |
| `EDU_NK_TongHop` (XML audit) | 1.25M events | ⏳ Có chọn lọc | Đợt 2: import 3 năm gần nhất, convert XML → JSONB, vào bảng `audit_logs` |
| `EDU_NK_DT_KetQuaHocTap` (audit điểm) | 739K | ⏳ Có chọn lọc | Đợt 2: gộp vào `audit_logs` |
| 50+ bảng rỗng | 0 | ❌ Bỏ | — |

---

## 3. Bounded contexts — Cấu trúc Postgres schema

```
PostgreSQL: dau_university
│
├─ schema: identity         (Identity & Access)
│   ├─ users
│   ├─ roles
│   ├─ user_roles
│   └─ sessions
│
├─ schema: master           (Master data, ít thay đổi)
│   ├─ provinces, districts, wards
│   ├─ ethnicities, religions, countries
│   ├─ departments, divisions
│   ├─ positions, titles
│   ├─ degrees, academic_ranks, civil_ranks
│   ├─ specializations
│   └─ contract_types, decision_types, allowance_types
│
├─ schema: hr               (HR module — kế thừa HRM_DAU)
│   ├─ employees            ← gộp NS_NhanSu + NS_NhanSuEx
│   ├─ contracts            ← NS_HopDong
│   ├─ contract_addendums   ← NS_PhuLucHopDong
│   ├─ employee_family_relations
│   ├─ employee_training_history
│   ├─ employee_career_history
│   ├─ employee_research_history
│   ├─ allowances
│   ├─ insurance_history
│   ├─ salary_grades
│   └─ decisions
│
├─ schema: academic         (Academic catalog — kế thừa EDU_DAU/TKB_*)
│   ├─ academic_years
│   ├─ semesters
│   ├─ programs             ← chương trình đào tạo
│   ├─ subjects             ← TKB_MonHoc
│   ├─ subject_equivalences ← DT_MonHocTuongDuong
│   ├─ course_classes       ← TKB_LopHocPhan (lớp học phần)
│   └─ student_classes      ← TKB_LopHoc (lớp hành chính)
│
├─ schema: student          (Student records — kế thừa EDU_DAU/DT_*)
│   ├─ students             ← gộp 4 bảng SV
│   ├─ enrollments          ← DT_DangKyHocPhan (PARTITION theo academic_year_id)
│   ├─ grades               ← DT_KetQuaHocTapMonHoc (slim 30 cột, PARTITION)
│   └─ graduations          ← DT_DSSinhVienTotNghiep
│
├─ schema: files            (Attachments — kế thừa EDU_DAU_DATA)
│   ├─ attachments          ← metadata file (URL MinIO + checksum)
│   └─ grade_change_records ← EDU_NK_FileSuaDiem (compliance)
│
└─ schema: audit            (Cross-cutting)
    └─ audit_logs           ← EDU_NK_TongHop (XML → JSONB, 3 năm gần nhất)
```

**Tổng: 6 schema, ~50 bảng.**

---

## 4. Sample DDL — 6 entities cốt lõi

### 4.1 `master.provinces` + `master.districts` + `master.wards`

```sql
CREATE SCHEMA master;

CREATE TABLE master.provinces (
    id          BIGSERIAL PRIMARY KEY,
    code        VARCHAR(10) UNIQUE NOT NULL,        -- mã chuẩn QG: '048' = Đà Nẵng
    name        TEXT NOT NULL,
    region      TEXT,                                -- Bắc/Trung/Nam
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ
);

CREATE TABLE master.districts (
    id           BIGSERIAL PRIMARY KEY,
    code         VARCHAR(10) UNIQUE NOT NULL,
    name         TEXT NOT NULL,
    province_id  BIGINT NOT NULL REFERENCES master.provinces(id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at   TIMESTAMPTZ
);

CREATE INDEX idx_districts_province ON master.districts(province_id) WHERE deleted_at IS NULL;

CREATE TABLE master.wards (
    id           BIGSERIAL PRIMARY KEY,
    code         VARCHAR(10) UNIQUE NOT NULL,
    name         TEXT NOT NULL,
    district_id  BIGINT NOT NULL REFERENCES master.districts(id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at   TIMESTAMPTZ
);

CREATE INDEX idx_wards_district ON master.wards(district_id) WHERE deleted_at IS NULL;
```

> Source: `DM_TinhThanh` (65) + `DM_Huyen` (760) + `DM_BH_Xa` (11,706). Drop bảng trùng `DM_BH_Tinh`, `DM_BH_Huyen`.

### 4.2 `hr.employees`

```sql
CREATE SCHEMA hr;

CREATE TYPE hr.gender_type AS ENUM ('male', 'female', 'other');
CREATE TYPE hr.marital_status_type AS ENUM ('single', 'married', 'divorced', 'widowed');

CREATE TABLE hr.employees (
    id                  BIGSERIAL PRIMARY KEY,
    employee_code       VARCHAR(20) UNIQUE NOT NULL,         -- mã CB do trường cấp
    legacy_id           INTEGER,                              -- giữ NS_NhanSu.MaNhanSu để traceback

    -- Personal
    full_name           TEXT NOT NULL,
    date_of_birth       DATE,
    gender              hr.gender_type,
    place_of_birth_id   BIGINT REFERENCES master.wards(id),
    nationality_id      BIGINT REFERENCES master.countries(id),
    ethnicity_id        BIGINT REFERENCES master.ethnicities(id),
    religion_id         BIGINT REFERENCES master.religions(id),
    marital_status      hr.marital_status_type,

    -- Contact
    citizen_id          VARCHAR(20),                          -- CCCD/CMND
    email               TEXT,
    phone               VARCHAR(20),
    permanent_address   TEXT,
    permanent_ward_id   BIGINT REFERENCES master.wards(id),
    current_address     TEXT,

    -- Work
    department_id       BIGINT REFERENCES master.departments(id),
    division_id         BIGINT REFERENCES master.divisions(id),
    position_id         BIGINT REFERENCES master.positions(id),
    title_id            BIGINT REFERENCES master.titles(id),
    civil_rank_id       BIGINT REFERENCES master.civil_ranks(id),

    -- Education
    highest_degree_id   BIGINT REFERENCES master.degrees(id),
    academic_rank_id    BIGINT REFERENCES master.academic_ranks(id),
    primary_specialization_id BIGINT REFERENCES master.specializations(id),

    -- Employment
    join_date           DATE,
    leave_date          DATE,
    is_active           BOOLEAN GENERATED ALWAYS AS (leave_date IS NULL) STORED,

    -- Photo
    photo_url           TEXT,                                 -- MinIO URL
    photo_uploaded_at   TIMESTAMPTZ,

    -- Audit
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by          BIGINT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by          BIGINT,
    deleted_at          TIMESTAMPTZ,

    CONSTRAINT chk_email_format CHECK (email IS NULL OR email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
);

CREATE INDEX idx_employees_dept ON hr.employees(department_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_employees_active ON hr.employees(is_active) WHERE deleted_at IS NULL;
CREATE INDEX idx_employees_legacy ON hr.employees(legacy_id);                  -- để ETL trace
CREATE INDEX idx_employees_code ON hr.employees(employee_code);
```

> Source gộp: `NS_NhanSu` (1024 dòng) + `NS_NhanSuEx` (1) + một số cột từ `DM_*` (denormalize join). Bỏ ~150 cột rỗng/trùng của hệ cũ.

### 4.3 `hr.contracts`

```sql
CREATE TYPE hr.contract_status_type AS ENUM ('draft', 'active', 'expired', 'terminated');

CREATE TABLE hr.contracts (
    id                  BIGSERIAL PRIMARY KEY,
    employee_id         BIGINT NOT NULL REFERENCES hr.employees(id),
    legacy_id           INTEGER,                              -- NS_HopDong.Id

    contract_number     VARCHAR(50) UNIQUE NOT NULL,
    contract_type_id    BIGINT NOT NULL REFERENCES master.contract_types(id),
    signed_date         DATE NOT NULL,
    start_date          DATE NOT NULL,
    end_date            DATE,                                 -- NULL = không thời hạn
    base_salary_grade_id BIGINT REFERENCES hr.salary_grades(id),
    coefficient         NUMERIC(5,2),
    status              hr.contract_status_type NOT NULL DEFAULT 'active',

    signed_by_employee_id BIGINT REFERENCES hr.employees(id),  -- người ký từ trường
    decision_id         BIGINT REFERENCES hr.decisions(id),    -- QĐ tuyển dụng/ký HĐ

    notes               TEXT,
    attachment_url      TEXT,                                  -- MinIO URL HĐ scan

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by          BIGINT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by          BIGINT,
    deleted_at          TIMESTAMPTZ,

    CONSTRAINT chk_contract_dates CHECK (end_date IS NULL OR end_date > start_date)
);

CREATE INDEX idx_contracts_employee ON hr.contracts(employee_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_contracts_status ON hr.contracts(status) WHERE deleted_at IS NULL;
CREATE INDEX idx_contracts_active_dates ON hr.contracts(start_date, end_date)
    WHERE status = 'active' AND deleted_at IS NULL;
```

### 4.4 `student.students` (gộp 4 bảng nguồn)

```sql
CREATE SCHEMA student;

CREATE TYPE student.enrollment_status_type AS ENUM (
    'enrolled', 'graduated', 'dropped_out', 'suspended', 'transferred', 'deferred'
);

CREATE TABLE student.students (
    id                  BIGSERIAL PRIMARY KEY,
    student_code        VARCHAR(20) UNIQUE NOT NULL,
    legacy_ids          JSONB,         -- {"DT_HoSoSinhVien": 12345, "DT_SinhVien": 6789}

    -- Personal
    full_name           TEXT NOT NULL,
    date_of_birth       DATE,
    gender              hr.gender_type,                      -- reuse ENUM
    place_of_birth_id   BIGINT REFERENCES master.wards(id),
    ethnicity_id        BIGINT REFERENCES master.ethnicities(id),
    religion_id         BIGINT REFERENCES master.religions(id),
    citizen_id          VARCHAR(20),

    -- Contact
    email               TEXT,
    phone               VARCHAR(20),
    permanent_address   TEXT,
    permanent_ward_id   BIGINT REFERENCES master.wards(id),

    -- Family (denormalized — frequent queries)
    father_name         TEXT,
    father_phone        VARCHAR(20),
    mother_name         TEXT,
    mother_phone        VARCHAR(20),

    -- Academic
    program_id          BIGINT REFERENCES academic.programs(id),
    student_class_id    BIGINT REFERENCES academic.student_classes(id),  -- lớp hành chính
    admission_year      INTEGER NOT NULL,
    admission_date      DATE,
    expected_graduation_year INTEGER,

    -- Status
    enrollment_status   student.enrollment_status_type NOT NULL DEFAULT 'enrolled',
    status_changed_at   TIMESTAMPTZ,

    -- Photo + extras
    photo_url           TEXT,
    extra_info          JSONB,                                -- 90+ cột rare-use → JSONB

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by          BIGINT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by          BIGINT,
    deleted_at          TIMESTAMPTZ
);

CREATE INDEX idx_students_program ON student.students(program_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_students_class ON student.students(student_class_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_students_status ON student.students(enrollment_status) WHERE deleted_at IS NULL;
CREATE INDEX idx_students_admission_year ON student.students(admission_year);
CREATE INDEX idx_students_legacy ON student.students USING GIN (legacy_ids);
CREATE INDEX idx_students_extra ON student.students USING GIN (extra_info);
```

> Đây là chỗ critical: 4 bảng nguồn (`DT_HoSoSinhVien` 14 cột, `DT_SinhVien` 145 cột, `DT_ThongTinSinhVien` 177 cột, `DT_SinhVienEx` 70 cột) → 1 bảng đích ~30 cột thiết yếu + JSONB cho phần rare. Cần ETL logic dedupe + merge cẩn thận.

### 4.5 `student.enrollments` (PARTITIONED)

```sql
CREATE TYPE student.enrollment_state_type AS ENUM (
    'registered', 'cancelled', 'completed', 'failed', 'in_progress'
);

CREATE TABLE student.enrollments (
    id                  BIGSERIAL,
    student_id          BIGINT NOT NULL REFERENCES student.students(id),
    course_class_id     BIGINT NOT NULL REFERENCES academic.course_classes(id),
    academic_year_id    BIGINT NOT NULL REFERENCES academic.academic_years(id),
    semester_id         BIGINT NOT NULL REFERENCES academic.semesters(id),

    enrolled_at         TIMESTAMPTZ NOT NULL,
    enrolled_by_id      BIGINT REFERENCES identity.users(id),
    state               student.enrollment_state_type NOT NULL DEFAULT 'registered',

    cancelled_at        TIMESTAMPTZ,
    cancelled_by_id     BIGINT REFERENCES identity.users(id),
    cancel_reason       TEXT,

    legacy_id           BIGINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (id, academic_year_id),
    UNIQUE (student_id, course_class_id, academic_year_id)
) PARTITION BY LIST (academic_year_id);

-- Tạo partition cho từng năm
CREATE TABLE student.enrollments_2024 PARTITION OF student.enrollments FOR VALUES IN (2024);
CREATE TABLE student.enrollments_2025 PARTITION OF student.enrollments FOR VALUES IN (2025);
CREATE TABLE student.enrollments_2026 PARTITION OF student.enrollments FOR VALUES IN (2026);
-- pattern: tự tạo trước cho 5 năm tới qua trigger/maintenance script
```

> Source: `DT_DangKyHocPhan` 2.3M dòng → partition theo năm để query 1 năm chỉ scan 1 partition.

### 4.6 `student.grades` (slim từ 153 cột → 30 cột)

```sql
CREATE TABLE student.grades (
    id                      BIGSERIAL,
    student_id              BIGINT NOT NULL REFERENCES student.students(id),
    course_class_id         BIGINT NOT NULL REFERENCES academic.course_classes(id),
    enrollment_id           BIGINT REFERENCES student.enrollments(id),
    academic_year_id        BIGINT NOT NULL REFERENCES academic.academic_years(id),
    semester_id             BIGINT NOT NULL REFERENCES academic.semesters(id),

    -- Scores
    process_score           NUMERIC(4,2),                      -- điểm quá trình
    midterm_score           NUMERIC(4,2),                      -- giữa kỳ
    final_score             NUMERIC(4,2),                      -- cuối kỳ
    overall_score           NUMERIC(4,2),                      -- tổng kết
    overall_letter_grade    VARCHAR(2),                        -- A, B+, B, ...
    overall_grade_point     NUMERIC(3,2),                      -- 4.0, 3.5, ...

    -- Status
    is_passed               BOOLEAN GENERATED ALWAYS AS (overall_score >= 4.0) STORED,
    is_excluded             BOOLEAN DEFAULT false,             -- không tính vào GPA
    exclusion_reason        TEXT,

    -- Provenance
    finalized_at            TIMESTAMPTZ,
    finalized_by_id         BIGINT REFERENCES identity.users(id),

    legacy_id               BIGINT,
    extra_scores            JSONB,                             -- 120+ cột rare → JSONB
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (id, academic_year_id),
    UNIQUE (student_id, course_class_id, academic_year_id)
) PARTITION BY LIST (academic_year_id);

CREATE INDEX idx_grades_student ON student.grades(student_id);
```

> Source: `DT_KetQuaHocTapMonHoc` 153 cột → 30 cột thiết yếu + `extra_scores JSONB` cho phần rare.

---

## 5. ETL pipeline — Cách bóc tách dữ liệu

### 5.1 Stack được đề xuất

| Component | Chọn | Lý do |
|---|---|---|
| **Source connector** | SQL Server JDBC driver | Standard |
| **Orchestrator** | **Python + SQLAlchemy** | Đơn giản, debug dễ; không cần Airflow cho 1-shot migration |
| **Validation** | **dbt + Great Expectations** (optional) | Sau ETL chạy assertion |
| **Blob extraction** | Python script + boto3 (MinIO S3 API) | |
| **Format trung gian** | Parquet files (cho batch lớn) | Nhanh hơn CSV 5-10x |
| **Postgres loader** | `\copy` + `INSERT ... ON CONFLICT` | Native, fastest |

### 5.2 Pipeline 5 phases

```
┌─────────────────────────────────────────────────────────────────┐
│ PHASE 1: SCHEMA SETUP                                           │
│  • Create Postgres DB + 6 schemas                               │
│  • Run DDL (50 tables, indexes, constraints DISABLED ban đầu)   │
│  • Create MinIO buckets                                         │
└─────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────┐
│ PHASE 2: MASTER DATA (~15 tables, dependencies-first)           │
│  • Order: countries → ethnicities → religions                   │
│           → provinces → districts → wards                       │
│           → departments → positions → titles → degrees          │
│  • Method: read SQL Server → transform → COPY into Postgres     │
│  • Time: ~5 phút                                                │
└─────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────┐
│ PHASE 3: HR + ACADEMIC CATALOG                                  │
│  • employees (1024) ← gộp NS_NhanSu + NS_NhanSuEx               │
│  • contracts (316) ← NS_HopDong                                 │
│  • subjects (75K) ← TKB_MonHoc                                  │
│  • course_classes (82K) ← TKB_LopHocPhan                        │
│  • student_classes (55K) ← TKB_LopHoc                           │
│  • Time: ~10 phút                                               │
└─────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────┐
│ PHASE 4: STUDENTS + ENROLLMENTS + GRADES (heavy)                │
│  • students (~38K) ← MERGE 4 bảng SV (logic phức tạp)           │
│  • enrollments (2.3M) ← DT_DangKyHocPhan, partition by year     │
│  • grades (2M) ← DT_KetQuaHocTapMonHoc, slim 153→30 cột         │
│  • graduations (18K) ← DT_DSSinhVienTotNghiep                   │
│  • Time: ~30-60 phút                                            │
└─────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────┐
│ PHASE 5: BLOBS + AUDIT                                          │
│  • Export 20K ảnh SV từ EDU_DT_SinhVien.HinhAnh → MinIO         │
│  • Export 652 ảnh NS từ HRM_HinhAnh → MinIO                     │
│  • Export 1.3K PDF biên bản sửa điểm → MinIO + grade_change_recs│
│  • Update photo_url trong students/employees                    │
│  • Import audit_logs (3 năm gần nhất) XML → JSONB               │
│  • Time: ~30-90 phút (tùy bandwidth)                            │
└─────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────┐
│ POST: VALIDATE + INDEXES + RLS                                  │
│  • Re-enable FK constraints, kiểm tra orphan rows               │
│  • Build indexes (sau khi load xong → nhanh hơn 5-10×)          │
│  • Apply RLS policies cho salary_history, grades                │
│  • Run dbt assertions: row counts match, no orphan FKs, ...     │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 ETL logic phức tạp — case `students` (gộp 4 bảng)

```python
# pseudocode
def merge_students():
    # 1. Read tất cả student IDs từ DT_HoSoSinhVien (canonical 97K)
    canonical_ids = read_sql("SELECT MaHoSoSinhVien, MaSinhVien FROM DT_HoSoSinhVien")

    # 2. Cho mỗi ID, build composite record
    for record in canonical_ids:
        base = read_one("DT_HoSoSinhVien", record.MaHoSoSinhVien)
        main = read_one("DT_SinhVien", record.MaSinhVien)  # có thể NULL
        ext  = read_one("DT_ThongTinSinhVien", record.MaSinhVien)  # có thể NULL
        ex2  = read_one("DT_SinhVienEx", record.MaSinhVien)  # có thể NULL

        # 3. Coalesce trường core (main thắng base)
        student = {
            "student_code": base.MaSinhVien,
            "full_name": main.HoTen if main else base.HoTen,
            "date_of_birth": main.NgaySinh if main else base.NgaySinh,
            # ... map ~30 cột thiết yếu
            "extra_info": {
                # Bỏ vào JSONB những cột rare
                **flatten(ext) if ext else {},
                **flatten(ex2) if ex2 else {},
            },
            "legacy_ids": {
                "DT_HoSoSinhVien": base.Id,
                "DT_SinhVien": main.Id if main else None,
                "DT_ThongTinSinhVien": ext.Id if ext else None,
                "DT_SinhVienEx": ex2.Id if ex2 else None,
            }
        }
        yield student

    # 4. Bulk INSERT vào Postgres
```

### 5.4 ETL logic — XML audit → JSONB

```python
def convert_xml_audit(xml_history: str):
    """
    Input:  <row Id="46020" IDLopHocPhan="141981" .../>
            <row Id="46020" IDLopHocPhan="141981" ... NguoiCapNhat="858"/>
    Output: {"before": {Id:46020, ...}, "after": {Id:46020, ..., NguoiCapNhat:858}}
    """
    rows = parse_xml(xml_history)
    return {
        "before": rows[0].attrib if len(rows) > 0 else None,
        "after":  rows[1].attrib if len(rows) > 1 else None,
    }

# Bảng đích: audit.audit_logs(table_name, primary_key, history JSONB, ...)
```

---

## 6. Ubuntu deployment recipe

### 6.1 Hardware tối thiểu (cho ~50K SV active + 1K NS)

| Resource | Min | Recommended |
|---|---|---|
| CPU | 4 cores | 8 cores |
| RAM | 16 GB | 32 GB |
| Disk Postgres | 100 GB SSD | 500 GB SSD |
| Disk MinIO | 50 GB | 200 GB (cho 50K ảnh + PDF) |
| OS | Ubuntu 24.04 LTS | Ubuntu 24.04 LTS |

### 6.2 Docker Compose stack (production-ready)

```yaml
# /opt/dau-uni/docker-compose.yml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: dau_university
      POSTGRES_USER: dau_admin
      POSTGRES_PASSWORD_FILE: /run/secrets/pg_password
      POSTGRES_INITDB_ARGS: "--locale=vi_VN.UTF-8 --encoding=UTF-8"
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./backups:/backups
    secrets: [pg_password]
    restart: unless-stopped
    ports: ["5432:5432"]

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minio_admin
      MINIO_ROOT_PASSWORD_FILE: /run/secrets/minio_password
    volumes:
      - miniodata:/data
    secrets: [minio_password]
    restart: unless-stopped
    ports: ["9000:9000", "9001:9001"]   # 9000=S3 API, 9001=Web UI

  pgadmin:
    image: dpage/pgadmin4:latest
    environment:
      PGADMIN_DEFAULT_EMAIL: admin@dau.edu.vn
      PGADMIN_DEFAULT_PASSWORD_FILE: /run/secrets/pgadmin_password
    secrets: [pgadmin_password]
    restart: unless-stopped
    ports: ["8080:80"]

  backup:
    image: postgres:16-alpine
    volumes:
      - ./backups:/backups
      - ./scripts:/scripts:ro
    entrypoint: /scripts/backup-cron.sh
    restart: unless-stopped

volumes:
  pgdata:
  miniodata:

secrets:
  pg_password: { file: ./secrets/pg.txt }
  minio_password: { file: ./secrets/minio.txt }
  pgadmin_password: { file: ./secrets/pgadmin.txt }
```

### 6.3 Postgres tuning cho 16GB RAM

```sql
-- /etc/postgresql/16/main/postgresql.conf
shared_buffers = 4GB              -- 25% RAM
effective_cache_size = 12GB       -- 75% RAM
work_mem = 32MB                   -- per query operation
maintenance_work_mem = 1GB        -- cho VACUUM, CREATE INDEX
max_connections = 100
random_page_cost = 1.1            -- SSD
effective_io_concurrency = 200
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100
```

### 6.4 Backup strategy

```bash
#!/bin/bash
# scripts/backup-cron.sh — daily 2AM
DATE=$(date +%Y%m%d)
pg_dump -h postgres -U dau_admin -Fc dau_university > /backups/dau_${DATE}.dump
mc mirror --overwrite /minio_data minio-remote/dau-backup/  # MinIO → remote S3

# Retention: keep 7 daily, 4 weekly, 12 monthly
find /backups -name "dau_*.dump" -mtime +7 -delete
```

### 6.5 Monitoring — pg_stat_statements + Grafana

- Enable `pg_stat_statements` extension trong `postgresql.conf`
- Postgres exporter cho Prometheus: `prometheuscommunity/postgres_exporter`
- Grafana dashboard ID 9628 (PostgreSQL Database)

---

## 7. Migration runbook (chronological)

| Step | Hành động | Thời gian | Risk |
|---|---|---:|---|
| 0 | Setup Postgres + MinIO trên Ubuntu (test env trước) | 2h | Low |
| 1 | Apply DDL (50 bảng, không index/FK) | 5 phút | Low |
| 2 | Load master data (provinces, districts, ...) | 5 phút | Low |
| 3 | Load HR (employees, contracts, ...) | 10 phút | Med (4 bảng SV merge) |
| 4 | Load Academic (subjects, course_classes, classes) | 5 phút | Low |
| 5 | Load Students (merge 4 bảng → 1) | 30 phút | **High** |
| 6 | Load Enrollments (2.3M, partitioned) | 20 phút | Med |
| 7 | Load Grades (2M, slim) | 20 phút | Med (153→30 cột) |
| 8 | Export blobs + upload MinIO + update URLs | 60 phút | Med |
| 9 | Load audit logs (3 năm, XML→JSONB) | 30 phút | Low |
| 10 | Build indexes (sau khi load xong) | 15 phút | Low |
| 11 | Re-enable FK constraints + check orphan | 10 phút | **High** |
| 12 | Apply RLS policies + GRANT permissions | 5 phút | Low |
| 13 | Run validation suite (dbt assertions) | 10 phút | Low |
| **Total** | | **~3h30m** | |

### Validation checklist

- [ ] Row counts match: `SELECT COUNT(*)` from source vs target cho mọi bảng
- [ ] No orphan FK: `LEFT JOIN ... WHERE child.parent_id NOT NULL AND parent.id IS NULL` = 0
- [ ] Random spot-check: lấy 100 sinh viên, so sánh đầy đủ thông tin với hệ cũ
- [ ] Blob URLs accessible: HTTP HEAD MinIO mỗi `photo_url` không trả 404
- [ ] Audit timeline preserved: random check 10 events, verify before/after match XML gốc
- [ ] Performance baseline: SELECT 1 SV với grades (200 dòng) < 100ms

---

## 8. Khuyến nghị ưu tiên

### Bắt buộc tuần này (nếu thầy đẩy mạnh)

1. **Cài Ubuntu test environment** (VirtualBox/VM hoặc cloud Hetzner $5/tháng)
2. **Apply DDL Phase 1+2** trên Postgres (master data có thể migrate được ngay)
3. **Validate được pattern**: chạy ETL master data → assertion pass → tự tin scale lên

### Tháng 1 — POC (proof of concept)

- ETL đầy đủ scope core ~50 bảng vào Postgres test
- Tạo 5-10 SQL view "tương đương báo cáo cũ" để chứng minh data đầy đủ
- So sánh số liệu với hệ cũ

### Tháng 2-3 — Production

- Chuyển Ubuntu sang server thật (or cloud)
- Build app layer (REST API + Vue/React UI) on top
- Cutover: import data lần cuối → switch user → khóa hệ cũ

### Tháng 4+ — Mở rộng

- Đợt 2: Thêm modules Tài chính, Tuyển sinh, Khảo thí
- Đợt 3: Tích hợp với hệ KĐCLGD đang xây
- Đợt 4: Migrate stored procedures → app code

---

## 9. Rủi ro chính & mitigation

| Rủi ro | Probability | Impact | Mitigation |
|---|---|---|---|
| **4 bảng SV merge sai → mất data** | High | Critical | Dùng `legacy_ids JSONB` để traceback; chạy assertion nghiêm ngặt; spot-check thủ công 100 SV |
| **Grade table 153 cột → JSONB → mất cột quan trọng** | Med | High | Phải khảo sát 153 cột để biết cột nào dùng thật. Run query `COUNT(col IS NOT NULL)` trên DB cũ để biết cột nào active. |
| **Orphan FK do hệ cũ không enforce** | High | Med | ETL phải resolve hoặc nullify. Ghi log orphan để báo cáo |
| **Blob upload chậm/fail** | Med | Med | Idempotent: dùng checksum, có thể resume; upload song song 10 threads |
| **Audit XML format khác nhau** | Low | Low | Test với 100 records trước khi full run |
| **Postgres performance kém với 2M grades** | Low | Med | Đã partition theo year + đúng index |
| **User của hệ cũ ID conflict với hệ mới** | Med | Low | Giữ `legacy_id` ở mọi bảng, mapping table `legacy_user_id_map` |

---

## 10. Bước tiếp theo cụ thể

Em đề xuất next action — thầy chọn 1:

1. **A — Em viết ETL prototype**: Python script load master data từ SQL Server → Postgres để test pattern
2. **B — Em viết DDL đầy đủ ~50 bảng**: thầy có file `target_schema.sql` chạy ngay được
3. **C — Em phân tích sâu 1 bảng critical** (ví dụ DT_KetQuaHocTapMonHoc 153 cột): xác định cột nào dùng thật, cột nào bỏ — quyết định trước khi viết DDL `grades`
4. **D — Em setup test Postgres + MinIO bằng Docker Compose ngay máy thầy**: validate stack trước khi đụng cloud

Em recommend **C trước, sau đó B**, vì:
- C giảm risk lớn nhất (slim 153→30 cột)
- B sau đó có data thật để validate
- A và D là execution, làm sau khi design lock
