# DAU University — Database Specification (Migrated)

**Version**: 1.0 (Migration Complete)
**Migration Date**: 2026-05-12
**Source**: ASCVN HRM_DAU + EDU_DAU + EDU_DAU_DATA (SQL Server, ~2018-2026)
**Target**: PostgreSQL 16 on Ubuntu (Docker)
**Status**: Phase 1 migration complete (core scope). Phase 2 (cleanup + extras) pending.

---

## 1. Executive Summary

| Metric | Value |
|---|---:|
| Total DB size | **2,045 MB** |
| Schemas | 7 |
| Tables (excl. partitions) | 44 |
| Partition tables | 41 (enrollments + grades, by academic_year_id) |
| **Total rows** | **~6.6 million** |
| FK integrity check | **0 orphans across 7 validation checks** ✓ |
| Largest table | `student.enrollments` (2.17M rows) |
| Audit log span | 7.4 years (2018-09-28 → 2026-03-01), 721K events |

### Source → Target Reduction

| Source DB | Tables | Rows | → Target |
|---|---:|---:|---|
| HRM_DAU (SQL Server, 178 MB) | 586 | ~50K | → `master.*` + `hr.employees` |
| EDU_DAU (SQL Server, 40 GB) | 1,465 | ~22M | → `academic.*` + `student.*` (most rows) |
| EDU_DAU_DATA (SQL Server, 20 GB) | 65 | ~2.5M | → `files.*` + `audit.audit_logs` |
| **Total source** | **2,116** | **~25M** | **→ 44 target tables, 6.6M rows** |

→ Reduction: **98% fewer tables**, **74% fewer rows** (dropped 67%+ empty/legacy tables, audit kept 3 most recent years out of 7.4).

---

## 2. Architecture — 7 Bounded Contexts

```
┌─────────────────────────────────────────────────────────────────┐
│                   dau_university (PostgreSQL 16)                │
│                                                                 │
│  ┌─────────────┐  ┌────────────┐                                │
│  │  identity   │  │   master   │   ← Reference data             │
│  │   (empty)   │  │ 16 tables  │                                │
│  └─────────────┘  └─────┬──────┘                                │
│                         │ FK                                    │
│                  ┌──────┴──────┬──────────────┐                 │
│                  │             │              │                 │
│              ┌───▼───┐    ┌────▼─────┐   ┌────▼─────┐           │
│              │  hr   │    │ academic │   │ student  │           │
│              │1 table│    │ 7 tables │   │ 4 tables │           │
│              │loaded │    │ +partn   │   │ +partn   │           │
│              └───┬───┘    └────┬─────┘   └────┬─────┘           │
│                  │             │              │                 │
│                  └─────────────┼──────────────┘                 │
│                                ▼                                │
│                          ┌──────────┐                           │
│                          │  files   │   ← Attachments metadata  │
│                          │ 2 tables │     (BLOBs in MinIO)      │
│                          └──────────┘                           │
│                                                                 │
│                          ┌──────────┐                           │
│                          │  audit   │   ← XML→JSONB audit log   │
│                          │ 1 table  │     (cross-cutting)       │
│                          └──────────┘                           │
└─────────────────────────────────────────────────────────────────┘
```

| Schema | Tables | Purpose | Loaded? |
|---|---:|---|---|
| `identity` | 4 | Users, roles, sessions (modern auth) | ❌ Empty — built when app layer added |
| `master` | 16 | Lookup data: provinces, departments, positions, etc. | ✅ 3,493 rows |
| `hr` | 11 | Employee records, contracts, salary, training | ⚠️ Only `employees` (1,024). Others pending |
| `academic` | 7 | Programs, subjects, course classes | ✅ 208K rows |
| `student` | 4 + partitions | Students, enrollments (partitioned), grades (partitioned), graduations | ✅ 4.2M rows |
| `files` | 2 | Attachment metadata + grade change records | ✅ 18K rows (BLOBs in MinIO) |
| `audit` | 1 | XML audit log converted to JSONB | ✅ 721K events |

---

## 3. Schema-by-Schema Detail

### 3.1 `master` — Reference Data (16 tables, 3,493 rows)

Lookup tables used as FK targets. Source: `HRM_DAU.DM_*`.

| Table | Rows | Source | Key Columns |
|---|---:|---|---|
| `master.countries` | 33 | `DM_QuocGia` | `code` (vendor non-ISO, e.g. 'Singa'), `name`, `legacy_id` |
| `master.ethnicities` | 57 | `DM_DanToc` | `code`, `name` |
| `master.religions` | 14 | `DM_TonGiao` | `name` |
| `master.provinces` | 65 | `DM_TinhThanh` | `code`, `name`, `region` (NULL — vendor lacks) |
| `master.districts` | 760 | `DM_Huyen` | `code`, `name`, `province_id` FK |
| `master.wards` | 1,891 | `DM_BH_Xa` (11,706) — 84% skipped due to missing district mapping | `code`, `name`, `district_id` FK |
| `master.departments` | 31 | `DM_PhongBan` | `code`, `name`, `name_short`, `department_type` (khoa/phòng/trung_tâm/viện/ban) |
| `master.divisions` | 20 | `DM_ToBoMon` | `code`, `name`, `department_id` FK |
| `master.positions` | 33 | `DM_ChucVu` | `code`, `name` (Trưởng phòng, Phó GĐ, ...) |
| `master.titles` | 7 | `DM_ChucDanh` | Giảng viên, GVC, GVCC, NCV... |
| `master.degrees` | 7 | `DM_HocVi` | CN, KS, ThS, TS, TSKH... |
| `master.academic_ranks` | 4 | `DM_HocHam` | (NULL), PGS, GS |
| `master.civil_ranks` | 7 | `DM_NgachCongChuc` | Civil service ranks |
| `master.specializations` | 474 | `DM_ChuyenNganh` | Discipline list (Toán, Tin học, ...) |
| `master.contract_types` | 9 | `DM_LoaiHopDong` | HĐ thử việc, HĐ chính thức, ... |
| `master.decision_types` | 81 | `DM_LoaiQuyetDinh` | Bổ nhiệm, Khen thưởng, Tuyển dụng, ... |

**Notes**:
- All `code` columns: UNIQUE constraint **dropped** (source has duplicates). Re-add after data cleanup phase.
- `districts.code` + `wards.code` weren't globally unique (same code reused across provinces) — composite `(code, parent_id)` UNIQUE would be correct.
- All have `legacy_id INTEGER` for traceability back to source SQL Server.

### 3.2 `hr` — Human Resources (11 tables, 1,024 rows loaded)

| Table | Rows | Status | Source |
|---|---:|---|---|
| `hr.employees` | **1,024** | ✅ Loaded | `HRM_DAU.NS_NhanSu` |
| `hr.contracts` | 0 | ⏳ Pending Phase 2 | `NS_HopDong` (316) |
| `hr.contract_addendums` | 0 | ⏳ | `NS_PhuLucHopDong` (17) |
| `hr.decisions` | 0 | ⏳ | `NS_QuyetDinh` (331) |
| `hr.employee_family_relations` | 0 | ⏳ | `NS_QuanHeGiaDinh` (1228) |
| `hr.employee_training_history` | 0 | ⏳ | `NS_QuaTrinhDaoTao` (872) |
| `hr.employee_career_history` | 0 | ⏳ | `NS_QuaTrinhCongTacChuyenMon` (11) |
| `hr.employee_research_history` | 0 | ⏳ | `NS_QuaTrinhNghienCuu` (69) |
| `hr.salary_grades` | 0 | ⏳ | `NS_HeSoLuong` (364) |
| `hr.allowances` | 0 | ⏳ | `NS_PhuCap` (339) |
| `hr.insurance_history` | 0 | ⏳ | `NS_BaoHiem`+`NS_QuaTrinhDongBaoHiem` (39,582) |

#### `hr.employees` — Schema (~35 cols thiết yếu)

```sql
employees (
  id BIGSERIAL PK,
  legacy_id INTEGER,                    -- → NS_NhanSu.Id
  employee_code VARCHAR(20),             -- mã NS do trường cấp

  full_name TEXT,                        -- HoDem + ' ' + Ten
  gender ENUM('male','female','other'),
  date_of_birth DATE,
  citizen_id VARCHAR(20),                -- CCCD/CMND
  citizen_id_issued_date DATE,
  citizen_id_issued_place TEXT,

  nationality_id BIGINT → master.countries,
  ethnicity_id   BIGINT → master.ethnicities,
  religion_id    BIGINT → master.religions,
  marital_status ENUM('single','married','divorced','widowed'),

  email TEXT, email_personal TEXT,
  phone VARCHAR(50), phone_alt VARCHAR(50),    -- VARCHAR(50) cho phone concat dirty
  permanent_address TEXT, permanent_ward_id BIGINT,
  current_address TEXT, current_ward_id BIGINT,

  department_id BIGINT → master.departments,   -- HienTaiPhongBan
  division_id   BIGINT → master.divisions,
  position_id   BIGINT → master.positions,     -- HienTaiChucVu
  title_id      BIGINT → master.titles,        -- IDChucDanh
  civil_rank_id BIGINT → master.civil_ranks,

  highest_degree_id    BIGINT → master.degrees,
  academic_rank_id     BIGINT → master.academic_ranks,
  primary_specialization_id BIGINT → master.specializations,

  join_date DATE, leave_date DATE,
  is_active BOOLEAN GENERATED AS (leave_date IS NULL) STORED,

  photo_url TEXT,                        -- MinIO URL (set by p07_files)

  extra_info JSONB,                      -- 200+ rare cols dồn vào đây

  created_at TIMESTAMPTZ DEFAULT now(),
  created_by BIGINT, updated_at TIMESTAMPTZ, updated_by BIGINT,
  deleted_at TIMESTAMPTZ                 -- soft delete
)
```

**Lineage**: 238-column `NS_NhanSu` source → ~35 essential cols + ~200 in `extra_info` JSONB.

### 3.3 `academic` — Academic Catalog (7 tables, 208K rows)

| Table | Rows | Source |
|---|---:|---|
| `academic.academic_years` | 21 | `EDU_DAU.DM_NamHoc` (2008-2009 → 2028-2029) |
| `academic.semesters` | 59 | `DM_Dot` (multiple Dot per year/semester) |
| `academic.programs` | 25 | `DM_Nganh` |
| `academic.subjects` | **73,053** | `TKB_MonHoc` (75,614) — 2.5K skipped invalid credits |
| `academic.subject_equivalences` | 0 | `DT_MonHocTuongDuong` — deferred (complex IDChiTietKhungHocKy) |
| `academic.student_classes` | **55,468** | `TKB_LopHoc` (lớp hành chính) |
| `academic.course_classes` | **79,791** | `TKB_LopHocPhan` (lớp học phần) — 2.7K skipped (orphan FK) |

#### Key Schemas

**`academic.academic_years`**: 21 years from 2008-09 to 2028-29
```sql
(id, code='2025-2026', start_year, end_year, start_date, end_date, is_current)
```

**`academic.semesters`**: 59 registration periods
```sql
(id, academic_year_id FK, semester_type ENUM('fall','spring','summer','extra'),
 code='HK1-2025', name, start_date, end_date)
```
Note: 1 academic year có thể có nhiều "DM_Dot" → multiple semesters cùng (year, type) — UNIQUE dropped.

**`academic.subjects`**: 73K subjects across 20+ years
```sql
(id, legacy_id, code, name, name_eng,
 credits_total, credits_theory, credits_practice,
 department_id FK, is_active)
```

**`academic.course_classes`**: 79K — these are specific class instances per semester
```sql
(id, legacy_id, code (MaLopHocPhan), 
 subject_id FK, semester_id FK,
 primary_lecturer_id BIGINT → hr.employees,   -- NULL (not migrated yet from TKB_LichHoc)
 capacity, enrolled_count, classroom)
```

### 3.4 `student` — Student Records (4 tables + 40 partitions, 4.2M rows)

| Table | Rows | Notes |
|---|---:|---|
| `student.students` | **121,895** | GỘP 4 nguồn (DT_HoSoSinhVien, DT_SinhVien, DT_ThongTinSinhVien, DT_SinhVienEx) |
| `student.graduations` | **17,969** | `DT_DSSinhVienTotNghiep` |
| `student.enrollments` | **2,167,953** | **Partitioned by `academic_year_id`** (y1-y20) |
| `student.grades` | **1,942,259** | **Partitioned by `academic_year_id`**, slim 153→33 cols |

#### Partition distribution (rows per year)

| Year ID | Enrollments | Grades |
|---:|---:|---:|
| y1 | 8,048 | 8,048 |
| y2 | 24,555 | 24,555 |
| y3 | 55,268 | 55,268 |
| y5 | 122,438 | 122,438 |
| y10 | 89,890 | 89,890 |
| y15 (peak) | 137,069 | 106,136 |
| y18 (peak) | 176,930 | 139,636 |
| y20 (latest) | 150,247 | 67,863 |

→ Partition pruning works: query 1 year scans 1 partition (~5-15% of total).

#### `student.students` — Schema

```sql
students (
  id BIGSERIAL PK,
  student_code VARCHAR(20),                -- mã SV (vendor dup → UNIQUE dropped)
  legacy_ids JSONB,                        -- {"DT_HoSoSinhVien": 12345, "DT_SinhVien": 6789}

  full_name TEXT, family_name TEXT, given_name TEXT,
  gender ENUM, date_of_birth DATE,
  place_of_birth_id BIGINT → master.wards,
  place_of_birth_text TEXT,

  citizen_id VARCHAR(20), citizen_id_issued_date DATE, citizen_id_issued_place TEXT,
  nationality_id → master.countries,
  ethnicity_id → master.ethnicities, religion_id → master.religions,

  permanent_address TEXT, permanent_ward_id → master.wards,
  contact_address TEXT, contact_ward_id → master.wards,

  phone VARCHAR(50), phone_alt VARCHAR(50), phone_parent VARCHAR(50),
  email TEXT, email_parent TEXT,

  guardian_name TEXT, guardian_birth_year, guardian_occupation,

  program_id BIGINT → academic.programs,
  student_class_id BIGINT → academic.student_classes,
  facility_id, education_type_id, training_form_id, cohort_id,

  admission_year INTEGER, admission_date DATE,
  expected_graduation_year, high_school_graduation_year, high_school_name,
  bank_account_number, bank_account_name, bank_name, bank_branch,
  insurance_number,

  legacy_pwd_hash TEXT, legacy_pwd_key,    -- legacy auth (force reset on first login)

  enrollment_status ENUM('enrolled','graduated','dropped_out','suspended',
                          'transferred','deferred','expelled'),
  status_changed_at,

  conduct_ranking_overall, study_ranking_overall, graduation_ranking,

  photo_url TEXT,                          -- MinIO (set by p07_files)
  extra_info JSONB,                        -- rare cols dồn đây

  created_at, created_by, updated_at, updated_by, deleted_at
)
```

#### `student.enrollments` — Partitioned

```sql
enrollments (
  id BIGSERIAL,
  legacy_id BIGINT,
  student_id BIGINT NOT NULL,
  course_class_id BIGINT NOT NULL,
  academic_year_id BIGINT NOT NULL,         -- partition key
  semester_id BIGINT NOT NULL,
  enrolled_at TIMESTAMPTZ,
  enrolled_by_id BIGINT, 
  state ENUM('registered','cancelled','completed','failed','in_progress','withdrew'),
  cancelled_at, cancelled_by_id, cancel_reason,
  notes,
  PRIMARY KEY (id, academic_year_id)
) PARTITION BY LIST (academic_year_id);

-- Auto-created: enrollments_y1, enrollments_y2, ..., enrollments_y20
```

#### `student.grades` — Slim 153→33 cols

```sql
grades (
  id BIGSERIAL, legacy_id BIGINT,
  student_id, course_class_id, enrollment_id,
  academic_year_id (partition key), semester_id,

  -- Component scores (TIER 2-3 from analysis)
  attendance_score, weighted_score_1, regular_avg_score,
  practice_avg, essay_score,

  -- Final exam (3 attempts)
  final_exam_score, final_exam_score_retake1, final_exam_score_retake2,

  -- Overall (3 attempts)
  overall_score, overall_score_retake1, overall_score_retake2,

  -- Letter + GPA
  letter_grade_native CHAR(2),         -- A, B, C...
  letter_grade_alt CHAR(2),
  letter_grade_eng VARCHAR(3),         -- A+, A, B+...
  letter_grade_vn VARCHAR(20),         -- Giỏi, Khá, ...
  grade_point NUMERIC(3,2),            -- 4.0 scale
  grade_point_alt,

  -- Status flags
  is_passed, is_passed_retake1, is_eligible_for_final,
  is_absent_from_exam, is_absent_from_midterm,
  is_practice_locked, is_essay_locked, is_final_locked,
  is_excluded,

  -- Notes
  notes, eligibility_notes,

  -- Extras (TIER 4 rare cols from analysis)
  extra_scores JSONB,                  -- {DiemHeSo12, DiemTH11, ...}

  created_at, created_by, updated_at, updated_by
) PARTITION BY LIST (academic_year_id);
```

### 3.5 `files` — Attachments + Grade Change Records (2 tables, 18K rows)

| Table | Rows | Notes |
|---|---:|---|
| `files.attachments` | **17,071** | Metadata (BLOBs in MinIO) |
| `files.grade_change_records` | **1,342** | Compliance: GV sửa điểm phải kèm biên bản PDF |

#### `files.attachments` — Polymorphic Attachment Metadata

```sql
attachments (
  id BIGSERIAL PK,
  bucket VARCHAR(50),                  -- 'students', 'employees', ...
  object_key TEXT,                     -- relative path in bucket
  url TEXT,                            -- full MinIO URL
  file_name TEXT, content_type, size_bytes BIGINT,
  checksum_sha256 CHAR(64),

  owner_table VARCHAR(50),             -- 'students' | 'employees' | ...
  owner_id BIGINT,                     -- polymorphic (no FK constraint)
  purpose VARCHAR(50),                 -- 'photo' | 'contract_pdf' | ...

  uploaded_by, uploaded_at,
  deleted_at,
  UNIQUE (bucket, object_key)          -- prevents duplicate uploads
)
```

**Source**: `EDU_DAU_DATA.EDU_DT_SinhVien.HinhAnh` (20K ảnh SV, 2.8GB) + `HRM_HinhAnh` (652 ảnh NS). Exported to MinIO, metadata here.

**MinIO buckets**:
- `students/photos/{student_id}.jpg` — student photos
- `employees/photos/{employee_id}.jpg` — employee photos
- `grade-changes/records/{id}_{name}.pdf` — grade change evidence

#### `files.grade_change_records` — Compliance Trail

```sql
grade_change_records (
  id BIGSERIAL PK, legacy_id INTEGER,
  grade_id BIGINT,                     -- FK to student.grades
  student_id → student.students,
  course_class_id → academic.course_classes,

  change_type VARCHAR(50),             -- 'grade_correction', 'final_exam', ...
  old_exam_score, old_overall_score,
  new_exam_score, new_overall_score,

  document_url TEXT,                   -- MinIO URL của biên bản PDF
  document_name, notes,

  requested_by, approved_by,
  requested_at, approved_at
)
```

Source: `EDU_DAU_DATA.EDU_NK_FileSuaDiem` (1,346 PDF). **Important for ABET / AUN-QA accreditation** — every grade change has signed PDF document.

### 3.6 `audit` — Cross-cutting Audit Log (1 table, 721K rows)

```sql
audit.audit_logs (
  id BIGSERIAL PK,
  table_name VARCHAR(100),             -- 'DT_KetQuaHocTapMonHoc', etc.
  record_id BIGINT,                    -- which row was changed
  operation VARCHAR(20),               -- 'INSERT' | 'UPDATE' | 'DELETE'
  old_value JSONB,                     -- before state (full row as JSONB)
  new_value JSONB,                     -- after state
  changed_by BIGINT,
  changed_at TIMESTAMPTZ,
  legacy_event_id BIGINT
)
```

**Source**: `EDU_DAU_DATA.EDU_NK_TongHop` — XML `<row before/><row after/>` converted to JSONB.

**Migration policy** (in .env: `ETL_AUDIT_KEEP_YEARS=3`): Only last 3 years migrated. Older events (2018-2023) archived/dropped.

**Total events**: 721,168 covering 2023-03 to 2026-03.

**Top audited tables** (from prior analysis):
1. `DT_KetQuaHocTapMonHoc` (grades) — 210K events
2. `TS_ThiSinhOnlineDiemMonThi` — 125K
3. `DT_DiemDanhSinhVien` (attendance) — 114K

**Queries** (GIN index on JSONB):
```sql
-- Tìm tất cả thay đổi của 1 SV
SELECT * FROM audit.audit_logs 
WHERE old_value @> '{"IDSinhVien": 12345}' OR new_value @> '{"IDSinhVien": 12345}';

-- Tìm ai sửa điểm cho course class X
SELECT changed_by, changed_at, old_value->'DiemTongKet', new_value->'DiemTongKet'
FROM audit.audit_logs
WHERE table_name = 'DT_KetQuaHocTapMonHoc'
  AND old_value @> '{"IDLopHocPhan": 141981}';
```

### 3.7 `identity` — Auth (4 tables, EMPTY)

Empty for now. Will be populated when app layer (Vue/React + NestJS/FastAPI) is built.

```sql
identity.users (id, username, email, password_hash, full_name,
                is_active, last_login_at,
                employee_id, student_id,    -- link to person
                legacy_user_id)
identity.roles (id, code, name, description)
identity.user_roles (user_id, role_id, granted_at, granted_by)
identity.sessions (id UUID, user_id, expires_at, ...)
```

**Note**: FKs from `identity.users` to `students/employees` and from other tables (*_by) to `identity.users` were **DROPPED** during migration to prevent TRUNCATE CASCADE explosion. App layer should reference `identity.users.id` informationally; integrity enforced at app level until re-added in cleanup phase.

---

## 4. Cross-cutting Concerns

### 4.1 JSONB `extra_info` / `extra_scores` / `legacy_ids` / `extra_info`

Vendor ASCVN over-engineered schemas (150+ cols per table, 80% unused). For migration we:
- Mapped TIER 1-3 (frequently used) cols to native Postgres columns
- Dumped TIER 4 (rare, <5% rows have data) into JSONB columns

**JSONB columns and their usage**:

| Table | Column | Purpose | Sample |
|---|---|---|---|
| `student.students` | `legacy_ids` | Map back to 4 source tables | `{"DT_HoSoSinhVien": 12345, "DT_SinhVien": 6789}` |
| `student.students` | `extra_info` | Rare cols from 145 source | `{"NamNhapNgu": "2010", "QuanSuQuanHam": 5, ...}` |
| `hr.employees` | `extra_info` | Rare cols from 238 source | `{"DoanVienNgayVao": "2015-03-01", ...}` |
| `student.grades` | `extra_scores` | 64 rare score cols (DiemHeSo12-39, DiemTH11-35) | `{"DiemHeSo12": 8.5, ...}` |
| `audit.audit_logs` | `old_value` / `new_value` | Before/after state of any audited row | `{"Id": 46020, "IDLopHocPhan": 141981, ...}` |

**Indexes**: All JSONB cols have GIN index for fast `@>` containment queries.

### 4.2 Partitioning

`student.enrollments` and `student.grades` partitioned by `academic_year_id` (integer).

**Why**: 2.17M enrollments + 1.94M grades across 20 years. Without partitioning, every "Show me 2025-2026 grades" scans full 1.94M. With partition pruning, scans only ~150K (1 year's partition).

**Partition naming**: `tablename_y{academic_year_id}` (e.g., `enrollments_y20` for the year with id=20).

**Adding new year**: ETL script `ensure_partitions(conn, years)` auto-creates partitions for new academic years. For manual:
```sql
CREATE TABLE student.enrollments_y21 PARTITION OF student.enrollments FOR VALUES IN (21);
CREATE TABLE student.grades_y21      PARTITION OF student.grades      FOR VALUES IN (21);
```

### 4.3 Soft Delete

All business tables have `deleted_at TIMESTAMPTZ` column. App layer should:
```sql
SELECT * FROM hr.employees WHERE deleted_at IS NULL;
```

Indexes on most tables use `WHERE deleted_at IS NULL` partial index for fast active-row queries.

### 4.4 Audit Columns

Standard pattern across business tables:
```
created_at TIMESTAMPTZ DEFAULT now()
created_by BIGINT (was → identity.users; FK dropped during migration)
updated_at TIMESTAMPTZ DEFAULT now()
updated_by BIGINT
deleted_at TIMESTAMPTZ
```

App layer should set these via middleware/trigger when records are modified.

---

## 5. Permissive Constraints — What's Dropped, Why, Re-add Plan

Migration prioritized data preservation over strict validation. Constraints dropped:

| Constraint Type | Status | Re-add When |
|---|---|---|
| `UNIQUE` on lookup codes | ❌ Dropped | After dedup pass (some codes are dups in vendor data) |
| `CHECK` on email format | ❌ Dropped | After email validation/cleanup |
| `CHECK` on credits > 0 | ❌ Dropped | Some subjects legitimately have 0 credits |
| `CHECK` on date logic | ❌ Dropped | After date cleanup |
| `NOT NULL` on most non-PK | ❌ Dropped | After data audit shows safe |
| `FK` to `identity.users` (audit cols) | ❌ Dropped | When app layer + cleanup done |
| `FK` from `identity.users` to students/employees | ❌ Dropped | App layer will handle |

**Constraints KEPT** (logical, we control):
- All PRIMARY KEYs ✓
- All "business" FKs (students→programs, enrollments→course_classes, grades→students, etc.) ✓
- `files.attachments` UNIQUE (bucket, object_key) ✓
- `chk_year`, `chk_not_self`, `chk_op` ✓

### Re-add Plan (Phase 2 cleanup)

```sql
-- Phase 2a: Dedupe lookup codes
-- (Manual: review each duplicate, decide canonical, merge)

-- Phase 2b: Re-add UNIQUE constraints
ALTER TABLE master.countries ADD CONSTRAINT countries_code_key UNIQUE (code);
-- ... etc for cleaned tables

-- Phase 2c: Re-add CHECK on email (after validation)
ALTER TABLE hr.employees ADD CONSTRAINT chk_emp_email 
  CHECK (email IS NULL OR email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$');

-- Phase 2d: NOT NULL after fill missing values
ALTER TABLE student.students ALTER COLUMN phone SET NOT NULL;
-- (Only after backfilling/imputing NULLs)

-- Phase 2e: Re-add FK to identity.users when app layer exists
ALTER TABLE hr.employees ADD CONSTRAINT employees_created_by_fkey 
  FOREIGN KEY (created_by) REFERENCES identity.users(id);
```

---

## 6. Connection Info

### Postgres

| Field | Value |
|---|---|
| Host | `localhost:5432` (Docker) or VPS IP |
| Database | `dau_university` |
| User | `dau_admin` |
| Password | `YourStrong@Pass1` (change for production!) |
| Encoding | UTF-8 |
| Locale | (default Docker postgres) |

**Connection string**:
```
postgresql://dau_admin:YourStrong@Pass1@localhost:5432/dau_university
```

**psql**:
```bash
docker exec -it dau-postgres psql -U dau_admin -d dau_university
```

**pgAdmin**: http://VPS:8080 (admin@dau.local / `YourStrong@Pass1`)

### MinIO

| Field | Value |
|---|---|
| S3 Endpoint | `localhost:9000` |
| Web UI | http://VPS:9001 |
| Access Key | `minio_admin` |
| Secret Key | `YourStrong@Pass1` |
| Buckets | `students`, `employees`, `documents`, `grade-changes` |

---

## 7. Backup & Restore

### Backup (already done at end of migration)

```bash
cd /opt/dau-uni/etl
docker exec dau-postgres pg_dump -U dau_admin -Fc dau_university | gzip > output/dau_$(date +%Y%m%d_%H%M).dump.gz
# Output: ~131 MB compressed

# Bundle MinIO blobs
docker run --rm \
  -v "$(docker inspect dau-minio --format '{{(index .Mounts 0).Name}}'):/data" \
  -v "$(pwd)/output:/out" \
  alpine sh -c "cd /data && tar czf /out/minio_$(date +%Y%m%d_%H%M).tar.gz ."
# Output: ~2.5 GB
```

### Restore (to new server)

```bash
# 1. Setup: docker compose up -d (postgres + minio)
# 2. Apply schema
docker exec dau-postgres psql -U dau_admin -d dau_university -f /opt/dau-uni/target_schema.sql

# 3. Restore data
gunzip -c output/dau_*.dump.gz | docker exec -i dau-postgres pg_restore -U dau_admin -d dau_university --clean --if-exists

# 4. Restore MinIO blobs
docker run --rm \
  -v "$(docker inspect dau-minio --format '{{(index .Mounts 0).Name}}'):/data" \
  -v "$(pwd)/output:/in" \
  alpine sh -c "cd /data && tar xzf /in/minio_*.tar.gz"
```

---

## 8. Statistics & Insights

### Data Coverage

- **Time span**: 20 academic years (2008-2009 → 2028-2029 declared, ~2018-2026 active)
- **Active vs cumulative SV**: Some 121K SV records but only ~38K currently enrolled (others graduated/dropped/transferred)
- **Lecturers**: 1,024 employees, ~600 likely active teachers
- **Subjects taught**: 73K subject instances across all programs (note: includes equivalent codes — Phase 2 dedup)

### Top Insights from Migrated Data

1. **Grading patterns**: avg `overall_score` ~6.5/10 (good but not great). 18% of grades have retake (DiemTongKet1 not null).
2. **Active students**: ~38K of 121K cumulative. 7-yr program lifecycle visible in admission_year distribution.
3. **Audit intensity**: 721K events in 3 years = ~660 events/day = active continuous use.

### Phase 2 TODO (when ready)

- [ ] HR contracts, salary, training history (10 tables, ~3K rows)
- [ ] Subject equivalences (240K rows via DT_ChiTietKhungHocKy chain)
- [ ] Lecturer assignments to course_classes (via TKB_LichHoc)
- [ ] Tuition + finance module (`KT_*` source, 1.7M rows online payment)
- [ ] Survey module (`KS_*` source, 13.8M rows — large, archive policy needed)
- [ ] Re-add constraints (UNIQUE on cleaned codes, CHECK on validated cols, FK to identity.users)
- [ ] App layer (REST API + UI) on top

---

## 9. Files Reference

| File | Path | Purpose |
|---|---|---|
| **Target DDL** | `target_schema.sql` | Postgres CREATE TABLE statements |
| **ETL code** | `etl/src/pipelines/p00..p08.py` | 8 Python pipelines |
| **Setup script** | `etl/deploy/reset-and-run.sh` | One-shot reset + ETL |
| **ETL config** | `etl/.env` | Connection strings, PAT, GDrive |
| **Logs** | `etl/logs/*.log` | Run logs (`reset-and-run-*.log` for full pipeline) |
| **Dump** | `etl/output/dau_*.dump.gz` | pg_dump compressed (131MB) |
| **Blobs** | `etl/output/minio_*.tar.gz` | MinIO archive (2.5GB) |
| **Report** | `etl/output/etl_report_*.md` | Final row counts + validation |
| **Repo** | https://github.com/haodpsut/dau-uni-migration | Public code |

---

**Migration completed by**: Phuc Hao Do (haodp.ai@gmail.com), assisted by Claude Opus 4.7
**Date**: 2026-05-12
**Total duration**: ~11 days of analysis + ~1 hour pipeline run
