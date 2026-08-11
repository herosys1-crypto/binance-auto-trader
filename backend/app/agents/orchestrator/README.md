# 🎩 Orchestrator Layer

**사장님 요구 (2026-08-11):**
1. "현재 개별 에이전트를 총괄지휘하는 지휘자가 있는지?"
2. "전체 에이젼트들을 통제할 수 있는 버스(메시지 공유 채널)도 구성해줘"

= Grand Orchestrator + EventBus 완성!

---

## 📁 파일 구조

```
app/agents/orchestrator/
├── __init__.py                # exports!
├── event_types.py             # 📡 EventType 상수! (Single Source!)
├── event_bus.py               # 📡 EventBus (pub/sub 메시지 채널!)
├── team_lead_base.py          # 👤 BaseTeamLead (팀 리더 base!)
├── grand_orchestrator.py      # 🎩 GrandOrchestrator (최상위!)
└── README.md
```

---

## 🎩 Grand Orchestrator

**최상위 총괄 지휘자!**

- 13 팀 리더 관리!
- 이벤트 방송!
- 우선순위 결정!
- Kill-switch 총괄!

```python
from app.agents.orchestrator import GrandOrchestrator

orchestrator = GrandOrchestrator()
orchestrator.startup()

# 이벤트 발신!
orchestrator.dispatch_event(EventType.STRATEGY_ENTERED, {"strategy_id": 838})

# 시스템 상태!
status = orchestrator.get_system_status()

# 🚨 최우선 = 전체 정지!
orchestrator.emergency_stop_all("사장님 결정!")
```

---

## 📡 EventBus (메시지 공유 채널!)

**pub/sub 패턴 = 팀 간 통신!**

```python
from app.agents.orchestrator import get_event_bus, EventType

bus = get_event_bus()  # 싱글톤!

# 구독!
def my_handler(event, data):
    print(f"이벤트 수신: {event.value}, {data}")

bus.subscribe(EventType.STRATEGY_ENTERED, my_handler)

# 발신!
bus.publish(EventType.STRATEGY_ENTERED, {"strategy_id": 838})

# 통계!
stats = bus.get_stats()
# {"total_events_published": 42, "event_counts": {...}}
```

---

## 👤 Team Lead 만들기

```python
from app.agents.orchestrator import BaseTeamLead, EventType
from app.agents.entry_team.stage_trigger_agent import StageTriggerAgent

class EntryTeamLead(BaseTeamLead):
    TEAM = "entry"
    AGENTS = [StageTriggerAgent, RetryReentryAgent, ...]
    HANDLED_EVENTS = [
        EventType.STRATEGY_CREATED,
        EventType.STAGE_TRIGGERED,
    ]

    def handle_event(self, event, data):
        if event == EventType.STRATEGY_CREATED:
            self.get_agent(StageTriggerAgent).execute(data)
        # ...
```

---

## 📡 이벤트 흐름 예시

```
1. 사장님 = 「+ 새 전략」 클릭!
   ↓
2. EntryTeamLead → StageTriggerAgent 진입!
   ↓
3. EntryTeamLead.publish(STRATEGY_ENTERED)
   ↓
4. EventBus → 관련 팀 자동 통보!
   ├─ MonitoringTeamLead = 감시!
   ├─ AlertTeamLead = Telegram!
   └─ CapitalTeamLead = 자본 재계산!
   ↓
5. 각 팀 = handle_event() = 자율 처리!
```

---

## 🚀 다음 세션

### Phase H2: 13 Team Lead 실 코드!
- entry_team/team_lead.py
- tp_team/team_lead.py
- sl_team/team_lead.py
- ... (13개!)

### Phase H3: 실 통합!
- scheduler_runner = GrandOrchestrator 사용!
- 기존 워커 = Team Lead 호출로 교체!
- 이벤트 실 동작!
