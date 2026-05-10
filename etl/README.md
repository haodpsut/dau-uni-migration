# ETL Prototype — DAU University Migration

ETL pipeline migrate dữ liệu từ SQL Server (vendor ASCVN) sang Postgres mới (target schema).

## Project layout

```
etl/
├── README.md                    ← bạn đang đọc
├── requirements.txt             ← Python deps
├── .env.example                 ← copy thành .env, điền credentials
├── docker-compose.yml           ← stack Postgres + MinIO cho test
├── run.py                       ← CLI entrypoint
└── src/
    ├── config.py                ← load .env
    ├── db.py                    ← connection helpers (SQL Server + Postgres)
    ├── log.py                   ← logging setup
    ├── load.py                  ← COPY-based bulk loader cho Postgres
    └── pipelines/
        ├── p00_setup.py         ← apply target_schema.sql
        ├── p01_master.py        ← master data (provinces, departments, ...)
        ├── p02_employees.py     ← HR employees (gộp NS_NhanSu + NS_NhanSuEx)
        └── p03_students.py      ← Students (gộp 4 bảng SV)
```

## Setup nhanh

### 1. Cài Python deps
```bash
cd etl
python -m venv .venv
source .venv/bin/activate          # Linux/Mac
# .venv\Scripts\activate            # Windows PowerShell
pip install -r requirements.txt
```

### 2. Tạo `.env` từ template
```bash
cp .env.example .env
# Sửa SOURCE_* và TARGET_* cho khớp môi trường
```

### 3. Khởi động Postgres + MinIO (target)
```bash
docker compose up -d
# Postgres: localhost:5432, db=dau_university, user=dau_admin, pass=YourStrong@Pass1
# MinIO:    http://localhost:9001 (UI), :9000 (S3 API), user=minio_admin, pass=YourStrong@Pass1
```

### 4. Apply target schema
```bash
python run.py setup
# Chạy `target_schema.sql` (đã viết ở Đợt 5) trên Postgres
# Tạo 7 schemas + ~50 tables + indexes
```

### 5. Chạy pipelines
```bash
python run.py master              # master data trước (provinces, etc.)
python run.py employees           # rồi employees
python run.py students            # rồi students (cần master + academic catalog xong trước)
python run.py all                 # chạy hết theo thứ tự
```

## Source SQL Server — kết nối thế nào?

Có 3 cách:

**A.** Docker container `mssql-edu` đã có (nếu thầy chưa xóa):
```env
SOURCE_HOST=localhost
SOURCE_PORT=1433
SOURCE_USER=sa
SOURCE_PASSWORD=YourStrong@Pass1
```

**B.** Restore .bak vào Postgres mới — một lần duy nhất, dùng container Docker:
```bash
docker run -d --name mssql-source \
  -e ACCEPT_EULA=Y -e MSSQL_SA_PASSWORD=YourStrong@Pass1 \
  -p 1433:1433 \
  -v "$(pwd)/../:/backups" \
  mcr.microsoft.com/mssql/server:2022-latest

# Đợi 30s, rồi RESTORE
```

**C.** Production server có sẵn SQL Server — chỉ điền hostname.

## Design principles

1. **Idempotent**: chạy lại không double-insert. Dùng `INSERT ... ON CONFLICT (legacy_id) DO UPDATE` hoặc `TRUNCATE` trước.
2. **Bulk via COPY**: dùng `psycopg.copy()` thay `INSERT` — nhanh 10× cho >10K rows.
3. **Legacy ID preserved**: mọi bảng đích có `legacy_id` để traceback.
4. **Validate sau load**: count rows, check orphan FK.
5. **Resumable**: pipeline ghi state vào `etl_state` table — restart từ đầu hay tiếp tục đều OK.
6. **Logging**: `loguru` ra cả console + file `logs/etl-YYYYMMDD.log`.

## Validate sau load

```bash
python run.py validate
# Kiểm tra:
# • Row counts source vs target
# • No orphan FK
# • Spot-check 10 random records (deep equality)
# • Performance: SELECT 1 student với grades < 100ms
```

## Performance benchmark (dự kiến trên máy laptop 16GB RAM)

| Pipeline | Source rows | Time |
|---|---:|---:|
| 00 setup | — | 5s |
| 01 master | ~13K | 30s |
| 02 employees | 1024 | 10s |
| 03 students | 38K (merge 4) | 2 min |
| 04 academic | 215K (subjects + classes) | 1 min |
| 05 enrollments | 2.3M | 10 min |
| 06 grades | 2M | 15 min |
| 07 files (BLOB → MinIO) | 24K files | 30 min |
| 08 audit (3 yr XML→JSONB) | 500K | 5 min |
| **TOTAL** | | **~1h** |

## Chuyển sang production Ubuntu

Sau khi pipeline chạy ổn local, lên Ubuntu VPS:

```bash
# Trên Ubuntu
git clone <github-repo>
cd dau-uni-migration/etl
docker compose up -d                     # Postgres + MinIO
cp .env.example .env && vim .env         # đổi SOURCE_HOST sang IP server SQL Server
python run.py all
```

Sau đó dump backup:
```bash
pg_dump -h localhost -U dau_admin -Fc dau_university > /tmp/dau_$(date +%Y%m%d).dump
b2 upload-file dau-backups /tmp/dau_*.dump backups/
```
