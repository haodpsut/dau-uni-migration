# Deploy guide — VPS Ubuntu

ETL chạy hoàn toàn trên VPS Ubuntu, đọc 3 file `.bak` từ Google Drive.

## Constraints

| Resource | Value |
|---|---|
| VPS RAM | 7.3 GB (+ 3.8 GB swap) |
| VPS disk | 79 GB total, ~69 GB free |
| Disk khi peak | ~55 GB (sequential strategy) |
| Final size | ~6 GB (Postgres + MinIO) |

## Strategy — Sequential ETL

Vì disk hạn chế, **không restore cả 3 DB cùng lúc**. Mỗi phase: download → restore → ETL → drop → delete .bak.

```
┌─────────────────────── VPS ───────────────────────┐
│                                                   │
│  ┌──────┐   ┌─────────┐   ┌──────────┐            │
│  │mssql │ ←─│ rclone  │ ←─│ GDrive   │            │
│  │ TEMP │   │ (1 .bak)│   │(3 files) │            │
│  └──┬───┘   └─────────┘   └──────────┘            │
│     │ restore                                     │
│     ▼                                             │
│  ┌────────┐    ETL    ┌──────────┐                │
│  │ source │ ────────► │ postgres │                │
│  │  data  │           │ + minio  │                │
│  └────────┘           └──────────┘                │
│                                                   │
│  After ETL: DROP source DB + delete .bak          │
└───────────────────────────────────────────────────┘
```

---

## Phase 0: Preprocess EDU_DAU.bak trên Windows (1 lần, ~15 phút)

EDU_DAU gốc có LDF 62GB pre-allocated → quá to. Slim trước khi upload.

### Trên máy Windows
```powershell
cd d:\Locals\git-working\for-daily\phan-tich-trang-thai-quanly-truong-daihoc\etl\deploy
.\preprocess-bak.ps1
```

Script này:
1. Start Docker mssql temp container
2. Restore EDU_DAU.bak (~10 phút)
3. Shrink LDF từ 62GB → 1MB
4. BACKUP DATABASE thành `EDU_DAU_slim.bak` (~16GB, nhưng metadata LDF nhỏ)
5. Stop + remove container
6. Output: `EDU_DAU_slim.bak` cạnh `.bak` gốc

### Verify
```powershell
ls *.bak
# HRM_DAU_*.bak               (21 MB)   — upload nguyên
# EDU_DAU_slim.bak            (~16 GB)  — upload thay file gốc
# EDU_DAU_DATA_*.bak          (5.7 GB)  — upload nguyên
```

---

## Phase 1: Upload to Google Drive (5-30 phút tùy bandwidth)

Trên Windows, mở Google Drive web → New Folder `dau-uni-backup` → upload **3 files**:
- `HRM_DAU_backup_*.bak`
- `EDU_DAU_slim.bak`
- `EDU_DAU_DATA_backup_*.bak`

**Note**: KHÔNG cần upload `EDU_DAU.bak` gốc (sẽ thay bằng slim).

Sau upload xong:
- Right-click folder → `Share` → đặt "Anyone with link can view" (cho phép rclone đọc), HOẶC giữ private và dùng OAuth (recommended)

---

## Phase 2: VPS one-time setup (~10 phút)

SSH vào VPS:

```bash
# 2.1 Install Docker + Compose
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER       # logout/login để áp dụng
sudo apt install -y docker-compose-plugin git python3-venv python3-pip

# 2.2 Install rclone
curl https://rclone.org/install.sh | sudo bash

# 2.3 Configure rclone for Google Drive (interactive)
rclone config
# > n (new remote)
# > name: gdrive
# > Storage: 18 (Google Drive)
# > client_id: (Enter cho default, hoặc tự tạo OAuth credentials cho rate limit cao hơn)
# > client_secret: (Enter)
# > scope: 1 (Full access)
# > root_folder_id: (Enter)
# > service_account_file: (Enter)
# > Edit advanced config: n
# > Use auto config: n  (vì server không có browser)
# > rclone sẽ in URL → mở browser local, login, copy code → paste vào VPS terminal
# > Configure as Shared Drive: n
# > Yes this is OK
# > q (quit)

# 2.4 Test rclone
rclone ls gdrive:dau-uni-backup
# → Phải thấy 3 file .bak

# 2.5 Clone code repo
mkdir -p /opt/dau-uni
cd /opt/dau-uni
git clone https://github.com/<you>/<repo>.git .
cd etl

# 2.6 Setup Python venv + deps
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2.7 Configure .env
cp .env.example .env
nano .env       # sửa các giá trị TARGET_*, MINIO_*, SOURCE_PASSWORD nếu cần
```

---

## Phase 3: Chạy ETL (~30-45 phút)

```bash
cd /opt/dau-uni/etl
source .venv/bin/activate

# 3.1 Start target Postgres + MinIO
docker compose up -d
docker compose ps         # cả 2 phải Healthy

# 3.2 Apply target schema
python run.py setup
# → 7 schemas, 44 tables created

# 3.3 Sequential ETL run
chmod +x deploy/vps-run-etl.sh
./deploy/vps-run-etl.sh

# Script này chạy 3 phase tự động:
#   Phase HRM:       download → restore → master + employees → drop → delete
#   Phase EDU_DAU:   download → restore → academic + students + enr + grades → drop → delete
#   Phase EDU_DATA:  download → restore → files + audit → drop → delete
# Tổng ~30-45 phút.

# 3.4 Verify
python run.py status
python run.py validate
```

---

## Phase 4: Output (auto-commit + auto-upload)

`vps-run-etl.sh` **tự động** commit report nhẹ lên GitHub + upload heavy files lên GDrive khi chạy xong, **nếu** có config:

### Setup auto-commit (1 lần, trong `.env`)

```bash
nano /opt/dau-uni/etl/.env
```

```ini
# GitHub auto-push report nhẹ (~50KB Markdown + JSON)
GITHUB_PAT=github_pat_XXXXXXXXX_or_ghp_XXXXX
GITHUB_REPO=haodpsut/dau-uni-migration
GIT_USER_EMAIL=haodp.ai@gmail.com
GIT_USER_NAME=Phuc Hao Do

# GDrive auto-upload heavy (pg_dump.gz, minio.tar.gz)
GDRIVE_OUTPUT_PATH=gdrive:dau-uni-output
```

Note: tạo folder `dau-uni-output` trong GDrive trước, hoặc rclone tự tạo lần đầu upload.

### Strategy phân chia

- **GitHub** (qua auto-commit): code + `etl_report_*.md` + `etl_state.json` (≤100KB)
- **GDrive** (qua rclone): `dau_*.dump.gz` (~500MB) + `minio_*.tar.gz` (~3GB)

### Khi `vps-run-etl.sh` chạy xong

Output cuối:
```
✓ Phase 1 complete (HRM)
✓ Phase 2 complete (EDU)
✓ Phase 3 complete (EDU_DAU_DATA)
=== Finalize ===
  Creating pg_dump.gz...
  Bundling MinIO blobs...
  Generating report (~50KB)...
=== Auto-commit report → GitHub ===
  ✓ Pushed report to GitHub
=== Auto-upload heavy output → gdrive:dau-uni-output ===
  ✓ Uploaded dau_*.dump.gz
  ✓ Uploaded minio_*.tar.gz
✓ ETL COMPLETE
```

### Tắt auto bằng cách để trống config

Nếu chỉ muốn manual:
```ini
GITHUB_PAT=                  # để trống → skip auto-commit
GDRIVE_OUTPUT_PATH=          # để trống → skip upload
```

### Trên Windows local (xem trạng thái)

```bash
cd C:\Users\DEXP\dau-uni-migration
git pull                     # Lấy report mới
cat etl/output/etl_report_*.md    # Markdown đẹp với row counts + validation
```

### Cần lấy data thật về local

```powershell
# Cài rclone trên Windows nếu chưa có: https://rclone.org/downloads/
rclone copy gdrive:dau-uni-output/dau_*.dump.gz .
rclone copy gdrive:dau-uni-output/minio_*.tar.gz .
```

---

## Cleanup

Sau khi xong + dump pushed:

```bash
# Free up VPS disk (giữ lại Postgres data + MinIO blobs)
docker rm -f mssql-temp 2>/dev/null   # nếu vẫn còn
rm -rf /tmp/dau-bak/                   # delete .bak nếu chưa xóa
docker system prune -af                # remove unused images
```

---

## Troubleshooting

### "no space left on device" khi restore
- Check `df -h /` — ngưỡng dưới 10GB là đỏ
- Nếu xảy ra: `docker stop mssql-temp && docker rm mssql-temp` ngay → free disk
- Tăng VPS disk hoặc xóa data Phase trước

### rclone download chậm
- GDrive throttle ~750GB/day per account
- Nếu lớn, tạo OAuth client riêng (https://rclone.org/drive/#making-your-own-client-id) → quota cao hơn
- Hoặc dùng `rclone copy --transfers 4 --checkers 8`

### mssql container OOM
- VPS chỉ 7.3GB RAM, mssql mặc định ăn nhiều
- Đã set `MSSQL_MEMORY_LIMIT_MB=2048` trong vps-run-etl.sh
- Nếu vẫn OOM: tăng swap `sudo fallocate -l 4G /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`

### Pipeline lỗi "table not found"
- `psql -h localhost -U dau_admin dau_university -c "\dt master.*"` — verify schemas exist
- Re-run `python run.py setup` để re-apply DDL

### GitHub LFS quota exceeded (1GB free)
- pg_dump compressed thường < 500MB cho dataset này
- Nếu vượt: nâng GitHub Pro $4/tháng = 5GB LFS storage
- Hoặc chuyển sang Backblaze B2 (rẻ hơn cho data lớn)

---

## File outputs sau Phase 3

| File | Size | Location |
|---|---|---|
| Postgres data | ~3 GB | docker volume `pgdata` |
| MinIO blobs | ~3 GB | docker volume `miniodata` |
| pg_dump.gz | ~500 MB | `/opt/dau-uni/etl/output/` |
| ETL logs | ~50 MB | `/opt/dau-uni/etl/logs/` |
