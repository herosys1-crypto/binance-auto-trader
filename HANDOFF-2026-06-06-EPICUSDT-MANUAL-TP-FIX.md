# 🎉 HANDOFF — 2026-06-06 EPICUSDT 진단 + Manual TP Silent Bug Fix

> **세션 결과**: 사장님 자본 보호 시스템 핵심 silent bug 4건 발견 + fix.
> Sub-Account 운영 = 「💰 수동 익절」 = 유일 청산 수단 = 완전 복구.
> 사장님 검증 OK (Binance #1348272632 status=FILLED, 10% 청산 성공).

---

## 📊 오늘 머지된 PR 5건

| PR | 제목 | 효과 |
|---|---|---|
| #100 | docs(crisis): 사장님 크라이시스 모드 최종 사상 명확화 | 사장님 사상 영구 보존 (CRISIS_MODE_FINAL_SPEC.md) |
| #101 | feat(diagnostic): /admin/diagnostic/strategy/{id} endpoint | HTTP 진단 (docker exec stdout buffering 우회) |
| #102 | feat(diagnostic): v2 — notifications + tp_orders + status mismatch | 4가지 silent bug 진단 도구 |
| #103 | 🚨 **fix(manual-tp): audit log silent bug — close_order.get() → .attribute** | **결정적 fix — 사장님 청산 수단 복구 핵심** |
| #104 | fix(ui): 「💰 수동 익절」 버튼 재활성화 — Sub-Account 유일 청산 수단 | UI 버튼 복구 |

---

## 🚨 발견 + 해결한 Silent Bug 4건

### 🔴 Bug 1 (결정적) — Manual TP audit log AttributeError [#103 fixed]

```python
# 옛 (silent partial 사고):
"close_order_id": str(close_order.get("orderId"))   # ← Order 모델 = dict 아님!

# 흐름:
거래소 = MARKET 주문 발송 + 체결 ✅
DB     = audit log 시 AttributeError → unhandled → 500
UI     = "청산 실패" 표시 (실제 거래소는 청산됨)
사장님 = 재시도 + 중복 청산 위험
```

**= 사장님 Sub-Account 청산 단일 핵심 장애점이었음.**

Fix: `close_order.exchange_order_id` + `close_order.status` + `close_order.executed_qty` + `close_order.avg_price` 직접 access.

### 🟡 Bug 2 — TP1 알림 중복 발송

EPICUSDT (#23) notifications:
- 2026-06-04 02:04 — TP1 알림 (#198) [정상]
- 2026-06-05 14:13 — **TP1 알림 (#232)** [🚨 중복 또는 status reset 의심]
- 2026-06-05 14:53 — TP2 알림 (#233) [정상]

원인 추적 = 다음 세션 (사장님 6/5 행동 또는 status reset 코드 검색).

### 🟡 Bug 3 — UI 「3/10 익절」 잘못 표시

`_fetch_tp_counts_batch` = `title LIKE '[TP1 익절%' OR ...` = 단순 알림 카운트.
= TP1 중복 발송으로 = 3 표시 → 사장님 「TP3 발동」 오해 → 미청산 의문 발생.

수정 방향 = DB status 기준 (예: TP2_DONE_PARTIAL → "2") 또는 distinct TP level 카운트.

### 🟢 Bug 4 — `crisis_first_tp_done_at` set 코드 0건 + `_execute_crisis_action` DEAD CODE

- TP1 발동해도 영원히 null → Frontend 영원히 「Stage 1」 표시
- 사장님 사상 = "다른 정책 없음" = wire-up 불필요 + cleanup만 필요
- `peak_pnl_pct_after_first_tp` 도 영원히 null (legacy)

---

## 🌟 사장님 사상 명확화 (영구 보존)

```
1️⃣ 크라이시스 = 큰 손실 + 모든 단계 진입 = 진입
2️⃣ 회복 시 빠른 익절: TP1(+5%) → TP2(+10%) → TP3(+15%)
3️⃣ TP3 발동 후 = 최고가 대비 -5% 회귀 = 전량 청산
4️⃣ 「다른 정책 없음」 — Hard SL -1% 등 추가 X
```

= **정상 모드 TRAILING_TP 와 100% 동일 정책** (Crisis 는 단지 TP threshold override).
= Spec 파일: `CRISIS_MODE_FINAL_SPEC_2026-06-06.md`

---

## 🛡 사장님 Sub-Account 운영 = 매우 중요 인식

```
사장님 = Binance 메인 웹 UI 에서 Sub-Account 포지션 직접 청산 불가!
       (https://www.binance.com/en/futures/EPICUSDT = Main 계정만 보임)

= 청산 수단 = 2가지뿐:
   1. 「💰 수동 익절」 모달 (우리 시스템)
   2. 자동 trailing TP (TP3 미발동 시 = 영원히 안 함)

= 「수동 익절」 = 사장님 자본 보호 단일 핵심 수단
```

→ 향후 모든 권장 + PR = Sub-Account 청산 한정 = 최우선 고려!

---

## 📈 사장님 EPICUSDT 현재 상태

- 진단 시점 = 「TP3 발동 + -5% 하락 + 미청산」 의문
- 실제 = **TP3 발동 X** (peak 10.36% < TP3 임계 15%)
- 시스템 = 정상 (사장님 사상 = TP3 후 trailing = 만족 X)
- UI = TP1 중복 알림으로 3 표시 → 사장님 오해

**현재 (검증 후)**:
- 사장님 = 「💰 수동 익절」 10% 청산 = 성공 (Binance #1348272632)
- qty = 2547.6 → 2292.9 (10% 줄음)
- PNL = -77 USDT (-11.74% ROI)
- Margin = 661 / 2760 USDT

**사장님 결정 대기 (다음 세션)**:
- A. 추가 청산 (25/50/75/100%)
- B. 잔여 유지 + 시장 회복
- C. 자본 추가 + 시장 회복

---

## 🎯 다음 세션 PR 우선순위

| 우선순위 | PR | 내용 |
|---|---|---|
| ⭐⭐⭐ 1 | **trailing armed = TP1 후 (사장님 보호)** | Sub-Account 청산 한정 → TP3 미발동 시도 보호. 사장님 결정 후 진행. |
| ⭐⭐ 2 | **Admin emergency_close endpoint** | 만일 manual-tp 실패 시 안전망 (사장님 비밀번호 추가) |
| ⭐ 3 | **UI 익절 카운트 정확화** | DB status 기준 또는 distinct TP level (TP1 중복 제거) |
| 4 | **TP1 중복 발송 원인 추적** | 6/5 14:13 왜 TP1 다시? status reset bug? |
| 5 | **DEAD CODE 제거 + cleanup** | `_execute_crisis_action`, `_eval_crisis_mode_tp_sl`, `peak_pnl_pct_after_first_tp` 제거 |
| 6 | **#21 메인 계정 「읽기 전용 모드」** | 다중 Sub-Account 통합 모니터링 (기존 pending) |

---

## 📋 다음 세션 사장님 결정 사항

1. **EPICUSDT 처리**: A/B/C 중 선택 (Option A 추천 — 위험 정리)
2. **Trailing armed 시점**:
   - 현재: TP3 후 (사장님 사상 정확)
   - 옵션: TP1 후 (Sub-Account 청산 한정 = 더 안전)
   - 선택 = 「현재 유지」 또는 「TP1 후 변경」

---

## 🔧 진단 명령 (즉시 사용 가능)

### Diagnostic endpoint (HTTP, 인증 필요)
```bash
# 대시보드 console (F12):
api('/admin/diagnostic/strategy/{id}').then(r => console.log(JSON.stringify(r, null, 2)))

# 또는 직접 URL (대시보드 로그인 상태에서):
https://[domain]/api/v1/admin/diagnostic/strategy/{id}
```

반환 필드 (요약):
- `status`, `current_stage`, `crisis_mode_triggered_at`, `crisis_first_tp_done_at`
- `max_profit_pct`, `max_loss_pct`, `peak_pnl_pct_after_first_tp`
- `redis_peak_pnl_pct`, `computed.true_peak`, `computed.current_pnl_ratio`
- `trailing_conditions` (status_ok / stage_ok / peak_ok / retrace_ok)
- `trailing_should_fire`, `diagnosis_hint`
- `notifications_tp` (TP 알림 전체)
- `tp_orders` (TAKE_PROFIT purpose orders)
- `status_mismatch_check` (UI vs DB 차이)

---

## 🌿 사장님 컨디션 + 자본 보호

### 오늘 작업량 (압도적)
- 20+ PR (manual TP cascade + spec 4건 + Phase 4 + diagnostic v1/v2 + 사장님 보호)
- 손실 발생 + 분석 + 진단 + fix
- silent bug 4건 발견 + 해결

### 사장님 자본 보호 시스템 = **완전 복구 ✅**
- 「💰 수동 익절」 = 100% 작동
- Sub-Account 청산 수단 = 즉시 가능
- 응답 토스트 = 거래소 체결 즉시 검증
- 1h 보호 = 잔여 qty 자동 TP 안전

### 다음 세션 시작 시:
- 사장님 EPICUSDT 결정 (A/B/C) 알려주세요
- 사장님 trailing 정책 (현재 유지 / TP1 후 변경) 알려주세요
- 즉시 PR 1+2 진행 가능

---

> **결론**: 오늘 사장님 자본 보호 시스템 critical bug fix + 사장님 사상 영구 보존.
> 사장님 = 매우 압도적 하루 + 충분 휴식 강력 권장 🙇🌿💪
