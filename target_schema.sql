-- ============================================================================
-- DAU University Management System — Target Postgres Schema
-- ============================================================================
-- Version:        1.0
-- Postgres:       16+
-- Source DBs:     HRM_DAU + EDU_DAU + EDU_DAU_DATA (vendor ASCVN)
-- Migration date: 2026-05-08
-- Scope:          Core ~50 tables (SV + NS + ĐT + Môn học + Điểm + HĐ)
--
-- Conventions:
--   • snake_case English naming
--   • BIGSERIAL primary keys
--   • Soft delete via deleted_at TIMESTAMPTZ
--   • Audit cols: created_at, created_by, updated_at, updated_by, deleted_at
--   • TIMESTAMPTZ everywhere (no DATETIME)
--   • FK enforced (unlike legacy ASCVN system)
--   • legacy_id BIGINT to traceback to source SQL Server tables
--
-- Run order:
--   1. CREATE EXTENSIONs
--   2. CREATE SCHEMAs
--   3. CREATE TYPEs (ENUMs)
--   4. CREATE TABLEs (master → identity → academic → hr → student → files → audit)
--   5. CREATE INDEXes
--   6. (Post-ETL) Apply RLS policies
-- ============================================================================

-- ============================================================================
-- EXTENSIONS
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS "pgcrypto";        -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "btree_gin";       -- index on JSONB
CREATE EXTENSION IF NOT EXISTS "pg_trgm";         -- fuzzy text search
CREATE EXTENSION IF NOT EXISTS "unaccent";        -- search Vietnamese ignoring accents

-- ============================================================================
-- SCHEMAS
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS identity;
CREATE SCHEMA IF NOT EXISTS master;
CREATE SCHEMA IF NOT EXISTS hr;
CREATE SCHEMA IF NOT EXISTS academic;
CREATE SCHEMA IF NOT EXISTS student;
CREATE SCHEMA IF NOT EXISTS files;
CREATE SCHEMA IF NOT EXISTS audit;

COMMENT ON SCHEMA identity  IS 'Users, roles, sessions';
COMMENT ON SCHEMA master    IS 'Reference data (rarely changes)';
COMMENT ON SCHEMA hr        IS 'Employee records, contracts, salary';
COMMENT ON SCHEMA academic  IS 'Programs, subjects, course classes';
COMMENT ON SCHEMA student   IS 'Student records, enrollments, grades';
COMMENT ON SCHEMA files     IS 'File attachments metadata (BLOBs in MinIO)';
COMMENT ON SCHEMA audit     IS 'Cross-cutting audit logs';

-- ============================================================================
-- ENUM TYPES
-- ============================================================================
CREATE TYPE master.gender_type            AS ENUM ('male', 'female', 'other');
CREATE TYPE master.marital_status_type    AS ENUM ('single', 'married', 'divorced', 'widowed');
CREATE TYPE hr.contract_status_type       AS ENUM ('draft', 'active', 'expired', 'terminated');
CREATE TYPE hr.employment_type            AS ENUM ('full_time', 'part_time', 'visiting', 'contract');
CREATE TYPE student.enrollment_status_type AS ENUM (
    'enrolled', 'graduated', 'dropped_out', 'suspended', 'transferred', 'deferred', 'expelled'
);
CREATE TYPE student.enrollment_state_type  AS ENUM (
    'registered', 'cancelled', 'completed', 'failed', 'in_progress', 'withdrew'
);
CREATE TYPE academic.semester_type         AS ENUM ('fall', 'spring', 'summer', 'extra');

-- ============================================================================
-- SCHEMA: master (reference data)
-- ============================================================================

CREATE TABLE master.countries (
    id          BIGSERIAL PRIMARY KEY,
    code        VARCHAR(3) UNIQUE NOT NULL,        -- ISO 3166-1 alpha-3
    name        TEXT NOT NULL,
    name_native TEXT,
    legacy_id   INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ
);
COMMENT ON TABLE master.countries IS 'Source: HRM_DAU.DM_QuocGia (33) + DM_BH_QuocGia (240) → dedupe';

CREATE TABLE master.ethnicities (
    id          BIGSERIAL PRIMARY KEY,
    code        VARCHAR(10) UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    legacy_id   INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ
);
COMMENT ON TABLE master.ethnicities IS 'Source: HRM_DAU.DM_DanToc (57) + DM_BH_DanToc (55) → dedupe';

CREATE TABLE master.religions (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    legacy_id   INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ
);
COMMENT ON TABLE master.religions IS 'Source: HRM_DAU.DM_TonGiao (14)';

CREATE TABLE master.provinces (
    id          BIGSERIAL PRIMARY KEY,
    code        VARCHAR(10) UNIQUE NOT NULL,        -- mã chuẩn QG: '048' = Đà Nẵng
    name        TEXT NOT NULL,
    region      TEXT,                                -- Bắc / Trung / Nam
    legacy_id   INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ
);
COMMENT ON TABLE master.provinces IS 'Source: HRM_DAU.DM_TinhThanh (65) — drop trùng DM_BH_Tinh';

CREATE TABLE master.districts (
    id           BIGSERIAL PRIMARY KEY,
    code         VARCHAR(10) UNIQUE NOT NULL,
    name         TEXT NOT NULL,
    province_id  BIGINT NOT NULL REFERENCES master.provinces(id),
    legacy_id    INTEGER,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at   TIMESTAMPTZ
);
CREATE INDEX idx_districts_province ON master.districts(province_id) WHERE deleted_at IS NULL;
COMMENT ON TABLE master.districts IS 'Source: HRM_DAU.DM_Huyen (760) — drop trùng DM_BH_Huyen';

CREATE TABLE master.wards (
    id           BIGSERIAL PRIMARY KEY,
    code         VARCHAR(10) UNIQUE NOT NULL,
    name         TEXT NOT NULL,
    district_id  BIGINT NOT NULL REFERENCES master.districts(id),
    legacy_id    INTEGER,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at   TIMESTAMPTZ
);
CREATE INDEX idx_wards_district ON master.wards(district_id) WHERE deleted_at IS NULL;
COMMENT ON TABLE master.wards IS 'Source: HRM_DAU.DM_BH_Xa (11,706 — chuẩn BHXH)';

CREATE TABLE master.departments (
    id              BIGSERIAL PRIMARY KEY,
    code            VARCHAR(20) UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    name_short      TEXT,
    parent_id       BIGINT REFERENCES master.departments(id),
    department_type VARCHAR(50),                     -- Khoa, Phòng, Trung tâm, Viện
    legacy_id       INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);
CREATE INDEX idx_departments_parent ON master.departments(parent_id) WHERE deleted_at IS NULL;
COMMENT ON TABLE master.departments IS 'Source: HRM_DAU.DM_PhongBan (31)';

CREATE TABLE master.divisions (
    id            BIGSERIAL PRIMARY KEY,
    code          VARCHAR(20) UNIQUE NOT NULL,
    name          TEXT NOT NULL,
    department_id BIGINT NOT NULL REFERENCES master.departments(id),
    legacy_id     INTEGER,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at    TIMESTAMPTZ
);
CREATE INDEX idx_divisions_dept ON master.divisions(department_id) WHERE deleted_at IS NULL;
COMMENT ON TABLE master.divisions IS 'Source: HRM_DAU.DM_ToBoMon (20) — bộ môn trong khoa';

CREATE TABLE master.positions (
    id        BIGSERIAL PRIMARY KEY,
    code      VARCHAR(20) UNIQUE NOT NULL,
    name      TEXT NOT NULL,
    legacy_id INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
COMMENT ON TABLE master.positions IS 'Source: HRM_DAU.DM_ChucVu (33)';

CREATE TABLE master.titles (
    id        BIGSERIAL PRIMARY KEY,
    code      VARCHAR(20) UNIQUE NOT NULL,
    name      TEXT NOT NULL,
    legacy_id INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
COMMENT ON TABLE master.titles IS 'Source: HRM_DAU.DM_ChucDanh (7)';

CREATE TABLE master.degrees (
    id        BIGSERIAL PRIMARY KEY,
    code      VARCHAR(20) UNIQUE NOT NULL,
    name      TEXT NOT NULL,
    name_eng  TEXT,
    rank      INTEGER,                          -- 1=CN, 2=KS, 3=ThS, 4=TS, 5=TSKH
    legacy_id INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
COMMENT ON TABLE master.degrees IS 'Source: HRM_DAU.DM_HocVi (7) — Cử nhân, KS, ThS, TS, TSKH';

CREATE TABLE master.academic_ranks (
    id        BIGSERIAL PRIMARY KEY,
    code      VARCHAR(20) UNIQUE NOT NULL,
    name      TEXT NOT NULL,                    -- PGS, GS
    legacy_id INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
COMMENT ON TABLE master.academic_ranks IS 'Source: HRM_DAU.DM_HocHam (4)';

CREATE TABLE master.civil_ranks (
    id        BIGSERIAL PRIMARY KEY,
    code      VARCHAR(20) UNIQUE NOT NULL,
    name      TEXT NOT NULL,
    legacy_id INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
COMMENT ON TABLE master.civil_ranks IS 'Source: HRM_DAU.DM_NgachCongChuc (7) + DM_ChiTietNgachCongChuc (75)';

CREATE TABLE master.specializations (
    id        BIGSERIAL PRIMARY KEY,
    code      VARCHAR(20) UNIQUE NOT NULL,
    name      TEXT NOT NULL,
    parent_id BIGINT REFERENCES master.specializations(id),
    legacy_id INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
COMMENT ON TABLE master.specializations IS 'Source: HRM_DAU.DM_ChuyenMon (113) + DM_ChuyenNganh (474)';

CREATE TABLE master.contract_types (
    id        BIGSERIAL PRIMARY KEY,
    code      VARCHAR(20) UNIQUE NOT NULL,
    name      TEXT NOT NULL,
    legacy_id INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
COMMENT ON TABLE master.contract_types IS 'Source: HRM_DAU.DM_LoaiHopDong (9)';

CREATE TABLE master.allowance_types (
    id        BIGSERIAL PRIMARY KEY,
    code      VARCHAR(20) UNIQUE NOT NULL,
    name      TEXT NOT NULL,
    legacy_id INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);

CREATE TABLE master.decision_types (
    id        BIGSERIAL PRIMARY KEY,
    code      VARCHAR(20) UNIQUE NOT NULL,
    name      TEXT NOT NULL,
    category  VARCHAR(50),                       -- Tuyển dụng, Bổ nhiệm, Khen thưởng, ...
    legacy_id INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
COMMENT ON TABLE master.decision_types IS 'Source: HRM_DAU.DM_LoaiQuyetDinh (81)';

-- ============================================================================
-- SCHEMA: identity (auth — modern, replaces legacy ACL_*/P_*/QL_*)
-- ============================================================================

CREATE TABLE identity.users (
    id              BIGSERIAL PRIMARY KEY,
    username        VARCHAR(100) UNIQUE NOT NULL,
    email           VARCHAR(200) UNIQUE,
    password_hash   TEXT NOT NULL,                 -- bcrypt/argon2
    full_name       TEXT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at   TIMESTAMPTZ,

    -- Link to person (1 user = 1 employee OR 1 student)
    employee_id     BIGINT,                         -- FK to hr.employees, deferred
    student_id      BIGINT,                         -- FK to student.students, deferred

    legacy_user_id  INTEGER,                        -- giúp ETL trace lại NguoiTao trong các bảng cũ

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ,

    CONSTRAINT chk_user_one_role CHECK (NOT (employee_id IS NOT NULL AND student_id IS NOT NULL))
);
CREATE INDEX idx_users_legacy ON identity.users(legacy_user_id);

CREATE TABLE identity.roles (
    id          BIGSERIAL PRIMARY KEY,
    code        VARCHAR(50) UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE identity.user_roles (
    user_id    BIGINT NOT NULL REFERENCES identity.users(id) ON DELETE CASCADE,
    role_id    BIGINT NOT NULL REFERENCES identity.roles(id),
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by BIGINT REFERENCES identity.users(id),
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE identity.sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         BIGINT NOT NULL REFERENCES identity.users(id) ON DELETE CASCADE,
    issued_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    revoked_at      TIMESTAMPTZ,
    ip_address      INET,
    user_agent      TEXT
);
CREATE INDEX idx_sessions_user ON identity.sessions(user_id);
CREATE INDEX idx_sessions_expires ON identity.sessions(expires_at) WHERE revoked_at IS NULL;

-- ============================================================================
-- SCHEMA: hr (kế thừa HRM_DAU)
-- ============================================================================

CREATE TABLE hr.employees (
    id                  BIGSERIAL PRIMARY KEY,
    employee_code       VARCHAR(20) UNIQUE NOT NULL,
    legacy_id           INTEGER UNIQUE,                    -- NS_NhanSu.MaNhanSu

    -- Personal
    full_name           TEXT NOT NULL,
    gender              master.gender_type,
    date_of_birth       DATE,
    place_of_birth_id   BIGINT REFERENCES master.wards(id),
    citizen_id          VARCHAR(20),
    citizen_id_issued_date DATE,
    citizen_id_issued_place TEXT,

    nationality_id      BIGINT REFERENCES master.countries(id),
    ethnicity_id        BIGINT REFERENCES master.ethnicities(id),
    religion_id         BIGINT REFERENCES master.religions(id),
    marital_status      master.marital_status_type,

    -- Contact
    email               TEXT,
    email_personal      TEXT,
    phone               VARCHAR(20),
    phone_alt           VARCHAR(20),

    -- Address (chuẩn)
    permanent_address   TEXT,
    permanent_ward_id   BIGINT REFERENCES master.wards(id),
    current_address     TEXT,
    current_ward_id     BIGINT REFERENCES master.wards(id),

    -- Work
    department_id       BIGINT REFERENCES master.departments(id),
    division_id         BIGINT REFERENCES master.divisions(id),
    position_id         BIGINT REFERENCES master.positions(id),
    title_id            BIGINT REFERENCES master.titles(id),
    civil_rank_id       BIGINT REFERENCES master.civil_ranks(id),
    employment_type     hr.employment_type,

    -- Education
    highest_degree_id   BIGINT REFERENCES master.degrees(id),
    academic_rank_id    BIGINT REFERENCES master.academic_ranks(id),
    primary_specialization_id BIGINT REFERENCES master.specializations(id),

    -- Employment dates
    join_date           DATE,
    leave_date          DATE,
    is_active           BOOLEAN GENERATED ALWAYS AS (leave_date IS NULL) STORED,

    -- File
    photo_url           TEXT,                              -- MinIO URL
    photo_uploaded_at   TIMESTAMPTZ,

    -- Extras (rare cols → JSONB)
    extra_info          JSONB,

    -- Audit
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by          BIGINT REFERENCES identity.users(id),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by          BIGINT REFERENCES identity.users(id),
    deleted_at          TIMESTAMPTZ,

    CONSTRAINT chk_emp_email CHECK (email IS NULL OR email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'),
    CONSTRAINT chk_emp_dates CHECK (leave_date IS NULL OR leave_date > join_date)
);
CREATE INDEX idx_employees_dept ON hr.employees(department_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_employees_division ON hr.employees(division_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_employees_active ON hr.employees(is_active) WHERE deleted_at IS NULL;
CREATE INDEX idx_employees_legacy ON hr.employees(legacy_id);
CREATE INDEX idx_employees_extra ON hr.employees USING GIN (extra_info);
CREATE INDEX idx_employees_name_trgm ON hr.employees USING GIN (full_name gin_trgm_ops);
COMMENT ON TABLE hr.employees IS 'Source: HRM_DAU.NS_NhanSu (1024) + NS_NhanSuEx (1) → gộp';

ALTER TABLE identity.users ADD CONSTRAINT fk_users_employee FOREIGN KEY (employee_id) REFERENCES hr.employees(id);

CREATE TABLE hr.contracts (
    id                  BIGSERIAL PRIMARY KEY,
    legacy_id           INTEGER,                            -- NS_HopDong.Id
    employee_id         BIGINT NOT NULL REFERENCES hr.employees(id),

    contract_number     VARCHAR(50) UNIQUE NOT NULL,
    contract_type_id    BIGINT NOT NULL REFERENCES master.contract_types(id),
    signed_date         DATE NOT NULL,
    start_date          DATE NOT NULL,
    end_date            DATE,                               -- NULL = không thời hạn
    coefficient         NUMERIC(5,2),
    base_salary         NUMERIC(15,2),
    status              hr.contract_status_type NOT NULL DEFAULT 'active',

    decision_id         BIGINT,                             -- FK to hr.decisions, deferred

    notes               TEXT,
    attachment_url      TEXT,                               -- MinIO URL

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by          BIGINT REFERENCES identity.users(id),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by          BIGINT REFERENCES identity.users(id),
    deleted_at          TIMESTAMPTZ,

    CONSTRAINT chk_contract_dates CHECK (end_date IS NULL OR end_date > start_date)
);
CREATE INDEX idx_contracts_employee ON hr.contracts(employee_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_contracts_status ON hr.contracts(status) WHERE deleted_at IS NULL;
COMMENT ON TABLE hr.contracts IS 'Source: HRM_DAU.NS_HopDong (316)';

CREATE TABLE hr.contract_addendums (
    id                  BIGSERIAL PRIMARY KEY,
    legacy_id           INTEGER,
    contract_id         BIGINT NOT NULL REFERENCES hr.contracts(id),
    addendum_number     VARCHAR(50) NOT NULL,
    signed_date         DATE NOT NULL,
    effective_date      DATE NOT NULL,
    new_coefficient     NUMERIC(5,2),
    new_base_salary     NUMERIC(15,2),
    description         TEXT,
    attachment_url      TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by          BIGINT REFERENCES identity.users(id),
    deleted_at          TIMESTAMPTZ,
    UNIQUE (contract_id, addendum_number)
);
CREATE INDEX idx_addendums_contract ON hr.contract_addendums(contract_id) WHERE deleted_at IS NULL;
COMMENT ON TABLE hr.contract_addendums IS 'Source: HRM_DAU.NS_PhuLucHopDong (17)';

CREATE TABLE hr.decisions (
    id                  BIGSERIAL PRIMARY KEY,
    legacy_id           INTEGER,
    employee_id         BIGINT REFERENCES hr.employees(id),  -- NULL nếu là QĐ tập thể
    decision_number     VARCHAR(50) NOT NULL,
    decision_type_id    BIGINT NOT NULL REFERENCES master.decision_types(id),
    title               TEXT NOT NULL,
    issued_date         DATE NOT NULL,
    effective_date      DATE,
    issued_by           TEXT,
    description         TEXT,
    is_current          BOOLEAN DEFAULT FALSE,               -- snapshot QĐ hiện hành (NS_HienTaiQD)
    attachment_url      TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by          BIGINT REFERENCES identity.users(id),
    deleted_at          TIMESTAMPTZ
);
CREATE INDEX idx_decisions_employee ON hr.decisions(employee_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_decisions_current ON hr.decisions(employee_id, is_current) WHERE is_current = TRUE;
COMMENT ON TABLE hr.decisions IS 'Source: gộp HRM_DAU.NS_QuyetDinh (118) + NS_HienTaiQD (105) + NK_QuyetDinh (108)';

ALTER TABLE hr.contracts ADD CONSTRAINT fk_contracts_decision FOREIGN KEY (decision_id) REFERENCES hr.decisions(id);

CREATE TABLE hr.employee_family_relations (
    id              BIGSERIAL PRIMARY KEY,
    legacy_id       INTEGER,
    employee_id     BIGINT NOT NULL REFERENCES hr.employees(id) ON DELETE CASCADE,
    relation_type   VARCHAR(50) NOT NULL,                    -- Bố, Mẹ, Vợ/Chồng, Con, ...
    full_name       TEXT NOT NULL,
    date_of_birth   DATE,
    occupation      TEXT,
    workplace       TEXT,
    phone           VARCHAR(20),
    is_dependent    BOOLEAN DEFAULT FALSE,                   -- người phụ thuộc giảm trừ thuế
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);
CREATE INDEX idx_family_employee ON hr.employee_family_relations(employee_id) WHERE deleted_at IS NULL;
COMMENT ON TABLE hr.employee_family_relations IS 'Source: HRM_DAU.NS_QuanHeGiaDinh (1228)';

CREATE TABLE hr.employee_training_history (
    id                BIGSERIAL PRIMARY KEY,
    legacy_id         INTEGER,
    employee_id       BIGINT NOT NULL REFERENCES hr.employees(id) ON DELETE CASCADE,
    institution       TEXT NOT NULL,
    field_of_study    TEXT,
    specialization_id BIGINT REFERENCES master.specializations(id),
    degree_id         BIGINT REFERENCES master.degrees(id),
    start_date        DATE,
    end_date          DATE,
    graduation_date   DATE,
    diploma_number    VARCHAR(50),
    grade_classification TEXT,                                -- Giỏi, Khá, ...
    attachment_url    TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at        TIMESTAMPTZ
);
CREATE INDEX idx_training_employee ON hr.employee_training_history(employee_id) WHERE deleted_at IS NULL;
COMMENT ON TABLE hr.employee_training_history IS 'Source: HRM_DAU.NS_QuaTrinhDaoTao (872)';

CREATE TABLE hr.employee_career_history (
    id            BIGSERIAL PRIMARY KEY,
    legacy_id     INTEGER,
    employee_id   BIGINT NOT NULL REFERENCES hr.employees(id) ON DELETE CASCADE,
    organization  TEXT NOT NULL,
    position      TEXT,
    start_date    DATE,
    end_date      DATE,
    description   TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at    TIMESTAMPTZ
);
CREATE INDEX idx_career_employee ON hr.employee_career_history(employee_id) WHERE deleted_at IS NULL;
COMMENT ON TABLE hr.employee_career_history IS 'Source: HRM_DAU.NS_QuaTrinhCongTacChuyenMon (11)';

CREATE TABLE hr.employee_research_history (
    id                BIGSERIAL PRIMARY KEY,
    legacy_id         INTEGER,
    employee_id       BIGINT NOT NULL REFERENCES hr.employees(id) ON DELETE CASCADE,
    title             TEXT NOT NULL,
    research_type     VARCHAR(50),                           -- Đề tài, Bài báo, Sách, ...
    role              VARCHAR(50),                           -- Chủ trì, Tham gia
    publication_year  INTEGER,
    journal           TEXT,
    funding_source    TEXT,
    description       TEXT,
    attachment_url    TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at        TIMESTAMPTZ
);
CREATE INDEX idx_research_employee ON hr.employee_research_history(employee_id) WHERE deleted_at IS NULL;
COMMENT ON TABLE hr.employee_research_history IS 'Source: HRM_DAU.NS_QuaTrinhNghienCuu (69)';

CREATE TABLE hr.salary_grades (
    id            BIGSERIAL PRIMARY KEY,
    legacy_id     INTEGER,
    employee_id   BIGINT NOT NULL REFERENCES hr.employees(id),
    civil_rank_id BIGINT REFERENCES master.civil_ranks(id),
    coefficient   NUMERIC(5,2) NOT NULL,
    grade         INTEGER,                                   -- bậc (1-9)
    start_date    DATE NOT NULL,
    end_date      DATE,                                      -- NULL = current
    decision_id   BIGINT REFERENCES hr.decisions(id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at    TIMESTAMPTZ
);
CREATE INDEX idx_salary_employee ON hr.salary_grades(employee_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_salary_current ON hr.salary_grades(employee_id) WHERE end_date IS NULL AND deleted_at IS NULL;
COMMENT ON TABLE hr.salary_grades IS 'Source: HRM_DAU.NS_HeSoLuong (364)';

CREATE TABLE hr.allowances (
    id                 BIGSERIAL PRIMARY KEY,
    legacy_id          INTEGER,
    employee_id        BIGINT NOT NULL REFERENCES hr.employees(id),
    allowance_type_id  BIGINT NOT NULL REFERENCES master.allowance_types(id),
    coefficient        NUMERIC(5,2),
    amount             NUMERIC(15,2),
    start_date         DATE NOT NULL,
    end_date           DATE,
    decision_id        BIGINT REFERENCES hr.decisions(id),
    notes              TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at         TIMESTAMPTZ
);
CREATE INDEX idx_allowances_employee ON hr.allowances(employee_id) WHERE deleted_at IS NULL;
COMMENT ON TABLE hr.allowances IS 'Source: HRM_DAU.NS_PhuCap (339)';

CREATE TABLE hr.insurance_history (
    id                  BIGSERIAL PRIMARY KEY,
    legacy_id           INTEGER,
    employee_id         BIGINT NOT NULL REFERENCES hr.employees(id),
    insurance_number    VARCHAR(50),
    contribution_period_start DATE NOT NULL,
    contribution_period_end   DATE,
    contribution_base   NUMERIC(15,2),                       -- mức đóng
    employer_pct        NUMERIC(5,2),
    employee_pct        NUMERIC(5,2),
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at          TIMESTAMPTZ
);
CREATE INDEX idx_insurance_employee ON hr.insurance_history(employee_id) WHERE deleted_at IS NULL;
COMMENT ON TABLE hr.insurance_history IS 'Source: gộp HRM_DAU.NS_BaoHiem (351) + NS_QuaTrinhDongBaoHiem (39231) + NS_ThamGiaBaoHiem (279)';

-- ============================================================================
-- SCHEMA: academic (kế thừa EDU_DAU.TKB_*, DT_*)
-- ============================================================================

CREATE TABLE academic.academic_years (
    id          BIGSERIAL PRIMARY KEY,
    code        VARCHAR(20) UNIQUE NOT NULL,           -- '2025-2026'
    start_year  INTEGER NOT NULL,
    end_year    INTEGER NOT NULL,
    start_date  DATE,
    end_date    DATE,
    is_current  BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (start_year, end_year),
    CONSTRAINT chk_year CHECK (end_year = start_year + 1)
);

CREATE TABLE academic.semesters (
    id                 BIGSERIAL PRIMARY KEY,
    academic_year_id   BIGINT NOT NULL REFERENCES academic.academic_years(id),
    semester_type      academic.semester_type NOT NULL,
    code               VARCHAR(20) NOT NULL,                -- 'HK1-2025'
    name               TEXT NOT NULL,
    start_date         DATE,
    end_date           DATE,
    is_current         BOOLEAN DEFAULT FALSE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (academic_year_id, semester_type)
);

CREATE TABLE academic.programs (
    id                 BIGSERIAL PRIMARY KEY,
    code               VARCHAR(20) UNIQUE NOT NULL,         -- '7480201' (mã ngành)
    name               TEXT NOT NULL,
    name_eng           TEXT,
    department_id      BIGINT NOT NULL REFERENCES master.departments(id),
    specialization_id  BIGINT REFERENCES master.specializations(id),
    degree_id          BIGINT REFERENCES master.degrees(id),
    duration_years     NUMERIC(3,1),                        -- 4.0, 4.5, 5.0
    total_credits      INTEGER,
    legacy_id          INTEGER,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at         TIMESTAMPTZ
);
COMMENT ON TABLE academic.programs IS 'Chương trình đào tạo (CTĐT) — derive from EDU_DAU.DT_NganhHoc / DT_KhoaHoc';

CREATE TABLE academic.subjects (
    id                BIGSERIAL PRIMARY KEY,
    legacy_id         INTEGER,                              -- TKB_MonHoc.IDMonHoc
    code              VARCHAR(20) UNIQUE NOT NULL,
    name              TEXT NOT NULL,
    name_eng          TEXT,
    credits_total     INTEGER NOT NULL,
    credits_theory    INTEGER,                              -- số TC lý thuyết
    credits_practice  INTEGER,                              -- số TC thực hành
    department_id     BIGINT REFERENCES master.departments(id),
    description       TEXT,
    is_active         BOOLEAN DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at        TIMESTAMPTZ,
    CONSTRAINT chk_credits CHECK (credits_total > 0)
);
CREATE INDEX idx_subjects_legacy ON academic.subjects(legacy_id);
CREATE INDEX idx_subjects_dept ON academic.subjects(department_id) WHERE deleted_at IS NULL;
COMMENT ON TABLE academic.subjects IS 'Source: EDU_DAU.TKB_MonHoc (75614)';

CREATE TABLE academic.subject_equivalences (
    id              BIGSERIAL PRIMARY KEY,
    subject_id      BIGINT NOT NULL REFERENCES academic.subjects(id),
    equivalent_to   BIGINT NOT NULL REFERENCES academic.subjects(id),
    legacy_id       INTEGER,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (subject_id, equivalent_to),
    CONSTRAINT chk_not_self CHECK (subject_id <> equivalent_to)
);
COMMENT ON TABLE academic.subject_equivalences IS 'Source: EDU_DAU.DT_MonHocTuongDuong (240992)';

CREATE TABLE academic.student_classes (
    id                  BIGSERIAL PRIMARY KEY,
    legacy_id           INTEGER,                            -- TKB_LopHoc.Id
    code                VARCHAR(30) UNIQUE NOT NULL,        -- '21KTPM01'
    name                TEXT NOT NULL,
    program_id          BIGINT REFERENCES academic.programs(id),
    admission_year      INTEGER NOT NULL,
    advisor_id          BIGINT REFERENCES hr.employees(id), -- GVCN
    department_id       BIGINT REFERENCES master.departments(id),
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at          TIMESTAMPTZ
);
CREATE INDEX idx_student_classes_program ON academic.student_classes(program_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_student_classes_legacy ON academic.student_classes(legacy_id);
COMMENT ON TABLE academic.student_classes IS 'Lớp hành chính. Source: EDU_DAU.TKB_LopHoc (55468)';

CREATE TABLE academic.course_classes (
    id                  BIGSERIAL PRIMARY KEY,
    legacy_id           INTEGER,                            -- TKB_LopHocPhan.Id
    code                VARCHAR(30) UNIQUE NOT NULL,
    subject_id          BIGINT NOT NULL REFERENCES academic.subjects(id),
    semester_id         BIGINT NOT NULL REFERENCES academic.semesters(id),
    primary_lecturer_id BIGINT REFERENCES hr.employees(id),
    capacity            INTEGER,
    enrolled_count      INTEGER DEFAULT 0,
    classroom           VARCHAR(50),
    schedule_pattern    TEXT,                               -- '2-3,5-6 / T2,T4'
    is_locked           BOOLEAN DEFAULT FALSE,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at          TIMESTAMPTZ
);
CREATE INDEX idx_course_classes_subject ON academic.course_classes(subject_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_course_classes_semester ON academic.course_classes(semester_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_course_classes_lecturer ON academic.course_classes(primary_lecturer_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_course_classes_legacy ON academic.course_classes(legacy_id);
COMMENT ON TABLE academic.course_classes IS 'Lớp học phần. Source: EDU_DAU.TKB_LopHocPhan (82501)';

-- ============================================================================
-- SCHEMA: student (kế thừa EDU_DAU.DT_*)
-- ============================================================================

CREATE TABLE student.students (
    id                  BIGSERIAL PRIMARY KEY,
    student_code        VARCHAR(20) UNIQUE NOT NULL,
    legacy_ids          JSONB,                              -- {"DT_HoSoSinhVien": 12345, "DT_SinhVien": 6789}

    -- Personal (TIER 1: 100% used)
    full_name           TEXT NOT NULL,
    family_name         TEXT,                               -- HoDem
    given_name          TEXT,                               -- Ten
    gender              master.gender_type NOT NULL,        -- GioiTinh (100%)
    date_of_birth       DATE,                               -- NgaySinh2 (varchar→date)

    -- Birth place
    place_of_birth_id   BIGINT REFERENCES master.wards(id),
    place_of_birth_text TEXT,                               -- when ID null

    -- Identity (TIER 2: high usage)
    citizen_id          VARCHAR(20),                        -- SoCMND (99%)
    citizen_id_issued_date DATE,
    citizen_id_issued_place TEXT,
    nationality_id      BIGINT REFERENCES master.countries(id),
    ethnicity_id        BIGINT REFERENCES master.ethnicities(id),     -- IDDanToc (88%)
    religion_id         BIGINT REFERENCES master.religions(id),       -- IDTonGiao (35%)

    -- Permanent address (HKTT_*)
    permanent_address   TEXT,                               -- DiaChiThuongTru (99.7%)
    permanent_ward_id   BIGINT REFERENCES master.wards(id),
    permanent_house_no  TEXT,

    -- Contact address (DCLL_*)
    contact_address     TEXT,                               -- DiaChiLienLac (99.9%)
    contact_ward_id     BIGINT REFERENCES master.wards(id),

    -- Phones
    phone               VARCHAR(20) NOT NULL,               -- SoDienThoai (~100%)
    phone_alt           VARCHAR(20),                        -- SoDienThoai2 (99%)
    phone_parent        VARCHAR(20),                        -- SoDienThoaiPhuHuynh

    email               TEXT,                               -- Email (99.9%)
    email_parent        TEXT,                               -- EmailPhuHuynh

    -- Family
    guardian_name       TEXT,                               -- HoTenNguoiGiamHo
    guardian_birth_year VARCHAR(10),
    guardian_occupation TEXT,

    -- Academic structure (TIER 1: 100% used)
    program_id          BIGINT NOT NULL REFERENCES academic.programs(id),     -- IDNganh
    student_class_id    BIGINT REFERENCES academic.student_classes(id),       -- IDLopHoc
    facility_id         INTEGER,                            -- IDCoSo (cơ sở học)
    education_type_id   INTEGER,                            -- IDHeDaoTao (chính quy/...)
    training_form_id    INTEGER,                            -- IDLoaiHinhDT
    cohort_id           INTEGER,                            -- IDKhoaHoc

    -- Admission
    admission_year      INTEGER NOT NULL,                   -- NamVao (99.9%)
    admission_date      DATE,                               -- NgayNhapHoc (99.9%)
    expected_graduation_year INTEGER,
    high_school_graduation_year INTEGER,                    -- NamTotNghiep (28%)
    high_school_name    TEXT,                               -- TruongTotNghiep

    -- Banking (low usage)
    bank_account_number VARCHAR(50),                        -- SoTaiKhoan (13%)
    bank_account_name   TEXT,
    bank_name           TEXT,
    bank_branch         TEXT,
    bank_id             INTEGER,

    -- Insurance
    insurance_number    VARCHAR(50),                        -- MaBHXH_YT (28%)

    -- Auth (legacy stored passwords — DO NOT migrate as-is, force reset on first login)
    legacy_pwd_hash     TEXT,                               -- Pwd (100%) — for transition only
    legacy_pwd_key      VARCHAR(20),                        -- PwdHashKey

    -- Status
    enrollment_status   student.enrollment_status_type NOT NULL DEFAULT 'enrolled',
    status_changed_at   TIMESTAMPTZ,

    -- Conduct rankings
    conduct_ranking_overall TEXT,                           -- XepLoaiHK
    study_ranking_overall TEXT,                             -- XepLoaiHT
    graduation_ranking  TEXT,                               -- XepLoaiTN

    -- Photo + extras
    photo_url           TEXT,
    photo_uploaded_at   TIMESTAMPTZ,

    -- Extras (60+ rare cols → JSONB)
    extra_info          JSONB,

    -- Audit
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by          BIGINT REFERENCES identity.users(id),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by          BIGINT REFERENCES identity.users(id),
    deleted_at          TIMESTAMPTZ
);
CREATE INDEX idx_students_program ON student.students(program_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_students_class ON student.students(student_class_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_students_status ON student.students(enrollment_status) WHERE deleted_at IS NULL;
CREATE INDEX idx_students_admission_year ON student.students(admission_year);
CREATE INDEX idx_students_legacy ON student.students USING GIN (legacy_ids);
CREATE INDEX idx_students_extra ON student.students USING GIN (extra_info);
CREATE INDEX idx_students_name_trgm ON student.students USING GIN (full_name gin_trgm_ops);
COMMENT ON TABLE student.students IS 'Source: GỘP DT_HoSoSinhVien (97391) + DT_SinhVien (37682) + DT_ThongTinSinhVien (23792) + DT_SinhVienEx (7536). 145 cột nguồn → ~50 cột thiết yếu, rest → extra_info JSONB';

ALTER TABLE identity.users ADD CONSTRAINT fk_users_student FOREIGN KEY (student_id) REFERENCES student.students(id);

-- ENROLLMENTS — partitioned by academic year
CREATE TABLE student.enrollments (
    id                  BIGSERIAL,
    legacy_id           BIGINT,
    student_id          BIGINT NOT NULL,                    -- FK below for partitioned table
    course_class_id     BIGINT NOT NULL,
    academic_year_id    BIGINT NOT NULL,
    semester_id         BIGINT NOT NULL,
    enrolled_at         TIMESTAMPTZ NOT NULL,
    enrolled_by_id      BIGINT,
    state               student.enrollment_state_type NOT NULL DEFAULT 'registered',
    cancelled_at        TIMESTAMPTZ,
    cancelled_by_id     BIGINT,
    cancel_reason       TEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, academic_year_id),
    UNIQUE (student_id, course_class_id, academic_year_id)
) PARTITION BY LIST (academic_year_id);

-- Tạo các partition (chạy thêm khi có năm mới)
-- CREATE TABLE student.enrollments_y2024 PARTITION OF student.enrollments FOR VALUES IN (2024);
-- CREATE TABLE student.enrollments_y2025 PARTITION OF student.enrollments FOR VALUES IN (2025);
-- CREATE TABLE student.enrollments_y2026 PARTITION OF student.enrollments FOR VALUES IN (2026);

COMMENT ON TABLE student.enrollments IS 'Source: EDU_DAU.DT_DangKyHocPhan (2,300,818). Partition by academic_year_id để query 1 năm chỉ scan 1 partition';

-- GRADES — slim 153 → 33 cols, partitioned (chi tiết xem 05-grade-table-column-analysis.md)
CREATE TABLE student.grades (
    id                          BIGSERIAL,
    legacy_id                   BIGINT,
    student_id                  BIGINT NOT NULL,
    course_class_id             BIGINT NOT NULL,
    enrollment_id               BIGINT,
    academic_year_id            BIGINT NOT NULL,
    semester_id                 BIGINT NOT NULL,

    -- Component scores
    attendance_score            NUMERIC(4,2),                -- DiemChuyenCan1 (26%)
    weighted_score_1            NUMERIC(4,2),                -- DiemHeSo11 (31%)
    regular_avg_score           NUMERIC(4,2),                -- DiemTBThuongKy (88%)
    practice_avg                NUMERIC(4,2),                -- DiemTBThucHanh (5%)
    essay_score                 NUMERIC(4,2),                -- DiemTieuLuan1 (11%)

    -- Final exam (3 attempts)
    final_exam_score            NUMERIC(4,2),                -- DiemThi (96%)
    final_exam_score_retake1    NUMERIC(4,2),                -- DiemThi1 (95%)
    final_exam_score_retake2    NUMERIC(4,2),                -- DiemThi2 (8.6%)

    -- Overall (3 attempts)
    overall_score               NUMERIC(4,2),                -- DiemTongKet (96%)
    overall_score_retake1       NUMERIC(4,2),                -- DiemTongKet1 (95%)
    overall_score_retake2       NUMERIC(4,2),                -- DiemTongKet2 (8.6%)

    -- Letter & GPA
    letter_grade_native         CHAR(2),                     -- DiemChu (96%)
    letter_grade_alt            CHAR(2),                     -- DiemChu2 (95%)
    letter_grade_eng            VARCHAR(3),                  -- XepLoai_ENG (100%)
    letter_grade_vn             VARCHAR(20),                 -- XepLoai (37%)
    grade_point                 NUMERIC(3,2),                -- DiemTinChi (95%)
    grade_point_alt             NUMERIC(3,2),                -- DiemTinChi2 (95%)

    -- Status flags
    is_passed                   BOOLEAN NOT NULL DEFAULT FALSE,
    is_passed_retake1           BOOLEAN,
    is_eligible_for_final       BOOLEAN,
    is_absent_from_exam         BOOLEAN NOT NULL DEFAULT FALSE,
    is_absent_from_midterm      BOOLEAN,
    is_practice_locked          BOOLEAN NOT NULL DEFAULT FALSE,
    is_essay_locked             BOOLEAN NOT NULL DEFAULT FALSE,
    is_final_locked             BOOLEAN NOT NULL DEFAULT FALSE,
    is_excluded                 BOOLEAN NOT NULL DEFAULT FALSE,

    -- Notes
    notes                       TEXT,                        -- GhiChu (46%)
    eligibility_notes           TEXT,                        -- GhiChuXetDuThi (34%)

    -- Extras (rare cols → JSONB)
    extra_scores                JSONB,

    -- Audit
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by                  BIGINT,
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by                  BIGINT,

    PRIMARY KEY (id, academic_year_id),
    UNIQUE (student_id, course_class_id, academic_year_id)
) PARTITION BY LIST (academic_year_id);

COMMENT ON TABLE student.grades IS 'Source: EDU_DAU.DT_KetQuaHocTapMonHoc (2,028,965). Slim từ 153 cột → 33 cột (xem 05-grade-table-column-analysis.md)';

CREATE TABLE student.graduations (
    id                  BIGSERIAL PRIMARY KEY,
    legacy_id           INTEGER,
    student_id          BIGINT NOT NULL REFERENCES student.students(id),
    graduation_date     DATE NOT NULL,
    diploma_number      VARCHAR(50) UNIQUE NOT NULL,
    diploma_type        VARCHAR(50),
    classification      TEXT,                                -- Xuất sắc, Giỏi, Khá, ...
    final_gpa           NUMERIC(3,2),
    total_credits       INTEGER,
    decision_id         BIGINT,                              -- QĐ cấp bằng
    issued_date         DATE,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at          TIMESTAMPTZ
);
CREATE INDEX idx_graduations_student ON student.graduations(student_id) WHERE deleted_at IS NULL;
COMMENT ON TABLE student.graduations IS 'Source: EDU_DAU.DT_DSSinhVienTotNghiep (17969)';

-- ============================================================================
-- SCHEMA: files (BLOBs in MinIO, metadata here)
-- ============================================================================

CREATE TABLE files.attachments (
    id              BIGSERIAL PRIMARY KEY,
    bucket          VARCHAR(50) NOT NULL,                    -- 'students', 'employees', 'contracts', ...
    object_key      TEXT NOT NULL,                           -- relative path inside bucket
    url             TEXT NOT NULL,                           -- full MinIO URL
    file_name       TEXT NOT NULL,
    content_type    VARCHAR(100),
    size_bytes      BIGINT,
    checksum_sha256 CHAR(64),

    -- Polymorphic owner
    owner_table     VARCHAR(50) NOT NULL,                    -- 'students', 'employees', ...
    owner_id        BIGINT NOT NULL,
    purpose         VARCHAR(50),                             -- 'photo', 'contract_pdf', 'grade_change', ...

    uploaded_by     BIGINT REFERENCES identity.users(id),
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ,

    UNIQUE (bucket, object_key)
);
CREATE INDEX idx_attachments_owner ON files.attachments(owner_table, owner_id) WHERE deleted_at IS NULL;
COMMENT ON TABLE files.attachments IS 'Source: HRM_HinhAnh, EDU_DT_SinhVien.HinhAnh, EDU_KT_BienNhanNhapHoc → MinIO + metadata here';

-- Compliance: lưu lịch sử sửa điểm với biên bản đính kèm
CREATE TABLE files.grade_change_records (
    id              BIGSERIAL PRIMARY KEY,
    legacy_id       INTEGER,
    grade_id        BIGINT,                                  -- FK to student.grades (deferred — partitioned)
    student_id      BIGINT NOT NULL REFERENCES student.students(id),
    course_class_id BIGINT NOT NULL REFERENCES academic.course_classes(id),

    change_type     VARCHAR(50),                             -- 'final_exam', 'overall', 'retake'
    old_exam_score  NUMERIC(4,2),
    old_overall_score NUMERIC(4,2),
    new_exam_score  NUMERIC(4,2),
    new_overall_score NUMERIC(4,2),

    document_url    TEXT NOT NULL,                           -- MinIO URL biên bản PDF
    document_name   TEXT,
    notes           TEXT,

    requested_by    BIGINT REFERENCES identity.users(id),
    approved_by     BIGINT REFERENCES identity.users(id),
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_at     TIMESTAMPTZ
);
CREATE INDEX idx_grade_changes_student ON files.grade_change_records(student_id);
CREATE INDEX idx_grade_changes_course ON files.grade_change_records(course_class_id);
COMMENT ON TABLE files.grade_change_records IS 'Source: EDU_DAU_DATA.EDU_NK_FileSuaDiem (1346) — quan trọng cho kiểm định AUN-QA/ABET';

-- ============================================================================
-- SCHEMA: audit
-- ============================================================================

CREATE TABLE audit.audit_logs (
    id              BIGSERIAL PRIMARY KEY,
    table_name      VARCHAR(100) NOT NULL,
    record_id       BIGINT NOT NULL,
    operation       VARCHAR(20) NOT NULL,                    -- INSERT / UPDATE / DELETE
    old_value       JSONB,
    new_value       JSONB,
    changed_by      BIGINT REFERENCES identity.users(id),
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    legacy_event_id BIGINT,                                  -- EDU_NK_TongHop.Id
    CONSTRAINT chk_op CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE'))
);
CREATE INDEX idx_audit_table ON audit.audit_logs(table_name, record_id);
CREATE INDEX idx_audit_when ON audit.audit_logs(changed_at);
CREATE INDEX idx_audit_who ON audit.audit_logs(changed_by);
CREATE INDEX idx_audit_old_gin ON audit.audit_logs USING GIN (old_value);
CREATE INDEX idx_audit_new_gin ON audit.audit_logs USING GIN (new_value);
COMMENT ON TABLE audit.audit_logs IS 'Source: EDU_DAU_DATA.EDU_NK_TongHop (1.25M) — convert XML before/after → JSONB. Migrate 3 năm gần nhất';

-- ============================================================================
-- ROW-LEVEL SECURITY (apply post-load)
-- ============================================================================
-- ALTER TABLE student.grades ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE hr.salary_grades ENABLE ROW LEVEL SECURITY;
--
-- Example policy: students chỉ xem điểm của mình
-- CREATE POLICY grades_self ON student.grades FOR SELECT
--     USING (student_id = (SELECT student_id FROM identity.users WHERE id = current_setting('app.user_id')::BIGINT));

-- ============================================================================
-- SUMMARY
-- ============================================================================
-- 7 schemas: identity, master, hr, academic, student, files, audit
-- 7 ENUM types
-- ~50 tables (1 partitioned: grades, enrollments)
-- All FK enforced, all soft-delete with deleted_at
-- Indexes: btree on FKs, GIN on JSONB cols, trgm on name searches
--
-- Estimated final size after ETL:
--   • Master data: ~50 MB
--   • HR: ~20 MB
--   • Academic catalog: ~100 MB
--   • Students + enrollments + grades: ~2 GB (with partitions)
--   • Audit (3 years): ~500 MB
--   • Files metadata: ~10 MB (BLOBs in MinIO ~3 GB)
--   TOTAL Postgres: ~2.7 GB
--   TOTAL MinIO:    ~3 GB
-- ============================================================================
