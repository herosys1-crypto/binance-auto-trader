---
name: 2026-08-23-fix30-capital-config
description: Fix 30 (v229) = 초기 세팅 조정 가능 (일 20 한도 + 300 USDT 초기 자본) + 변경 시 모든 워커 (진입/증거금/마틴게일/재진입) = 초기값 기준 자동 계산!
metadata: 
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-08-23T07:23:44.265Z
---

# 🎯 Fix 30 (v229): 초기 세팅 조정 가능!

**날짜**: 2026-08-23  
**사장님 요구**:
> "지금 일 20개까지 가능한데 이것을 조정할수 있는 옵션을 만들어줘"
> "초기 세팅 300usdt도 변경가능하게"
> "변경되면 모두 초기값을 기준으로 포지션 진입과 증거금추가 등등 할수 있어야 해"

---

## 📊 신 SystemSetting (2개!):

### **1. auto_bb_break_daily_limit** (이미 있음!)
- 값: default 20
- UI 조정 가능!
- 사장님 = 원하는 만큼! (10, 30, 50...)

### **2. martingale_base_capital_usdt** (신!)
- 값: default **300 USDT**
- UI 조정 가능!
- 사장님 = 원하는 만큼! (200, 500, 1000...)

---

## 🎯 마틴게일 자동 계산 (v219 사장님 사상!):

**규칙**:
- stage1 = **base** (사장님 지정!)
- stage2 = **base × 2** (이전 × 2)
- stage3 = **(base + base×2) × 2 = base × 6** (투자금 전체 × 2!)
- stage4+ = **None** (진입 금지!)

**예시 (base=500 USDT!):**
- stage1 = 500
- stage2 = 1000
- stage3 = 3000
- stage4+ = X!

---

## 🎯 모든 워커 = base 기반!

**base 참조 워커:**
1. **auto_bb_breakdown_worker** = stage1 진입!
2. **unified_15m_entry_worker (v224)** = stage1 진입!
3. **resistance_reversal_worker (Fix 29!)** = stage2 진입!
4. **auto_add_margin_worker** = base 만큼 증거금 추가!
5. **success_pyramiding_worker** = base 만큼 추가!
6. **realtime_reentry** (auto_bb_breakdown 내부!) = base 기반 마틴게일!

---

## 💡 구현 방안:

**신 파일**: `backend/app/core/martingale_config.py`
```python
from decimal import Decimal
from sqlalchemy.orm import Session
from app.models.system_setting import SystemSetting

MARTINGALE_BASE_KEY = 'martingale_base_capital_usdt'
DEFAULT_BASE_USDT = Decimal('300')

def get_base_capital(db: Session) -> Decimal:
    row = db.get(SystemSetting, MARTINGALE_BASE_KEY)
    if row and row.value:
        try:
            v = Decimal(str(row.value))
            if v > 0: return v
        except Exception: pass
    return DEFAULT_BASE_USDT

def get_stage_capital(db: Session, stage: int) -> Decimal | None:
    base = get_base_capital(db)
    if stage == 1: return base
    if stage == 2: return base * 2
    if stage == 3: return base * 6
    return None  # stage 4+ = 금지!

def get_add_margin_capital(db: Session) -> Decimal:
    return get_base_capital(db)  # 증거금 추가 = base와 같음!

def get_pyramiding_capital(db: Session) -> Decimal:
    return get_base_capital(db)  # 성공 재진입 = base와 같음!
```

**UI 추가**:
- 세팅 모달 (기존 auto_bb_break!)에 「초기 자본 (USDT)」 input 추가!
- 기본 300, 조정 가능!

**Backend endpoint**:
- POST /system-settings/martingale-base
- Value validation (100~10000!)

---

## Why:
사장님 실 매매 = 시장 상황에 따라 자본 조정 필요! 지금은 하드코딩! = 사장님 자율 통제 X! = 유연성 필요!

## How to apply:
- **base 변경 시** = 모든 워커 자동 반영 (다음 사이클!)
- **기존 진입 = 그대로** (base는 진입 시점 값!)
- **UI 리셋 버튼** = 300으로 복귀 옵션!
- **spec 필수**: docs/MARTINGALE_CONFIG_SPEC_v229.md
- **헌법 65/66 준수**: Workflow Agent 검증!

## 관련:
- [[2026-08-22-v219-final-complete]] (v219 마틴게일 원형!)
- [[2026-08-23-resistance-reversal-short-spec]] (Fix 29 = MARTINGALE_STAGE2_USDT 하드코딩!)
- [[feedback_orchestra_agent_validation]] (Agent 검증 필수!)
