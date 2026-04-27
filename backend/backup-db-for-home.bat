@echo off
REM ============================================================
REM Office testnet DB backup for home PC.
REM gzip-safe (uses docker compose cp, not PowerShell redirect).
REM ============================================================
setlocal
cd /d "%~dp0"

REM Build timestamp via PowerShell (wmic-free)
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd-HHmm"') do set TIMESTAMP=%%i
set BACKUP_NAME=office-to-home-%TIMESTAMP%.sql.gz

if not exist db_backups (
    mkdir db_backups
)

echo.
echo ==========================================================
echo  Office -^> Home DB backup
echo  Output: db_backups\%BACKUP_NAME%
echo ==========================================================
echo.

echo [1/3] pg_dump + gzip inside db container...
docker compose exec db sh -c "pg_dump -U postgres binance_auto_trader | gzip > /tmp/backup.sql.gz"
if errorlevel 1 (
    echo ERROR: pg_dump failed. db container may be down.
    pause
    exit /b 1
)

echo [2/3] docker cp container -^> host (binary safe)...
docker compose cp db:/tmp/backup.sql.gz "db_backups\%BACKUP_NAME%"
if errorlevel 1 (
    echo ERROR: cp failed.
    pause
    exit /b 1
)

echo [3/3] cleanup temp file in container...
docker compose exec db rm -f /tmp/backup.sql.gz

echo.
echo --- file verification (first 4 bytes should be 1F 8B 08 00) ---
powershell -NoProfile -Command "$b = [System.IO.File]::ReadAllBytes('db_backups\%BACKUP_NAME%'); 'first 4 bytes: {0:X2} {1:X2} {2:X2} {3:X2}    file size: ' + $b.Length -f $b[0], $b[1], $b[2], $b[3]"

echo.
echo ==========================================================
echo  DONE. Move this file to home PC (USB / cloud):
echo    db_backups\%BACKUP_NAME%
echo.
echo  At home PC run:
echo    home-pc-sync-from-office.bat %BACKUP_NAME%
echo ==========================================================
pause
