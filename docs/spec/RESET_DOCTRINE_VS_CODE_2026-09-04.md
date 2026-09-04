# 처음부터 다시 — 사장님 사상 원문 vs 코드 현실 (2026-09-04)

> 사장님 2026-09-04:
> "내가 언제 이렇게 로직을 만들었나?"
> "빠른 익절은 볼밴 분할전략에서 만든건데 확인해줘 정말 너 맘대로구나"
> "개발 기획를 처음부터 다시 확인하고 수정해야 할것 같이 모든게 엉망이야 바로 잡을 방법을 찾아줘"

이 문서의 목적은 하나다. **사장님이 말씀하신 규칙**과 **코드가 실제로 하는 것**을 한 줄씩 나란히 놓고,
숫자 하나하나에 「누가 정했나」를 붙여서, 사장님이 O/X 만 하시면 되게 만드는 것.
확인 전에는 값을 바꾸지 않는다.

---

## 0. 한 장 요약 — 오늘 확인된 것

| # | 사장님 규칙 | 코드가 실제로 한 것 | 누가 정했나 | 근거 |
|---|---|---|---|---|
| 1 | 사다리 2단계 = **최고점에서 조정이 시작되는 시점**(차트·보조지표), 3단계 = 다시 최고점 → 하락 시작 | 2·3단계의 **전제 조건이 「가격 +1.5%」**(Claude 값). 그 뒤 SHORT 만 Fix 312 「꺾임 대기」(15m 밴드 밖 지속 → 극값 꺾임, 운영 ON)를 거침. **LONG 은 가격만**. 3단계 「다시 최고점 → 꺾임」(재갱신) 판정은 사다리에 없음 | 1.5% = **Claude** (Fix 315) / 꺾임 대기 = 사장님 9/3 verbatim | `auto_bb_breakdown_worker.py:1783-1800`, `stage_trigger_worker.py:1128-1134`, `execution_service.py:1808-1829`, `stage_entry_timing.py` |
| 1b | 같은 규칙이 9/1 **Fix 260 「정점-주춤」**(극값 기준 주춤/꺾임 + 3단계 재갱신)으로도 구현·ON | **볼밴 분할(split_entry)에만** 적용, 사다리는 제외 → 사다리는 Fix 312, 볼밴은 Fix 260 = **같은 사상이 두 구현으로 갈라짐** | Claude 가 범위를 갈라 붙임 | `stage_trigger_worker.py:896-902` `_is_split` 게이트 |
| 1c | #2264 의 경우 | +1.5% 도달 4회 이상 → **130% 가드가 먼저 차단**해서 꺾임 대기까지 못 감 | 3번 항목 | 로그 「130% 초과 차단 strategy=2264」 |
| 2 | 사다리 TP1 = **15%** (9/2 3단 사다리 스펙, 사장님 검산 확인) / 빠른 익절(3~5%)은 **볼밴 분할** 얘기 | 사다리에도 |24h|<15% 면 **TP1 3%** | **Claude** (Fix 299 를 공용 진입 경로에 붙임) | `auto_bb_breakdown_worker.py:1855-1890` / #2264 tp1_pct_override=3 |
| 3 | 사다리 10 → 300 → 600 을 여러 심볼에 동시에 | **130% 지갑 예약 가드**가 열린 사다리마다 미진입 900 을 예약으로 세어 **2단계를 전부 차단** (24h 106회, 11전략) | 2026-05-19 사장님 요구(−2019 방지)와 9/2 사다리 사상의 **충돌** | `capital_calculator.py calc_reserved_for_strategy` / 로그 「실=959 + 예약=11,527 = 207% > 허용 7,235」 |
| 4 | — | 「설정만 수정」 저장이 트리거를 **20/20** 으로 덮음 (2433/2098/2189, 2264 는 205→20→1.5) | 화면 기본값 20 (Fix 234 의 이중 저장 자리) | `control.py:572` / 템플릿 #4978~#4986 |
| 5 | 손실 −5% → 10 USDT 남기고 부분손절 | 동작은 맞음. **알림 문구**만 「전량 강제 청산 + 전략 종료」로 거짓 | 옛 문구 | risk_events 3건 (#2264) |
| 6 | — | 「자동 진입 X 즉시 확인」 알림 9건 = 130% 차단을 모르는 감시자의 **허위 경보** | — | `setting_preservation_agent.py` |
| 7 | — | 정점 돌파 반전 워커(Fix 41) 진입이 **인자 누락 예외**로 한 번도 실행 안 됨 | 버그 | 로그 `ExecutionService.__init__() missing api_key/api_secret` |
| 8 | 볼밴 분할 TP1 = **5%** 부터 (8/29 확정, 「빠른 익절」) | 적응 TP 가 켜지면 볼밴 후보는 전부 \|24h\|≥15% 라 **항상 15%** → 사장님 5% 가 사라짐 | **Claude** (Fix 299/336-c 배선 구조) | `pump_split_entry_worker.py:732-739, 996-1006` |
| 9 | (8/30) 손실이면 청산 후 재진입 / (9/3) 10 USDT 남기고 부분손절 | 볼밴 분할은 **부분손절 대상에서 제외**(전량 청산). 「물타기 전략이라 대상 아님」은 Claude 해석 | **Claude** (Fix 313) | `stage_trim.py:75, 148-155` |
| 10 | 130% 한도 하나 | **세 곳이 세 가지로** 계산 (생성 시 ÷레버 / 화면 Binance 실마진 / 워커 DB 마진+미발동 원금). 주석 「화면과 100% 동일 함수」는 거짓 | 드리프트 | `strategy_service.py:379-415`, `exchange_accounts.py:671-703`, `capital_calculator.py:52-106` |
| 11 | 수정 화면 | 트리거 칸을 **10/20 기본값으로 미리 채우고 그대로 전송** → 저장 한 번에 사다리 1.5% 가 20% 로 (4번 항목의 원인) | 수동 템플릿용 기본값이 자동 사다리에 적용 | `cm-capitals-grid.js:23-29`, `cm-collectors.js:37-75` |
| 12 | 「전고점 돌파 후 하락 시점에 2단계」(저항 반전·정점 돌파 반전 워커) | 조건은 구현됐으나 **`ExecutionService(db)` 인자 누락으로 한 번도 발주 못 함** (7번 항목의 범위 확대: 워커 2개 + 볼밴 중단선 48h 청산 = 같은 버그 3곳) | 버그 | `resistance_reversal_worker.py:330`, `peak_break_reversal_worker.py:442`, `bb_mid_line_worker.py:145` |
| 13 | 볼밴 중단선 전략 | 코드 기본은 shadow 이나 **운영 DB 는 `on`** = 실자금으로 돌고 있음. 자본 100·레버 2·슬롯 3·SL 가격 5%·TP 5/10/15/20 이 **전부 Claude 값**이고, 전체 상한·4H·합의 게이트를 **안 거침** | Claude 값으로 실운영 중 | `bb_mid_line_worker.py:42-55`, `surge_ladder_entry.py:122-158` |
| 14 | — | 코드 주석의 **「사장님 verbatim!」 라벨이 원문에 없는 숫자에 붙어 있음**(bb_upper 15%·0.3%·RSI 70·볼륨 1.5) → 「사장님 값」으로 오인하게 만듦 | Claude 주석 관행 | `bb_upper_breakout_short_worker.py:61-64` |
| 15 | 「4시간 같은 방향일 때 성공률 높음」(macd 15m 반전) | 4H 필터가 **OR 로 완화**돼 반대 방향도 부호만 맞으면 통과 | Claude (Fix 146) | `macd_reversal_15m_worker.py:198-270` |

---

## 1. 사장님 사상 원문 (verbatim — 요약하지 않음)

### 1-A. 정점 SHORT / 저점 LONG 자본 사다리 (주력)

**2026-08-30 (사상 v3 ①)**
> "당일 급등하는 심볼을 모니터링하면서 15분차트와 obv 최고점 macd rsi cci 모든 지표가 **최고점에서 하락과 지지를 여러번 반복**하고 하락을 시작할 심볼에 투자하는거야"
> "**4시간봉 최상단 볼밴 최상단밖** obv 최고점 macd rsi cci 모든 지표가 최고점에서 하락하면 본격적으로 포지션 진입하기 시작하고 **전체자산에 1-2% 분할 진입**"
> "진입 후 지속적인 손실이면 **청산하고 처음 진입금액의 2배**를 다시 반등이나 상승후 하락 **15분과 4시간 보조지표가 하락으로 전환되는 시점**에 다시 포지션 진입"

**2026-09-01 (Fix 260 원문)**
> "2단계부터는 차트와 보조지표가 조정으로 바뀌면이 아니라 **최고점에서 들어가야** 하는데 … **최고점으로 가다가 주춤할때 2단계 진입** 그리고 **다시 최고점으로 가면 다시 대기해서 꺾이면 3단계 진입**"

**2026-09-02 (3단 사다리 스펙 — 숫자 검산 완료)**
> 1차 10 → 추가 300 → 추가 300 (총 610) → **TP1 15%** = 91.5 ("95부터")
> 실패 → SHORT −5% / LONG −10% 손절 → 같은 심볼 재진입 모니터링 → 2차 300 → … → 3차 600
> "급등도 한계점이 있어. 그 한계점을 우리가 공략하는거야. 첫번째는 실패할 확률이 매우 높지만"

**2026-09-03 (Fix 315 원문 — 단계 방식으로 확정)**
> "부분 손절하고 **다음 트리거 단가에 포지션 진입**하고 또 손실이면 부분청산하고 다음단계 트리거 단가에 포지션 진입"
> "첫진입이 10이라 손절없이 그냥 **좋은 포지션에 2단계 300으로 진입**"

**2026-09-03 (정정 3건)**
> "+2%가 아니야 수익중에 **차트와 보조지표가 지속 상승이나 하락이 데이터를 보이면** 포지션 추가하는거야"
> "**15분이 기준이고 4시간을 참고**하고 … 4시간 차트의 의미는 중단기 지속적인 흐름을 판단하는 정도 차트"
> "소액 진입 → 실패하면 부분손절 → 2번 더 → 다시 한번 더 같은 로직 → 그래도 안되면 모니터링하다 진입시점에 재진입. 난 24시간 실시간으로 모니터링 할수 없어서 시스템을 개발하는거야. 상승50/하락50은 15분에 200-400% 올랐다 내릴수 있는 시장"

**2026-09-04 (오늘)**
> "2단계는 **차트와 보조지표가 최고점에서 조정이 시작되는 시점**에 진입하고 그리고 숏을 −5% 손실이면 2단계 진입후 10usdt 남기고 부분 손절하고 다시 모니터링 대기해서 차트가 **최고점을 찍고 하락과 상승을 반복하고 다시 하락시작하는 시점에 3단계 진입**하는 로직"

⚠️ 9/3 「다음 트리거 단가」와 9/4 「최고점에서 조정 시작 시점」은 **같은 것을 다른 말로** 하신 것으로 읽힌다 = 트리거 단가는 「거기까지 갔다가(최고점) 꺾일 때」이지 「거기 닿으면」이 아니다. 이것이 정확히 Fix 260 의 정의(비교 주체 = mark 가 아니라 **극값**)다. → **사장님 확인 ①**

### 1-B. 볼밴 분할

**2026-08-25 (사상 v2)**
> "급등해서 볼밴 상단돌파 했을때 **마틴게일 전략**으로 진입해야 확실한 수익을 만들수 있어 최상단에서 하락이 지속해서 TP1 발동되고"

**2026-08-29 (설계 확정)**
> 분할 −3% / −5% / −7% (SHORT +3/+5/+7) · TP1 **+5%** 부터 20단계 · 손절 평단 ROI −10% 전량 · 긴추세 = **15분봉**

**2026-09-02 (Fix 299 원문)**
> "급등락하는 심볼투자는 tp1 +15%, 매우 안정적은 상위심볼은 +5%나 +3% 등등 **낮은 익절을 만들어 경우의 수를 가져가야해**"
> "**볼밴 처음에는 tp1 +5%에서 시작을 제안했었어.** 시스템이 제대로 운영이 되지않아 로직을 변경하고 tp1 +15% 유지한거야"

**2026-09-04 (오늘)**
> "빠른 익절은 **볼밴 분할전략에서 만든건데**"

### 1-C. 볼밴 중단선 · 급등중 조정 LONG · 급락 SHORT

**2026-08-30 (사상 v3 ②③④⑤⑥)**
> "롱은 당일 **급등후 큰조정**에 롱으로 들어가서 분할 익절은 우리가 만들어둔 **볼밴 중간 전략**을 사용하면됨"
> "롱은 지금 **급등중인 심볼**을 찾아 **지속상승**에 투자가 확실해 — 몇일 이상 상승하는 심볼"
> "급락한것은 이전급등에 대한 급락이라 확실한 숏 … **볼밴 하단 이탈시 지속적인 하락**에 포지션 진입"
> "**obv가 하락하지 않으면 결국은 obv 방향으로 간다**"
> "큰상승후 큰하락해서 **원점을 간 심볼은** 다시 상승하는 심볼을 찾기는 힘들어"
> "**4시간을 확정된 흐름으로 보고** … 4시간이 조정인데 지속상승하는 심볼은 롱으로 **미리미리 분할 진입**"

### 1-D. 공통 — 손절·추가·재진입·인간의 한계

> (8/31 Fix 232) "기본방식은 OBV전략 다르게 운영을 해야해. 기본전략은 「**기본방식은 가격만 본다**」로 진행해줘"  ← **수동 템플릿(기본 방식)** 얘기. 사다리에 확장한 것은 Claude.
> (9/3) "증거금 주입은 필요없는 기능이야 … 손실이면 10usdt 남기고 부분손절입니다"
> (8/30) "인간이라 **욕심을 제어 하지 못했어** … 큰금액을 손실보면 그때부터는 더 빠른 시간에 큰수익을 위해서 **무리한 투자**를 하면서 손실과 청산을 지속적으로"

---

## 2. 코드 현실 대조표 (전략 가족별)

각 줄에 「값의 출처 = 사장님 인용 / Claude 가 정함 / 출처 불명」을 단다. 줄 번호는 이 worktree(main `39924fc`) 기준.

**운영 DB 실값 (2026-09-04 09:5x KST 조회 — 코드 기본과 다른 것이 많다)**

| 스위치 | 코드 기본 | 운영 실값 |
|---|---|---|
| `stage_trim_before_next_enabled` (부분손절 10 USDT) | OFF | **1 (ON)** |
| `stage_wait_for_turn_enabled` (사다리 2단계 꺾임 대기, SHORT) | OFF | **1 (ON)** |
| `adaptive_tp_enabled` (적응 TP 15/3) | OFF | **1 (ON)** |
| `split_peak_stall_enabled` (볼밴 정점-주춤) | OFF | **1 (ON)** |
| `sajangnim_ladder_stages_enabled` (사다리 단계 방식) | ON | 1 |
| `bb_mid_line_mode` (볼밴 중단선) | shadow | **on (실자금)** |
| `unified_entry_enabled` / `auto_bb_break_daily_limit` | 1 / — | **0 / 0 (둘 다 OFF)** |
| `entry_chg24_gate_enabled` (24h 순위 50+50) | OFF | **1** |
| `trend_4h_gate_enabled` / `confluence_gate_enabled` | OFF / OFF | **1 / true** (반전·재진입은 면제) |
| `support_score_gate_enabled` (지지선 7점) | OFF | 없음 = OFF |
| `sajangnim_pyramid_trigger_roi` | 5 | **2** |
| env `MAX_CONCURRENT_STRATEGIES_PER_ACCOUNT` / `WALLET_LIMIT_PCT` | 10 / 130 | **100** / 130 |

### 2-A. 정점 SHORT / 저점 LONG 사다리 (`_SAJANGNIM_TOP` / `_SAJANGNIM_BOTTOM`, `stage_ladder`)

| 규칙(단계) | 코드가 실제로 하는 것 | 근거 file:line | 숫자 | 출처 | 설정키 |
|---|---|---|---|---|---|
| 1단계 후보 | 상승50∪하락50 중 \|24h\|≥5%·거래대금≥5M → 15m 5지표 score≥3/5, 1h/4h 반대 score≥3 이면 skip → Redis 알람 | `pump_top_detector_worker.py:49-59, 404-413` | 50 / 5% / 5M / 3/5 / conf 0.85 | 50위 verbatim; **5%·0.85·3/5·5M 은 Claude**(「감으로 정한 값이다」) | 감지 워커는 설정 불가 |
| 1단계 정점확인 | 슬롯→활성심볼 skip→conf≥0.85→OBV(SHORT ratio≥0.35 차단)→블록→국면→`confirm_peak`(15m swing≥2 + RSI/MACD/CCI 꺾임≥2/3, 4H 참고만) | `auto_short_at_top_worker.py:130-269`, `peak_confirmation.py:44-51` | swing 2 / 꺾임 2/3 / RSI 65 / CCI 80 / OBV 0.35 | swing 2 = 「한번올랐다 다시 내려오고 2-3번 반복」 verbatim; **꺾임 2·RSI65·CCI80·OBV 0.35 는 Claude** | 없음(상수) |
| 1단계 공용 관문 | Fix274 LONG 24h≥15% → Fix270 4H(OFF, 반전 참고만) → Fix251 되돌림 → Fix247 합의(OFF) → Fix310/325/328 24h 순위 → Fix327 지지선(OFF). **일한도 없음** (동시 보유 상한으로 흡수) | `auto_bb_breakdown_worker.py:1433-1688`, `execution_service.py:207-262` | — | 「15분 기준 4시간 참고」「가능하면 10%」 verbatim; LONG 15%·슬롯 70% Claude | 다수 |
| 1단계 자본 | 사다리 첫 칸 10 (전체자산 무관) | `sajangnim_capital.py:57, 160-166` | 10, 레버 2 | 「10 300 600으로 마틴게일 설정」 verbatim. ⚠️ 주석 「전체 자산 × 1~2%」「300 default」는 낡음 | `sajangnim_capital_ladder` |
| **2단계 트리거** | ① 가격 전제: SHORT `mark ≥ start×1.015` (Fix 232 가격 분기) → ② 130% 가드 → ③ **SHORT 만** Fix 312 「꺾임 대기」(`evaluate_first_entry`: 15m 밴드 밖 지속 → 극값에서 꺾임, 최대 120봉, 강제 진입 없음) → 진입. **LONG 은 ①②만**. 정점-주춤(Fix 260)·재앵커(Fix 209)는 split 전용 = 미적용 | `auto_bb_breakdown_worker.py:1793-1801`, `stage_trigger_worker.py:862-868, 1128-1140`, `execution_service.py:1808-1829`, `stage_entry_timing.py` | 1.5% / 120봉 | 「다음 트리거 단가에 포지션 진입」(Fix315) + 「모니터링 후 좋은 포지션에 진입」(Fix312) verbatim; **1.5%·120봉·SHORT 전용은 Claude 실측**(대기 시 SHORT 32.3→47.6%) | `sajangnim_stage_gap_pct`, `stage_wait_for_turn_enabled`(**DB ON**), `_sides`, `_klines` |
| **3단계 트리거** | 2단계 트리거 × 1.015, 상한 3 | `strategy_calculator.py:264-318` | 1.5% / 3 | 상한 3 verbatim(「가능하면 가지않는」); 간격 Claude | `sajangnim_max_stage` |
| 손절·부분손절 | `force_sl_roi_override=5`(SHORT/LONG 동일, 가격 2.5%). trim ON(DB=1) 이면 잔량 10×레버, ×1.1, 청산분<잔량×2 면 SKIP→다음 단계 있으면 유지(Fix326)/없으면 전량(Fix332). **trim OFF 면 전량+종료** | `risk_service.py:165-253`, `tp_sl_orchestrator.py:640-720`, `stage_trim.py:65-88` | −5 / 10 / ×1.1 / 2 | −5·10 verbatim; ×1.1·2·Fix332 Claude. ⚠️ 이벤트 문구 「전량 강제 청산」 모순 | `stage_trim_before_next_enabled`(코드 OFF, **DB ON**) |
| TP1 / 사다리 | 템플릿 10/15/20/25 → 인스턴스 override 15 → 15/20/25/30. 적응 TP ON(DB) 이면 \|24h\|≥15 → 15, 아니면 **3** | `auto_bb_breakdown_worker.py:1858-1913, 1999-2005`, `adaptive_tp.py:120-162` | 15 / 3 | 15 = 「tp1 단계 시작도 15%로」 verbatim; **3%·경계 15% 는 Claude**; 템플릿 10/15/20/25 출처 불명 | `adaptive_tp_*` |
| 트레일링 | TP 하나라도 발동 후 peak−5 이하 → 전량 | `risk_service.py:740-798` | 5%p | 「tp1 실행후 -5% 회기하면 청산」 verbatim | `trailing_retrace_pct` |
| 피라미딩 | ROI≥설정(코드 5, DB 2) & peak 되돌림≤2.5 & 시작가≥0.5 & 쿨다운 5분 & <2회 & 4H·15m hist 상승 → 300 MARKET 추가, 손절 하향(cap_loss) | `success_pyramiding_worker.py:46-61, 544-603, 762-816` | 2 / 2.5 / 0.5 / 300s / 2회 / 300 | 300·2회 verbatim; **2.5·0.5·300s·지표식·cap_loss Claude**. ⚠️ docstring 「MAX=5」 ≠ 코드 2 | `sajangnim_pyramid_*` |
| 손절 후 재진입 | 24h 내 **종료된** 전략만(활성 심볼 skip = 잔량 남긴 부분손절은 대상 아님), 반등≥1%, 대기≥3분, 지표 2/8→3/8→4/8, 자본 300→600, 라스트 600 | `realtime_reentry_worker.py:62-94, 1119-1162, 1456-1499` | 1% / 3분 / 2·3·4 of 8 / 30% | 사다리·라스트챈스 verbatim; **1%·3분·N/8·30%·±15%·4h 는 Claude** | `sajangnim_reentry_*` |
| 130% 예약 | Σ(실마진 + **미진입 단계 planned_capital 원금**) > wallet×1.3 → 차단 + 30분 쿨다운. 사다리 1건마다 900 예약 | `stage_trigger_worker.py:1308-1351`, `capital_calculator.py:70-125` | 130 | verbatim「130% 까지 허용」; 예약 정의 v112 | env `WALLET_LIMIT_PCT` |
| 동시 보유 상한 | ACTIVE_LIKE ≥ 상한(설정 50→20) 차단. **별도로** `max_concurrent_strategies_per_account`(env, 기본 10) 가 먼저 막을 수 있음 | `position_limit.py:120-147`, `strategy_service.py:263-275` | 20 / 10 | 20 verbatim; 10 출처 불명 | env |

⚠️ **사다리 루프의 세 스위치**가 코드 기본 OFF 다(부분손절 `stage_trim_before_next_enabled`, 좋은 포지션 대기 `stage_wait_for_turn_enabled`, 적응TP). DB 실값은 아래 「실값」 참조.
⚠️ 낡은 docstring 4곳(SL −80% / 자산 1~2% / 300→600→1800 / MAX 5)이 코드와 다르다.

### 2-B. 볼밴 분할 (`split_entry`)

| 규칙(단계) | 코드가 실제로 하는 것 | 근거 file:line | 숫자/임계값 | 출처 | 설정키 |
|---|---|---|---|---|---|
| 1차 후보·방향 | 24h \|변동\|≥15% 상위 40개만, **부호만으로** 방향(+→LONG, −→SHORT). 4H 방향 게이트 없음 | `pump_split_entry_worker.py:131-132, 848-850, 888` | 15% / 40개 / 레버 2 | 「급등락중인 심볼을 모니터링」에 숫자 없음 → **출처 불명** | 없음(하드코딩) |
| 1차 볼밴 위치 | 15m BB(20, 2σ) 완료봉 종가가 LONG=하단 아래 / SHORT=상단 위 | `bb_entry_rules.py:196-205` | 20봉·2σ | 「15분차트로 … 볼밴 하단 이탈」 verbatim, 20/2σ 는 **출처 불명** | 없음 |
| 1차 봉수 | 밴드 밖 연속 봉수 ≥ N (심도와 OR) | `bb_entry_rules.py:114-115, 210-214` | LONG 2 / SHORT 4 | 주석「사장님 "3-5번" / 실측 최선 2」 → **Claude 실측**(사장님 값과 다름) | `pump_split_persist_bars_long/short` |
| 1차 심도 | 밴드 대비 ±D% 넘으면 후보 | `bb_entry_rules.py:116, 215-228` | 10% | 「-10%/+10% 전후」 verbatim | `pump_split_depth_pct` |
| 1차 극값 꺾임 | 극값에서 종가 되돌림 ≥ R% 이면 **무조건 진입** | `bb_entry_rules.py:118-119, 232-252` | LONG 0.6% / SHORT 0.0% | 「실측: LONG 은 0.6%」 → **Claude 실측** | `pump_split_retrace_long/short` |
| 1차 방향 4H | **없음** — Fix 204 로 4H 조회 제거 | `pump_split_entry_worker.py:133, 935` | — | 주석「긴 추세도 15분봉」. 사상 ⑥「4H=방향」과 **어긋남** | `pump_split_long_min_chg24`(기본 OFF) |
| 1차 자본 | 3칸 중 1칸 MARKET | `pump_split_entry_worker.py:118, 703-716` | 100/200/300 | 「자금 100 200 300 이렇게 600」 verbatim (⚠️ `stage_trim.py:72` 주석은 100→200→500) | `pump_split_capitals` |
| 2·3차 가격 간격 | 기준선 대비 3/5/7% 복리 → 실제 간격 2.06/2.11% | `pump_split_entry_worker.py:562-624` | 3/5/7% | 「-3% … 100 / -5% … 200 / -7% … 300」 verbatim | `pump_split_steps` |
| 앵커 | 1차 체결 후 15초마다 **마지막 체결가**로 2·3차 재깔기 | `pump_split_entry_worker.py:626-690`, `stage_trigger_worker.py:480-517` | 동일값 0.01% | 사장님 「b」 verbatim; 0.01% 는 **Claude** | 없음(항상 ON) |
| 2·3차 판정(주춤 OFF) | mark 트리거 도달 AND `check_stage_entry_signal`(OBV+지표 꺾임 2/3) | `stage_trigger_worker.py:865-868, 1047-1099` | — | 「2단계부터는 차트와 보조지표가 조정으로 바뀌면」 verbatim(Fix 218) | `split_peak_stall_enabled`=0 이면 이 경로 |
| 정점-주춤(ON, 현재 운영값) | 극값≥트리거 ① 되돌림≥gap×비율 ② 극값 갱신 정지≥N봉 ③ 3단계 재갱신 ④ 전부 AND, MARKET 강제 | `peak_stall.py:105-125, 226-251`, `stage_trigger_worker.py:896-978` | 주춤 5봉·꺾임 5봉 / 되돌림 gap×0.40(2단계)·×0.55(3단계) / 재갱신 gap×0.15 | verbatim「가다가 주춤 … 꺾이면 3단계」. **숫자는 Claude 추정**(docstring 자인) | 스위치만, 봉수·비율은 **상수** |
| 손절 % | `force_sl_roi_override` 로 평단 ROI 기준, 어느 차수든 발동 | `pump_split_entry_worker.py:124, 985`, `risk_service.py:200-202` | **15%** | 「-15%되면 청산」 verbatim(Fix 218). ⚠️ 주석 모순: 헤더 −10% / risk_service −5% | `pump_split_sl_roi` |
| 부분손절·잔량 | `split_entry` 는 **부분손절 제외** → 손절 시 전량, 잔량 0 | `stage_trim.py:75, 148-155` | 잔량 0 | 주석「일부러 물타기하는 전략이다. 대상 아님」 → **Claude 해석** | 없음(코드 고정) |
| TP1 / 사다리 | 적응TP OFF 면 5% (5/10/15/20). ON 이면 \|24h\|≥15 → 15%. 🚨 **볼밴 후보는 전부 \|24h\|≥15 라 ON = 항상 15%** = 사장님 5% 가 소멸 | `pump_split_entry_worker.py:125-126, 732-739, 996-1006` | 5/10/15/20 · 적응 15 | 「tp1 익절도 5%부터 분할로 25%씩」 verbatim. 배선 구조는 **Claude** | `adaptive_tp_*` |
| 트레일링 | 첫 TP 후 정점 대비 3%p 되돌리면 잔량 청산 | `pump_split_entry_worker.py:127, 986`, `risk_service.py:739-800` | 3%p | 「익절 회기도 -3% 짧게」 verbatim | 없음 |
| 피라미딩 | 2중으로 **제외** | `success_pyramiding_worker.py:464, 495-501` | — | 실측 −252.18 → **Claude 실측**(지시 아님) | 없음 |
| 손절 후 재진입 | 1차 자본 100 그대로, 단 **1단계 단일 전략**으로 재생성(2·3차 없음) | `realtime_reentry_worker.py:565-589, 1580-1590` | ×1.00 / 하루 2회 | 「다시 한번더」 → 2 로 번역 = **Claude** | 없음 |
| 동시 슬롯 | 전용 상한 3 + 계정당 10 | `pump_split_entry_worker.py:860-876`, `strategy_service.py:265-274` | 3 / 10 | 「별도로 상한」 verbatim, 숫자는 **출처 불명** | `pump_split_max_concurrent` |

### 2-C. 볼밴 중단선 · 급등중 조정 LONG · 기타 워커

**볼밴 중단선 (`bb_mid_line_worker`)** — 15분 주기, **mode = shadow (자금 0)**

| 규칙 | 코드 | 근거 | 숫자 | 출처 |
|---|---|---|---|---|
| 진입 | 15m 완료봉: 중단저항(6봉 기울기↓+고가≥중단+종가<중단)→SHORT / 중단하락돌파→SHORT. LONG 2종 OFF | `bb_mid_line.py:143-197` | 6봉 | 「중단지지와 중단저항 그리고 중단돌파 중단하락돌파」 verbatim; ON/OFF 배분은 Claude 실측 |
| 방향 | 15m 트리거, 1H·4H 참고. `mid_break_down` 만 4H 필수. Fix 336 은 **진행중 4H봉** 사용(Fix 291 완료봉 원칙과 어긋남) | `bb_mid_line_worker.py:300-325, 381-390` | — | 헤더 「4H 진입조건은 중단하락돌파 하나뿐」 ↔ Fix 336 모순 |
| 자본·손절·TP | 100×2배 / 가격 −5%(ROI −10%) / 5·10·15·20 + 트레일링 3 (적응TP ON 이면 15 또는 3) | `bb_mid_line_worker.py:46-55, 398-411` | — | 전부 **Claude**(백테스트 가정) |
| 보유 48h 청산 | `ExecutionService(db)` 호출이 **TypeError** → 청산 불능, 예외 삼킴 | `bb_mid_line_worker.py:145` | 48h | 주석 「전량 시장가 청산」 ↔ 코드 불가 |
| 게이트 | 전용 슬롯 3, 상승30∪하락30, 거래대금≥5M. **전체 상한·합의·4H·Fix 274 안 거침** | `surge_ladder_entry.py:122-158` | — | **Claude** |

**급등중 조정 LONG (`surge_pullback`, auto_long_at_bottom 안)**

| 규칙 | 코드 | 근거 | 숫자 | 출처 |
|---|---|---|---|---|
| 진입 | 필수: 3일≥+45% · 4H 되돌림≤0.35 · 볼밴≤1.05 / 선택 4중3: CCI15m≥60·RSI15m≥58·볼밴≥0.70·OBV4H≥0.08 | `surge_pullback.py:56-66, 114-203` | 45/0.35/60/58 | 「급등중에 조정은 다시 급등으로 간다」 verbatim; 숫자는 **Claude 실측**(승12/패13 중앙값) |
| 경로 | **티커 자체스캔 경로에서만** 판정. 알람 경로(`sajangnim:bottom_long:*`)는 판정 없이 직행 | `auto_long_at_bottom_worker.py:1410-1503, 1736` | — | 주석 「자체 스캔은 fallback」 ↔ 실제론 유일한 경로 |
| 자본·단계·손절·TP | 사다리 10/300/600 간격 1.5% / ROI −5% / TP 10·15·20·25 (적응TP 시 덮음) | `auto_bb_breakdown_worker.py:1755-1800, 1906-1910` | — | 10/300/600·−5 verbatim, **1.5%·TP 는 Claude/출처 불명**. 헤더 「−10% 손절」 주석은 값 5 와 모순 |
| 게이트 | BTC 24h<−3% 전체 skip / 후보 \|24h\|≥3% 40심볼 / OBV LONG −0.10 / Fix 274 15%(OFF) / 4H(OFF) / 합의(OFF) | `auto_long_at_bottom_worker.py:203, 1289-1310` | — | **Claude** |

**bb_upper_breakout_short** (5분) — 24h≥+15% 상위 50 → **진행중 15m봉** close>상단+0.3% 또는 3봉 중 2봉 → RSI>70/MACD 3봉↑/볼륨×1.5 중 2 → confirm_peak → 알람. 소비자 = 정점 SHORT 사다리(10, −5%). ⚠️ 주석에 「사장님 verbatim!」이 붙은 숫자(15%·0.3%·70·1.5)가 **원문에 없음** = 출처 불명. 헤더 「300 USDT」는 옛값. (`bb_upper_breakout_short_worker.py:61-64, 139-148, 412-435`)

**macd_reversal_15m** (3분) — 상위 100 → \|24h\|≥15 skip → hist pivot(진행중봉 포함) → 4H 필터 → 볼륨≥1.3 → 알람. ⚠️ 4H 필터가 **OR 로 완화**(상승 **또는** ≥0) = 스케줄러 주석 「4시간 같은 방향」 verbatim 과 반대. (`macd_reversal_15m_worker.py:198-270`)

**resistance_reversal / peak_break_reversal** (30초, 사장님 「전고점 돌파 후 하락 시점에 2단계」) — 조건은 구현돼 있으나 **`ExecutionService(db)` 호출이 TypeError**(api_key/api_secret 누락) → **한 번도 진입한 적 없음**. RR 은 텔레그램 「저항 반전 감지」만 30초마다 반복, PBR 은 `REVERSAL_DETECTED` 상태로 24h 고착. (`resistance_reversal_worker.py:330`, `peak_break_reversal_worker.py:442`)

**auto_bb_break 기본 경로(v174)** — 스케줄 주석 처리(사장님 「통합」 지시) + 무접미사 생성 0. 대체 = `unified_15m_entry`(30초).

**지금 실제로 안 도는 것**: resistance_reversal · peak_break_reversal · bb_mid_line 실진입(shadow) · bb_mid_line 48h 청산 · auto_bb_break 기본 경로 · surge_pullback 알람 경로 · (비활성) time_reverse_exit.

### 2-D. 공통 가드 · 자본 · 청산

| 항목 | 코드가 실제로 하는 것 | 근거 file:line | 숫자 | 출처 | 설정키 |
|---|---|---|---|---|---|
| 130% 「예약」의 정의 (워커) | 전략 1건 = DB 실마진(qty×평단÷레버) + **미발동 단계 planned_capital 합(레버 나눗셈 없음)** | `capital_calculator.py:52-106` | — | 「capital = margin = 지갑 lock 원 금액」(v112) | env `WALLET_LIMIT_PCT` |
| 130% 포함 상태 | STAGE1~9_OPEN(_PENDING)·LIQUIDATED_WAITING_RETRY 만. **익절 진행중(TP*_DONE_PARTIAL)·트레일링 중은 예약에서 빠짐** | `capital_calculator.py:114-125`, `strategy_status.py:116-120` | wallet×1.3 | 「거래소 잔액에 130% 까지 허용하는 걸로만 하자」 verbatim | 130 |
| 130% 워커 차단 | 예약 > wallet×1.3 이면 다음 단계 차단+쿨다운. Binance 실마진은 **알림 문구에만** 씀 | `stage_trigger_worker.py:1316-1342` | 130% | 위 verbatim | — |
| 🚨 130% 가 **세 곳에서 세 가지로** 계산됨 | 생성 시(`strategy_service`)는 plans 합 **÷ 레버**, 대상 = 종료 아닌 전체 / 화면(`exchange_accounts`)은 Binance 실마진 + 미발동 + 미체결 LIMIT / 워커는 위 정의. 주석 「화면과 100% 동일 함수」는 거짓 | `strategy_service.py:379-415`, `exchange_accounts.py:467-471, 671-703`, `stage_trigger_worker.py:1306` | — | 주석끼리 모순 (v112 「나눗셈 X」 vs 2026-06-09 「1000 = 마진 500」) | — |
| 동시 보유 상한 | ACTIVE_LIKE 건수 ≥ 상한이면 차단, 0=OFF, 조회 실패=차단. 진입 워커 11곳 호출 | `position_limit.py:57-147` | 20 | 「일 20개로 하지말고 … 최대 20개」 verbatim | `sajangnim_top_short_daily_limit`(=50 DB) → `auto_bb_break_daily_limit` |
| 재진입 전용 슬롯 | 전체 상한이 차도 재진입 템플릿 수 < 10 이면 진행 | `realtime_reentry_worker.py:978-990` | 10 | 「10개는 가능하게 해줘」 verbatim | `sajangnim_reentry_concurrent_slots` |
| 급등 사다리 상한 | 5, 집계 실패=상한 간주 | `surge_ladder_entry.py:63-104` | 5 | 「표본 없음 — 보수적 초기값」 = **Claude** | `surge_ladder_max_concurrent` (mode=shadow) |
| 24h 순위 게이트 | `start_stage1` 만: 상승50+하락50 안이면 통과, \|24h\|≥10 우선, 슬롯 사용률 ≥70% 면 10% 미만 차단. 수동 `_quick_` 면제 | `chg24_entry_gate.py:70-76, 176-283` | 50 / 10 / 70 | 50·10 은 verbatim, **70 은 Claude** | `entry_chg24_gate_enabled` 외 4키 |
| 4H 추세 게이트 | hist 상승 중 AND 내 편 부호. 반전·재진입은 참고만. auto_bb 경로만 | `trend_4h_gate.py:169-267` | 60봉 | 조건식 **Claude 실측**; 면제는 「15분 기준 4시간 참고」 verbatim | `trend_4h_gate_enabled`(OFF) |
| 합의 게이트 | EMA/VCP+SAR 합의 blocked 면 차단, 반전·재진입 참고만 | `confluence_gate.py:56-189` | — | **Claude 실측**(v139) | `confluence_gate_enabled`(OFF) |
| 지지선 7점 게이트 | `start_stage1` 만, swing_low 접촉 시 LONG≥6 / SHORT≤1 | `support_score.py:164-183, 348-403` | 6/1 | **Claude 실측** | `support_score_gate_enabled`(OFF) |
| 일반 SL | ROI ≤ −template.stop_loss_percent_of_capital, 없으면 50. **화면 기본 90 vs 코드 50** | `risk_service.py:283-320`, `cm-collectors.js:117` | 90/50 | 90 = 「SYNUSDT 사건」, 50 출처 불명 | — |
| SL 단계 게이트·면제 | 단계 남으면 SL 보류(v130). 면제: 재진입 ON / split / stage_ladder / trim ON / force_sl override 명시 | `risk_service.py:165-253` | — | 「다음단계가 남아 있는 경우에는 청산되면 안된다」 verbatim | — |
| Force SL 기본 | 코드 기본 LONG ON/SHORT OFF, ROI 5 → DB 는 둘 다 ON, 80. 전략 override(−5) 우선 | `risk_constants.py:78-81`, `risk_service.py:76-92` | 5/80 | 「모두에게 같은 적용 + 각 전략에 우선」 verbatim | `force_sl_*` |
| 🚨 알림 문구 | `evaluate_force_stop_loss` 가 **청산 방식을 정하기 전에** 「전량 강제 청산 + 전략 종료」를 기록 → 부분손절·유지여도 같은 문구 | `risk_service.py:505`(force), `:344`(일반) | — | 2026-06-24 spec 잔재 | — |
| 부분손절 10 USDT | TRIM(잔량 남김·전략 유지) / SKIP(다음 단계 있으면 유지, 없으면 전량) / BLOCK(전량). 잔량 = 10×레버, 최소 MIN_NOTIONAL×1.1 | `tp_sl_orchestrator.py:546-585, 640-724`, `stage_trim.py:77-88` | 10 / ×1.1 / ratio 2 | 「10usdt 남기고」 verbatim; **ratio 2·1.1·「없으면 전량」은 Claude** | `stage_trim_before_next_enabled`(DB ON) |
| 트레일링 | TP 하나라도 발동 후 peak−retrace 이하면 청산. Fix 335 로 peak≥TP1 조건 해제 | `risk_service.py:737-815` | 전역 5 / 볼밴 3 | 「tp1 실행후 -5% 회기하면 청산」 verbatim; 3 은 Claude | `trailing_require_peak_ge_tp1`(OFF) |
| 피라미딩 트리거 | ROI ≥ 설정값 AND peak 되돌림 ≤2.5% AND 시작가 대비 ≥0.5% AND **4H·15m MACD hist 둘 다 내 편 상승** (게이트 ON), 쿨다운 300s | `success_pyramiding_worker.py:308-352, 576-603, 781-802`, `trend_4h_gate.py:314-384` | 2(DB) / 2.5 / 0.5 / 300s | 「+2%부터」 verbatim → 설정; **지표 지속 조건식·2.5·0.5·300 은 Claude** | `sajangnim_pyramid_trigger_roi`, `pyramid_indicator_gate_enabled` |
| 피라미딩 자본·횟수 | 300 × 최대 2회, preserve 모드 | `success_pyramiding_worker.py:700-816` | 300/2 | 「300으로 고정」「최대 2번까지만」 verbatim | `sajangnim_pyramid_capital` |
| 자동 증거금 주입 | 첫 줄 return + 스케줄 등록 주석 → **폐지 확인** | `auto_add_margin_worker.py:216-221` | — | 「삭제해줘」 verbatim | — |
| Kill-switch 자동 해제 | 사유가 정확히 QTY_MISMATCH_PERSISTENT 이고 stuck 0건일 때만 | `zombie_guardian.py:186-260` | — | **Claude 결정** | — |
| 수정 화면 PATCH | `trigger_percents` 저장 + 마지막 값으로 `last_stage_trigger_percent` 덮어쓰기 + **미발동 plan 의 trigger/price/capital 전부 덮어씀** | `control.py:350-397, 560-575` | — | Fix 234 = Claude | — |
| 🚨 트리거 빈칸 기본값 | 화면이 2단계 **10** / 3단계+ **20** 을 실제 값으로 미리 채우고, 손대지 않은 값도 **그대로 전송** → 저장하면 plan 이 그 값으로 바뀜 | `cm-capitals-grid.js:23-29`, `cm-collectors.js:37-75` | 10/20 | 「2단계만 트리거 10으로 하고 나머진 20%」 verbatim(수동 템플릿용) | — |

---

## 3. 「Claude 가 혼자 정한 값」 — 지금까지 확인된 것

| 값 | 어디 | 사장님 지시? | 처리 제안 |
|---|---|---|---|
| 사다리 단계 간격 **1.5%** | `sajangnim_capital.py:351` `STAGE_GAP_DEFAULT` (설정 `sajangnim_stage_gap_pct`) | 없음 (850사이클 실측으로 정함) | 정점-주춤으로 바꾸면 「새 고점이 진입가보다 최소 얼마 위여야 하나」의 뜻만 남음 → 사장님 값 |
| 사다리 TP1 **3%** (|24h|<15%) | `adaptive_tp.py` + `auto_bb_breakdown_worker.py:1855` | 볼밴 맥락 지시를 사다리에 적용 | 사다리는 **15%** 로 복원, 적응 TP 는 볼밴 분할에만 |
| 볼밴 중단선에도 적응 TP | `bb_mid_line_worker.py:393-407` (Fix 336) | 없음 | 사장님 확인 ② |
| 정점-주춤 파라미터: 주춤 4~5봉 · 되돌림 비율 · 최소전진 | `peak_stall.py` 상수 | 원문은 「주춤」「꺾임」만 | 실측(+97.4)으로 정함 — 값 공개하고 확인 |
| 24h 순위 우선 통과 **10%** / 슬롯 빠듯 **70%** | `chg24_entry_gate.py` (Fix 328) | 「가능하면 10%」는 사장님 | 70% 는 Claude |
| 피라미딩 트리거 ROI **2%** | 설정 `sajangnim_pyramid_trigger_roi` | 사장님 9/3 「+2% 가 아니야, 지표 지속성」 | 지표 지속 조건으로 교체 필요 |
| 지지선 7점 임계 LONG≥6 / SHORT≤1 | `support_score.py` (설정 OFF) | 없음 | OFF 유지, 사장님 확인 |
| 130% 지갑 한도 | env `WALLET_LIMIT_PCT` (기본 130) | 2026-05-19 사장님 | 값은 사장님 것이나 **사다리와 충돌** → 확인 ③ |

**볼밴 분할에서 추가로 확인된 것 (2-B)**

| 값 | 어디 | 사장님 지시? | 처리 제안 |
|---|---|---|---|
| 후보 필터 \|24h\|≥15% · 상위 40개 · 방향 = 부호만 | `pump_split_entry_worker.py:131-132` | 숫자 없음 | 설정키로 빼고 사장님 값 |
| 봉수 LONG 2 / SHORT 4 | `bb_entry_rules.py:114-115` | 사장님 「3-5번」을 실측으로 바꿈 | 사장님 확인 |
| 극값 되돌림 LONG 0.6% / SHORT 0% | `bb_entry_rules.py:118-119` | 없음 | 사장님 확인 |
| 정점-주춤 5종 상수 (주춤 5봉·꺾임 5봉·되돌림 0.40/0.55·재갱신 0.15) | `peak_stall.py` | 「주춤」「꺾임」만 | 설정키로 빼고 값 공개 |
| 재앵커 동일값 허용 0.01% | `pump_split_entry_worker.py:626-690` | 없음 | 무해, 기록만 |
| 볼밴 부분손절 제외 (전량 청산) | `stage_trim.py:75` | 없음 (Claude 해석) | 사장님 확인 ⑥ |
| 볼밴 피라미딩 제외 | `success_pyramiding_worker.py:464` | 없음 (실측 −252) | 사장님 확인 |
| 재진입 = 1차 100 단일 전략(볼밴 구조 없음), 하루 2회 | `realtime_reentry_worker.py:565-589` | 「다시 한번더」 | 사장님 확인 |
| 동시 상한 3 / 계정 10 / SL 90% / BB 20·2σ | 여러 곳 | 출처 불명 | 기록·확인 |
| 볼밴 손절 주석 모순 (헤더 −10% / risk_service −5% / 코드 15%) | `pump_split_entry_worker.py:57`, `risk_service.py:175` | 코드 15% 는 verbatim | 주석 정리 |

**공통 가드에서 추가로 확인된 것 (2-D)**

| 값 | 어디 | 사장님 지시? | 처리 제안 |
|---|---|---|---|
| 24h 게이트 슬롯 빠듯 기준 70% | `chg24_entry_gate.py` | 「가능하면」을 Claude 가 해석 | 사장님 값 |
| 4H 게이트 조건식(hist 상승 AND 부호)·60봉 / 합의 게이트 도입 / 면제 기본 ON | `trend_4h_gate.py`, `confluence_gate.py` | 없음 (실측) | 둘 다 OFF 상태, 기록 |
| 지지선 7규칙·6/1점·swing_low 접촉 | `support_score.py` | 없음 (실측) | OFF 유지 |
| 부분손절 ratio 2 · MIN_NOTIONAL×1.1 · 「다음 단계 없으면 전량」(Fix 332) | `stage_trim.py`, `tp_sl_orchestrator.py` | 「10 USDT 남기고」만 | 사장님 확인 ⑦ |
| 피라미딩 peak 되돌림 2.5 / 시작가 0.5 / 쿨다운 300s / 사이클 3 / 지표 조건식(4H·15m hist 둘 다 상승) | `success_pyramiding_worker.py`, `trend_4h_gate.py:314-384` | 「300 고정」「2번까지」「+2%부터」만 | 사장님 확인 ④ |
| 급등 사다리 동시 5 (shadow) | `surge_ladder_entry.py` | 없음 | 기록 |
| 볼밴 트레일링 3%p | `pump_split_entry_worker.py:127` | 「-3% 짧게」 verbatim 있음 | 유지 |
| Kill-switch 자동 해제 조건 | `zombie_guardian.py` | 「만들어달라」만 | 유지, 기록 |
| 일반 SL 코드 기본 50 (화면 90) / Force SL SHORT 코드 기본 OFF (DB ON) / 수정화면 트리거 10·20 | 여러 곳 | 출처 불명 | 코드 기본을 DB·화면과 맞춤 |

**기타 워커에서 추가로 확인된 것 (2-C)**

| 값 | 어디 | 사장님 지시? | 처리 제안 |
|---|---|---|---|
| 볼밴 중단선: shadow · 자본 100·레버 2 · 슬롯 3 · top 30 · SL 가격 5% · TP 5/10/15/20 · 보유 48h · 쿨다운 8h · LONG 2종 OFF | `bb_mid_line_worker.py:42-55` | 패턴 4종 verbatim 만 | 사장님 값·ON/OFF 확인 |
| 급등중 조정 LONG 8개 임계(45/0.35/1.05/60/58/0.70/0.08/4중3) | `surge_pullback.py:56-66` | 「급등중 조정은 다시 급등」만 | 실측 근거 공개 후 확인 |
| 저점 LONG 후보: BTC −3% skip · \|24h\|≥3% · 40심볼 · conf 0.85 | `auto_long_at_bottom_worker.py:203` | 없음 | 설정키로 |
| bb_upper: 15% / 0.3% / RSI 70 / 볼륨 1.5 / 2중3 / 50심볼 | `bb_upper_breakout_short_worker.py:61-64` | 「상단돌파 마틴게일」만 (숫자 없음) | 「verbatim」 라벨 제거, 확인 |
| macd 반전: 100심볼 / 극단 15 / 볼륨 1.3 / 4H OR 완화 | `macd_reversal_15m_worker.py` | 「15분과 4시간의 움직임」만 | 4H 를 AND 로 되돌릴지 확인 |
| 저항·정점돌파 반전: 1% 근접 / 꼬리 1.5 / RSI −3 / 볼륨 1.2 / 672봉 | `resistance_reversal_worker.py:23-35`, `peak_break_reversal_worker.py:34-37` | 「전고점 … 2단계」만 | 버그 수정 후 값 확인 |
| 공통 TP 기본 10/15/20/25 · tp1 수량 10% · OBV 0.35/−0.10 | `auto_bb_breakdown_worker.py:1906-1910` | 없음 | 확인 |

**사다리에서 추가로 확인된 것 (2-A)**

| 값 | 어디 | 사장님 지시? | 처리 제안 |
|---|---|---|---|
| 정점 감지: 24h 하한 5% · conf 0.85(+0.03/점) · 15m score 3/5 · 반대 3 · 거래대금 5M | `pump_top_detector_worker.py:49-59` | 「50위」만 | 설정키로, 값 확인 |
| 정점확인: 지표 꺾임 2/3 · RSI 65/35 · CCI ±80 · 40봉 | `peak_confirmation.py:44-51` | 「2-3번 반복」만 | 확인 |
| OBV 게이트 SHORT 0.35 / LONG 0.6 | `obv_gate.py:29, 49` | 없음 (실측) | 확인 |
| 좋은 포지션 대기(Fix 312) SHORT 전용 · 120봉 · 기본 OFF | `execution_service.py:1808-1829` | 「모니터링 후 좋은 포지션에 진입」 verbatim 있음 | 정점-주춤과 통합 여부 확인 ① |
| 재진입: 반등 1% · 대기 3분 · 지표 2/3/4 of 8 · 볼륨 1.3 · 3단계 ±15%·4h · 1h 5건 · 학습 30% | `realtime_reentry_worker.py:62-94` | 사다리 자본만 | 확인 |
| 템플릿 TP 10/15/20/25 · 수량비 10/15/20/25 · 계정당 10 | `auto_bb_breakdown_worker.py:1906-1910`, `config.py:38` | 출처 불명 | 확인 |

---

## 4. 바로잡는 방법

1. **이 문서 2절이 완성되면 사장님이 표를 보고 O/X** — 확인 ①②③ 부터.
2. O 가 난 것만 고친다. 순서:
   - **사상 무관 버그(확인 없이 바로 가능)**: `ExecutionService(db)` 인자 누락 3곳(저항 반전·정점 돌파 반전·중단선 48h 청산) / 알림 문구 「전량 청산」 / 「사장님 verbatim!」 거짓 라벨 제거 / 주석·코드 모순 정리(볼밴 손절 −10/−5/15, 피라미딩 docstring, 「화면과 100% 동일 함수」).
   - **확인 ① 후**: 사다리 2·3단계 = 정점-주춤 하나로 통일(`_is_split` 게이트에 `stage_ladder` 추가 + 되돌리기 설정 `ladder_peak_stall_enabled`; Fix 312 꺾임 대기는 중복이므로 사다리에서 끔). 정점-주춤 상수 5종을 설정키로. 실행 테스트(Fix 320 방식)로 「가격만 닿고 꺾임 없으면 진입 안 함 / 꺾이면 MARKET 진입 / 3단계는 재갱신 필수」 3건 고정.
   - **확인 ② 후**: 적응 TP 를 볼밴 분할에서도 「항상 15%」가 되지 않게(볼밴 후보는 전부 \|24h\|≥15%) — 사장님 5% 복원 또는 기준 재정의. 사다리는 15%.
   - **확인 ③ 후**: 130% 예약을 **한 함수·한 정의**로 통일하고, 사다리 미진입 단계의 예약 취급을 사장님 결정대로.
   - **확인 ④ 후**: 피라미딩 = 「지표 지속」 정의(지금은 ROI≥2 AND 4H·15m hist 상승).
   - 수정 화면: 자동 사다리 전략은 트리거 기본값(10/20)을 **채우지 않는다** — 원래 값 유지.
3. 고칠 때마다 **실행 테스트**(Fix 320 방식: 실제 함수 호출 + 주문 가로채기) + AST 호출경로 강제 → 배포 → 실로그로 확인.
4. 앞으로의 규칙 (Claude 가 지킬 것):
   - 숫자를 정해야 하면 **설정키로 빼고 기본값은 사장님이 말한 값**. 사장님 말이 없으면 「Claude 가 정함」이라고 코드 주석과 이 문서에 적는다.
   - 어떤 지시든 **전략 가족(A/B/C) 을 명시**해서 적용한다. 공용 경로에 붙이지 않는다.
   - 「사장님 verbatim」이라고 주석에 쓴 문장은 실제 채팅 원문만.

---

## 5-0. 사장님 결정 기록 (2026-09-04 09:5x KST)

> 사장님: **"실자금으로 운영하고 123으로 진행해줘"**

| # | 결정 | 구현 | 커밋 |
|---|---|---|---|
| ① | 사다리 2·3단계 = 정점-주춤 하나로 (LONG 포함), +1.5% 는 「새 극값 최소 폭」 뜻만 | **Fix 342** `stage_trigger_worker` `_is_ladder` + `ladder_peak_stall_enabled`(기본 ON) / `execution_service` Fix 312 대기 생략 | `1673481` |
| ② | 사다리 TP1 15% / 볼밴 분할 TP1 5% (적응 TP 는 두 경로에서 뗌) | **Fix 343** `auto_bb_breakdown_worker` `_is_ladder_tpl` / `pump_split_entry_worker` Fix 336-c 제거 | `1673481` |
| ③ | (a) 사다리 미진입 단계는 예약에서 제외 + 발주 직전 가용 잔고 검사 | **Fix 344** `capital_calculator.ladder_reserves_untriggered`(설정 `ladder_reserve_untriggered_enabled` 기본 0) + `strategy_service` 동일 규칙 + `availableBalance ≥ planned×1.02` | `1673481` |
| ⑧ | 볼밴 중단선 **실자금 운영 유지** (변경 없음) | — | — |
| ⑤ | 열린 사다리 7건의 TP1 3% → 15% DB 수정 | **미결** (사장님 결정 대기, 신규 사다리부터 15%) | — |

되돌리기(재시작 불필요): `ladder_peak_stall_enabled=0` / `ladder_reserve_untriggered_enabled=1`. 적응 TP 분리는 코드라 커밋 되돌림.

## 5. 사장님 확인 필요 (O/X)

| # | 질문 | 제 해석 |
|---|---|---|
| ① | 사다리 2·3단계 판정. 지금은 「가격 +1.5%」 전제 + SHORT 만 꺾임 대기(Fix 312) 이고, 3단계 「다시 최고점 → 꺾임」은 없음. (a) Fix 260 정점-주춤(극값 기준 주춤/꺾임 + 3단계 재갱신)으로 **통일** (b) +1.5% 가격 전제를 **없앨지** (c) LONG 도 같은 판정을 쓸지 | (a) O, (b) 「새 고점이 진입가보다 최소 얼마 위」로 뜻만 남김, (c) O — 사장님 「최저점도 같은 전략」 |
| ② | 적응 TP(급등락 15%/안정 3%)는 **볼밴 분할에만**. 볼밴 중단선은? 사다리는 15% | 사다리 15% 확실, 중단선은 모름 |
| ③ | 130% 예약 가드: (a) 미진입 단계는 예약에서 뺀다 (b) 한도를 올린다 (c) 동시 사다리 수를 제한한다 | (a) 가 사다리 사상과 맞음. 대신 2단계 발주 직전 실잔고 검사 유지 |
| ④ | 피라미딩 조건 = ROI 2% 대신 「지표 지속」— 어떤 지표·몇 봉? | 15m MACD hist 방향 + OBV 기울기 (실측 후 제안) |
| ⑤ | 지금 열린 사다리 7건의 TP1 3% 를 15% 로 되돌릴지 (DB 수정) | 사장님 결정 |
| ⑥ | 볼밴 분할도 「10 USDT 남기고 부분손절」 대상인가, 아니면 물타기라 전량 청산이 맞나 (지금 = 전량, Claude 해석) | 모름 |
| ⑦ | 부분손절 세부값: 잔량 10 USDT 는 확정. 「최소 정리 비율 2배」「MIN_NOTIONAL×1.1」「다음 단계 없으면 전량」(Fix 332)은 Claude 값 | 유지 제안, 확인 |
| ⑧ | 볼밴 중단선 전략을 실자금으로 켤지 (지금 shadow, 자본 100·레버 2·슬롯 3 전부 Claude 값) | 사장님 결정 |
| ⑨ | 저항 반전·정점 돌파 반전 워커(「전고점 돌파 후 하락 시점에 2단계」)를 버그 수정 후 **켤지** — 사다리 2단계(정점-주춤)와 역할이 겹침 | 정점-주춤 하나로 통일 제안 |
| ⑩ | 볼밴 1차 봉수 LONG 2 / SHORT 4 (사장님 「3-5번」을 실측으로 바꿈) 유지할지 | 사장님 결정 |
