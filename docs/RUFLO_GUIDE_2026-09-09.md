# Ruflo 로 개발 이어가기 — 설치 완료 상태와 사용법 (2026-09-09)

> 사장님: "ruflo를 활용해서 개발을 이어가고 싶어 어떻게 해야 하는지 자세히 알려주고 그렇게 할 수 있게 만들어줘"

## 0. Ruflo 가 뭔가
Ruflo(옛 이름 Claude-Flow, ruvnet 제작, MIT)는 **Claude Code 위에 얹는 에이전트 조율 층**이다. Claude Code 가 실행자이고, Ruflo 는 ① 여러 에이전트를 스웜(팀)으로 굴리고 ② 작업·학습을 로컬 벡터 메모리(`.swarm/memory.db`)에 남기고 ③ 세션 시작/편집/명령 때마다 훅으로 자동 기록·라우팅하고 ④ MCP 서버로 300여 개 도구(메모리·스웜·보안·성능)를 Claude 에 붙인다. 모델 비용 외에 추가 비용은 없다.

이 PC 에는 **v3.39.0** 이 프로젝트 루트(`C:\Users\user\바이낸스\binance-auto-trader`)에 설치·등록돼 있다. Node 24 / npm 11 이면 된다.

## 1. 설치된 것 (전부 커밋됨, 비밀 없음)
| 항목 | 위치 | 역할 |
|---|---|---|
| MCP 서버 등록 | `.mcp.json` → `claude-flow` = `cmd /c npx -y ruflo@latest mcp start` | Claude 세션에서 `mcp__claude-flow__*` 도구 사용 |
| 훅·권한 | `.claude/settings.json` | 세션 시작/종료, 편집 전후, 명령 전후, 컴팩션 때 `.claude/helpers/hook-handler.cjs` 실행. 권한은 ruflo 명령·MCP 만 허용, `.env` 읽기 금지 |
| 에이전트/커맨드/스킬 | `.claude/agents/*`, `.claude/commands/*`, `.claude/skills/*` | 17 에이전트(코더·리뷰어·테스터·아키텍트…), 슬래시 커맨드 16, 스킬 30 |
| 프로젝트 지침 | `CLAUDE.md` | **맨 위 = 이 프로젝트 규칙 9개**(비밀·주문·매매 판정·설정 키·가족별·실검증·stash·줄끝·문서 위치), 그 아래 Ruflo 일반 지침 |
| 런타임 설정 | `.claude-flow/config.yaml` | 토폴로지 hierarchical-mesh, 최대 15 에이전트, 메모리 hybrid |
| 로컬 데이터 (미커밋) | `.swarm/memory.db`, `.claude-flow/data|logs|sessions|neural` | `.gitignore` 에 넣음 |

제가 손댄 것: 앱의 모델 선택을 덮지 않도록 `settings.json` 의 `model` 키 제거, `Co-Authored-By` 금지 문장을 이 프로젝트 관례(붙인다)로 바꿈, `.gitignore` 보강, 프로젝트 규칙 9개를 CLAUDE.md 맨 위에.

## 2. 처음 한 번 할 일 (사장님)
1. Claude Code 앱에서 이 프로젝트를 **다시 연다**. 「.mcp.json 의 MCP 서버를 신뢰하겠습니까」 대화가 뜨면 **허용**. 첫 기동 때 npx 가 패키지를 받으므로 1~2분 걸릴 수 있다.
2. 세션에서 `/mcp` 를 치면 `claude-flow` 가 connected 로 보여야 한다. 안 보이면 터미널에서:
   ```bash
   npx ruflo@latest doctor
   ```
3. 집 PC 는 `git pull` 뒤 `npx ruflo@latest init check`. 「not initialized」면 사무실과 같은 옵션으로:
   ```bash
   npx ruflo@latest init --no-global --no-signup --no-skills-sh --no-codex-detect
   ```
   (이미 커밋된 `.claude/`·`.mcp.json`·`CLAUDE.md` 는 그대로 두고 로컬 런타임만 만든다. 덮어쓰기 질문이 나오면 「아니오」.)

## 3. 일상 사용 — 네 가지 방식
**A. 그냥 대화 (기본).** 지금처럼 Claude Code 와 대화하면 훅이 알아서 편집·명령을 메모리에 남기고, 세션 시작 때 지난 맥락을 복구한다. 아무것도 더 안 해도 된다.

**B. 스웜 — 조사·리뷰·테스트를 여러 에이전트로.** 세션 안에서 말로:
> "스웜으로 `app/workers/managed_symbol_worker.py` 를 4명(리서처·아키텍트·테스터·리뷰어)이 검토하게 해줘"

또는 터미널에서:
```bash
npx ruflo@latest swarm start -o "Fix 366: 관리 재진입 화면에 심볼별 손익 그래프 추가" -s development
```
슬래시: `/claude-flow-swarm`, `/claude-flow-memory`, `/claude-flow-help`.

**C. 하이브마인드 — 긴 작업을 여왕-작업자 구조로.** 세션이 끊겨도 이어진다.
```bash
npx ruflo@latest hive-mind spawn "Fix 366 화면 정리" --claude
npx ruflo@latest hive-mind status
npx ruflo@latest hive-mind resume <session-id>
```

**D. 메모리 — 사상·결정을 저장하고 찾기.** 프로젝트 사상 4건을 미리 넣어 두었다(`namespace project`).
```bash
npx ruflo@latest memory search -q "OBV 자동 프로브 모드"
npx ruflo@latest memory store -k "decision/2026-09-10" -v "…" --namespace project
npx ruflo@latest memory stats
```
Claude 세션에서는 "ruflo 메모리에서 … 찾아줘" 라고 말하면 `memory_search` 도구를 쓴다.

## 4. 이 프로젝트에서 스웜을 쓸 때 지킬 것 (CLAUDE.md 상단 규칙의 요약)
- **매매 판정 코드(진입·손절·자본·단계)는 리드(대화 중인 Claude)가 직접 쓴다.** 스웜 에이전트에는 조사·UI·API·문서·테스트·리뷰만.
- **주문·VPS 조작은 사장님만.** 스웜이 `docker compose restart` 나 DB UPDATE 를 하게 두지 않는다. 배포는 지금처럼 명령을 보고 실행.
- **`--dangerously-skip-permissions` 는 쓰지 않는다.** Ruflo 문서·블로그가 흔히 권하지만 실자금 저장소에선 금지.
- **비밀.** 저장소가 공개라 `.env`·키는 절대 커밋하지 않는다. 훅 권한에 `.env` 읽기 금지가 들어 있고, 커밋 전 비밀 스캔은 그대로.
- **완료 = 실검증.** 테스트 + 배포 뒤 `backend/scripts/verify_fix364_deploy.py` 로 3층 확인.

## 5. 추천 흐름 (예: 다음 Fix)
1. `memory search` 로 관련 사상·결정을 먼저 꺼낸다.
2. 스웜(리서처·아키텍트)으로 현재 코드 지도를 만든다 — 읽기 전용.
3. 리드가 매매 로직을 쓴다. UI/API/테스트는 `impl` 에이전트나 스웜의 coder.
4. 스웜(리뷰어 3~4렌즈)으로 반박 검증. 잡힌 것을 닫는다.
5. 테스트 → 커밋(비밀 스캔) → 사장님 배포 → 검사기 → 결과와 결정을 `memory store`.

## 6. 끄기·되돌리기·문제 해결
- MCP 만 끄기: Claude Code 앱의 MCP 설정에서 `claude-flow` 비활성, 또는 `.mcp.json` 의 항목 삭제.
- 훅만 끄기: `.claude/settings.json` 의 `hooks` 블록 삭제.
- 완전 제거: `npx ruflo@latest cleanup`(생성물 제거) 후 `git checkout -- .claude .mcp.json CLAUDE.md`.
- 컨텍스트 부담: MCP 도구 333개 스키마가 세션당 약 6만 토큰을 먹는다(`doctor` 경고). 필요 없을 땐 MCP 를 끄거나 `npx ruflo@latest mcp toggle` 로 도구를 줄인다.
- 백그라운드 데몬: `memory` 명령이 자동으로 띄운다. `npx ruflo@latest daemon status | stop`. 켜 두지 않아도 MCP·훅은 동작한다.
- Windows: `.mcp.json` 은 `cmd /c npx` 로 등록돼 있다(필수). `npm warn cleanup EPERM` 은 캐시 정리 경고라 무해.
- **Windows 메모리 CLI 주의(실측)**: 백그라운드 데몬이 DB 에 네이티브 WAL 잠금을 걸어 두면 `memory store` 가 「active native WAL connection … refusing」으로 거부된다. 해결은 두 줄:
  ```bash
  npx ruflo@latest daemon stop
  del .swarm\memory.db-wal .swarm\memory.db-shm
  ```
  그 뒤 `memory store/search` 를 실행한다. `CLAUDE_FLOW_ENABLE_NATIVE_BRIDGE_ON_WINDOWS=1` 은 **켜지 말 것** — 이 PC 에서 네이티브 드라이버가 3.9GB 메모리 할당 실패로 죽는다(ruflo #3024 로 Windows 기본 OFF). 명령 끝에 `Assertion failed: !(handle->flags & UV_HANDLE_CLOSING)` 가 찍히는 건 종료 시 잡음이고 저장은 된다.
- 그 외 `doctor` 경고(TypeScript·agentic-flow·AIDefence 미설치, 암호화 OFF)는 선택 사항이라 그대로 둬도 된다.

## 7. 참고
- 저장소: https://github.com/ruvnet/ruflo · 설치 위키: https://github.com/ruvnet/ruflo/wiki/Installation-Guide · npm `ruflo`
- 이 저장소의 Claude 작업 규칙 원본: `DEVELOPMENT_PRINCIPLES_2026-06-07.md`(헌법), `docs/spec/*`
