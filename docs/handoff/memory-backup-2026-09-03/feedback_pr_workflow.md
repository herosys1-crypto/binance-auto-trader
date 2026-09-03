---
name: GitHub PR 머지 가이드 (사장님 패턴)
description: 사장님이 GitHub 웹 UI 만 사용 — PR 만들기/머지 시 자주 발생하는 함정 + 안내 패턴.
type: feedback
originSessionId: 73d5bd06-3223-4c19-89d8-a16c5b80647b
---
사장님은 GitHub 웹 UI 만 사용. `gh` CLI 안 씀. 사무실↔집 핸드오프 패턴.

## 자주 발생하는 함정 (사장님 잘못 X — UI 가 헷갈리게 만듦)

### 1. 「Create pull request」 의도치 않게 중복 클릭

2026-05-21: 사장님이 Phase 1 의 PR 을 **3번** 만들었음 (PR #26, #27, #29 — 같은 변경 3번 머지). 이유: 머지 후 URL 이 갱신되지 않은 상태에서 다시 클릭하면 새 PR 생성됨.

**Why:** GitHub 의 `/pull/new/<branch>` URL 은 머지 후에도 같은 페이지를 다시 보여줘서, 사장님이 「PR 또 만들어야 하나?」 헷갈림.

**How to apply:** PR 생성 가이드 시 「머지 완료되면 PR 페이지로 자동 이동 — 거기서 머지 버튼 누르고 끝. 다시 `pull/new/` URL 클릭하지 마세요」 명시. PR 번호 확인 방법 안내 (예: PR #28 머지 후 → #28 페이지에 「Merged ✔」 표시).

## Stacked PR 머지 시 순서 중요

여러 PR 이 base 위에 stacked 인 경우 (예: Phase 1 → 2 → 2B → 3), **반드시 순서대로** 머지. 아래 PR 부터 머지 시도하면 충돌 발생.

**Why:** 아래 PR 의 head 가 위 PR 의 커밋을 포함하고 있어 main 과 충돌.

**How to apply:** PR 가이드 시 명확한 순서 + 각 PR 머지 후 「다음 PR 페이지 새로고침 (F5) — 충돌 해소되는지 확인」 안내.

## 충돌 발생 시 대응

사장님에게 「Resolve conflicts」 버튼 (web editor) 은 권장 X — 너무 복잡함.

**How to apply:** 충돌 발견 시 사장님 동의 받고 worktree 에서 rebase + force push 로 정리. 사장님은 GitHub 에서 머지만 진행. PR #28 case (2026-05-21) 가 첫 사례 — 성공적으로 처리됨.
