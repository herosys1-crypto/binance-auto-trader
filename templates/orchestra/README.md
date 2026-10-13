# 🎼 orchestra — 오케스트라 에이전트 팀 범용 템플릿

binance-auto-trader 의 오케스트라 팀(`backend/app/agents/` — 2026-08-11 사장님 「총괄지휘하는 지휘자」 + 「메시지 공유 버스」)에서
**매매 전용 부분을 떼어 낸 뼈대**다. 파이썬 표준 라이브러리만 쓴다 (3.10+). 새 프로젝트에 복사하고 팀만 새로 만든다.

```
지휘자 Conductor ── 팀 등록 · 시작/종료 · 이벤트 보내기(규칙 검사) · 전체 정지 · 자체 진단
   │  이벤트 버스 EventBus (pub/sub · "*" 전체 구독 · 한 팀 실패가 다른 팀을 막지 않음)
   ├─ 팀 리더 TeamLead ── 구독 이벤트 받기 → 소속 에이전트에게 일 나누기 · 정지/재개 · 상태
   │     └─ 에이전트 Agent ── 한 가지 일(execute) · 규칙 검사 · 실행/실패/시간 기록
   └─ 규칙집 Rulebook ── 프로젝트 규칙(원본의 「헌법」)을 검사 함수로 · 위반 = 막는다
```

## 다른 프로젝트에 넣기
1. `orchestra/` 폴더를 새 프로젝트로 복사 (예: `myproject/orchestra/`). 패키지 이름을 바꾸려면 `from orchestra.` 를 한꺼번에 바꾼다.
2. 프로젝트 이벤트를 **한 파일**에 정의 — `class AppEvent(str, Enum)` (예시 `examples/example_app.py`).
3. 팀마다 `TeamLead` 를 상속해 `TEAM` · `AGENTS` · `HANDLED_EVENTS` · `handle_event()` 를 쓴다. 일꾼은 `Agent` 를 상속해 `execute()`.
4. 규칙은 `Rulebook` 에 검사 함수로 — 돈·권한·삭제 같은 위험 행동은 `ACTION` 을 붙여 실행 전에 검사.
5. 시작 코드: `Conductor(rules=...)` → `register(팀)` 들 → `startup()`. 주기 작업(스케줄러·크론)에서 `conductor.dispatch(이벤트)`.
6. 감시: `conductor.health_check()` 를 몇 분마다(오류 팀 · 정지 팀 · 놀고 있는 팀) · `conductor.status()` 를 관리 화면에.

## 원본과 달라진 점 (원본의 약점을 고침)
| 원본 (binance-auto-trader) | 템플릿 |
|---|---|
| 이벤트 이름이 매매 전용 Enum 하나에 고정 | 시스템 공용 이벤트만 두고 프로젝트 이벤트는 따로 정의 (문자열·Enum 둘 다 받음) |
| 「헌법 검증」이 규칙 파일이 있는지만 보고 **실제로 막지 않음** | `Rulebook` = 검사 함수 · 위반이면 `RuleViolation` · 검사 오류는 기본 위반(fail-closed), 보조 규칙만 `fail_open` |
| 이벤트마다 INFO 로그 (운영 48시간 879줄) | DEBUG — 통계는 `bus.stats()` |
| 정지(emergency_stop)가 로그만 남기고 팀은 계속 이벤트를 처리 | 정지된 팀은 이벤트를 처리하지 않고 센다 · `resume()` 으로 재개 |
| 전체 구독 없음 | `"*"` 구독 (감사 팀) — 원인 → 결과 순서로 기록 |
| 팀이 남의 에이전트를 부를 수 있음 | `AGENTS` 에 없는 에이전트는 거부(팀 경계) |
| 메모리·헌법 파일을 읽는 `MemoryReader` 에 묶임 | 없음 — 규칙은 코드로 |
| 자체 진단은 별도 워커 | `health_check()` 내장 |

## 시험
```
cd templates/orchestra
python -m pytest -q          # 9개
python -m examples.example_app
```

## 주의
- 이벤트 처리는 **같은 스레드에서 차례로**(동기) 돈다. 오래 걸리는 일은 에이전트 안에서 큐·작업자로 넘긴다.
- 버스는 프로세스 하나 안에서만 공유된다. 여러 프로세스(웹 서버 + 스케줄러)를 잇려면 `EventBus.publish` 를 Redis pub/sub 등으로 바꾼 하위 클래스를 쓴다.
- 이 템플릿은 「팀 구조·통신·정지·감시」의 뼈대다. 판단 로직(무엇을 언제 할지)은 각 프로젝트의 에이전트가 갖는다.
