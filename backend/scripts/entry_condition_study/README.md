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
