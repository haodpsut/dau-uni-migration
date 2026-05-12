#!/bin/bash
# reset-and-run.sh — DESTRUCTIVE full reset + ETL pipeline (one-shot)
#
# What it does:
#   1. Drop mssql temp DBs (HRM_DAU, EDU_DAU, EDU_DAU_DATA) — preserves container + .bak
#   2. DROP all Postgres schemas (clean slate)
#   3. Apply target_schema + permissive patches (python run.py setup)
#   4. Run full ETL pipeline (vps-run-etl.sh: Phase 1 HRM → 2 EDU → 3 EDU_DATA)
#
# Output: ALL logged to logs/reset-and-run-YYYYMMDD_HHMMSS.log
# Exit code: 0 = success, non-zero = failure (check log)
#
# Usage: cd /opt/dau-uni/etl && ./deploy/reset-and-run.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ETL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$ETL_DIR/logs"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/reset-and-run-${TIMESTAMP}.log"

mkdir -p "$LOG_DIR"

# Mirror ALL stdout + stderr to log file
exec > >(tee -a "$LOG_FILE") 2>&1

G='\033[0;32m'
R='\033[0;31m'
Y='\033[0;33m'
N='\033[0m'

log()  { echo -e "${G}[$(date +%H:%M:%S)]${N} $*"; }
warn() { echo -e "${Y}[$(date +%H:%M:%S)]${N} $*"; }
fail() { echo -e "${R}[$(date +%H:%M:%S)] FAIL:${N} $*"; echo ""; echo "Log: $LOG_FILE"; exit 1; }

cd "$ETL_DIR"

echo ""
log "============================================================"
log " DAU University Migration — Full Reset + ETL"
log "============================================================"
log " Start    : $(date)"
log " Log file : $LOG_FILE"
log " ETL dir  : $ETL_DIR"
log "============================================================"
echo ""

# Verify environment
[ -f .env ] || fail "Missing .env file. cp .env.example .env then edit."
[ -d .venv ] || fail "Missing .venv. Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"

# Verify Docker stack
docker ps --filter "name=dau-postgres" --filter "status=running" -q | grep -q . \
    || fail "dau-postgres not running. Run: docker compose up -d"

# ───────────────────────────────────────────────────────────────
log "Step 1/4: Drop mssql temp databases (preserve container + .bak)"
# ───────────────────────────────────────────────────────────────
if docker ps --filter "name=mssql-temp" --filter "status=running" -q | grep -q .; then
    for db in HRM_DAU EDU_DAU EDU_DAU_DATA; do
        docker exec mssql-temp /opt/mssql-tools18/bin/sqlcmd \
            -S localhost -U sa -P "YourStrong@Pass1" -C -Q "
            IF EXISTS (SELECT * FROM sys.databases WHERE name='$db') BEGIN
                ALTER DATABASE [$db] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
                DROP DATABASE [$db];
            END" >/dev/null 2>&1 || true
        log "  ✓ Dropped mssql.$db (if existed)"
    done
else
    warn "  mssql-temp not running — will be auto-started by Phase 1"
fi

# ───────────────────────────────────────────────────────────────
log "Step 2/4: Drop ALL Postgres schemas (clean slate)"
# ───────────────────────────────────────────────────────────────
docker exec -i dau-postgres psql -U dau_admin -d dau_university >/dev/null 2>&1 <<'SQL' || fail "Drop schemas failed"
DROP SCHEMA IF EXISTS identity CASCADE;
DROP SCHEMA IF EXISTS master CASCADE;
DROP SCHEMA IF EXISTS hr CASCADE;
DROP SCHEMA IF EXISTS academic CASCADE;
DROP SCHEMA IF EXISTS student CASCADE;
DROP SCHEMA IF EXISTS files CASCADE;
DROP SCHEMA IF EXISTS audit CASCADE;
SQL
log "  ✓ All 7 schemas dropped"

# ───────────────────────────────────────────────────────────────
log "Step 3/4: Apply target_schema + permissive patches"
# ───────────────────────────────────────────────────────────────
source "$ETL_DIR/.venv/bin/activate"
python run.py setup || fail "Setup failed"

# Sanity check: FK around identity.users dropped
FK_COUNT=$(docker exec dau-postgres psql -U dau_admin -d dau_university -t -c \
    "SELECT COUNT(*) FROM pg_constraint WHERE confrelid='identity.users'::regclass AND contype='f';" | tr -d ' ')
[ "$FK_COUNT" = "0" ] || warn "  WARNING: $FK_COUNT FKs still reference identity.users (cascade may explode)"

# ───────────────────────────────────────────────────────────────
log "Step 4/4: Run full ETL pipeline (Phase 1+2+3)"
# ───────────────────────────────────────────────────────────────
chmod +x "$SCRIPT_DIR/vps-run-etl.sh"
"$SCRIPT_DIR/vps-run-etl.sh"

# Done
echo ""
log "============================================================"
log " ✓ ALL DONE"
log " End  : $(date)"
log " Log  : $LOG_FILE"
log "============================================================"

# Quick summary
echo ""
log "Row counts:"
docker exec dau-postgres psql -U dau_admin -d dau_university -c "
SELECT n.nspname AS schema, c.relname AS table, c.reltuples::BIGINT AS est_rows
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind='r' AND n.nspname IN ('master','hr','academic','student','files','audit','identity')
ORDER BY n.nspname, c.relname;
" 2>&1 | tail -50
