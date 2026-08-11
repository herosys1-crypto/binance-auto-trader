# 🤖 서버 에이전트 시스템 (v132!)

**모든 서버 에이전트 = 메모리 시스템 참조 = 사장님 사상 100% 준수!**

---

## 📁 구조

```
app/agents/
├── __init__.py                    # 패키지 exports
├── base.py                        # BaseAgent 클래스
├── memory_reader.py               # MemoryReader (헌법/spec/default 로드)
├── constitution_validator.py     # 헌법 자동 검증
└── README.md                      # 이 파일

앞으로 = Phase D:
app/agents/entry_team/       # ⚔️ Entry Team (4 에이전트)
app/agents/tp_team/          # 🎯 Take Profit Team
app/agents/sl_team/          # 🛑 Stop Loss Team
app/agents/monitoring_team/  # 📊 Monitoring Team
app/agents/alert_team/       # 🚨 Alert Team
app/agents/capital_team/     # ⚙️ Capital Team
app/agents/analysis_team/    # 📈 Analysis Team
app/agents/maintenance_team/ # 🔧 Maintenance Team
app/agents/ui_team/          # 🎨 UI Team
app/agents/audit_team/       # 📚 Audit Team
```

---

## 🚀 사용법

### 신 에이전트 만들기:

```python
from app.agents import BaseAgent

class StageTriggerAgent(BaseAgent):
    TEAM = "entry"
    AGENT_NAME = "stage_trigger_agent"

    def execute(self, strategy_id: int, next_stage: int):
        # 1. 헌법 자동 검증 (STAGE_ENTRY 액션!)
        self.validate("STAGE_ENTRY", {
            "strategy_id": strategy_id,
            "stage": next_stage,
        })

        # 2. 신 default 참조!
        lev_default = self.get_default("leverage_2x")
        # → "# 신 default: 레버리지 2x\n..."

        # 3. spec 참조!
        spec = self.get_spec("retry_after_liquidation_v131")
        # → "# 청산 후 자동 재진입 spec\n..."

        # 4. 실제 실행!
        ...
```

### 메모리 시스템 조회:

```python
from app.agents import MemoryReader

reader = MemoryReader()
summary = reader.summary()
# → {"constitution": 13, "specs": 0, "defaults": 1, "silent_bugs": 0}

rule = reader.get_constitution_rule("C10_tp1_override_tp1_only")
# → 헌법 내용 반환!
```

---

## 📜 헌법 검증 흐름

```
[에이전트 execute()]
    ↓
self.validate(action="TP1_OVERRIDE_APPLY")
    ↓
ConstitutionValidator.check()
    ↓
관련 헌법 = C10 확인!
    ↓
✅ 통과 (헌법 파일 존재!)
    or
❌ ConstitutionViolationError → 로그 + 재발 방지 기록!
```

---

## 🎯 다음 Phase (D!)

### 팀별 폴더 리팩터링:
- 기존 워커들 = 팀별로 이동!
- 모든 워커 = BaseAgent 상속!
- 자동 헌법 검증!

### 예:
```python
# 기존 (before):
# app/workers/stage_trigger_worker.py

# 신 (after):
# app/agents/entry_team/stage_trigger_agent.py
from app.agents import BaseAgent

class StageTriggerAgent(BaseAgent):
    TEAM = "entry"
    AGENT_NAME = "stage_trigger_agent"

    def execute(self):
        # 기존 로직 + 자동 헌법 검증!
        ...
```
