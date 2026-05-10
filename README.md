# DAU University — Migration from ASCVN (SQL Server) to Postgres

Migrate dữ liệu hệ thống quản lý đại học cũ (vendor ASCVN, SQL Server, từ 2018) sang
Postgres 16 hiện đại trên Ubuntu, schema thiết kế lại theo best practices.

## Trạng thái

| Phase | Status |
|---|---|
| Discovery & analysis | ✅ Done — xem `01-05-*.md` |
| Target schema (Postgres) | ✅ Done — `target_schema.sql` (~50 tables, 7 schemas) |
| ETL prototype (Python) | ✅ Done — `etl/` (8 pipelines) |
| Deploy plan VPS | ✅ Done — `etl/deploy/DEPLOY.md` |
| First ETL run | ⏳ Pending |

## Source databases

| DB | Size | Tables | Purpose |
|---|---:|---:|---|
| HRM_DAU | 21 MB .bak / 180 MB DB | 586 | HR module (employees, contracts, salary) |
| EDU_DAU | 16 GB .bak / 38 GB DB | 1465 | Academic module (students, grades, enrollments) |
| EDU_DAU_DATA | 5.7 GB .bak / 20 GB DB | 65 | Shared blob storage + XML audit log |

## Target schema highlights

- **7 schemas**: `identity`, `master`, `hr`, `academic`, `student`, `files`, `audit`
- **~50 tables** (giảm từ 2,116 source tables — 67% rỗng hoặc legacy)
- **Foreign keys ENFORCED** (source chỉ có 4% FK)
- **Partitioned by year**: `student.enrollments`, `student.grades`
- **JSONB cho rare cols**: gộp 64 cột rare của `grades` vào 1 cột `extra_scores`
- **`grades` slim 153 → 33 cột** (xem `05-grade-table-column-analysis.md`)
- **Soft delete** + audit cols chuẩn (created_at/by, updated_at/by, deleted_at)

## Documentation

| File | Nội dung |
|---|---|
| [01-discovery-overview.md](01-discovery-overview.md) | HRM_DAU module discovery |
| [02-discovery-overview-EDU.md](02-discovery-overview-EDU.md) | EDU_DAU module discovery |
| [03-discovery-overview-EDU-DATA.md](03-discovery-overview-EDU-DATA.md) | DB chia sẻ blob + audit |
| [04-target-design-and-migration-plan.md](04-target-design-and-migration-plan.md) | Postgres design + ETL plan |
| [05-grade-table-column-analysis.md](05-grade-table-column-analysis.md) | Slim 153→33 cột phân tích NULL distribution |
| [target_schema.sql](target_schema.sql) | DDL chạy được trên Postgres 16 |
| [etl/README.md](etl/README.md) | ETL Python pipeline guide |
| [etl/SCHEMA_NOTES.md](etl/SCHEMA_NOTES.md) | Source column verifications + caveats |
| [etl/deploy/DEPLOY.md](etl/deploy/DEPLOY.md) | VPS deployment runbook |

## Quick start (VPS Ubuntu)

```bash
# 1. Setup VPS (one-time)
curl -fsSL https://raw.githubusercontent.com/haodpsut/dau-uni-migration/main/etl/deploy/vps-setup.sh | bash
rclone config       # OAuth GDrive (interactive)

# 2. Clone repo
mkdir -p /opt/dau-uni && cd /opt/dau-uni
git clone https://github.com/haodpsut/dau-uni-migration.git .

# 3. Setup ETL
cd etl
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env

# 4. Apply schema + run ETL
docker compose up -d
python run.py setup
./deploy/vps-run-etl.sh

# 5. Output
# - GitHub: etl/output/etl_report_*.md (~50KB)
# - GDrive: dau_*.dump.gz, minio_*.tar.gz (heavy)
```

Detail xem [etl/deploy/DEPLOY.md](etl/deploy/DEPLOY.md).

## License

Internal use, university migration project.
