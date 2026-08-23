# UNIFIED 15M ENTRY SPEC v224

> **작성일**: 2026-08-23
> **작성자**: 오케스트라 에이전트 (사장님 통합 요구 100% 반영!)
> **헌법**: 70 = 15m 급등/급락 = 유일 진입 유니버스 (사장님 통합!)
> **선행 spec**: v219 (7중 정점) / v222 (다중 시간대) / v223 (15m MAIN gate + 1h/4h 역방향)

---

## 1. 사장님 verbatim (2026-08-23)

> **"지금까지 모든 자동매매는 오늘 15분 차트 급등과 급락한 심볼만 자동매매를 하는걸로 통합해서 운영할수 있게 하나도 통합정리해줘"**

**의미**:
- 진입 소스가 4개 (auto_bb_breakdown / pump_top_detector / auto_short_at_top / pending_hc_fast) → **1개로 통합!**
- 유일 진입 조건 = **오늘 15m 차트 급등 OR 급락한 심볼!**
- 나머지 워커(후속 대응)는 유지 = 실패/성공 사이클 담당!

---

## 2. 신 통합 워커: `unified_15m_entry_worker.py`

| 항목 | 값 | 근거 |
|------|----|----|
| 주기 | **30초** | 사장님 verbatim "실시간 급등급락 대응" |
| 스캔 상한 | 40 심볼 | API Ban 방지 (v196 학습!) |
| Pre-filter | 24h \|변동\| ≥ 3% | 무의미한 잔잔한 심볼 제거 |
| 트리거 A | 15m 4봉(1h) 변동 ≥ **±5%** | `unified_15m_1h_pct` (default 5%) |
| 트리거 B | 15m 12봉(3h) 변동 ≥ **±10%** | `unified_15m_3h_pct` (default 10%) |
| 방향 판정 | 급등→SHORT (정점 반전!) / 급락→LONG (저점 반등!) | 사장님 사상 = 반전 매매 |
| 지표 검사 | v223 = 15m score ≥ 3/5 | RSI+CCI+BB+MACD+OBV |
| 역방향 skip | 1h/4h 반대 score ≥ 3/5 = skip | 큰 그림 존중 |
| 자본 | `compute_stage1_capital` (default 300 USDT) | v219 사장님 신 마틴게일 시작금 |
| 레버리지 | default 2x (profile 우선) | v130 사장님 default |
| suggestion_type | `unified_15m_entry` | `_count_used_slots`에 이미 포함! |
| daily_limit | `auto_bb_break_daily_limit` 공유 | v219 통합 사상 유지! |

---

## 3. 필터 (진입 차단)

1. **활성 심볼 skip** — `_get_active_symbol_keys` (같은 심볼+방향 중복 진입 방지)
2. **최근 48h 손실 skip** — `_get_recent_loss_symbol_keys` (마틴게일은 realtime_reentry_worker 담당!)
3. **학습된 실패 조건 skip** — `_matches_failure_condition` (RSI/CCI + 24h + hour + regime + BTC 방향)
4. **API Ban 시 즉시 skip** — `is_account_banned`
5. **daily_limit 소진 시 skip** — `_count_used_slots >= daily_limit`

---

## 4. 안전 마이그레이션: 기존 워커 disable

`scheduler_runner.py`에서 **4개 워커 주석 처리** (완전 삭제 X = 롤백 가능!):

| 옛 워커 | 옛 주기 | 상태 | 이유 |
|--------|---------|------|------|
| `auto_bb_breakdown` | 1h | ⛔ 주석 | 진입 소스 통합 (BB SUSTAINED 소스 병합) |
| `pump_top_detector` | 5m | ⛔ 주석 | 7중 정점 검사는 `PumpTopDetector.check_v223_15m_primary()`로 호출! |
| `auto_short_at_top` | 30s | ⛔ 주석 | 정점 SHORT 진입 = 통합 워커의 SHORT 분기로 흡수 |
| `pending_hc_fast` | 2m | ⛔ 주석 | PENDING_HC 85%+ 소스 통합 |

**롤백 방법**: 4개 블록 주석 해제 + `SystemSetting unified_entry_enabled=0` 세팅.

---

## 5. 유지되는 후속 대응 워커 (통합 아님!)

진입 후 사이클 관리는 그대로:

| 워커 | 주기 | 역할 |
|------|------|------|
| `realtime_reentry` | 30s | 청산 후 마틴게일 재진입 (300→600→1800 사장님 사상!) |
| `success_pyramiding` | 30s | 익절중 지속 신호 시 원 자본 추가 (v218 사장님!) |
| `auto_add_margin` | 15s | ROI < -30% = 초기금액 증거금 추가 (v220 사장님!) |
| `reentry_alert_watcher` | 2m | OBV+RSI+10% 알람 저장 (학습용) |
| `pump_bb_middle_watcher` | 10m | 급등+BB중단 알람 (사장님 판단용) |
| `stage_trigger` | 15s | 2~N단계 자동 진입 트리거 감시 |

= **진입 = 통합 워커 하나 / 사이클 = 기존 워커 유지!**

---

## 6. 텔레그램 알림

진입 시 자동 발송:

```
🌟 [v224 통합] {symbol} {side} 진입! ({conf}%)
🐻/🐂 15m 급등/급락 통합 자동 진입!
심볼: {symbol} {side}
자본: {base_capital} USDT × {leverage}x
신뢰도: {conf}% (15m={score_15m}/5)
트리거: {matched_window} = {matched_pct}%
24h: {change_24h}%
오늘 {used}/{daily_limit}
```

---

## 7. 학습 데이터 (entry_snapshot)

`StrategySuggestion.strategy_config.entry_snapshot`에 저장:

- `rsi`, `cci` (15m 실측)
- `regime`: "NEUTRAL" (15m 기반이라 판정 X → fail-open)
- `change_24h`, `kst_hour`
- `source`: `"UNIFIED_15M"`
- `confidence`, `score_15m`, `opp_score_1h`, `opp_score_4h`
- `surge_meta`: `{matched_window, matched_pct, change_1h_pct, change_3h_pct}`
- `spec_version`: `"v224"`

= 다음 사이클에 `_matches_failure_condition` 학습 재료!

---

## 8. SystemSetting 스위치

| 키 | Default | 역할 |
|----|---------|------|
| `unified_entry_enabled` | 1 (ON) | 0 = 통합 워커 완전 OFF (긴급 킬 스위치!) |
| `auto_bb_break_daily_limit` | (사장님 세팅!) | 통합 워커도 이 카운터 공유 |
| `unified_15m_1h_pct` | 5.0 | 4봉 트리거 임계 |
| `unified_15m_3h_pct` | 10.0 | 12봉 트리거 임계 |

---

## 9. 헌법 70 (신설)

> **15m 급등/급락 = 유일한 진입 유니버스!**
>
> 모든 자동 진입은 오늘 15m 차트 급등 또는 급락한 심볼에 한한다.
> 큰 그림(1h/4h)이 역방향이면 skip. 지표 3/5 미달이면 skip.
> 후속 사이클(재진입/피라미딩/증거금)은 기존 워커가 담당한다.

---

## 10. 배포 후 검증 체크리스트

1. `docker compose logs scheduler | grep "unified_15m_v224"` → 30초마다 로그
2. `docker compose logs scheduler | grep -E "pump_top_detector|auto_short_at_top|pending_hc_fast|auto_bb_breakdown"` → **0건이어야 정상!**
3. Telegram 알림 → `🌟 [v224 통합]` prefix 진입 알림 수신
4. `StrategySuggestion` 테이블 → `suggestion_type='unified_15m_entry'` 신규 row
5. `_count_used_slots` = 통합 카운터로 daily_limit 소진 확인
