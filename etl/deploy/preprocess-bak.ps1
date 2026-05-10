# preprocess-bak.ps1 — slim EDU_DAU.bak để LDF không pre-allocate 62GB khi restore trên VPS
#
# Run: .\preprocess-bak.ps1
# Output: EDU_DAU_slim.bak (cùng folder với .bak gốc, ~16GB)
# Time: ~15 phút
# Disk peak local: ~100GB tạm thời (Windows VHDX)

$ErrorActionPreference = "Stop"
$BackupDir = (Resolve-Path "$PSScriptRoot\..\..").Path
$BakFile   = Get-ChildItem $BackupDir -Filter "EDU_DAU_backup_*.bak" | Select-Object -First 1
$SlimFile  = Join-Path $BackupDir "EDU_DAU_slim.bak"
$Pwd       = "YourStrong@Pass1"

if (-not $BakFile) {
    Write-Error "Cannot find EDU_DAU_backup_*.bak in $BackupDir"
    exit 1
}

Write-Host "Source .bak: $($BakFile.Name) ($([math]::Round($BakFile.Length/1GB,2)) GB)"
Write-Host "Will produce: EDU_DAU_slim.bak"
Write-Host "Disk free check..."
$Free = (Get-PSDrive C).Free / 1GB
Write-Host ("  Free: {0:N1} GB" -f $Free)
if ($Free -lt 100) {
    Write-Warning "Disk free <100GB. Restore EDU_DAU pre-allocates ~100GB (LDF 62GB + MDF 38GB). Có thể fail giữa chừng."
    $resp = Read-Host "Tiếp tục? (y/N)"
    if ($resp -ne "y") { exit 0 }
}

# Step 1: Start mssql container
Write-Host "`n[1/5] Starting mssql container..."
docker rm -f mssql-prep 2>$null | Out-Null
docker run -d --name mssql-prep `
    -e "ACCEPT_EULA=Y" -e "MSSQL_SA_PASSWORD=$Pwd" `
    -p 1433:1433 `
    -v "${BackupDir}:/backups" `
    mcr.microsoft.com/mssql/server:2022-latest | Out-Null
Start-Sleep -Seconds 20
docker ps --filter name=mssql-prep --format "{{.Status}}"

# Step 2: Restore EDU_DAU
Write-Host "`n[2/5] Restoring EDU_DAU (~10 minutes, peak ~100GB disk)..."
$BakInContainer = "/backups/$($BakFile.Name)"
docker exec mssql-prep /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P $Pwd -C -Q @"
RESTORE DATABASE EDU_DAU FROM DISK='$BakInContainer'
WITH MOVE 'EDU_ORG2' TO '/var/opt/mssql/data/EDU_DAU.mdf',
     MOVE 'EDU_ORG2_log' TO '/var/opt/mssql/data/EDU_DAU.ldf',
     REPLACE, STATS=20
"@
if ($LASTEXITCODE -ne 0) { Write-Error "Restore failed"; exit 1 }

# Step 3: Shrink LDF
Write-Host "`n[3/5] Shrinking LDF (62GB → 1MB)..."
docker exec mssql-prep /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P $Pwd -C -Q @"
ALTER DATABASE EDU_DAU SET RECOVERY SIMPLE WITH NO_WAIT;
USE EDU_DAU;
DBCC SHRINKFILE (N'EDU_ORG2_log', 1) WITH NO_INFOMSGS;
SELECT name, size*8/1024 AS size_mb FROM sys.database_files;
"@

# Step 4: Backup to slim file
Write-Host "`n[4/5] Creating EDU_DAU_slim.bak (~16GB)..."
docker exec mssql-prep /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P $Pwd -C -Q @"
BACKUP DATABASE EDU_DAU TO DISK='/backups/EDU_DAU_slim.bak'
WITH FORMAT, COMPRESSION, INIT, STATS=20
"@
if ($LASTEXITCODE -ne 0) { Write-Error "Backup failed"; exit 1 }

# Step 5: Cleanup container + volume
Write-Host "`n[5/5] Cleanup..."
docker stop mssql-prep | Out-Null
docker rm mssql-prep | Out-Null

# Verify slim file
$SlimInfo = Get-Item $SlimFile -ErrorAction SilentlyContinue
if ($SlimInfo) {
    Write-Host "`n✓ EDU_DAU_slim.bak created: $([math]::Round($SlimInfo.Length/1GB, 2)) GB" -ForegroundColor Green
    Write-Host "Path: $SlimFile"
} else {
    Write-Error "EDU_DAU_slim.bak NOT found!"
    exit 1
}

Write-Host "`nNext steps:"
Write-Host "  1. Upload these 3 files to Google Drive folder 'dau-uni-backup':"
Write-Host "     - HRM_DAU_backup_*.bak (21MB)"
Write-Host "     - EDU_DAU_slim.bak (~16GB) ← thay file gốc"
Write-Host "     - EDU_DAU_DATA_backup_*.bak (5.7GB)"
Write-Host "  2. SSH vào VPS, follow DEPLOY.md Phase 2+"
Write-Host ""
Write-Host "To free local disk now: shutdown WSL + delete docker_data.vhdx"
Write-Host '  wsl --shutdown'
Write-Host '  Remove-Item "C:\Users\$env:USERNAME\AppData\Local\Docker\wsl\disk\docker_data.vhdx" -Force'
