@echo off
REM ============================================================
REM Home PC sync from office:
REM   1) git pull (code)
REM   2) restore DB from backup file in backend\db_backups\
REM   3) restart containers
REM
REM Usage:
REM   home-pc-sync-from-office.bat <backup-filename>
REM   e.g.  home-pc-sync-from-office.bat office-to-home-2026-04-27-1830.sql.gz
REM ============================================================
setlocal
cd /d "%~dp0"

if "%~1"=="" (
    echo.
    echo ERROR: backup filename required as first arg.
    echo.
    echo Example:
    echo   home-pc-sync-from-office.bat office-to-home-2026-04-27-1830.sql.gz
    echo.
    if exist "backend\db_backups" (
        echo Backup files in backend\db_backups\:
        dir /b backend\db_backups\*.sql.gz 2^>nul
    )
    pause
    exit /b 1
)

set BACKUP_FILE=%~1

echo.
echo ==========================================================
echo  Home PC sync from office
echo ==========================================================
echo.

echo [1/5] git pull origin main
git pull origin main
if errorlevel 1 (
    echo.
    echo ERROR: git pull failed. Resolve conflicts manually:
    echo   git status
    echo   git stash
    echo   git pull origin main
    echo   git stash pop
    pause
    exit /b 1
)
echo.

echo [2/5] Start db + redis containers
cd backend
docker compose up -d db redis
timeout /t 5 /nobreak >nul
cd ..
echo.

echo [3/5] Apply new migrations (if any)
cd backend
docker compose up -d api
timeout /t 5 /nobreak >nul
docker compose exec api alembic upgrade head
cd ..
echo.

echo [4/5] Restore DB from office backup
cd backend
call restore-from-home-backup.bat %BACKUP_FILE%
cd ..
echo.

echo [5/5] Restart all workers
cd backend
docker compose up -d
cd ..
echo.

echo ==========================================================
echo  DONE. Home PC synced to office state.
echo  Dashboard: http://localhost:8000
echo ==========================================================
pause
