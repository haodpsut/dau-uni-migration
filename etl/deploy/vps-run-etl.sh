#!/bin/bash
# vps-run-etl.sh — Sequential ETL trên VPS
# Run: ./deploy/vps-run-etl.sh (từ folder etl/)
#
# Pipeline xử lý từng .bak một, drop mssql DB ngay sau ETL → tiết kiệm disk.

set -euo pipefail

# Colors
G='\033[0;32m'
Y='\033[0;33m'
R='\033[0;31m'
N='\033[0m'

# Config
GDRIVE_FOLDER_ID="${GDRIVE_BACKUP_FOLDER_ID:-1OzCtCJ7AVcR_Ox0owOtKe7DFfFT72zJz}"
BAK_DIR="/tmp/dau-bak"
MSSQL_CONTAINER="mssql-temp"
MSSQL_PASS="${SOURCE_PASSWORD:-YourStrong@Pass1}"

mkdir -p "$BAK_DIR"

# =============================================================================
# Helpers
# =============================================================================

log()    { echo -e "${G}[$(date +%H:%M:%S)]${N} $*"; }
warn()   { echo -e "${Y}[$(date +%H:%M:%S)]${N} $*"; }
fail()   { echo -e "${R}[$(date +%H:%M:%S)]${N} $*"; exit 1; }

# Download all .bak files from public GDrive folder once at start
download_all_baks() {
    if [ -f "$BAK_DIR/.downloaded" ]; then
        log "  .bak files already downloaded"
        ls -lh "$BAK_DIR"/*.bak 2>/dev/null
        return 0
    fi
    log "Downloading 3 .bak files from GDrive folder $GDRIVE_FOLDER_ID..."
    log "  (~22GB total — 5-10 phút tùy bandwidth)"

    gdown --folder "https://drive.google.com/drive/folders/$GDRIVE_FOLDER_ID" \
        -O "$BAK_DIR" --remaining-ok \
        || fail "gdown download failed. Check folder is shared 'Anyone with link can view'"

    # gdown nested files into a subfolder named after folder — flatten
    find "$BAK_DIR" -mindepth 2 -name "*.bak" -exec mv {} "$BAK_DIR/" \;
    find "$BAK_DIR" -mindepth 1 -type d -empty -delete

    ls -lh "$BAK_DIR"/*.bak
    touch "$BAK_DIR/.downloaded"
    log "  ✓ All .bak downloaded"
}

check_disk() {
    local need_gb=$1
    local free_gb=$(df -BG / | tail -1 | awk '{gsub(/G/,"",$4); print $4}')
    log "Disk free: ${free_gb}GB (need: ${need_gb}GB)"
    if [ "$free_gb" -lt "$need_gb" ]; then
        fail "Not enough disk! Free ${free_gb}GB but need ${need_gb}GB"
    fi
}

ensure_mssql_running() {
    if ! docker ps --filter "name=$MSSQL_CONTAINER" --filter "status=running" -q | grep -q .; then
        log "Starting mssql temp container (memory limit 2GB)..."
        docker rm -f $MSSQL_CONTAINER 2>/dev/null || true
        docker run -d --name $MSSQL_CONTAINER \
            -e "ACCEPT_EULA=Y" \
            -e "MSSQL_SA_PASSWORD=$MSSQL_PASS" \
            -e "MSSQL_MEMORY_LIMIT_MB=2048" \
            -p 1433:1433 \
            -v "$BAK_DIR:/backups" \
            --restart=no \
            mcr.microsoft.com/mssql/server:2022-latest >/dev/null
        log "Waiting for mssql to be ready..."
        for i in {1..30}; do
            if docker exec $MSSQL_CONTAINER /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$MSSQL_PASS" -C -Q "SELECT 1" >/dev/null 2>&1; then
                log "  mssql ready"
                return 0
            fi
            sleep 2
        done
        fail "mssql failed to start"
    fi
}

restore_bak() {
    local bak_name=$1
    local logical_name=$2
    local logical_log=$3
    local target_db=$4

    log "Restoring $target_db from $bak_name..."
    docker exec $MSSQL_CONTAINER /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$MSSQL_PASS" -C -Q "
        RESTORE DATABASE $target_db FROM DISK='/backups/$bak_name'
        WITH MOVE '$logical_name' TO '/var/opt/mssql/data/$target_db.mdf',
             MOVE '$logical_log' TO '/var/opt/mssql/data/$target_db.ldf',
             REPLACE, STATS=20;
        ALTER DATABASE $target_db SET RECOVERY SIMPLE WITH NO_WAIT;
        USE $target_db;
        DBCC SHRINKFILE (N'$logical_log', 1) WITH NO_INFOMSGS;
    " || fail "Restore failed for $target_db"
    log "  ✓ $target_db restored"
}

drop_mssql_db() {
    local db=$1
    log "Dropping mssql DB $db..."
    docker exec $MSSQL_CONTAINER /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$MSSQL_PASS" -C -Q "
        ALTER DATABASE $db SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
        DROP DATABASE $db;
    " >/dev/null 2>&1 || warn "DB $db may not exist"
}

# =============================================================================
# PHASE 1: HRM_DAU
# =============================================================================

phase_hrm() {
    log "=== Phase 1: HRM_DAU ==="
    check_disk 2

    local bak=$(ls "$BAK_DIR" 2>/dev/null | grep -E "^HRM_DAU.*\.bak$" | head -1)
    [ -z "$bak" ] && fail "HRM_DAU.bak not in $BAK_DIR (run download_all_baks first)"

    ensure_mssql_running
    restore_bak "$bak" "HRM_ORG2" "HRM_ORG2_log" "HRM_DAU"

    log "Running ETL: master + employees"
    python run.py master
    python run.py employees

    drop_mssql_db "HRM_DAU"
    rm -f "$BAK_DIR/$bak"
    log "✓ Phase 1 complete (deleted $bak)"
}

# =============================================================================
# PHASE 2: EDU_DAU (slim)
# =============================================================================

phase_edu_dau() {
    log "=== Phase 2: EDU_DAU ==="
    check_disk 50

    local bak="EDU_DAU_slim.bak"
    [ ! -f "$BAK_DIR/$bak" ] && fail "$bak not in $BAK_DIR (run preprocess-bak.ps1 on Windows + upload to GDrive)"

    ensure_mssql_running
    restore_bak "$bak" "EDU_ORG2" "EDU_ORG2_log" "EDU_DAU"

    log "Running ETL: academic + students + graduations + enrollments + grades"
    python run.py academic
    python run.py students
    python run.py graduations
    python run.py enrollments
    python run.py grades

    drop_mssql_db "EDU_DAU"
    rm -f "$BAK_DIR/$bak"
    log "✓ Phase 2 complete (deleted $bak, freed ~16GB)"
}

# =============================================================================
# PHASE 3: EDU_DAU_DATA
# =============================================================================

phase_edu_data() {
    log "=== Phase 3: EDU_DAU_DATA ==="
    check_disk 25

    local bak=$(ls "$BAK_DIR" 2>/dev/null | grep -E "^EDU_DAU_DATA.*\.bak$" | head -1)
    [ -z "$bak" ] && fail "EDU_DAU_DATA.bak not in $BAK_DIR"

    ensure_mssql_running
    restore_bak "$bak" "EDU_BTU_DATA" "EDU_BTU_DATA_log" "EDU_DAU_DATA"

    log "Running ETL: files + audit"
    python run.py files
    python run.py audit

    drop_mssql_db "EDU_DAU_DATA"
    rm -f "$BAK_DIR/$bak"
    log "✓ Phase 3 complete (deleted $bak)"
}

# =============================================================================
# CLEANUP + DUMP
# =============================================================================

finalize() {
    log "=== Finalize: stop mssql + dump Postgres ==="
    docker rm -f $MSSQL_CONTAINER 2>/dev/null || true
    rm -rf "$BAK_DIR"

    mkdir -p output
    local stamp=$(date +%Y%m%d_%H%M)
    log "Creating pg_dump.gz..."
    docker exec dau-postgres pg_dump -U dau_admin -Fc dau_university | gzip > "output/dau_${stamp}.dump.gz"

    log "Bundling MinIO blobs..."
    docker run --rm \
        -v "$(docker inspect dau-minio --format '{{(index .Mounts 0).Name}}'):/data" \
        -v "$(pwd)/output:/out" \
        alpine sh -c "cd /data && tar czf /out/minio_${stamp}.tar.gz . 2>/dev/null || echo 'minio archive skipped'"

    log "Generating report (~50KB)..."
    python scripts/dump_summary.py
    python run.py validate
    python run.py status

    ls -lh output/

    auto_commit_report "$stamp"
    auto_upload_gdrive "$stamp"

    log ""
    log "${G}════════════════════════════════════════${N}"
    log "${G} ✓ ETL COMPLETE${N}"
    log "${G}════════════════════════════════════════${N}"
    log "Output local: $(pwd)/output/"
}

# =============================================================================
# Auto-commit report → GitHub
# =============================================================================

auto_commit_report() {
    local stamp=$1
    if [ -z "${GITHUB_PAT:-}" ]; then
        warn "GITHUB_PAT not set in .env — skip auto-commit"
        warn "  Manually: git add etl/output/etl_report_*.md && git commit && git push"
        return 0
    fi

    log "=== Auto-commit report → GitHub ==="

    # Setup git credentials (one-time per session)
    local repo_owner="${GITHUB_REPO%%/*}"
    git config --global user.email "${GIT_USER_EMAIL:-haodp.ai@gmail.com}"
    git config --global user.name "${GIT_USER_NAME:-Phuc Hao Do}"
    git config --global credential.helper store
    echo "https://${repo_owner}:${GITHUB_PAT}@github.com" > ~/.git-credentials
    chmod 600 ~/.git-credentials

    # Find repo root (parent of etl/)
    local repo_root="$(cd .. && pwd)"
    cd "$repo_root"

    # Add light files only
    git add etl/output/etl_report_*.md etl/output/etl_state.json 2>/dev/null || true

    if git diff --cached --quiet; then
        warn "  No changes to commit"
    else
        git commit -m "data: ETL run ${stamp}" \
            -m "Automated commit from VPS after sequential ETL pipeline." \
            >/dev/null 2>&1
        log "  Pushing to GitHub..."
        if git push origin main 2>&1 | tail -3; then
            log "  ${G}✓ Pushed report to GitHub${N}"
        else
            warn "  Push failed — credentials may be invalid. Check GITHUB_PAT in .env"
        fi
    fi

    cd - >/dev/null
}

# =============================================================================
# Auto-upload heavy output → GDrive
# =============================================================================

auto_upload_gdrive() {
    local stamp=$1
    if [ -z "${GDRIVE_OUTPUT_PATH:-}" ]; then
        warn "GDRIVE_OUTPUT_PATH not set in .env — skip auto-upload"
        warn "  Manually: rclone copy output/*.gz ${GDRIVE_OUTPUT_PATH:-gdrive:OUTPUT_FOLDER}/"
        return 0
    fi

    log "=== Auto-upload heavy output → ${GDRIVE_OUTPUT_PATH} ==="

    if ! command -v rclone &>/dev/null; then
        warn "  rclone not installed — skip upload"
        return 0
    fi

    if rclone copy "output/dau_${stamp}.dump.gz" "${GDRIVE_OUTPUT_PATH}/" --progress 2>&1 | tail -3; then
        log "  ${G}✓ Uploaded dau_${stamp}.dump.gz${N}"
    else
        warn "  dump.gz upload failed"
    fi

    if [ -f "output/minio_${stamp}.tar.gz" ]; then
        if rclone copy "output/minio_${stamp}.tar.gz" "${GDRIVE_OUTPUT_PATH}/" --progress 2>&1 | tail -3; then
            log "  ${G}✓ Uploaded minio_${stamp}.tar.gz${N}"
        else
            warn "  minio.tar.gz upload failed"
        fi
    fi
}

# =============================================================================
# Main
# =============================================================================

main() {
    cd "$(dirname "$0")/.."
    [ -f .env ] || fail "Missing .env file. Run: cp .env.example .env"

    # Export .env variables (for GITHUB_PAT, GDRIVE_OUTPUT_PATH, etc.)
    set -a
    source .env
    set +a

    source .venv/bin/activate || fail "Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"

    log "Starting sequential ETL pipeline"
    log "Strategy: gdown all .bak once → process each → drop DB + delete .bak"
    if [ -n "${GITHUB_PAT:-}" ]; then
        log "Auto-commit report:  ${G}ON${N} → ${GITHUB_REPO:-?}"
    else
        log "Auto-commit report:  ${Y}OFF${N} (set GITHUB_PAT in .env)"
    fi
    if [ -n "${GDRIVE_OUTPUT_PATH:-}" ]; then
        log "Auto-upload GDrive:  ${G}ON${N} → ${GDRIVE_OUTPUT_PATH} (cần rclone OAuth)"
    else
        log "Auto-upload GDrive:  ${Y}OFF${N} (output stay on VPS, fetch via SCP)"
    fi
    log ""

    download_all_baks
    phase_hrm
    phase_edu_dau
    phase_edu_data
    finalize
}

main "$@"
