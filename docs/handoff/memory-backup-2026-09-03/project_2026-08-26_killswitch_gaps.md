---
name: project_2026-08-26_killswitch_gaps
description: Kill-switch 가 자동 증거금 추가를 막지 못함 + orphan 먼지 하나가 계정 전체를 막음 + KS 해제 시 보류 알람 일괄 발사 (2026-08-26 실측)
metadata: 
  node_type: memory
  type: project
  originSessionId: 9810b26c-b7e1-4349-8e91-83e3a14b072a
  modified: 2026-08-26T15:33:10.761Z
---

# 🚨 Kill-Switch 3대 공백 (2026-08-26 실측 확인, main `375865a`)

## ① kill-switch 가 자동 증거금 추가를 **막지 못한다** (CRITICAL, 미수정)

`ExecutionService.add_position_margin` (execution_service.py:883) 에 kill-switch 검사가 **없다**.
시스템 전체에서 `AccountKillSwitchService.is_enabled` 를 검사하는 지점은 **5곳뿐**:

```
execution_service.py:192, 239, 1143, 1262   (진입/단계/청산 계열)
strategy_service.py:222                      (전략 생성)
```

`auto_add_margin_worker.py` 에는 "kill" 문자열조차 없다.
→ **KS 가 켜져 있어도 -30% ROI 자동 포지션에 +300 USDT 가 계속 주입된다.**

상수: `ROI_TRIGGER=-30.0` / `DEFAULT_ADD_MARGIN_USDT=300.0` / `DEDUP_TTL_SEC=86400` / 스케줄 15초.
⚠️ dedup 덕분에 **심볼:방향당 24h 1회**다 (감사 에이전트의 "15초마다 주입" 은 과장 — 내가 정정함).
임시 차단 = Redis `add_margin_done:{SYMBOL}:{SIDE}` 를 미리 setex.

**나는 사장님께 "kill-switch = 우회 경로 없는 확실한 정지" 라고 말했고 그것은 틀렸다.**

## ② `auto_add_margin_usdt = 0` 이 300 으로 둔갑 — 헌법 83 **세 번째** 재발

```python
if row and row.value:
    val = Decimal(str(row.value))
    if val > 0: return val      # 0 은 여기를 못 지나감
return DEFAULT_ADD_MARGIN_USDT  # → 300
```
Fix 108 과 **완전히 같은 패턴**. 이 워커엔 별도 ON/OFF 스위치도 없어 **끌 방법이 없다**.

## ③ orphan 먼지 하나가 계정 전체를 막고 2분마다 재발동

`zombie_guardian.detect_orphan_exchange_positions` 는 판정이 `if amt == 0: continue` **뿐 — dust 임계값이 없다**.
실제 사고: 거래소 `CLUSDT SHORT amt=-0.24` (명목가 1 USDT 미만) → 계정 #1 전체 KS 발동.
`position_reconcile` = **2분 주기** (scheduler_runner.py:518) → 해제해도 2분 뒤 재발동.
유일한 예외는 5분 내 `REENTRY_READY` race window 하나. **운영자 ack 수단이 없다.**
→ 진짜 해결은 거래소에서 그 잔량을 청산하는 것뿐 (reduceOnly 는 minNotional 면제).

## ④ KS 해제 = 보류 알람 **일괄 발사** (설계이지만 위험)

Fix 75 는 진입 실패 시 알람을 지우지 않고 유지한다 (`[Fix75/alert-long] ❌ 진입 실패 = 알람 유지 (재시도!)`).
KS 로 9분간 막혀 있다가 해제한 순간 **1.5초 만에 3건**이 들어갔다 (#1563 DOT LONG / #1564 TUT SHORT / #1565 SUI LONG).
**안전 해제법 = 동시보유 상한을 0 으로 둔 채 KS 만 해제** → 워커는 `check_position_slot` 에서 막히고,
**수동 「포지션 추가」는 상한 검사를 지나지 않으므로** 사장님 수동 작업만 통과한다. 실측 확인:
`자동진입 슬롯: (False, '동시보유 상한=0 = 자동 진입 완전 OFF (src=sajangnim_top_short_daily_limit)', 0, 0)`

## ⑤ 고아는 **시스템이 스스로 만들고 있었다** (Fix 166/167 — CLUSDT 의 출처)

고아 포지션이 어디서 왔는지 추적한 결과, **두 개의 생산 경로**가 있었다:

**`escalate_stuck_strategy` 호출부 2곳의 전제가 정반대인데 처리가 같았다** (Fix 166):
- `reconcile_worker.py:305` `PENDING_STUCK_NO_EXCHANGE_POSITION` = 거래소에 포지션 **없음** → STOPPED+qty=0 **옳음**
- `reconcile_worker.py:458` `QTY_MISMATCH_PERSISTENT` = `matched ≠ None` = 거래소에 포지션이 **있는데** 수량만 다름
  → 그런데도 STOPPED(TERMINAL)+qty=0 → ACTIVE_LIKE 매칭 소멸 → **즉시 고아** → 계정 전체 KS
  → 해제해도 포지션은 그대로 → 2분 뒤 재발동 = **무한 루프**
  → `preserve_position=True` 신설 = `MANUAL_CLEANUP_REQUIRED`(ACTIVE_WITH_POSITION) + qty 보존.
    reconcile 이 MCR 을 stuck 집계에서 제외하므로(`:285`) 반복도 없다.

**`stream_service.py:163` 이 조회 실패(None)를 「잔량 0」과 동일 취급** (Fix 167):
```python
if actual_remaining is not None and actual_remaining > 0:   # 잔재 처리
else:                                                        # qty=0 + REENTRY_READY  ← None 이 여기로
```
**바로 위 주석이 설명하는 그 방어가 API 장애 때 정확히 사라진다.** 오늘 418 IP ban 이 있었으므로 살아있던 경로.

**`auto_bb_breakdown_worker` 의 「좀비 정리」** (Fix 162, 위 별도 기록) — 주문 발사 후 예외 시 전략 row 삭제.
`order_repo.create` 는 add+flush 만 하고 commit 하지 않아 rollback 이 Order row 까지 지운다 = **DB 에 흔적 0**.

## ⑥ 워커 간 TOCTOU = 상한 초과 (Fix 168)

각 워커가 루프 **시작 전 1회** `check_position_slot` 으로 `remaining` 을 잡고 그만큼 만든다.
`guarded_job` 락은 **job 이름별**이라 6개 진입 워커가 동시에 돌며 **각자 같은 remaining 을 예산으로 잡는다.**
실측 증거: `[sajangnim_top_v219+Fix112] SKIP: 동시보유 상한 도달 36/20` (상한 20 / 활성 36 = 80% 초과).
→ 호출부 6곳이 아니라 **공용 깔때기 `_create_auto_bb_strategy` 진입부**에서 재검사 (헌법 101).

## ⚠️ 안 고친 것 — C1 (의도적)

`strategy_service.py:265` `max_concurrent = max(1, _settings.max_concurrent_strategies_per_account)`
0 을 넣어도 1 = 헌법 83 위반은 사실. **그러나 고치지 않았다** — default 10 이고
`len(active) >= max_concurrent` 로 **생성을 막는** 가드라, 운영 실값을 모르고 0=OFF 로 바꾸면
**모든 전략 생성이 막힐 수 있다.** 활성 15건+ 인데 생성이 되고 있으므로 운영 env 는 10 초과.
⚠️ 이건 사장님 상한과 **별개의 숨은 상한**이다 — 값을 한 번 확인해 둘 것.

## ⚠️ 내가 틀린 진단 2건 (같은 실수 반복 금지)

1. **일일 손실 한도 가설** — 실제 KS 사유는 `ZOMBIE:ORPHAN_EXCHANGE_POSITION` 이었고
   `daily_loss_limit` 은 global=0.0 / 계정=None 으로 **애초에 비활성**이었다. 사유 코드를 먼저 읽었어야 했다.
2. **"상한 0 인데 3건 생성 = 우회"** — 타임스탬프가 반박했다.
   생성 `14:19:53~54` vs 설정 저장 `14:20:11` = **18초 차이로 생성이 먼저**. 그 시점 상한은 40 = 정상 동작.
   36 에이전트 감사도 이 타임스탬프를 모른 채 「row 부재 → 폴백 20」을 최상위 원인으로 지목했으나
   실측 `('sajangnim_top_short_daily_limit','0',14:20:11)` + `check_position_slot → (False, ..., 0, 0)` 로 **기각**.

**헌법 111** = KS/게이트를 「확실한 정지」라고 말하기 전에 `is_enabled` 검사 지점을 **grep 으로 전수 확인**할 것.
**헌법 112** = 사건 원인을 추정하기 전에 **사유 코드(reason_code)를 먼저 읽을 것**.
**헌법 113** = 「설정 무시」 의심 시 **설정 `updated_at` 과 생성 `created_at` 을 먼저 비교**할 것 (순서가 사건을 설명한다).
**헌법 114** = 에이전트 감사 결과도 **실측과 충돌하면 실측이 이긴다** — 감사는 내가 준 전제만큼만 정확하다.
**헌법 115** = 거래소에 주문이 나간 뒤에는 DB row 를 절대 지우지 말 것 (고아 생산).
**헌법 116** = 계정 전체를 막는 안전장치엔 반드시 **임계값과 해제(ack) 수단**을 함께 둘 것.
**헌법 117** = 같은 함수라도 **호출부의 전제가 다르면 처리도 달라야 한다** (escalate 2곳 = 포지션 없음 vs 있음).
**헌법 118** = fail-soft 는 **「확인 못 함」을 「이상 없음」으로 바꾸면 안 된다**.
**헌법 119** = 예산을 루프 밖에서 한 번 잡으면 **동시 실행 워커끼리 그 예산을 중복 사용한다** → 한도 검사는 생성 직전에.
**헌법 120** = **고칠 수 있다고 다 고치지 말 것** — 운영 실값을 모르는 가드는 보고만 할 것.
**헌법 121** = 같은 원칙(헌법 108)이라도 **누락의 결과가 정반대인 호출부가 있다** — 일괄 적용 전에 각 쿼리가 무엇을 판정하는지 볼 것.
**헌법 122** = 검증 스크립트가 소스를 문자열로 훑을 땐 **주석을 먼저 제거**할 것 — 내가 쓴 설명 문구가 검사 대상으로 잡혀 거짓 통과/실패를 낸다 (실제로 FAIL 2건이 났다).

## ⑦ `is_archived` 누락 9곳 — **8곳만 고쳤다** (Fix 171)

전수 감사 = `ACTIVE_LIKE` 쿼리 **17곳 중 9곳** 누락. 그런데 **누락의 결과가 정반대인 곳이 있다**:
- **「활성 심볼 skip」 6곳** (auto_long_at_bottom:994 / auto_short_at_top:155 / bb_upper_breakout_short:377 /
  long_bottom_detector:564 / pump_top_detector:405 / realtime_reentry:874)
  → 보관 전략이 심볼을 영구 점유해 **진입을 계속 막았다**. (LONG 진입이 드물던 원인 후보!)
- **「기존 전략에 주문」 2곳** (peak_break_reversal:510 / resistance_reversal:356)
  → **보관된 전략에 신규 주문**을 내고 있었다 (더 위험).
- **「고아 판정 매칭」 1곳** `zombie_guardian:437` → **일부러 안 고침.**
  필터로 좁히면 매칭이 줄어 **false orphan 이 늘고 계정 전체 KS 가 더 자주 걸린다.**
  헌법 108 의 목적(보관 전략이 슬롯을 점유 못하게)과 이 쿼리의 방향이 정반대다. 코드에 사유 주석 기록.

## ⑧ `auto_reentry_worker` = 상한의 마지막 구멍 (Fix 172)

`create_strategy_instance` 직접 호출 = 새 동시 포지션인데 `check_position_slot` 이 없었다.
**자동 진입 워커 7개 중 유일한 구멍** — 상한 0 이어도 재진입은 계속 들어갔다.
루프 **안**에서 검사 + 차단 시 `REENTRY_FAILED` 마킹 안 함 (일시 상한으로 재진입 기회를 영구히 잃으면 안 됨).

## 배포 상태 (2026-08-26 말 기준)

브랜치 `claude/infallible-euler-6dc297` — `4866db5`(Fix 162~165) + `f600f8d`(Fix 166~170) + `25ab742`(Fix 171~172).
**PR 미머지 = 운영 미반영.** 머지 후 `git pull && docker compose restart api scheduler`.
PR: https://github.com/herosys1-crypto/binance-auto-trader/pull/new/claude/infallible-euler-6dc297

관련: [[project_2026-08-26_capital_ladder_and_silent_failures]] [[project_2026-08-26_ip_ban_spiral]]
[[project_2026-08-26_stop_switch_broken]] [[feedback_verify_before_complete]]
