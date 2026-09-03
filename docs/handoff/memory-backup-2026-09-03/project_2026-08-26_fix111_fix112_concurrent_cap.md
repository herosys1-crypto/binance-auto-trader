---
name: 2026-08-26-fix111-fix112-concurrent-cap
description: 🎯 Fix 112 = 「하루 20건」 → 「동시 보유 20건」 상한 (사장님 요구). Fix 111 = 정점 판정 4H→15m 정정 + 재진입 비대칭 해소. 헌법 86~88 신설.
metadata: 
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-08-26T05:26:48.465Z
---

# Fix 111 + 112 (2026-08-26, main `713a74a`)

## 🎯 Fix 112 — 사장님 verbatim

> **"일 20개로 하지말고 일 20개 최대 20개 수정해줘"**

**발단**: UI 「활성 전략 44건」인데 설정은 「일 자동 진입 한도 20」

| | 옛 | 신 |
|---|---|---|
| 의미 | 하루 **신규** 20건 | **동시 보유** 20건 |
| 리셋 | KST 자정마다 | 없음 (포지션 청산 시 자동 회복) |
| 결과 | 20 → 44 → 무한 누적 | 노출 **고정** |

**신설** `app/services/position_limit.py` (헌법 6 단일 진실)
- `get_max_concurrent(db)` → `(limit, src)`, 키 체인:
  `sajangnim_max_concurrent_positions` → `sajangnim_top_short_daily_limit` → `auto_bb_break_daily_limit` → 20
- `count_active_positions(db)` = `ACTIVE_LIKE` ∧ `is_archived=False`
- `check_position_slot(db, tag)` → `(ok, why, active, limit)`
- **0 = 완전 OFF 존중** (헌법 83 계승)
- ⚠️ **fail-SAFE** = 조회 실패 시 **차단**! (다른 게이트의 fail-open 과 의도적 반대 — 자본 노출 상한이므로)

**적용 4곳**: `auto_short_at_top` / `auto_long_at_bottom` / `realtime_reentry` / `unified_15m_entry`
- **재진입 포함이 핵심!** 재진입도 새 StrategyInstance 를 만든다 (JASMYUSDT #1480 이 증거)
- UI/API 도 같은 함수 재사용 → 라벨 「최대 동시 포지션」, 카드 「📦 동시 보유 / 상한」

## 🎯 Fix 111 — Fix 106 이 틀렸음 (사장님 龙虾USDT 지적)

> **"선택한 박스에서 숏으로 진입해야 하는데 왜 이런 진입은 없는거지?"**

내가 만든 Fix 106 의 **2가지 잘못**:
1. **peak 카운트를 4H 로** 함 → 사장님 기준은 **15분 차트**!
   4H 급등은 폭발 캔들 1~2개 = peak 0~1 → **정상 정점까지 전부 차단**
2. **「4H MACD 양수 상승 중이면 금지」 하드 차단** → 4H 는 **후행지표**!
   급등 직후엔 언제나 양수 상승 중 → **헌법 72(급등 BB상단돌파 마틴게일)를 영구 봉쇄**

**신설** `app/services/peak_confirmation.py` (헌법 6)
```
[A] 15m swing peak(SHORT) / valley(LONG) >= 2회   ← 사장님 "2-3번 반복"
[B] 15m 지표 「극단 후 꺾임」 RSI/MACD/CCI 중 2개+  ← 사장님 "고점에 이란 신호"
[C] 4H = 참고 정보만 (차단 X) — bb4h_broken 은 헌법 72 긍정 신호로 기록
```
- 상수: `MIN_PEAK_COUNT_15M=2`, `MIN_TURNS=2`, `RSI_HIGH=65/LOW=35`, `CCI_HIGH=80/LOW=-80`
- LONG 대칭 구현 (`count_swing_valleys` + `_turns_for_long`)
- **로컬 검증**: 단조상승(STARUSDT형) peaks=0 → 차단 / 계단식(龙虾형) peaks=4 → 통과 ✅

## 🎯 Fix 111 Part B — 재진입 비대칭 (사장님 JASMYUSDT 지적)

> **"지금 진입이 첫진입을 해야 하는데 지금은 재진입으로 포지션에 진입한거야"**

**근본 결함**: 재진입은 「옛 손절가 대비 반등」 + 「범용 지표 반전」만 확인.
**새로 형성된 정점의 조건은 한 번도 검사 X** → 첫 진입보다 **재진입이 더 느슨**했음 (역전!)

**fix**: `realtime_reentry` 에도 첫 진입과 **동일한** `confirm_peak` 적용 = 대칭 (헌법 5)

## ✅ 실 로그 검증 (헌법 69~71)

배포 직후 grep 이 비었던 것은 **컨테이너가 재시작 중**이었기 때문 (코드 문제 아님).
```
02:41:23 [sajangnim_top_v219+Fix112] SKIP: 동시보유 상한 도달 36/20
02:43:23 ... 33/20   ← 청산되며 감소 = 정상 동작
직접 호출: limit=(20,'sajangnim_top_short_daily_limit') active=33 slot=(False,...)
```

## 🚨 Fix 111b + 112b (`2860101`) — 감사가 잡아낸 후속 결함

에이전트 43개 6축 감사 → **Fix 111 이 반쪽이었음**:

**4H 하드차단이 「알람 생산자」에 그대로 남아 있었다** (`pump_top_detector:483`,
`bb_upper_breakout:522`). 소비자만 고쳐서 **알람 자체가 안 만들어짐** →
사장님 龙虾USDT 지적이 해결되지 않은 진짜 이유. 둘 다 `confirm_peak(15m)` 으로 교체.

**동시보유 상한 우회 3경로**: `_create_auto_bb_strategy` 호출자 7개 중 4개만 게이트됨.
`success_pyramiding`(30초마다 신규 생성!) / `pending_hc_fast` / `auto_bb_breakdown` 추가.
→ 특히 success_pyramiding 은 `auto_bb_break_daily_limit` 만 봐서 **상한 0 으로도 안 멈춤** (헌법 83 위반).

그 외: 재진입 루프가 상한을 1회만 체크(19/20에서 10건 → 29건 가능) / `auto_long_at_bottom`
`entered >= remaining` 이중 차감으로 실효 예산 절반 / `get_max_concurrent` 가 파싱 예외를
삼키고 20 반환(fail-OPEN 구멍) / LONG 저점 게이트 부재 / GET·PUT `/auto-bb-limit` 키 불일치 /
clamp 30 → 200.

⚠️ 감사의 **"UI 드롭다운이 dead control" 주장은 오탐** — 실 로그 `src=sajangnim_top_short_daily_limit` 가 정상 배선을 증명.

## 🚨 헌법 신설

**헌법 86: 진입 상한은 「하루 건수」가 아니라 「동시 보유」로 걸 것!**
- 하루 카운터는 자정 리셋 → 포지션이 안 닫히면 노출이 무한 누적
- 자본 노출 상한 = 시점 개념이지 기간 개념이 아님

**헌법 87: 자본 노출 게이트만은 fail-SAFE (막는 쪽)!**
- 다른 게이트는 fail-open (오류가 기존 동작을 막지 않도록)
- 그러나 **상한 조회 실패 = 차단**! 불확실할 때 무한 진입은 실 손실

**헌법 89: 게이트는 「소비자」가 아니라 「생산자」까지 전부 고칠 것!**
- alert 생산자 → Redis → 소비자 구조에서 소비자만 고치면 **알람이 안 생겨 무의미**
- 게이트를 바꿀 땐 `grep` 으로 같은 상수/조건을 쓰는 **모든** 워커를 찾아 동시에 고친다
- (Fix 111 이 정확히 이 실수 = 龙虾USDT 가 계속 막혀 있었음)

**헌법 90: 진입 상한은 「포지션을 만드는 모든 함수」의 호출자 전부에 걸 것!**
- `grep -rln "_create_auto_bb_strategy("` → 호출자 7개 중 4개만 걸려 있었음
- 상한/정지 스위치를 추가하면 **호출자 목록을 grep 으로 열거해 빠짐없이** 적용
- 루프 안에서 진입하는 워커는 **루프 예산도** 상한과 묶을 것 (1회 선체크로 부족!)

**헌법 88: 재진입 기준은 첫 진입보다 느슨할 수 없다!**
- 첫 진입에 게이트를 추가하면 **재진입 경로에도 반드시 같이** 추가
- 안 하면 「첫 진입은 막히고 재진입은 통과」 = 역전 (JASMYUSDT 사고)
- 사장님 기준 판정은 **서비스로 분리**해 모든 경로가 같은 함수를 호출할 것

## 관련
- [[2026-08-26-stop-switch-broken]] (헌법 83~85)
- [[2026-08-26-reentry-structural-failure]] (헌법 80~82)
- [[2026-08-25-sajangnim-long-short-philosophy-v2]] (헌법 72 = 급등 BB상단돌파!)
- [[feedback-verify-before-complete]] (헌법 69~71 = 실 로그 검증 전엔 "완료" 금지!)
