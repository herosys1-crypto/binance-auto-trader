# 사장님 매매 사상 vs 코드 — 전수 대조 기획서

> 작성 2026-08-31 · 대상 커밋 `f7ecec5`
>
> **목적**: 사장님이 말씀하신 매매 사상과 **지금 실제로 도는 코드**가 어디서
> 같고 어디서 다른지를 `file:line` 근거로 확정한다.
> 사장님 요구 — *"감이 아니라 **숫자로 된 판정식**"*.
>
> **검증 방법**: 6개 축(지표 임계값 / 판정식 / 전략 파라미터 / 자본·리스크 /
> 죽은 값 / 구상-코드 갭)을 각각 조사한 뒤, **같은 수의 반증 에이전트**가
> 모든 `file:line` 을 다시 열어 확인했다. **정정 39건**이 나왔고 전부 반영했다.
> 반증에서 뒤집힌 주장은 본문에 **「⚠️ 정정」**으로 표시했다.
>
> **직접 재확인한 항목** (에이전트 보고를 그대로 믿지 않고 본인이 파일을 연 것):
> `bb4h_broken` 읽기 0곳 · `_classify_pattern` 패턴 A skip · `REENTRY_MULTIPLIER=1.5` 실사용 ·
> `DEFAULT_CAPITAL_LADDER` 위치 · `V223_ENABLED=True` · 되돌림 계산 부재.
> 이 과정에서 에이전트가 준 줄번호 **3건이 틀려** 실측으로 교체했다.
>
> 관련: `docs/spec/NEW_STRATEGY_MODES_2026-08-31.md` ·
> `docs/spec/PUMP_CONTINUATION_CASE_STUDY_2026-08-30.md`

---

## 0. 한 장 요약

| 사상 | 코드 | 판정 |
|---|---|---|
| ① 급등 정점 SHORT — **4H 볼밴 상단 밖** 확인 | 계산은 하는데 **읽는 코드가 0건** | 🔴 **모순** |
| ① 전체자산 **1~2%** 분할 | 고정 USDT (사다리 10/300/600, 프로필 500×4) | 🔴 **미구현** |
| ② LONG = 급등 후 큰 조정 | 존재하나 **15분 BB** 기준 | 🟡 부분 |
| ② LONG 대상 = **몇일 이상 지속상승** | 3일 +30% 이상이면 **후보에서 제외** | 🔴 **정반대** |
| ③ 급락 = 확실한 SHORT | `pump_completed_dumping` 으로 **SHORT 차단** | 🔴 **정반대** |
| ③ 볼밴 하단 **이탈**에 분할 SHORT | 분할 SHORT 는 **반등해서 밴드 위로 올라올 때** | 🔴 **정반대** |
| ④ OBV 가 **방향의 최종 심판** | 극단(±0.6)일 때만 거부하는 **조건부 거부권** | 🟡 부분 |
| ④ OBV 강하면 하단이어도 상승 전환 | **긍정 신호가 코드에 없음** (기록 전용) | 🔴 **없음** |
| ④ 우선순위 OBV > 4H > 15m | 실제 강제력 **15m > 4H > OBV** | 🔴 **뒤집힘** |
| ⑤ LONG = 큰상승 시작 심볼 | LONG 후보 = 24h **−15%~−3% 급락만** | 🔴 **정반대** |
| ⑤ 되돌림 비율 판정 | **주석에만 있고 계산 코드 0건** | 🔴 **없음** |
| ⑥ 4H = 확정된 흐름 / 15m = 타이밍 | 15m 만 **하드 게이트**, 4H 는 참고 | 🔴 **뒤집힘** |
| ⑥ 4H 조정 구간 LONG **미리 분할** | **국면 자체가 없음** | 🔴 **없음** |
| ⑦ 손실 후 2배 재진입은 **조건부** | 단계·시간·건수 상한 있음 | 🟢 구현 |
| ⑦ 「욕심 제어」 계좌 단위 제동 | 일일 손실 한도 **기본 미설정** | 🟡 부분 |
| ⑧ 급등 50 / 급락 50 모니터링 | 실제로 등록되어 돎 | 🟢 구현 |
| ⑧ 숫자로 된 단일 판정식 | 워커 4개가 **서로 다른 임계**로 판정 | 🟡 부분 |

**정반대로 도는 것이 8건**이다. 이것이 「전략이 사상대로 안 움직인다」의 실체다.

---

## 1. 사장님 사상 (verbatim)

> **①** "당일 급등하는 심볼을 모니터링하면서 15분차트와 obv 최고점 macd rsi cci 모든 지표가
> **최고점에서 하락과 지지를 여러번 반복**하고 하락을 시작할 심볼에 투자하는거야"
> "**4시간봉 최상단 볼밴 최상단밖** obv 최고점 macd rsi cci 모든 지표가 최고점에서 하락하면
> 본격적으로 포지션 진입하기 시작하고 **전체자산에 1-2% 분할 진입**"

> **②** "롱은 당일 **급등후 큰조정**에 롱으로 들어가서 분할 익절은 **볼밴 중간 전략**을 사용"
> "롱은 지금 **급등중인 심볼**을 찾아 **지속상승**에 투자가 확실해 — **몇일 이상 상승**하는 심볼"

> **③** "**급락한것은 이전급등에 대한 급락**이라 확실한 숏으로 급반등하는 위험을 줄이고"
> "**볼밴 하단 이탈시 지속적인 하락**에 포지션 진입 ... 분할 포지션 진입"

> **④** "무엇보다 **obv가 하락하지 않으면 결국은 obv 방향으로 간다**는거야.
> 볼밴 하단까지 갔다가도 **obv가 강하면 이것도 다시 상승으로 전환**된다고 봐야해"

> **⑤** "큰상승후 큰하락해서 **원점을 간 심볼은 다시 상승하는 심볼을 찾기는 힘들어**.
> 그래서 롱은 **큰상승을 시작한 심볼**을 모니터링해서 포지션에 들어가는게 매우 유리해"

> **⑥** "**4시간을 확정된 흐름으로 보고** 만들어줘. 4시간이 조정인데 **지속상승하는 심볼은
> 롱으로 미리미리 분할 진입**해서 큰 수익을 만들어가면 좋겠어"

> **⑦** "인간이라 **욕심을 제어 하지 못했어** ... **큰금액을 손실보면** 그때부터는 더 빠른
> 시간에 큰수익을 위해서 **무리한 투자**를 하면서 손실과 청산을 지속적으로 하게되었어"

> **⑧** "급등 50위 급락 50위 그렇게 모니터링해서 빠른 포지션 진입"

---

## 2. 정반대로 도는 8건 (가장 중요)

### 2-1. 🔴 LONG 후보가 「급락 종목만」이다 — 사상 ②⑤와 정반대

```python
# long_bottom_detector_worker.py:398-413  _classify_pattern
if PATTERN_A_MIN_CHG <= chg24 <= PATTERN_A_MAX_CHG:
    return None          # skip!  (헌법 78 = LONG = 급락만!)
```

- `PATTERN_A` = 24h **+5~+15%** (= 사장님이 원하는 「큰상승을 **시작한**」 구간) → **버린다**
- `PATTERN_B` = 24h **−15%~−3%** (= 사장님이 「다시 상승하기 힘들다」고 한 구간) → **이것만 담는다**
- 같은 로직이 `auto_long_at_bottom_worker.py:481-488` 에도 인라인으로 있다

⚠️ **정정**: `_check_pattern_signals` 안의 **패턴 A 분기는 도달 불가능한 죽은 코드**다.
그 함수는 `_classify_pattern` 의 결과로 분기하는데, 위 코드에서 보듯 그 함수의 반환값은
`"B"` 아니면 `None` **둘뿐**이다. 즉 패턴 A 코드는 남아 있지만 **한 번도 실행되지 않는다.**
(직접 확인: `long_bottom_detector_worker.py:398-413` 의 반환 경로 3개가 전부 `"B"`/`None`)

**여기에 더해**, 3일 +30% 이상 오른 종목은 LONG 후보에서 또 한 번 걸러진다:

```python
# auto_long_at_bottom_worker.py:141, :360-361, :469-477
TREND_EXTREME_BULL_PCT_3D = 30.0
if trend == "extreme_bull":
    detected = False     # "3일 +30%↑ extreme_bull SKIP (정점 위험!)"
```

⚠️ **정정**: LONG 쪽은 `chg_3d >= 30` **단일 조건**이라 정말로 통째 배제가 맞다.
반면 SHORT 쪽(`pump_top_detector_worker.py:153`)은 **3중 AND**
(3일 +80%(`:72 TREND_EXTREME_BULL_PCT`) **그리고** OBV 상승 **그리고** BB 중단 아래로
안 눌림)이라 「통째 제외」가 아니다.
같은 이름의 게이트인데 **강도가 다르다.**

> **결론**: 사장님이 LONG 대상으로 지목한 「몇일 이상 지속상승 / 큰상승을 시작한」 심볼이
> **두 겹으로 배제**되고, 「원점 회귀」 종목만 남는다.

---

### 2-2. 🔴 급락 SHORT 가 차단되어 있다 — 사상 ③과 정반대

```python
# pump_dump_regime.py:46-48, :71-78
# 판정식: 3일 +30% 급등  +  정점 대비 −5% 하락  →  "pump_completed_dumping"
def is_regime_blocked_for_short(...):
    if regime == "pump_completed_dumping":
        return (True, "SHORT 늦음")      # ← 차단
```

호출자 **5곳 전부** SHORT 진입 경로다 —
`auto_short_at_top_worker.py:231` / `bb_upper_breakout_short_worker.py:478` /
`macd_reversal_15m_worker.py:593` / `pump_dump_early_detector_worker.py:304` /
`stage_entry_signal.py:102`

> 사장님이 **「확실한 숏」**이라고 규정한 「급등이 끝나고 내려오는 중」이,
> 코드에서는 **「늦었다」는 이유로 차단되는 국면**이다.

---

### 2-3. 🔴 분할 SHORT 가 「반등할 때」 들어간다 — 사상 ③과 정반대

```python
# pump_split_entry_worker.py:435, :438-446
base = Decimal(str(mid)) if long_trend else Decimal(str(up))   # SHORT 기준 = BB 상단/중단
if close < need:  # 미도달
```

진입 규칙표(`:29~34`): SHORT 는 **「하락 중 반등: close > BB 상단」** / 긴추세 **「close > BB 중단」**.

- 코드: **반등해서 밴드 위로 올라와야** 분할이 시작된다
- 사상: **하단을 이탈해 계속 내려갈 때** 나눠 판다

> 급락 지속 구간에서는 트리거가 **영원히 안 잡히고**, 반등 국면에서만 물량이 들어간다.

---

### 2-4. 🔴 4H 볼밴 상단 확인이 계산만 되고 버려진다 — 사상 ①⑥

```python
# peak_confirmation.py:206, :219
# "[C] 4H = 참고 정보만! (Fix 106 의 하드 차단 제거!)"
detail["bb4h_broken"] = ...
```

`bb4h_broken` 은 **쓰기 1곳, 읽기 0곳**이다.

그리고 4H 7중 정점 판정(`pump_top_detector_worker.py:279 check_7_signals`)은
`V223_ENABLED = True` (`:57`) 때문에 **도달 불가능한 죽은 코드**다 —
v223 경로가 매 side 마다 `continue` 로 끝나 `:665` 의 유일한 호출자에 닿지 않는다.

⚠️ **정정**: 다만 실제 알람이 「15m score 3/5 만」으로 나는 것은 **아니다.**
`extreme_bull` 스킵(`:464`) → `confirm_peak`(`:501`) → 1h/4h 역방향 score≥3 거부(`:200-221`)
→ `conf >= 0.85`(`:533`) 를 모두 통과해야 한다. 특히 `strong_bull` 은 confidence 가
0.05 감산돼 **15m score 5/5 여야만** 알람이 난다.

> 그래도 **사장님이 「본격 진입」의 조건으로 규정한 「4시간봉 볼밴 최상단 밖」이
> 진입 판정에 한 번도 쓰이지 않는다**는 사실은 그대로다.

---

### 2-5. 🔴 시간프레임 권한이 뒤집혀 있다 — 사상 ⑥

| | 사장님 | 코드의 실제 강제력 |
|---|---|---|
| **OBV** | 방향의 **최종 심판** | fail-open 극단 거부권 (`obv_gate.py:180`) |
| **4H** | **확정된 흐름** | 참고 / 역방향일 때만 veto |
| **15m** | 진입 **타이밍만** | 🔴 **유일한 필수 관문** (`peak_confirmation.py:186, :199`) |

4H 를 가중 0.5 로 대장 취급하는 `chart_analyzer.py:399-401` 은 v222 fallback 이라
`V223_ENABLED=True` 아래서는 도달하지 않는다.

---

### 2-6. 🔴 OBV 가 판정에 안 쓰인다 — 사상 ④

`obv_metrics.obv_direction_ratio` 는 **존재하지만 호출처가 전부 기록용**이다:

| 호출처 | 용도 |
|---|---|
| `pump_top_detector_worker.py:244` | entry_snapshot 저장 |
| `long_bottom_detector_worker.py:254` | entry_snapshot 저장 |
| `realtime_reentry_worker.py:308` | snapshot |
| `market_observation_worker.py:95` | 관찰 저장 |

**진입 허용/거부 분기에 쓰는 코드 0건.**

`check_obv_gate` 는 LONG 을 `direction=="down" and ratio <= −0.6` 일 때만,
SHORT 를 `direction=="up" and ratio >= +0.6` 일 때만 막는다. 그 외에는 전부 통과하고,
조회 실패는 `unknown_pass` / `error_pass` 로 **없는 것과 같다**.

> 「OBV 가 강하면 하단이어도 LONG 으로 본다」는 **긍정 신호가 코드에 없다.**
> 사장님이 최종 심판이라 한 지표가 판정식에서는 **관전자**다.

---

### 2-7. 🔴 되돌림 비율이 주석에만 있다 — 사상 ⑤

```python
# long_bottom_detector_worker.py:96-101  (주석)
# 진짜 판정은 되돌림 비율이어야 한다
#   >= 70~80% → 원점 회귀 = LONG 금지
#   30~60%    → 추세 중 조정 = LONG 자리
#   이건 기획서에 설계로 넣고 별도 구현한다
```

`retrace` / `되돌림` / `원점` / `swing_start` / `giveback` 전수 grep — **계산 코드 0건**.
(`trailing_retrace_pct` 는 ROI 고점 대비 청산용이라 무관.)

---

### 2-8. 🔴 4H 볼밴 중단 이탈 SHORT 워커가 꺼져 있다 — 사상 ③

```python
# scheduler_runner.py:307-320   ← add_job 이 주석 처리됨
# "v224 통합: auto_bb_breakdown = unified_15m_entry로 대체"
```

`run_auto_bb_breakdown` 호출자 **0건**.

⚠️ **정정**: 모듈이 「한 줄도 안 도는」 것은 아니다 — `_count_used_slots` 는
`orchestra_status.py:73-77` 이, `_reset_reentry_count` 는 `stream_service.py:235-236` 이
계속 부른다. **4H BB SUSTAINED SHORT 스캔만** 안 돈다.

---

## 3. 자본 — 「전체자산 1~2%」는 없다

### 3-1. 실제 자본원이 **세 갈래**다

| 경로 | 자본 | 위치 |
|---|---|---|
| 사장님 사다리 | `[10, 300, 600]` USDT 고정 | `sajangnim_capital.py:57` |
| 제안 프로필 | `[500,500,500,500]` / `[1000×4]` / `[300×4]` | `suggestion_profiles.py:48/67/86` |
| 재진입 마틴게일 | `500 → 750 → 1125` | `auto_bb_breakdown_worker.py:1226` |

```python
# sajangnim_capital.py:146
# "사장님 규정: 전체 자산 = 시스템 고려 X! 초기 금액만!"
```

**`totalWalletBalance` 를 진입 사이징에 쓰는 코드는 0건이다.**

🚨 그런데 `auto_short_at_top_worker.py:18` 의 주석은
**"자본 = compute_stage1_capital (전체 자산 × 1~2%!)"** 라고 적혀 있다 — **거짓 주석**이다.
코드를 읽는 사람이 구현됐다고 오인한다.

### 3-2. ⚠️ 정정 — 살아 있는 마틴게일이 하나 있다

```python
# auto_bb_breakdown_worker.py:1226-1227, :1287-1288
REENTRY_MULTIPLIER = 1.5
multiplier = REENTRY_MULTIPLIER ** (count + 1)
return base_capital * multiplier          # 500 → 750 → 1125
```

`:607-616` 에서 이 값이 그대로 `_entry_cfg["capitals"]` 가 되어 **실제 진입 자본**이 된다.
사다리(10/300/600)와 무관하게 **지금 동작 중**이다.

### 3-3. ⚠️ 정정 — 재진입 상한이 우회된다

```python
# realtime_reentry_worker.py:77-78, :1288-1292
ENABLE_LAST_CHANCE = True
MAX_REENTRY_STAGE_WITH_LAST = 4
_is_last_chance = (ENABLE_LAST_CHANCE and _stage == MAX_REENTRY_STAGE_WITH_LAST)
if _stage > MAX_REENTRY_STAGE and not _is_last_chance: continue
```

`sajangnim_capital.MAX_REENTRY_STAGE = 3` 인데 **실제로는 4단계까지** 간다.

---

## 4. 「욕심 제어」 장치 — 계좌 단위 제동이 꺼져 있다 (사상 ⑦)

**단계 단위 제동은 촘촘하다** (여기는 사상대로다):

| 항목 | 값 | 위치 |
|---|---|---|
| 최소 학습 성공률 | 0.30 | `realtime_reentry_worker.py:61` |
| 시간당 재진입 상한 | 5 | `:65` |
| 3단계 최소 대기 | 4.0h | `:66` |
| 손절 후 최소 대기 | 3.0분 | `:70` |
| 단계별 지표 통과 요구 | 2 / 3 / 4 (of 8) | `:87-89` |
| 사다리 재시작 상한 | 2 | `ladder_restart_worker.py:67` |
| 24h 손실 한도 | −300 USDT | `ladder_restart_worker.py:71` |

**그런데 계좌 전체 제동은 기본 꺼져 있다**:

| 장치 | 상태 | 위치 |
|---|---|---|
| 일일 손실 한도 | `None` = **미설정** → 워커 no-op | `config.py:33` |
| 손실 심볼 재진입 차단 | Fix 71 로 **항상 빈 set** 반환 | `auto_bb_breakdown_worker.py:1378-1387` |
| 재시작 카운터 | 익절 시 리셋 / 7일 TTL | `ladder_restart_worker.py:187` |

> 사장님이 **"큰금액을 손실보면 그때부터 무리한 투자를 하면서 손실과 청산을 지속"**이라고
> 하신 그 실패를 막는 **계좌 수준 브레이크가 사실상 없다.**

---

## 5. 살아 있는 지표 임계값 (판정에 실제로 쓰이는 것만)

### 5-1. 정점·저점 확인 (`peak_confirmation.py`) — 모든 진입의 공통 관문

| 상수 | 값 | 역할 |
|---|---|---|
| `PEAK_TF` | `"15m"` | 판정 시간프레임 |
| `PEAK_LOOKBACK_BARS` | 40 | 스윙 탐색 창 |
| `PEAK_MIN_GAP` | 3 | 스윙 간 최소 간격 |
| `MIN_PEAK_COUNT_15M` | **2** | [A] 「여러번 반복」 = 2회 이상 |
| `MIN_TURNS` | **2** | [B] RSI/MACD/CCI **3개 중 2개** 꺾임 |
| `RSI_HIGH` / `RSI_LOW` | 65 / 35 | SHORT / LONG 극단 |
| `CCI_HIGH` / `CCI_LOW` | 80 / −80 | SHORT / LONG 극단 |
| MACD 꺾임 | `hp > 0 and hn < hp` | **크기 기준 없음 = 부호만** |

🚨 **MACD 만 극단 임계가 없다.** RSI(65)·CCI(80)는 「최고점 부근」을 요구하는데
MACD 는 「양수에서 줄어들기만」 하면 통과다 → **3지표 중 가장 쉽게 turn 1 을 준다.**

🚨 **fail-open 이 두 곳**이다 — `:179-180` (a15 가 빈 dict) 과
`:227-229` (**모든 예외**). 조회가 실패하면 **확인 없이 통과**한다.

### 5-2. OBV 게이트 (`obv_gate.py`)

| 상수 | 값 | 역할 |
|---|---|---|
| `OBV_SLOPE_LOOKBACK` | 20 | 창 크기 |
| `OBV_EXTREME_RATIO` | **0.6** | 이 이상이어야 차단 |
| 방향 zero-band | **±0.5** (이름 없는 하드코딩) | up / down / flat 분기 |

### 5-3. 워커별 판정이 제각각이다 (사상 ⑧ 「단일 판정식」과 어긋남)

| 워커 | 대상 수 | 24h 하한 | 진입 판정 |
|---|---|---|---|
| `pump_top_detector` | 50 | 5.0 | 15m score ≥3/5 + conf ≥0.85 |
| `auto_long_at_bottom` | 40 | −15.0 | 패턴 B + BB 위치 |
| `macd_reversal_15m` | 100 | 3.0 | 15m hist pivot |
| `unified_15m_entry` | 40 | 10.0 | 4봉/12봉 변동 |

> 같은 「급등 정점 SHORT」를 **네 워커가 다른 임계로** 판정한다.
> 어느 숫자가 사장님 사상을 대표하는지 **코드만 봐서는 결정할 수 없다.**

---

## 6. 죽은 값 목록 (정의됐지만 아무 판정에도 안 쓰임)

| 상수 | 값 | 위치 | 비고 |
|---|---|---|---|
| `RSI_OVERSOLD_MAX` | 45 | `auto_long_at_bottom_worker.py:96` | 기존 확인 |
| `RSI_MIN_TURNUP` | 0.5 | `:97` | 기존 확인 |
| `CCI_OVERSOLD_MAX` | −50 | `:98` | 기존 확인 |
| `CCI_MIN_TURNUP` | 5.0 | `:99` | 기존 확인 |
| `MIN_PASSED` | 5 | `:181` | 🆕 주석은 「5/7 = 더 엄격」인데 코드는 `"passed": 3` 하드코딩 |
| `MIN_24H_CHANGE` | 10.0 | `long_bottom_detector_worker.py:58` | 🆕 「사장님 verbatim 완화 요구」인데 안 읽힘 |
| `MIN_PEAK_COUNT_4H` | 2 | `pump_top_detector_worker.py:86` | 🆕 사장님 「2회 반복」인데 참조 0회 |
| `MIN_PEAK_COUNT_4H` | 2 | `bb_upper_breakout_short_worker.py:80` | 🆕 동일 |
| `OBV_DECLINE_MIN_PCT` | 2.0 | `pump_dump_early_detector_worker.py:24` | 🆕 크기 기준이 죽고 부호(`<0`)만 씀 |
| `V223_OPP_SKIP` | 3 | `unified_15m_entry_worker.py:68` | 🆕 이 워커만 역방향 스킵이 없다 |
| `TP_FINAL_QTY_RATIO_PCT` | 100 | `risk_constants.py:97` | 🆕 import 만 되고 미사용 |
| `NEAR_BAND_PCT` | 0.5 | `bb_4h_band_analyzer.py:71` | |
| `VOL_SPIKE` | 1.5 | `bb_top_analyzer.py:80` | 「참고용」 |

⚠️ **정정**: `OBV_DECLINE_MIN_PCT` 가 죽은 것은 맞지만
**「OBV 신호 자체가 6중에서 빠졌다」는 것은 거짓**이다 —
`pump_dump_early_detector_worker.py:83-87` 의 `signals["obv_dump"]` 는 살아 있고
`passed` 카운트에 포함된다. 죽은 것은 **2.0% 라는 크기 기준 하나**뿐이다.

🚨 **학습 데이터 오염 1건**: `pump_top_detector_worker.py:545-546` 과
`bb_upper_breakout_short_worker.py:276` 이 entry_snapshot 에
`peak_lookback_bars=20 / peak_min_gap=3` (4H 기준)을 기록하는데,
**실제 판정은 `peak_confirmation` 의 40/3 (15m)** 이다. → 스냅샷이 **틀린 창을 기록**한다.

---

## 7. 무엇부터 고칠 것인가 (권고 순서)

우선순위는 **「사상과 정반대로 도는 것」 > 「없는 것」 > 「부정확한 것」** 이다.

| # | 항목 | 근거 | 성격 |
|---|---|---|---|
| **1** | LONG 후보에서 상승 종목을 버리는 필터 해제 | 2-1 | 사상 ②⑤ 정반대 |
| **2** | 되돌림 비율 판정 신설 (70~80% 금지 / 30~60% 진입) | 2-7 | 1번의 **안전판** |
| **3** | 계좌 단위 일일 손실 한도 설정 | 4장 | 사상 ⑦ |
| **4** | 4H 를 하드 게이트로 승격 (`bb4h_broken` 을 읽게) | 2-4, 2-5 | 사상 ①⑥ |
| **5** | 급락 SHORT 차단(`pump_completed_dumping`) 재검토 | 2-2 | 사상 ③ 정반대 |
| **6** | 분할 SHORT 를 「하단 이탈 지속」 방향으로 | 2-3 | 사상 ③ 정반대 |
| **7** | OBV 를 **긍정 신호**로 승격 | 2-6 | 사상 ④ |
| **8** | 「4H 지속상승 + 지금 조정 → LONG 미리 분할」 국면 신설 | 사상 ⑥ | 신규 |
| **9** | 전체자산 비율 사이징 (1~2%) | 3장 | 사상 ① |
| **10** | 거짓 주석 제거 (`auto_short_at_top_worker.py:18`) | 3-1 | 오해 유발 |

### ⚠️ 순서를 지켜야 하는 이유

**2번 없이 1번만 하면 안 된다.** 지금 LONG 필터를 열면 사장님이 「다시 상승하기 힘들다」고
하신 **원점 회귀 종목까지 함께 들어온다.** 되돌림 판정이 먼저 있어야 한다.

**3번은 다른 무엇보다 먼저 해도 된다** — 코드 변경 없이 설정값 하나이고,
사장님이 **스스로 지목한 실패 모드**를 막는 유일한 계좌 수준 장치다.

---

## 8. 이 문서의 한계

- 조사는 `f7ecec5` 시점의 **정적 분석**이다. 런타임 설정(SystemSetting)으로 켜고 꺼지는
  것은 실제 DB 값을 봐야 확정된다.
- 「정반대」 판정은 **사상 대비**이지 「버그」라는 뜻이 아니다.
  헌법 78(LONG=급락만) 처럼 **과거에 사장님이 직접 정하신 것**도 있다.
  바꾸려면 그 결정을 **의식적으로 뒤집는 것**이어야 한다.
- 정정 39건을 반영했지만 반증 에이전트도 놓쳤을 수 있다.
  **임계값을 바꾸기 전에는 반드시** ① grep 으로 실사용 확인 ② 승/패 분포 비교.
