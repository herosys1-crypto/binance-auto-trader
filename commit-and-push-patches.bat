@echo off
REM ============================================================
REM Commit and push 6 patches found during testnet validation.
REM Commit #1 (Bug #2) was already done in sandbox.
REM This script handles the remaining 4 commits + push.
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo ==========================================================
echo  binance-auto-trader - commit/push validation patches
echo ==========================================================
echo.

REM --- Clean stuck lock files ---
if exist ".git\index.lock"  del /f ".git\index.lock"
if exist ".git\HEAD.lock"   del /f ".git\HEAD.lock"
if exist ".git\objects\maintenance.lock" del /f ".git\objects\maintenance.lock"
echo [0/6] Lock files cleaned.
echo.

REM --- Line ending policy ---
git config --local core.autocrlf false
git config --local core.eol lf
echo [1/6] Line-ending policy fixed.
echo.

REM --- Index recovery if corrupt ---
git status >nul 2>&1
if errorlevel 1 (
    echo Recovering corrupted index...
    if exist ".git\index" del /f ".git\index"
    git reset
)
echo [2/6] Index OK.
echo.

echo [3/6] Commit 1: Bug #5 reconcile_worker PENDING self-recovery
git add backend/app/workers/reconcile_worker.py
git commit -m "fix(reconcile): self-heal stuck STAGE*_OPEN_PENDING strategies (Bug #5)" -m "user-stream worker that dies before processing ORDER_TRADE_UPDATE leaves strategy stuck in *_PENDING. reconcile WHERE clause only handled *_OPEN, leaving no recovery path." -m "- Add *_PENDING to WHERE clause" -m "- Auto-transition PENDING -> OPEN when exchange has matching position" -m "- Log RECONCILE_RECOVERED_PENDING risk_event for audit"
if errorlevel 1 echo WARNING: commit 1 had issues.
echo.

echo [4/6] Commit 2: Bug #6 SHORT TP/SL never triggered
git add backend/app/services/tp_sl_orchestrator.py
git commit -m "fix(tp_sl): handle SHORT positions correctly (Bug #6 critical)" -m "SHORT current_position_qty is stored as negative. Guard `qty <= 0` returned True for ALL SHORT strategies, exiting orchestrator immediately. With all 38 templates being SHORT, automatic TP/SL never worked." -m "- run_for_strategy: check abs(qty) == 0" -m "- _execute_take_profit: abs() current_qty"
if errorlevel 1 echo WARNING: commit 2 had issues.
echo.

echo [5/6] Commit 3: Bug #7 latest_by_strategy missing LIMIT
git add backend/app/repositories/position_repository.py
git commit -m "fix(position_repo): add LIMIT 1 to latest_by_strategy (Bug #7)" -m "reconcile inserts a new Position row each cycle, accumulating multiple snapshots per strategy. scalar_one_or_none() raises when there are 2+ rows, breaking evaluate_take_profit_level entirely." -m "- .limit(1) + .scalars().first()"
if errorlevel 1 echo WARNING: commit 3 had issues.
echo.

echo [6/6] Commit 4: validation artifacts (test plan + helper scripts)
git add backend/LOGIC-VALIDATION-TEST-PLAN.md backend/cleanup_testnet_strategies.py backend/force_close_orphaned_positions.py backend/restore-from-home-backup.bat backend/backup-db-for-home.bat
git add DEV-WORKFLOW.md home-pc-sync-from-office.bat 2>nul
git commit -m "test+tools: testnet validation plan + cleanup helper scripts" -m "Today's testnet validation found 7 critical bugs and fixed 6. Adding regression docs + ops tools." -m "- LOGIC-VALIDATION-TEST-PLAN.md: 13 checkpoints" -m "- DEV-WORKFLOW.md: two-PC dev workflow + emergency response" -m "- cleanup_testnet_strategies.py: bulk-stop active strategies" -m "- force_close_orphaned_positions.py: force-close orphaned exchange positions" -m "- restore-from-home-backup.bat / backup-db-for-home.bat / home-pc-sync-from-office.bat: PC-to-PC sync"
if errorlevel 1 echo WARNING: commit 4 had issues.
echo.

echo ==========================================================
echo  All commits done. git log:
echo ==========================================================
git log --oneline -7
echo.
echo Pushing to GitHub...
git push origin main
if errorlevel 1 (
    echo.
    echo ERROR: push failed. May need GitHub Personal Access Token.
    echo  https://github.com/settings/tokens
    echo  scope: repo
    echo  Use the token as password when prompted.
    pause
    exit /b 1
)
echo.
echo ==========================================================
echo  DONE. Office patches pushed to GitHub.
echo  At home PC: git pull origin main
echo ==========================================================
pause
