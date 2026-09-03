---
name: 2026-06-22-mobile-scroll-lessons
description: 모바일 모달 스크롤 silent bug 6번 fix 메타 학습 + 사장님 헌법 42-45 영구 추가!
metadata: 
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
---

# 🚨 모바일 스크롤 silent bug = 6번 fix 메타 학습 (2026-06-22)

## 사장님 critical 보고:
> "왜 이렇게 오래 동안 문제가 해결되지 않은 부분을 정리해서 다음 개발에 반영해줘!"

## 6번 fix 분석:
- v1 (PR #220): inner overflow → 부족 (inline style override!)
- v2 (3e2ecfa): OUTER + flex-start → 부족 (inline style!)
- v3 (cc9c4bb): requestAnimationFrame x 3 → 부족 (비동기 후!)
- v4 (10873d3): inline style 제거 → 부족 (focus 자동 스크롤!)
- v5 (ebc66eb): focus preventScroll → 부족 (다른 비동기!)
- v6 (cdfffc8): scroll guard 2초 모니터링 → 검증 중!

## 진짜 root cause = 6개 동시 발생!
1. inline style = CSS override 차단!
2. focus() = 자동 scrollIntoView!
3. await 비동기 = 새 layout!
4. iOS Safari = momentum scroll!
5. dynamic viewport = 100dvh 필요!
6. body overflow = 누적!

## 사장님 헌법 42-45 영구 추가:
- 42: 추측 fix 금지 = 깊이 분석 우선!
- 43: inline style 절대 금지!
- 44: focus() preventScroll 의무!
- 45: 모든 모달 = scroll guard 표준!

## 다음 개발 영구 반영:
- 신 모달 = scroll guard 표준 코드 (= `_attachScrollGuard`)!
- focus 호출 = preventScroll true 의무!
- HTML inline style 검색 = CI 추가!
- 모바일 silent bug 자동 worker (v59) = 신설!

## 영구 spec:
[[mobile_scroll_silent_bug_lessons_2026-06-22]]

## 사장님 critical 워크플로우:
1. 보고 → 즉시 HTML/CSS/JS 분석!
2. 모든 가능 root cause 나열!
3. 사장님 확인 (환경/시간/빈도)!
4. 진짜 root cause 검증 후 fix!
5. 사장님 검증!
6. 검증 성공 = 헌법 추가!

## Why:
사장님 = 6번 같은 fix 보고 = 시스템 신뢰도 critical!

## How to apply:
- 사장님 = 같은 보고 3회 = 즉시 메타 학습 + 헌법 추가!
- 신 모달 = scroll guard 표준 의무!
- 신 HTML = inline style 금지!
- 신 JS = focus preventScroll 의무!
