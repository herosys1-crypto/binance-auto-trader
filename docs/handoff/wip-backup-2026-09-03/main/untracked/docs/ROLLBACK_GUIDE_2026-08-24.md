# 🛡️ 롤백 가이드 (2026-08-24 세션)

> **목적**: 실수 방지! 문제 발생 시 안전한 롤백!
> **작성**: 2026-08-24 세션 종료 시점
> **대상**: 사장님 (긴급 상황 대응용)

---

## 📋 오늘 세션 요약

- **배포된 Fix**: 10개 (Fix 47 ~ Fix 61)
- **main HEAD 커밋**: `1c0f141`
- **안정 git tag**: `v-2026-08-24-session-final-fix47-61` ⭐ (오늘 백업!)
- **이전 안정 tag**: `v-2026-08-23-fix32-33-v219-only` (어제 백업!)
- **활성 심볼 (배포 시점)**:
  - SHORT 11건
  - LONG 25건
  - **총 36건**

---

## 🔧 각 Fix별 롤백 방법

### Fix 47 / Fix 50 v2 롤백

**방법 1 = 특정 commit revert (권장!)**
```bash
cd ~/binance-auto-trader
git log --oneline | grep -i "fix 47\|fix 50"
# 해당 commit hash 확인 후:
git revert <commit-hash> --no-edit
git push origin main
docker compose restart api scheduler
```

**방법 2 = 이전 tag checkout (완전 롤백!)**
```bash
# ⚠️ 이후 fix 모두 사라짐! 매우 위험!
git checkout v-2026-08-23-fix32-33-v219-only
```

---

### Fix 51 ~ Fix 55 롤백

각 Fix의 tag가 있다면 개별 revert 가능!

```bash
cd ~/binance-auto-trader

# tag 목록 확인
git tag | grep "fix5"

# 특정 fix commit 찾기
git log --oneline --grep="Fix 51\|Fix 52\|Fix 53\|Fix 54\|Fix 55"

# 개별 revert
git revert <commit-hash> --no-edit
git push origin main
docker compose restart api scheduler
```

---

### Fix 56 ~ Fix 60 롤백 (spec + 오케스트라 워커!)

**spec 파일 롤백**:
```bash
cd ~/binance-auto-trader
git checkout v-2026-08-23-fix32-33-v219-only -- docs/
git commit -m "revert: Fix 56-60 spec 롤백"
git push origin main
```

**오케스트라 워커 disable (즉시 효과!)**:
```sql
-- DB에서 SystemSetting 조작
UPDATE system_settings SET value = '0' WHERE key = 'worker_XXX_enabled';
-- XXX = 해당 워커 이름 (예: pump_top_detector, auto_short_at_top)
```

또는 `scheduler_runner.py`에서 해당 job 주석:
```python
# scheduler.add_job(...)  # Fix XX 워커 비활성!
```
그 후:
```bash
docker compose restart scheduler
```

---

### Fix 61 롤백 (_count_used_slots 원복!)

**파일 위치**:
- `backend/app/workers/auto_short_at_top_worker.py`
- `backend/app/workers/auto_bb_breakdown_worker.py`

**원복 방법**:
```bash
cd ~/binance-auto-trader
git log --oneline -- backend/app/workers/auto_short_at_top_worker.py
# 이전 버전 commit hash 찾기

# 특정 파일만 이전 버전으로!
git checkout <previous-commit> -- backend/app/workers/auto_short_at_top_worker.py
git commit -m "revert: Fix 61 _count_used_slots 원복"
git push origin main
docker compose restart scheduler
```

---

## 🚨 전체 롤백 (최악의 상황!)

⚠️ **매우 위험! 사장님 명시 승인 후만 실행!**

```bash
cd ~/binance-auto-trader

# 1. 현재 상태 백업 (필수!)
git tag v-2026-08-24-BEFORE-ROLLBACK-BACKUP
git push origin v-2026-08-24-BEFORE-ROLLBACK-BACKUP

# 2. DB 백업 (필수!)
docker compose exec db pg_dump -U postgres binance_auto_trader > backup_before_rollback_$(date +%Y%m%d_%H%M%S).sql

# 3. 이전 안정 tag로 체크아웃
git checkout v-2026-08-23-fix32-33-v219-only

# 4. main 브랜치에 force push (⚠️ 매우 위험!)
git branch -f main HEAD
git push origin main --force  # 사장님 승인 필수!

# 5. 컨테이너 재시작
docker compose restart api scheduler

# 6. 활성 심볼 확인
# UI에서 배지/거래 확인!
```

**주의사항**:
- `--force` push = 이후 모든 commit 사라짐! 되돌릴 수 없음!
- DB 마이그레이션이 되돌아가지 않으면 = 코드/DB 스키마 불일치!
- 활성 포지션 = 그대로 유지 (SL/TP만 코드 기준으로 재관리됨)

---

## 💾 DB 백업/복원

### 백업 (즉시 실행 권장!)
```bash
# 백업 파일명에 날짜/시간
docker compose exec db pg_dump -U postgres binance_auto_trader > backup_2026-08-24_$(date +%H%M%S).sql

# 백업 파일 크기 확인
ls -lh backup_*.sql
```

### 복원 (최악 상황!)
```bash
# ⚠️ 기존 데이터 완전 대체!
docker compose exec -T db psql -U postgres binance_auto_trader < backup_2026-08-24.sql

# 복원 후 컨테이너 재시작
docker compose restart api scheduler
```

### 부분 백업 (특정 테이블만!)
```bash
# 활성 거래만
docker compose exec db pg_dump -U postgres -t trades -t strategies binance_auto_trader > backup_trades.sql
```

---

## ⚙️ SystemSetting 백업/복원

### 백업 (파일로!)
```bash
docker compose exec db psql -U postgres -d binance_auto_trader -c "COPY system_settings TO STDOUT WITH CSV HEADER" > system_settings_backup_2026-08-24.csv

# 또는 SQL dump
docker compose exec db pg_dump -U postgres -t system_settings binance_auto_trader > system_settings_2026-08-24.sql
```

### 복원 (파일에서!)
```bash
# CSV 복원
docker compose exec -T db psql -U postgres -d binance_auto_trader -c "TRUNCATE system_settings; COPY system_settings FROM STDIN WITH CSV HEADER" < system_settings_backup_2026-08-24.csv

# SQL 복원
docker compose exec -T db psql -U postgres binance_auto_trader < system_settings_2026-08-24.sql
```

### 주요 SystemSetting 값 (참고용)
```
auto_bb_break_daily_limit = 5          # v219 공유 일일 한도
auto_bb_breakdown_enabled = 0          # Fix 33 DISABLE
unified_entry_enabled = 0              # v224 OFF
pending_hc_fast_enabled = 0            # Fix 32 OFF
success_pyramiding_enabled = 0         # Fix 32 OFF
sajangnim_max_stage = 2                # Fix 31 마틴게일 최대
force_sl_roi_override = 0.15           # 강제 SL -15%
```

---

## 🚨 활성 심볼 = 강제 청산 방법 (긴급 상황!)

### 방법 1 = 사장님 UI 개별 청산 (권장!)
1. 대시보드 접속
2. 활성 심볼 카드에서 「청산」 버튼 클릭
3. 개별 심볼 즉시 청산!

### 방법 2 = 전체 강제 청산 (⚠️ 매우 위험!)
```sql
-- SystemSetting에서 강제 SL을 즉시 발동!
UPDATE system_settings SET value = '0.1' WHERE key = 'force_sl_roi_override';
-- ROI -0.1% = 거의 즉시 SL 발동!
```

**주의**: 이 방법 = 전 심볼 SL 발동! 사장님 승인 필수!

### 방법 3 = 워커 즉시 중단!
```bash
docker compose stop scheduler
# 신규 진입 100% 차단!
# 기존 활성 심볼 = UI에서 개별 청산!
```

---

## 🎼 오케스트라 워커 = 개별 disable 방법

### 방법 1 = SystemSetting (즉시 효과!)
```sql
-- DB 접속
docker compose exec db psql -U postgres -d binance_auto_trader

-- 특정 워커 비활성
UPDATE system_settings SET value = '0' WHERE key = 'worker_pump_top_detector_enabled';
UPDATE system_settings SET value = '0' WHERE key = 'worker_auto_short_at_top_enabled';
```

### 방법 2 = scheduler_runner.py 주석
파일: `backend/app/workers/scheduler_runner.py`

```python
# 해당 job 주석 처리
# scheduler.add_job(
#     pump_top_detector,
#     trigger='interval',
#     minutes=5,
# )
```

그 후:
```bash
docker compose restart scheduler
```

### 활성 워커 목록 (참고!)
- `pump_top_detector` (매 5분) - v219 정점 감지
- `auto_short_at_top` (매 30초) - v219 SHORT 자동 진입
- `auto_add_margin` - 증거금 자동 추가
- `resistance_reversal` - Fix 29 저항 반전 SHORT
- `time_reverse_exit` - Fix 31 시간 기반 청산
- `reconcile_worker` (매 2분) - v133 자동 회복
- `stage_trigger_worker` - 단계별 진입 트리거
- `learning_sync_worker` (매 5분) - 학습 데이터 동기화

---

## 🛡️ 재발 방지 (헌법!)

### 1. 신 Fix 개발 전 = spec 먼저!
- `docs/FIX_XX_SPEC.md` 파일 신설
- 사장님 사상 verbatim 기록
- 검증 조건 명시

### 2. unit test 필수!
- `backend/tests/unit/test_fix_XX.py`
- 최소 3개 케이스: 정상/경계/예외
- CI 통과 확인 후 merge!

### 3. 오케스트라 감시 = 자동!
- v206 orchestra_health worker 활용
- 신 워커 등록 시 = health check 등록!

### 4. 배포 후 즉시 검증!
- git tag = 배포 즉시!
- UI 배지 = 사장님 verbatim 확인!
- 활성 심볼 = 배치 전/후 비교!

### 5. 롤백 태그 필수!
- 배포 전: `v-YYYY-MM-DD-BEFORE-XXX`
- 배포 후: `v-YYYY-MM-DD-AFTER-XXX`
- 최소 7일 tag 보존!

---

## 📞 긴급 연락 체크리스트

문제 발생 시 순서:

1. ✅ **DB 백업 즉시 실행!** (5분 소요)
2. ✅ **활성 심볼 상태 캡처** (스크린샷)
3. ✅ **git tag 백업** (`v-YYYY-MM-DD-BEFORE-ROLLBACK`)
4. ✅ **문제 분석** (log 확인 = `docker compose logs api scheduler | tail -200`)
5. ✅ **최소 영향 롤백 시도** (개별 fix revert 우선!)
6. ⚠️ **최악의 경우** = 전체 롤백 (사장님 승인 후!)
7. ✅ **롤백 후 검증** (활성 심볼 + UI 배지 + 신규 진입 여부)

---

## 📚 관련 문서

- `docs/DEVELOPMENT_PRINCIPLES.md` - 헌법 (개발 원칙)
- `docs/SYSTEM_MASTER_SPEC.md` - 시스템 마스터 spec
- `docs/AUDIT_2026-07-24_CRITICAL_60ISSUES.md` - CRITICAL 감사
- `memory/project_2026-08-22_v219_final_complete.md` - v219 최종 확정
- `memory/project_2026-08-23_fix32_33_v219_only.md` - Fix 32/33 세션

---

**🌟 사장님 안전 = 최우선!**
**언제든 이 가이드 참고 = 안전한 롤백 가능!**
