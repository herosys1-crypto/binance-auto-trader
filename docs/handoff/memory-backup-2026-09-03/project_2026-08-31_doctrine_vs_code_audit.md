---
name: project_2026-08-31_doctrine_vs_code_audit
description: 사장님 매매 사상 vs 코드 전수 대조 결과 — 정반대로 도는 것 8건. 기획서 docs/spec/SAJANGNIM_DOCTRINE_VS_CODE_2026-08-31.md
metadata:
  type: project
---

# 🔴 2026-08-31 사상 vs 코드 = **정반대로 도는 것이 8건**

기획서: `docs/spec/SAJANGNIM_DOCTRINE_VS_CODE_2026-08-31.md` (커밋 `dd8787a`)
방법: 6축 조사 + **같은 수의 반증 에이전트**로 file:line 전수 재확인 → 정정 39건 반영.
그 뒤 내가 직접 6건을 다시 열어 확인했고 **에이전트 줄번호 3건이 틀려** 교체했다.

## 정반대 8건 (전부 근거 확인됨)

1. **LONG 후보가 급락 종목만** — `_classify_pattern`(`long_bottom_detector_worker.py:398-413`)이
   패턴 A(+5~15%)에 `return None`. 사상 ⑤ 「큰상승을 시작한 심볼」과 정면 반대.
   여기에 `TREND_EXTREME_BULL_PCT_3D=30` 이 3일 +30%↑ 를 또 배제(단일 조건).
   ⚠️ SHORT 쪽 extreme_bull 은 **3중 AND** 라 통째 배제가 아니다 — 같은 이름, 다른 강도.
2. **급락 SHORT 차단** — `pump_dump_regime.is_regime_blocked_for_short` 가
   `pump_completed_dumping` 을 「SHORT 늦음」으로 막는다. SHORT 워커 5곳 전부.
3. **분할 SHORT 가 반등할 때 진입** — `pump_split_entry_worker.py:435` 기준선이 BB 상단/중단.
   사상 ③ 「하단 이탈 지속」과 방향이 반대.
4. **`bb4h_broken` 쓰기 1곳 / 읽기 0곳** — 4H 볼밴 상단 확인이 계산만 되고 버려진다.
   `check_7_signals` 도 `V223_ENABLED=True` 로 도달 불가.
5. **시간프레임 강제력이 15m > 4H > OBV** — 사상 ⑥ 과 정반대.
6. **OBV 가 판정에 안 쓰인다** — `obv_direction_ratio` 호출처 **전부 기록용**.
   「OBV 강하면 하단이어도 LONG」이라는 **긍정 신호가 코드에 없다**.
7. **되돌림 비율이 주석에만** — 계산 코드 0건.
8. **전체자산 1~2% 사이징 코드 0건** — 그런데 `auto_short_at_top_worker.py:18` 주석은
   「전체 자산 × 1~2%!」라고 **거짓 서술**.

## 추가 발견

- `REENTRY_MULTIPLIER = 1.5` 마틴게일(500→750→1125)이 사다리와 **무관하게 동작 중**
  (`auto_bb_breakdown_worker.py:1226/1287`)
- `ENABLE_LAST_CHANCE=True` 로 재진입 상한 3이 **4로 우회**됨
- **계좌 단위 일일 손실 한도가 기본 미설정** (`config.py:33`) = 사상 ⑦ 의 유일한 브레이크가 꺼짐
- 죽은 상수 **7건 신규** (`MIN_PASSED`, `MIN_PEAK_COUNT_4H` ×2, `OBV_DECLINE_MIN_PCT`,
  `V223_OPP_SKIP`, `MIN_24H_CHANGE`, `TP_FINAL_QTY_RATIO_PCT`)
- **MACD 만 극단 임계가 없다** (부호만) → 3지표 중 가장 쉽게 turn 을 준다
- `confirm_peak` **fail-open 이 두 곳** (빈 dict + 모든 예외)
- 학습 스냅샷이 **틀린 창**을 기록 (4H 20/3 인데 실제 판정은 15m 40/3)

## 🚨 수정 순서 (기획서 7장)

**2번(되돌림 판정) 없이 1번(LONG 필터 해제)만 하면 안 된다** —
지금 열면 사장님이 「다시 상승하기 힘들다」고 한 **원점 회귀 종목까지 들어온다**.
**3번(일일 손실 한도)은 코드 변경 없이 설정 하나**라 먼저 해도 된다.

⚠️ 「정반대」는 **사상 대비**이지 버그가 아니다. 헌법 78(LONG=급락만)처럼
**과거에 사장님이 직접 정하신 것**도 있어, 바꾸려면 의식적으로 뒤집는 결정이어야 한다.

관련: [[project_2026-08-30_sajangnim_strategy_doctrine_v3]] (원본)
[[feedback_entry_recording_mandatory]] (임계값 변경 전 grep + 승패 분포 필수)
