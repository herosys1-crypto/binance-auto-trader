# AGENTS.md — Codex 등 Claude 가 아닌 에이전트용 안내

이 저장소의 규칙은 **`CLAUDE.md` 맨 위 「프로젝트 규칙」 1~12** 가 전부이고, 모든 에이전트에 똑같이 적용된다. 작업 전에 반드시 읽는다.
(CLAUDE.md 아래쪽 「Ruflo」 절의 스웜·다인 파이프라인은 쓰지 않는다 — 규칙 10.)

가장 중요한 다섯 줄:
1. 실자금(mainnet) 자동매매이고 저장소는 **공개**다. 비밀(`.env`·`npg_`·`sk-`·`ghp_`·DB 접속 문자열·서버 IP·계정)은 커밋·출력·기록 어디에도 쓰지 않는다.
2. 주문·자금 조작·API 키·운영 DB 쓰기·컨테이너 재시작은 하지 않는다 — 명령만 적어 사장님께 보고한다.
3. 매매 판정 코드(진입·손절·자본·단계·청산 값)는 Claude 리드가 쓴다. 필요하면 `C:\ai_hq\tools\duel_pair.py --important` 로 Claude 대기열에 넣는다.
4. 시험은 `py -3.14 -m pytest …`. CRLF 파일은 줄끝을 보존한다. `git stash` 금지.
5. 커밋마다 Obsidian 볼트 `C:\Users\user\OneDrive\Obsidian\바이낸스 자동매매\` 에 기록한다(규칙 11). 답변·기록은 한국어.

지금 인계 상황: `docs/handoff/` 의 가장 최근 `HANDOFF-*.md` 를 먼저 읽는다.
