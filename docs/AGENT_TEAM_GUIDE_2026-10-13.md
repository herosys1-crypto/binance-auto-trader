# 에이전트 팀 안내서 (2026-10-13)

> 사장님 10/13 「우리 구성되어있는 에이전트팀을 확인해주고 다른 프로젝트에서 쓸 수 있게 md 파일로 만들어줘」.
> 지금 있는 에이전트·명령·스킬을 **어디서 쓸 수 있는지** 기준으로 정리하고, 다른 프로젝트에서 쓰는 법을 적는다.

## 0. 범위 규칙 (Claude Code)
| 위치 | 쓸 수 있는 곳 | 같은 이름이 둘 다 있으면 |
|---|---|---|
| `~/.claude/agents/*.md` · `~/.claude/commands/*.md` · `~/.claude/skills/*/` | **모든 프로젝트** (사용자 범위) | 프로젝트 쪽이 우선 |
| `<프로젝트>/.claude/agents/` · `commands/` · `skills/` | 그 프로젝트만 | — |

호출: 에이전트 = 대화에서 「locator 로 찾아줘」 또는 Agent 도구 `subagent_type: "locator"` · 명령 = `/duel 과제명 요구사항` · 스킬 = `/스킬이름`.

## 1. 모든 프로젝트에서 바로 쓰는 팀 (사용자 범위)

### 1-1. 범용 실무 3인 (10/13 이 프로젝트에서 일반화해 옮김)
| 에이전트 | 모델 | 맡는 일 | 하지 않는 일 |
|---|---|---|---|
| `locator` | haiku | 「어디서 정의·읽나·누가 집어가나」 위치 찾기 — **결론만** 보고(컨텍스트 절약) | 코드 수정 · 추측 |
| `mech` | haiku | 테스트 실행·실패 분류(신규/기존/수집 오류) · 문법·타입 검사 · 로그 세기 | 핵심 로직 판단 · 테스트를 고쳐서 통과시키기 |
| `impl` | sonnet | UI·API·문서·스크립트·테스트·리팩터링 구현 | 돈·권한·데이터 삭제 판정, CLAUDE.md 가 「리드 전용」이라 한 코드 |
파일: `~/.claude/agents/locator.md` · `mech.md` · `impl.md` (이 프로젝트 `.claude/agents/` 의 원본은 매매 문구가 들어간 채 그대로 — 여기서는 원본이 우선)

### 1-2. 개발 파이프라인 명령
| 명령 | 하는 일 |
|---|---|
| `/duel 과제명 요구사항` | GPT·Claude 가 초안을 따로 쓰고 서로 교차 감사 (`C:\ai_hq\02_Output\Duel_Lab\<과제명>\`) |
| `/merge 과제명` | 리드가 감사 반영해 병합·테스트 → Gemini 심판 PASS/FAIL → Obsidian 기록 |
⚠️ 요구사항은 외부 AI 3곳으로 전송 — 비밀·서버 정보 금지. Anthropic API 크레딧이 부족하면 Claude 초안이 실패한다(그땐 세션 안 반박 리뷰 에이전트로 대체).

### 1-3. GSD 개발 팀 (에이전트 33 + 스킬)
`gsd-planner` · `gsd-executor` · `gsd-verifier` · `gsd-code-reviewer` · `gsd-debugger` · `gsd-doc-writer` · `gsd-security-auditor` 등.
큰 기능을 「단계(phase) → 계획 → 실행 → 검증」으로 나눌 때 `/gsd-new-project` · `/gsd-plan-phase` · `/gsd-execute-phase` 로 시작. `.planning/` 폴더를 만든다.

### 1-4. 그 밖의 사용자 스킬
`fastapi` · `agent-browser` · `binance`(binance-cli) · `crypto-regime-analyzer`(코인 장세 점수) · `design-taste-frontend` · `find-skills` 등.

## 2. 이 프로젝트 전용 (binance-auto-trader)
| 이름 | 종류 | 역할 | 다른 프로젝트로 |
|---|---|---|---|
| `strategy-analyst` | 에이전트(sonnet, 읽기 전용) | 전략 운영팀 **분석관** — 성적표·가상·그림자·실거래를 읽고 「어떤 전략을 어떤 장세에, 무엇과 같이」를 숫자로 | 트레이딩 프로젝트만 — 아래 3절 |
| `strategy-auditor` | 에이전트(sonnet, 읽기 전용) | 전략 운영팀 **반박 감사관** — 미래 참조·생존 편향·겹친 거래·장세 편중·표본 부족·실주문 경로 차이로 결론을 깨 본다 | 〃 |
| `/new-strategy` | 스킬 | 새 전략 편입 표준 절차(명세 → 사전 백테스트 → /duel 구현 shadow → 가상 등록 → 성적표 편입 → 승격 기준 → 사장님 승인) | 〃 (DB·Redis 키를 바꿔야 함) |
| `/strategy-review` | 스킬 | 운영팀 정기 회의 — 분석관·감사관 동시 검토 → 리드가 쓸 칸/멈출 후보/조합/승격·강등 권고 | 〃 |
| `impl` · `locator` · `mech` | 에이전트 | 1-1 의 원본(매매 문구 포함) | 이미 일반화본이 사용자 범위에 있음 |
| `sparc/` · `swarm/` · `consensus/` · `testing/` · `core/` · `browser/` 에이전트, `v3-*` · `agentdb-*` · `github-*` · `swarm-*` 스킬, `.claude/commands/` 하위 | Ruflo 자동 생성 | 스웜·합의·SPARC 방법론 | 다른 프로젝트에서 `npx ruflo@latest init` 하면 똑같이 생긴다 (복사 불필요) |

### 이 프로젝트에서의 역할 분담 (CLAUDE.md 규칙 3·10)
- **리드(메인 세션)**: 매매 판정 코드(진입·손절·자본·단계)를 직접 쓴다 · 병합·배포·기록
- **impl**: UI·API·문서·테스트·리팩터링만 · **locator/mech**: 찾기·기계 점검
- **/duel → /merge**: 개발 기본 경로(한두 줄 수정·문서·읽기 측정·긴급 대응은 예외)
- **분석관 + 감사관**: 전략을 켜고 끄는 결론 전에 항상 둘 다 — 반박을 통과한 결론만 사장님께

## 3. 다른 프로젝트에서 쓰는 법

### 3-1. 일반 프로젝트 (웹·API·자동화 등)
1. 아무것도 복사할 필요 없다 — `locator` · `mech` · `impl` · `/duel` · `/merge` · GSD 가 이미 보인다.
2. 그 프로젝트 루트에 `CLAUDE.md` 를 두고 **「리드만 쓰는 코드」**(돈·권한·삭제 등)를 적는다 → `impl` 이 그 영역을 거절한다.
3. (선택) 스웜이 필요하면 `npx ruflo@latest init` .

### 3-2. 다른 트레이딩 프로젝트 (전략 운영팀까지)
1. 이 저장소에서 복사:
   ```
   .claude/agents/strategy-analyst.md   → <새 프로젝트>/.claude/agents/
   .claude/agents/strategy-auditor.md   → <새 프로젝트>/.claude/agents/
   .claude/skills/new-strategy/         → <새 프로젝트>/.claude/skills/
   .claude/skills/strategy-review/      → <새 프로젝트>/.claude/skills/
   ```
2. 파일 안에서 바꿀 것: 성적표 위치(`council:latest` Redis 키) · 가상매매 표 이름(`paper_trades`) · 운영 서버 조회 명령 · 판정 스크립트 경로(`verdict_2026_10_25.py`) · 「사장님 승인」 절차.
3. 그 프로젝트에 성적표가 없다면 분석관은 「백테스트 결과·거래 기록 CSV」를 읽도록 입력 부분만 바꿔 쓴다 — 감사관의 반박 렌즈(미래 참조·생존 편향·겹친 거래·장세 편중·표본 부족·실주문 차이)는 그대로 쓸 수 있다.
4. 사용자 범위로 올리지 않는다 — 트레이딩이 아닌 프로젝트에서 잘못 불리는 것을 막기 위해.

## 3-3. 🎼 오케스트라 에이전트 팀 (프로그램 안 · 사장님이 8/11~8/25 구성)
Claude Code 에이전트(`.claude/agents`)가 **아니라** 자동매매 프로그램 안의 Python 코드 — `backend/app/agents/` (운영 서버에서 돌고 있다).
- 지휘자 `orchestrator/` — `GrandOrchestrator`(8/11 「개별 에이전트를 총괄지휘하는 지휘자」) · 이벤트 버스(30+ 이벤트) · 팀 리더 공통 틀(`team_lead_base`)
- 팀 17개: `strategy_suggestion_team`(9, 1,515줄 — 매일 전략 제안) · `learning_team`(5) · `chart_pattern_learning_team`(5) · `coding_team`(6 — 8/16 「코딩·기획 2팀」) · `planning_team`(6) · `entry_team` · `market_flow_team` · `timezone_pattern_team` · 그리고 틀만 있는 `tp/sl/capital/alert/analysis/audit/maintenance/monitoring/ui_team`(각 13~16줄)
- 10/13 운영 로그(48h): 이벤트 버스 879 · 팀 리더 공통 66 · 학습 팀 10 · 차트 패턴 학습 팀 10 · 전략 제안 팀 4 — **살아 있다**. 상태 감시 `orchestra_health_worker`
- 설명서: `backend/app/agents/TEAMS.md` · `README.md` · `docs/ORCHESTRA_INTEGRATION_SPEC.md`
- 다른 프로젝트로: 매매 DB·워커에 묶인 코드라 그대로는 못 옮긴다 → **범용 템플릿 `templates/orchestra/`** (10/13, 표준 라이브러리만 · 지휘자 Conductor · 팀 리더 TeamLead · 에이전트 Agent · 이벤트 버스 · 규칙집 Rulebook · 예시 3팀 · 테스트 9개). 사용법은 그 폴더 README — `orchestra/` 를 새 프로젝트에 복사하고 팀만 새로 만든다.

## 4. 바꿀 때
- 사용자 범위 에이전트를 고치면 **모든 프로젝트**에 바로 적용된다 → 프로젝트 특유 규칙은 넣지 말고 그 프로젝트 `CLAUDE.md` 에 쓴다.
- 이 프로젝트 원본(`.claude/agents/impl.md` 등)과 사용자 범위 일반화본은 따로 관리한다.
