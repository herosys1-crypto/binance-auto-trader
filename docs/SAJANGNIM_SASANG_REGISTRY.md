# 사장님 사상 등록 시스템 (SASANG REGISTRY)

> **Fix 60**: 모든 사장님 verbatim = 즉시 등록! 각 사상 → 구현 파일 + 검증 함수 매핑!

---

## 목적

- 모든 사장님 verbatim = 즉시 등록!
- 각 사상 = 구현 파일 매핑!
- 각 사상 = 검증 함수 매핑!
- 자동 감지 = `spec_audit_worker` (매일 실행!)
- 미구현 사상 = 상태 `⏳` = 다음 fix 우선순위!

---

## 헌법 근거

- **헌법 2**: 사장님 사상 우선 (silent bug 금지!)
- **헌법 17**: critical 발견 시 = 즉시 spec 갱신!
- **헌법 69/70/71**: 사장님 요구 = 즉시 메모리 저장!
- **Fix 60**: 사장님 verbatim = 즉시 SASANG-XXX 등록!

---

## 사장님 사상 표 (SASANG TABLE)

| ID | 사장님 verbatim | 구현 파일 | 검증 함수 | 상태 |
|---|---|---|---|---|
| SASANG-001 | "OBV 절대 우선 - MACD보다 먼저 봐라" (2026-08-24) | `backend/app/workers/auto_long_at_bottom_worker.py` | `_check_obv_uptrend` | ✅ |
| SASANG-002 | "마틴게일 3단계까지 갈수 있다야 가능하면 가지않는 관리가 필요" (v219) | `backend/app/workers/realtime_reentry_worker.py` | `MAX_REENTRY_STAGE = 3` | ✅ |
| SASANG-003 | "짧은 손절후 적당히 시점에 다시 마틴게일 전략으로 진입" (Fix 40) | `backend/app/workers/realtime_reentry_worker.py` | `_apply_smart_reentry` | ✅ |
| SASANG-004 | "TP1 -5% 회귀 시 즉시 청산" (Fix 31) | `backend/app/services/trailing_stop_service.py` | `_check_tp1_retrace` | ✅ |
| SASANG-005 | "4h 청산 + 반대 신뢰도 SHORT 진입" (Fix 31) | `backend/app/workers/reverse_confidence_worker.py` | `check_4h_reverse_signal` | ✅ |
| SASANG-006 | "마틴게일 300 / 600 / 1800 USDT" (v219) | `backend/app/core/risk_constants.py` | `MARTINGALE_STAGES` | ✅ |
| SASANG-007 | "3단계까지 최대, 4단계+ 금지" (v219) | `backend/app/workers/realtime_reentry_worker.py` | `_calc_martingale_capital` (None 반환) | ✅ |
| SASANG-008 | "라스트 챈스 - 마지막 반등 시점 진입" (Fix 53) | `backend/app/workers/last_chance_worker.py` | `detect_last_chance_signal` | ✅ |
| SASANG-009 | "급등 반대매매 금지 - 물타기 폭발 방지" (헌법 64) | `backend/app/workers/auto_bb_breakdown_worker.py` | `_check_24h_surge_filter` | ✅ |
| SASANG-010 | "세력이 그림을 그리는거라 정의하고 싶어" (Fix 45) | `backend/app/workers/seryeok_pattern_worker.py` | `detect_consolidation_pattern` | ⏳ |
| SASANG-011 | "심리선 3번 조정 후 진입" (Fix 46) | `backend/app/services/chart_analyzer.py` | `_check_third_correction` | ⏳ |
| SASANG-012 | "LONG 시스템도 v219 SHORT처럼 대칭 구조" (Fix 47) | `backend/app/workers/auto_long_at_bottom_worker.py` | `_check_7_bottom_signals` | ✅ |
| SASANG-013 | "LONG 2 패턴 - 급락 + OBV 재매집" (Fix 50 v2) | `backend/app/workers/auto_long_at_bottom_worker.py` | `_check_dump_and_obv_recovery` | ✅ |
| SASANG-014 | "SHORT SL -5% 통일" (Fix 51) | `backend/app/core/risk_constants.py` | `SHORT_SL_PCT = -5.0` | ✅ |
| SASANG-015 | "3 워커 SL -5% 통일" (Fix 52) | `backend/app/workers/{auto_short_at_top,pump_top_detector,resistance_reversal}_worker.py` | `_apply_sl_pct` | ✅ |
| SASANG-016 | "daily_limit SHORT+LONG 통합 카운트" (2026-08-24) | `backend/app/workers/scheduler_runner.py` | `_count_used_slots` (통합!) | ✅ |
| SASANG-017 | "마틴게일 계단식 - 1.5x → 2.25x → 3.375x" (Fix 55) | `backend/app/services/reentry_service.py` | `_stair_martingale_multiplier` | ✅ |
| SASANG-018 | "진입 조건 상향 - 7중 정점 → 6/7 이상만" (2026-08-24) | `backend/app/workers/pump_top_detector_worker.py` | `MIN_TOP_SIGNALS = 6` | ✅ |
| SASANG-019 | "손실 심볼 7일 blocklist" (Fix 54 P1) | `backend/app/workers/symbol_blocklist_worker.py` | `add_to_blocklist_7days` | ⏳ |
| SASANG-020 | "사장님 verbatim = 즉시 SASANG-XXX 등록!" (Fix 60) | `docs/SAJANGNIM_SASANG_REGISTRY.md` | `spec_audit_worker._verify_sasang_registry` | ✅ |
| SASANG-021 | "급락 종목만 LONG 진입" (Fix 50 v2) | `backend/app/workers/auto_long_at_bottom_worker.py` | `_check_24h_dump_filter` | ✅ |
| SASANG-022 | "이렇게 급등락하는건 세력이 그림을 그리는거" (Fix 45) | `backend/app/services/seryeok_recognizer.py` | `recognize_pattern` | ⏳ |
| SASANG-023 | "다음 단계 남으면 SL 발동 X" (v130) | `backend/app/services/stage_calculator.py` | `_check_next_stage_available` | ✅ |
| SASANG-024 | "TP1 옵션 - 실시간 변경 = confirm 모달 X" (6-08) | `backend/app/static/index.html` | `updateStrategyRealtime` | ✅ |
| SASANG-025 | "capital = margin, qty = capital × leverage" (v107) | `backend/app/services/strategy_service.py` | `_calc_quantity` | ✅ |

---

## 등록 규칙 (RULES)

### 1. 신규 사장님 verbatim 발견 시:
- **즉시 SASANG-XXX ID 신설!** (다음 번호 = 26)
- **verbatim 원문 그대로 기록!** (요약 X, 각색 X!)
- **날짜 필수 기록!** (예: `2026-08-24`)
- **spec 문서에도 동기화!** (`docs/SAJANGNIM_*_SPEC.md`)

### 2. 매핑 필수 (구현 X + 검증 X = 반려!):
- **구현 파일**: 절대 경로! (예: `backend/app/workers/xxx_worker.py`)
- **검증 함수**: 실제 함수명! (예: `_check_obv_uptrend`)
- **미구현 = 상태 `⏳`** = 다음 fix 우선순위 자동 배정!

### 3. 상태 정의:
- ✅ = 구현 + 검증 완료
- 🔄 = 구현 완료, 검증 pending
- ⏳ = 미구현 (다음 fix 대상!)
- 🚨 = 구현 있으나 사고 발생 (즉시 fix!)
- ❌ = 폐기 (히스토리 보존)

### 4. 자동 검증 (`spec_audit_worker`):
- **매일 03:00 KST 실행!**
- `_verify_sasang_registry()`:
  - 구현 파일 존재 확인
  - 검증 함수 존재 확인 (grep!)
  - 상태 자동 갱신 (파일 삭제 시 `🚨`!)
  - 텔레그램 알림 (미구현 개수!)

### 5. 사장님 검토:
- **주 1회 사장님 verbatim 통과 확인!**
- **미구현 우선순위 = 사장님 결정!**
- **폐기 사상 = 사장님 명시 승인!**

---

## 우선순위 (다음 fix 대상)

### ⏳ 미구현 사상 (4건):
1. **SASANG-010 세력 그림 인식** (Fix 45) → `seryeok_pattern_worker.py` 신설!
2. **SASANG-011 심리선 3번 조정** (Fix 46) → `chart_analyzer._check_third_correction` 추가!
3. **SASANG-019 손실 심볼 7일 blocklist** (Fix 54 P1) → `symbol_blocklist_worker.py` 신설!
4. **SASANG-022 세력 그림 인식 서비스** (Fix 45) → `seryeok_recognizer.py` 신설!

### 관련 spec 문서:
- `docs/SAJANGNIM_TRADING_PHILOSOPHY_v219.md` (6대 사상!)
- `docs/SAJANGNIM_PROVEN_STRATEGY_v219.md` (실 성공!)
- `docs/DEVELOPMENT_PRINCIPLES.md` (헌법 ⭐)
- `docs/SYSTEM_MASTER_SPEC.md` (마스터 통합!)

---

## 변경 이력 (CHANGELOG)

| 날짜 | 버전 | 변경 |
|---|---|---|
| 2026-08-24 | v1.0 | Fix 60 = 사장님 사상 등록 시스템 신설! (25개 사상 등록!) |

---

## 참고

- **헌법 원문**: `docs/DEVELOPMENT_PRINCIPLES.md`
- **자동 검증 워커**: `backend/app/workers/spec_audit_worker.py` (v48!)
- **텔레그램 알림**: `SasangRegistryAudit` 채널
- **다음 세션 우선순위**: 미구현 4건 즉시 구현!
