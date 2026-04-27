@echo off
REM ============================================================
REM binance-auto-trader - Restore DB from home PC backup
REM
REM Usage:
REM   1) Copy the home PC's backup file to:
REM      C:\Users\user\binance\binance-auto-trader\backend\db_backups\
REM      (e.g. binance_auto_trader-20260427-XXXXXX.sql.gz)
REM   2) Run this script as:
REM      restore-from-home-backup.bat <backup-filename>
REM
REM      Example:
REM      restore-from-home-backup.bat binance_auto_trader-20260427-031500.sql.gz
REM
REM What this script does:
REM   1) Stops api/scheduler/user-stream (so they don't write to DB)
REM   2) Drops the empty DB and recreates it
REM   3) Copies the backup file into the db container
REM   4) Restores it into postgres
REM   5) Restarts all services
REM
REM PREREQUISITE:
REM   .env's ENCRYPTION_KEY MUST match home PC's value before running this!
REM ============================================================

setlocal
cd /d "%~dp0"

if "%~1"=="" (
    echo.
    echo ERROR: backup filename is required.
    echo.
    echo Usage:
    echo   restore-from-home-backup.bat ^<backup-filename^>
    echo.
    echo Available backups in db_backups\:
    if exist "db_backups" dir /b "db_backups\*.sql.gz" 2^>nul
    if exist "db_backups\last" dir /b "db_backups\last\*.sql.gz" 2^>nul
    echo.
    pause
    exit /b 1
)

set BACKUP_FILE=%~1

REM --- find the actual file ---
if exist "db_backups\%BACKUP_FILE%" (
    set BACKUP_PATH=db_backups\%BACKUP_FILE%
) else if exist "db_backups\last\%BACKUP_FILE%" (
    set BACKUP_PATH=db_backups\last\%BACKUP_FILE%
) else if exist "%BACKUP_FILE%" (
    set BACKUP_PATH=%BACKUP_FILE%
) else (
    echo ERROR: backup file not found: %BACKUP_FILE%
    echo Looked in:
    echo   db_backups\
    echo   db_backups\last\
    echo   current dir
    pause
    exit /b 1
)

echo.
echo ==========================================================
echo  Restore from: %BACKUP_PATH%
echo ==========================================================
echo.
echo  IMPORTANT: this will WIPE the current database
echo  (which is empty anyway, but confirm if unsure).
echo.
set /p CONFIRM="Type YES to proceed: "
if /i not "%CONFIRM%"=="YES" (
    echo Aborted.
    pause
    exit /b 0
)

echo.
echo [1/6] Stopping app services...
docker compose stop api scheduler user-stream
if errorlevel 1 (
    echo WARNING: stop returned an error. Continuing anyway.
)
echo.

echo [2/6] Dropping and recreating database...
docker compose exec -T db psql -U postgres -c "DROP DATABASE IF EXISTS binance_auto_trader;"
docker compose exec -T db psql -U postgres -c "CREATE DATABASE binance_auto_trader;"
if errorlevel 1 (
    echo ERROR: could not drop/create database.
    pause
    exit /b 1
)
echo.

echo [3/6] Copying backup file into db container...
docker compose cp "%BACKUP_PATH%" db:/tmp/backup.sql.gz
if errorlevel 1 (
    echo ERROR: could not copy backup into container.
    pause
    exit /b 1
)
echo.

echo [4/6] Restoring backup (this can take a while)...
docker compose exec -T db sh -c "gunzip -c /tmp/backup.sql.gz | psql -U postgres -d binance_auto_trader"
if errorlevel 1 (
    echo ERROR: restore failed. Check the file is a valid pg_dump gzip.
    pause
    exit /b 1
)
echo.

echo [5/6] Cleaning up tmp file in container...
docker compose exec -T db rm -f /tmp/backup.sql.gz
echo.

echo [6/6] Restarting app services...
docker compose start api scheduler user-stream
echo.
echo Waiting 15 seconds for services to settle...
timeout /t 15 /nobreak >nul
echo.

echo --- container status ---
docker compose ps
echo.
echo --- user-stream logs (last 20 lines) ---
docker compose logs --tail=20 user-stream
echo.

echo ==========================================================
echo  RESTORE DONE.
echo
echo  Verify above:
echo    * user-stream STATUS = Up (not Restarting)
echo    * No 'No active Binance exchange account found' errors
echo    * No 'InvalidToken' / 'Fernet' decryption errors
echo
echo  If you see decryption errors, ENCRYPTION_KEY in .env
echo  does NOT match the home PC's. Fix it and re-run:
echo      docker compose restart api scheduler user-stream
echo ==========================================================
pause
