---
name: 2026-08-25-sajangnim-no-blocklist-directive
description: "🚨 사장님 CRITICAL 방침 (2026-08-25!): '제한 심볼들 모두 해제해줘 제한 심볼을 만들지 않도록해' = 모든 blocklist/제한 해제 + 신 저장 금지!"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-08-25T00:29:08.332Z
---

# 🚨 사장님 신 방침 = 제한 심볼 완전 해제 + 생성 금지!

## 사장님 verbatim (2026-08-25!):

> **"제한 심볼들 모두 해제해줘 제한 심볼을 만들지 않도록해"**

## 의미 (사장님 사상!):
- 모든 blocklist/제한 = **해제!**
- 신 제한 심볼 = **생성 금지!**
- 자유로운 매매 = 사장님 선호!

## Why:
- 사장님 자율 매매 우선!
- 시스템이 진입을 막는 것 지양!
- 헌법 X: "제한 심볼 = 예측 불가"라는 가정이 사장님과 다름!

## How to apply:
- **즉시 해제**: Fix 66 (bidirectional_blocklist) 완전 비활성화!
- **즉시 해제**: Fix 16 (WORST blocklist) 완전 비활성화!
- **즉시 해제**: auto_bb_breakdown ban 리스트 완전 비활성화!
- **신 저장 금지**: blocklist 저장 로직 = fail-open (통과!)
- **예외 유지**: Fix 65 (OBV 극단) = 지표 판단 (제한 X 아님!)
- **예외 유지**: Fix 66 P2 (pump_completed_dumping) = 시장 국면 판단 (제한 X 아님!)

## 헌법 76: 제한 심볼 = 사장님 사상 위배!
- 심볼별 blocklist = 만들지 않기!
- 특정 심볼 = 영구 차단 X!
- 심볼과 무관하게 = 지표만 판단!

## 앞으로 개발 원칙:
- 심볼 이름 기반 필터 = 금지!
- 실패 학습 = OK (지표 기반!)
- 지표/시장 국면 기반 필터 = OK!

## 관련:
- [[2026-08-25-sajangnim-long-short-philosophy-v2]] (사장님 사상 v2!)
- [[2026-08-25-pump-dump-failure-pattern-learning]] (실패 학습 = 유지!)
