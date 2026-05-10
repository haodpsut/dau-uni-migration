# Push code to GitHub repo

Repo: https://github.com/haodpsut/dau-uni-migration

## One-time setup — Lựa chọn 1 trong 2 cách

### Cách A — Clone vào folder mới + copy files (an toàn nhất, không đụng repo `for-daily`)

```bash
# Trên Windows PowerShell hoặc Bash
cd ~          # hoặc bất kỳ folder nào ngoài for-daily
git clone https://haodpsut:<PAT>@github.com/haodpsut/dau-uni-migration.git
cd dau-uni-migration

# Copy nội dung migration sang
cp -r d:/Locals/git-working/for-daily/phan-tich-trang-thai-quanly-truong-daihoc/* .
cp d:/Locals/git-working/for-daily/phan-tich-trang-thai-quanly-truong-daihoc/.gitignore .

# Verify .bak không bị stage (gitignore chặn)
git status
ls *.bak 2>/dev/null && echo "WARNING: .bak files present, gitignore should exclude them"

# Push
git add .
git commit -m "feat: initial migration code + analysis docs"
git push origin main
```

### Cách B — Init git ngay tại thư mục hiện tại (nested repo cảnh báo)

```bash
cd d:/Locals/git-working/for-daily/phan-tich-trang-thai-quanly-truong-daihoc

# Init local git (nested trong for-daily — but separate)
git init
git remote add origin https://haodpsut:<PAT>@github.com/haodpsut/dau-uni-migration.git
git checkout -b main

# Stage everything (gitignore sẽ chặn .bak)
git add .
git status

# Commit + push
git commit -m "feat: initial migration code + analysis docs"
git push -u origin main
```

⚠️ Cách B có thể conflict với git của parent `for-daily/`. Recommend cách A.

## Lần sau — chỉ push report nhẹ

Sau khi VPS chạy xong ETL, lấy report về:

```bash
# Trên VPS
cd /opt/dau-uni
git pull
git add etl/output/etl_report_*.md etl/output/etl_state.json
git commit -m "data: ETL run $(date +%Y-%m-%d)"
git push origin main
```

Em local pull về xem:

```bash
cd ~/dau-uni-migration
git pull
cat etl/output/etl_report_*.md   # Markdown đẹp với row counts + validation
```

## Authentication với PAT

Nếu git prompt hỏi password, dùng PAT (không phải password GitHub):

```bash
# Cách 1: Embedded trong URL (đơn giản nhưng URL có PAT)
git remote set-url origin https://haodpsut:<PAT>@github.com/haodpsut/dau-uni-migration.git

# Cách 2: Credential helper (an toàn hơn)
git config --global credential.helper store      # Linux/Mac
git config --global credential.helper manager    # Windows
# Lần đầu push, prompt PAT 1 lần → cached vĩnh viễn

# Cách 3: SSH key (an toàn nhất, dài hạn)
# Generate ssh key, add to GitHub Settings → SSH keys
git remote set-url origin git@github.com:haodpsut/dau-uni-migration.git
```

## Files được push (qua .gitignore)

```
✓ Push (text/code, ~5MB total):
  README.md, .gitignore, PUSH-TO-GITHUB.md
  01-05-*.md (analysis docs)
  target_schema.sql
  etl/ (toàn bộ code, scripts, docs)
  etl/output/etl_report_*.md (report nhẹ ~50KB sau khi ETL)

✗ Bị bỏ qua bởi .gitignore (heavy, đi GDrive):
  *.bak (.bak source files)
  etl/output/dau_*.dump.gz (Postgres dump)
  etl/output/minio_*.tar.gz (MinIO blobs)
  etl/.venv/, __pycache__/, *.pyc
  etl/.env (chứa secrets)
  etl/logs/
```
