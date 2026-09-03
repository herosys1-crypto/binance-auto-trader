---
name: 작업 진행 패턴
description: 사용자가 검증한 협업 워크플로우 — 우선순위 추천 + 자동 진행 + GitHub 웹 머지
type: feedback
originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
---
**사용자가 「추천으로 진행해줘」 / 「우선순위로 진행해줘」 라고 하면 어시스턴트가 직전에 제시한 우선순위 목록의 1번 항목부터 자동 진행 — 매 단계 재확인 없이.**

**Why**: 2026-05-07 세션에서 사용자가 4개 PR (#13~#16) 을 이 패턴으로 진행. 각 단계마다 "이대로 진행할까요?" 묻지 않고 코드 작성 → 테스트 → 커밋 → push → PR URL 제공까지 한 번에 가능했음. 사용자가 GitHub 웹에서 머지/브랜치 삭제만 처리하고 어시스턴트는 로컬 sync + 다음 우선순위 작업으로 자동 이동.

**How to apply**:
- 우선순위 목록 (A/B/C/D 또는 1/2/3/4) 을 먼저 제시
- 사용자가 「추천」 / 「우선순위로」 / 「1번」 등으로 답하면 그 항목 자동 시작
- 도중에 audit 발견 / 가벼운 사이드 작업이 우선순위 변경을 정당화하면 사용자에게 한 번 확인 (예: 5-07 의 kill-switch alert audit 발견 → "C 작업을 이걸로 변경할까요?" 1회 묻고 진행)
- 파괴적 작업 (docker restart, 외부 API 호출, force push) 은 별도 명시 승인 필요 — 「응」 1단어 답이라도 받기
- PR 단계는 사용자 직접 작업 (웹 UI). 어시스턴트는 push + compare URL + 제목/설명 안 제공 후 대기

**부수 패턴**:
- 머지 완료 직후 어시스턴트가 자동 처리: `git checkout main && git pull && git fetch --prune && git branch -d <feat-branch>` + 필요 시 `docker compose restart api scheduler`
- 7 커밋 이상 main 미머지 누적 시 즉시 머지 권장 — 메모리 outdate / worktree conflict 위험

**예외**:
- 「오늘은 여기까지」 / 「다음에」 같은 종료 신호 시 즉시 stop, 자동 진행 X
