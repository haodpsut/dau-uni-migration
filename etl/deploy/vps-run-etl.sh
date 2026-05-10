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
GDRIVE_REMOTE="${GDRIVE_REMOTE:-gdrive:dau-uni-backup}"
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

    local bak=$(rclone ls "$GDRIVE_REMOTE" | awk '/HRM_DAU.*bak$/ {print $2; exit}')
    [ -z "$bak" ] && fail "HRM_DAU.bak not found in $GDRIVE_REMOTE"
    log "Downloading $bak..."
    rclone copy "$GDRIVE_REMOTE/$bak" "$BAK_DIR/" --progress

    ensure_mssql_running
    restore_bak "$bak" "HRM_ORG2" "HRM_ORG2_log" "HRM_DAU"

    log "Running ETL: master + employees"
    python run.py master
    python run.py employees

    drop_mssql_db "HRM_DAU"
    rm -f "$BAK_DIR/$bak"
    log "✓ Phase 1 complete"
}

# =============================================================================
# PHASE 2: EDU_DAU (slim)
# =============================================================================

phase_edu_dau() {
    log "=== Phase 2: EDU_DAU ==="
    check_disk 60

    local bak="EDU_DAU_slim.bak"
    if ! rclone ls "$GDRIVE_REMOTE" | grep -q "$bak"; then
        fail "$bak not found in $GDRIVE_REMOTE — run preprocess-bak.ps1 first on Windows"
    fi
    log "Downloading $bak (~16GB)..."
    rclone copy "$GDRIVE_REMOTE/$bak" "$BAK_DIR/" --progress

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
    log "✓ Phase 2 complete"
}

# =============================================================================
# PHASE 3: EDU_DAU_DATA
# =============================================================================

phase_edu_data() {
    log "=== Phase 3: EDU_DAU_DATA ==="
    check_disk 30

    local bak=$(rclone ls "$GDRIVE_REMOTE" | awk '/EDU_DAU_DATA.*bak$/ {print $2; exit}')
    [ -z "$bak" ] && fail "EDU_DAU_DATA.bak not found"
    log "Downloading $bak (~5.7GB)..."
    rclone copy "$GDRIVE_REMOTE/$bak" "$BAK_DIR/" --progress

    ensure_mssql_running
    restore_bak "$bak" "EDU_BTU_DATA" "EDU_BTU_DATA_log" "EDU_DAU_DATA"

    log "Running ETL: files + audit"
    python run.py files
    python run.py audit

    drop_mssql_db "EDU_DAU_DATA"
    rm -f "$BAK_DIR/$bak"
    log "✓ Phase 3 complete"
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
    ls -lh output/

    log "Generating Markdown summary report (~50KB, push GitHub easily)..."
    python scripts/dump_summary.py

    log "Running validate..."
    python run.py validate

    log "Running status..."
    python run.py status

    log ""
    log "${G}════════════════════════════════════════${N}"
    log "${G} ✓ ETL COMPLETE${N}"
    log "${G}════════════════════════════════════════${N}"
    log "Output: output/dau_${stamp}.dump.gz"
    log "Next: git add + commit + push (with LFS)"
}

# =============================================================================
# Main
# =============================================================================

main() {
    cd "$(dirname "$0")/.."
    [ -f .env ] || fail "Missing .env file. Run: cp .env.example .env"
    source .venv/bin/activate || fail "Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"

    log "Starting sequential ETL pipeline"
    log "Strategy: process each .bak → ETL → drop → next"
    log ""

    phase_hrm
    phase_edu_dau
    phase_edu_data
    finalize
}

main "$@"
