# 진입 조건 연구 (Fix 375, 2026-09-17) — 재측정 절차

데이터 파일(csv·parquet·klines/)은 커밋하지 않는다 (.gitignore). 모두 **읽기 전용**.

1. 운영 가상 진입 내보내기 (VPS 읽기만):
   `ssh root@<VPS> "cd ~/binance-auto-trader/backend && docker compose exec -T api python -" < export_paper_rows.py > dumpall.csv`
2. 봉 받기 (로컬 IP · 바이낸스 공개 API · 요청 무게 조절): `python fetch_klines.py`
3. 진입 시점에 닫힌 봉만으로 chart_state 재계산: `python build_features.py`
4. 규칙별 탐색 `python analyze.py` → 방향별 공통 조건 `python analyze_side.py` → 미리 정한 가설 `python hypo.py`
5. 운영 게이트 모듈(app/services/entry_conditions.py)로 같은 데이터 재생: `python replay_gate.py`

원칙: 조건은 사전등록 **이전** 표본에서 고르고 **이후** 표본으로만 검증한다. 규칙마다 고른 조건은 대부분 검증에서 뒤집혔다.
결과: docs/learning/ENTRY_CONDITIONS_2026-09-17.md

## 2026-09-18 추가 (Fix 377 상승 초입 LONG)
- `fetch_update.py` — 캐시에 최신 봉만 덧붙인다 (없는 심볼은 전체 받음).
- `long_surge.py` → `surge_final.py` → `surge_pick.py` 순으로 상승 초입 LONG 조건을 좁혔다.
  (「급등 뒤 1시간 되돌림」 가설은 검증에서 뒤집혀 기각 — 과정이 그대로 남아 있다.)
- `replay_surge.py` — 운영 모듈(entry_conditions, family='rf_surge_long')로 같은 데이터를 재생해 수치 일치 확인.

결과: docs/learning/SURGE_START_LONG_2026-09-18.md

## 2026-09-18 추가 (Fix 378 미세조정 후보)
- `regime.py` — 시장 국면(상승/보합/하락)별로 게이트 P5·P6·P7 을 다시 재서, 하루치 역전이 표본 문제였음을 확인한다.
- `tune.py` — 미세조정 후보를 발견·검증 두 기간에서 동시에 재고, **둘 다 통과 쪽이 나은 것만** ✅ 로 표시한다.
  채택(사전등록)된 것은 P8(SHORT·1H ATR ≤1.5) · P9(SHORT·4H 하단이탈 14봉+) · P10(LONG 게이트 or (P7 & 일봉 %B ≤0.5)).

결과: docs/learning/TUNING_CANDIDATES_2026-09-18.md
- `tune_p9.py` — P9 의 `h4_bb_bars_since_below_lower` 가 **없음(None)** 인 행(38%)을 어떻게 볼지 6가지로 갈라 재본다.
  결론: 「이탈 없음」은 취지상 통과처럼 보이지만 발견 +2.79 / 검증 −0.62 로 뒤집혀 **universe 에서 뺀다**.

## 2026-09-19 추가 — 기회 지도 (규칙 신호와 무관하게 모든 자리를 채점)
- `opportunity_scan.py` — 모든 종목 · 모든 1시간 마감에 LONG/SHORT 둘 다 진입했다고 치고 실매매 청산 규칙(손절 −25 · TP1 15 · 트레일링)으로 24시간 채점. 24시간이 다 지난 자리만 쓴다(검열 편향 없음). → `opportunity.parquet`
- `zones.py` (지표 1개) → `zones_flip.py` (무엇이 뒤집혔나) → `zones2.py l|s` (지표 2개 · 두 기간+날짜별) → `zones_final.py` (주제를 단순 규칙으로 고정해 지금 게이트와 비교)

결과: docs/learning/OPPORTUNITY_ZONES_2026-09-19.md
- `parity_oz.py` — 운영 모듈 `opportunity_zones`(Fix 379 가상 규칙)가 분석과 같은 자리를 고르는지 워커와 같은 재료로 대조 (L1 100% · S4 99.85%).

## 2026-09-19 추가 — 사장님 첨부 전략서 「볼린저 밴드 & 세력 CCI」
- `bbcci_backtest.py` (전략서 신호 A/A+/B × 15m·1h · 전략서 청산과 우리 청산 둘 다) → `bbcci_eval.py` (무작위 대비) → `bbcci_filter.py` (필터로 쓰면?)

결과: docs/learning/BB_FORCE_CCI_2026-09-19.md
