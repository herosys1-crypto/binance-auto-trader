---
name: project-2026-08-21-v211-leftover-incident
description: v211 잔재 코드가 롤백 안 되어 자동매매 전면 중단 사고. PR 머지 방식이 완전 rollback 안 함! 함수 중복 정의 → unpack 예외!
metadata: 
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-08-21T06:39:09.500Z
---

# 🚨 2026-08-21 v211 잔재 사고

## 배경
- 사장님 지적으로 v208~v216 롤백 (사장님 명시 요구 X!)
- 롤백 PR #339 = main 머지 완료 확인
- 자동매매 정상 작동 확인 (+64 USDT 흑자!)

## 사고 발견 (사장님 로그 확인 중!):
- 사장님: "자동 진입이 적다"
- VPS 확인 → `[v194] worst 추가` 로그만 매 15분 (realtime_watchlist에서 호출!)
- **auto_bb_breakdown 실 실행 로그 = 0건!**
- 수동 실행 = `TypeError: cannot unpack non-iterable bool object`

## 진짜 원인
main 브랜치 파일에 **`_matches_failure_condition` 함수 = 2번 정의!**
- 713줄: v211 정의 (tuple 반환!)
- 766줄: v198 정의 (bool 반환!)

파이썬 = 나중 정의가 이김 = 766줄 bool 반환 → 281줄에서 tuple unpack 실패 → 예외!

= **매 4h 실행되지만 = 예외 → 진입 X 상태 지속!**
= 오늘 KST 08:14 METUSDT 진입 = 8:14 이전 아직 v207 정상 상태에서 진입 (그 이후 예외!)

## 왜 롤백이 안 됐나?
- git reset --hard cd519b6 (worktree) → force push → PR #339 → main 머지
- **하지만 = PR #339 머지 방식이 = 완전 롤백 X!**
- v211에서 `_matches_failure_condition` 를 **덮어쓰지 않고 추가**한 것이 원인!
- worktree 파일에는 정상 (v207 = 함수 1개) 였는데
- main으로 머지된 후 = 함수 2개 존재!
- **PR 머지 시 3-way merge가 v208 정의를 유지한 것으로 추정**

## 해결 (fix PR)
- fix/v211-leftover-rollback-main branch 신설
- v207 (cd519b6) 시점에서 정확히 checkout:
  - auto_bb_breakdown_worker.py (함수 1개만!)
  - pattern_learning_worker.py (v208 확장 제거)
  - api/v1/pattern_learning.py (v208 /health-check 제거)
  - learning-insights.html (v208 카드 제거)
  - orchestra_health_worker.py (v208 필드 감지 제거)
  - scheduler_runner.py (v209~v216 job 제거)
- v209~v216 파일 = git rm (7개 삭제!)
- PR 머지 + 배포 (docker up -d --build!)
- **정상 복구 = 자동매매 즉시 2건 진입!** (CRCLUSDT/BTWUSDT!)

## 헌법 62 (2026-08-21 신 추가!)
**롤백 PR 머지 후 = 반드시 실 파일 상태 검증!**

= grep으로 롤백 대상 함수/코드 확인!
= "PR 머지됨" ≠ "코드 완전 롤백"!

## 헌법 63 (2026-08-21 신 추가!)
**함수 재정의 = 신 이름 사용! 절대 같은 이름으로 덮어쓰지 X!**

= v211에서 v198의 `_matches_failure_condition` 를 재정의한 것이 근본 원인!
= 같은 이름으로 재정의 = 롤백 시 잔재 위험!
= 확장 시 = `_matches_failure_condition_v2()` 처럼 신 이름!

## 사장님 학습
- 사장님이 "자동 진입이 적다" 지적 = **실 관찰의 힘!**
- 로그 명령어 순차 확인 = 진짜 원인 발견!
- 학습: **매매 시스템 = 반드시 실 실행 확인 필수!**

## 관련 메모리
- [[project_2026-08-21_v186_v207_full_autonomous]] — v207까지 배포!
- [[feedback_no_unrequested_features]] — v208~v216 롤백 사건 근본 원인!
