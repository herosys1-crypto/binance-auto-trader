# 🧠 Memory System = 서버 에이전트 지식 저장소

**모든 서버 에이전트 = 이 메모리 참조 = 사장님 사상 100% 준수!**

---

## 📚 4계층 구조

### Layer 1: `constitution/` = 헌법 (절대 원칙!)
- 51+ 헌법 = 모든 에이전트가 준수!
- 예: C01 (메인넷 실자금), C09 (retry 순차), C10 (TP1_override = TP1만!)

### Layer 2: `specs/` = 사양 (상세 규칙!)
- 각 기능의 상세 명세
- 예: retry_after_liquidation_v131, pump_bb_middle_alert

### Layer 3: `defaults/` = 신 default 설정
- 신 전략 만들 때 = 자동 적용!
- 예: leverage_2x, tp_qty_gradient, force_sl_15pct

### Layer 4: `silent_bugs/` = fix 기록
- 발견된 silent bug + 해결법 + 재발 방지!
- 예: SB023 (TP1_override 초과 청산), SB026 (레버리지 5x stuck)

---

## 🤖 에이전트 활용 방법

```python
from app.agents.base import BaseAgent
from app.agents.memory_reader import MemoryReader

class MyAgent(BaseAgent):
    def __init__(self):
        self.memory = MemoryReader(team="entry")
        # 자동 로드:
        self.constitution = self.memory.load_constitution()
        self.specs = self.memory.load_specs()
        self.defaults = self.memory.load_defaults()

    def execute(self):
        # 실행 시 = 헌법 자동 검증!
        assert self.constitution.check("C07_capital_equals_margin")
        # 실행!
```

---

## 🔄 메모리 업데이트 흐름

```
[사장님 결정] → memory/constitution/ 저장
[신 fix] → memory/silent_bugs/ 저장
[신 default] → memory/defaults/ 저장
[신 기능] → memory/specs/ 저장

[에이전트] → 시작 시 = 자동 로드
[Audit Team] → 자율 검증 = 신 헌법 제안
```

---

## 📖 관련 문서

- `docs/ARCHITECTURE_TEAM_AGENT_SPEC_v132.html` = 팀+에이전트 종합 기획서
- `CLAUDE.md` = Claude Code 프로젝트 규칙
