---
name: new-strategy
description: 새 매매 전략(사장님 첨부 md·yaml·설명)을 자동매매에 편입하는 표준 절차 — 명세 정리 → 사전 백테스트 → /duel 구현(shadow) → 가상매매 등록 → 전략 운영팀 성적표 자동 편입 → 승격 기준 → 사장님 승인. 사용법 /new-strategy <과제명> <전략 파일 경로 또는 설명>
---

# 새 전략 편입 절차 (전략 운영팀)

새 전략은 **혼자 켜지지 않는다.** 기존 전략들과 같은 잣대(같은 날 무작위 대비 edge · 장세별 · 겹침)로 비교되고,
운영팀 배치표가 「이 장세에서 이 칸을 쓴다」고 고를 때만 쓰인다. 실주문 승격은 언제나 사장님이 한다.

## 0. 시작 전
- 대시보드(Obsidian `00 대시보드.md`)·`git log -5`·`docs/spec/STRATEGY_COUNCIL_2026-10-10.md` 확인.
- 전략 문서의 숫자는 **verbatim** 으로 옮기고, 문서에 없는 숫자는 설정 키로 빼서 「Claude가 정함」이라 적는다 (CLAUDE.md 규칙 4).
- 판정 봉을 문서 숫자에서 정한다(예: 「30일」 → 일봉). 애매하면 그때만 사장님께 묻는다.

## 1. 사전 백테스트 (구현 전, 로컬, 공개 API·키 없음)
`backend/scripts/entry_condition_study/` 에 `<이름>_backtest.py`. 판정은 **운영과 같은 함수**를 import 해서 쓴다.
- 반드시: 겹침 없음(청산 뒤에만 재진입) · 연도별 · 무작위/2R 고정 비교 · 수수료 미반영 명시 · 생존 편향 명시
- `strategy-auditor` 에이전트로 렌즈 8개 반박을 받는다.
- 결과가 나빠도 그림자로는 넣는다(운영 데이터가 진짜 판정). 단 보고에 그대로 적는다.

## 2. 구현 = /duel → /merge (CLAUDE.md 규칙 10)
**가장 쉬운 길 (Fix 431·432):** 판정 모듈에 `PREFIX·STYPE·SETTINGS·params_from·min_bars·evaluate(bars, j, side, p, cache)` 를 두고
`app/workers/external_strategies_worker.py` 의 `FAMILIES` 에 `FL.Family("<key>", 모듈, "이름", ("봉",…), force_shadow=…)` 한 줄 → 루프는 `ext_family_loop.py` 가 공용으로 돈다.
가상 규칙은 `PAPER_RULES`(15분 `ctx.kl15` 또는 일봉 `ctx.kl1d`) → chart_learning RULES 에 추가하면 운영팀 성적표에 자동 편입.

그 밖의 등록 지점(Fix 423·429·431 을 본보기로):
| 곳 | 할 일 |
|---|---|
| `app/services/<이름>.py` | 지표·판정 순수 함수 · SETTINGS(기본 `<접두>_mode=shadow`) · `params_from` · 가상 규칙 `PAPER_RULES` |
| `app/services/external_strategies.py` | `SETTINGS.update(...)` |
| `app/workers/external_strategies_worker.py` | 모드 읽기 · 봉 마감 게이트 키 · 판정 루프 · 그림자 기록 · 실주문 = `create_surge_position` |
| `app/services/chart_learning.py` | 가상 규칙 RULES 에 추가 (← **운영팀 성적표 자동 편입은 이것 하나로 된다**) |
| `app/workers/paper_trading_worker.py` | 설정 주입(`set_paper_params`) |
| `app/services/auto_control.py` | 관제실 패널 + `LINE_ORDER` |
| `app/services/auto_family_registry.py` · `single_entry_guard.py` · `api/v1/terminal.py` | 가족 등록 |
| `scripts/entry_condition_study/ext_rules_report.py` · `scripts/verify_fix364_deploy.py` | 보고서 접두사 · 배포 검사 표식 |
| `tests/test_fixNNN_<이름>.py` + 규칙 수 핀(test_fix353·361·374) | |
매매 판정 코드는 초안·감사를 참고만 하고 **리드가 직접** 쓴다(규칙 3). 실주문 청산이 검증한 청산과 다르면 `on` 을 shadow 로 강제한다(Fix 429 선례).

## 3. 배포 뒤 (사장님 「배포」 승인 뒤에만)
- 검사기 PASS · 첫 사이클 로그에 새 모드·신호 키·오류 0 확인 → Fix 노트 「배포됨」, 판정 기준 시각 기록.
- 다음 날부터 운영팀 성적표(`council:latest`) F 항목에 새 규칙이 「표본 부족」으로 나타나는지 확인.

## 4. 승격 기준 (모두 「Claude가 정함」 — 사장님이 바꿀 수 있음)
shadow → **실주문 후보**로 사장님께 올리는 조건:
1. 배포 뒤 가상 n ≥ 100, 진입일 ≥ 10일
2. 운영팀 배치표(E)에 최근 14일 중 7일 이상 「사용 후보」
3. 같은 날 무작위 대비 edge > 0 인 장세 구간이 2개 이상 (한 장세 전용이면 「장세 전용」으로 표시하고 그 구간 게이트와 함께만)
4. `strategy-auditor` 판정 통과 또는 조건부(조건 충족)
5. 실주문 경로(진입가·청산·수량)가 검증한 경로와 같음
6. **사장님 승인** — 에이전트는 모드를 바꾸지 않는다

강등 권고(on → shadow): F 「중지 후보」 7일 연속 · 가족 손실 차단기(Fix 384) 발동 · 전진 검증 최악의 날이 새 기록.

## 5. 기록 (규칙 11)
Fix 노트 · 개발일지 · 대시보드 「진행 중 · 예정 판정」에 판정 예정일(배포 + 14일) 등록.
