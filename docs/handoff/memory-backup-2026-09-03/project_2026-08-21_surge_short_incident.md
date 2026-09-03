---
name: project-2026-08-21-surge-short-incident
description: 급등 종목 SHORT 사고 = -849 USDT 손실! 24h +30%+ 급등에 SHORT → 물타기 3단계 폭발. 자동매매에 급등 필터 추가!
metadata: 
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-08-21T08:30:12.356Z
---

# 🚨 2026-08-21 급등 종목 SHORT 사고

## 사고 요약
사장님 수동 매매 = 급등 종목에 SHORT 진입 = 급등 계속 = 물타기 3단계 = 큰 손실!

### 손실 상세 (24h!):
| 심볼 | 24h 변동 | 방향 | Stage | 손실 |
|------|---------|------|-------|------|
| BOMEUSDT | **+35.82%** | SHORT | 3 | **-417.59** |
| ONGUSDT | **+31.68%** | SHORT | 3 | **-411.61** |
| HEMIUSDT | **+21.99%** | SHORT | 1 | -20.77 |
| **합계** | | | | **-849.97 USDT** |

### 사장님 진입 vs 자동 진입:
- **자동 진입 PnL: +64.11 USDT** ✅ (잘 됨!)
- **수동 진입 PnL: -1031.38 USDT** 🚨 (급등에 SHORT!)

## 사장님 요구 (verbatim)
> "내가 급등한 종목에 잘못된 진입으로 손실이 발생했어
> 이부분도 문제점을 분석해줘 학습해줘
> 실패한 심볼의 차트를 분석해서 다음 자동매매에 활용해줘"

## Fix: 급등/급락 필터 추가!
**`auto_bb_breakdown_worker.py`에 = v179 RSI 필터 다음에 추가!**

```python
# 24h 변동 > +15% = SHORT skip! (급등 계속 위험!)
# 24h 변동 < -15% = LONG skip! (급락 계속 위험!)
change_24h = it.get("change_24h")
if change_24h is not None:
    _c = float(change_24h)
    if side == "SHORT" and _c > 15.0:
        skipped += 1; continue
    if side == "LONG" and _c < -15.0:
        skipped += 1; continue
```

**commit**: `c548ab8` (branch: fix/v211-leftover-rollback-main)

## 헌법 64 (2026-08-21 신 추가!)
**급등 (>+15%) 종목 = SHORT 진입 금지!**
**급락 (<-15%) 종목 = LONG 진입 금지!**

= 시장 관성 = 급등 계속 / 급락 계속 = 반대 방향 = 물타기 폭발!
= 자동매매 최우선 = 사장님 자본 보호!

## 시장 관성 분석
- 급등 20%+ = **관성 계속** 확률 높음 (다음 캔들도 상승!)
- SHORT 진입 = 관성 반대 방향!
- 물타기 = **더 높은 가격에 추가 진입** = 손실 배증!
- 3단계 물타기 시 = **평균 손실 -400 USDT+!**

## 관련 메모리
- [[project_2026-08-21_v186_v207_full_autonomous]] — 오늘 세션 전체
- [[project_2026-08-21_v211_leftover_incident]] — v211 롤백 사고
- [[project_2026-08-14_v137_ema_vcp_strategy]] — v141 급등락 실시간 진입 (기존 학습!)
