# 📖 Specs = 사양 문서 (10+!)

**각 기능의 상세 명세 = 에이전트가 참조!**

---

## 🌟 최신 spec (v130~v132!)

| Spec | 파일 위치 | 버전 |
|------|----------|------|
| 청산 후 자동 재진입 | `docs/AUTO_RETRY_AFTER_LIQUIDATION_SPEC_v131.md` | v131 |
| OBV 자동 재진입 | `docs/CHART_REENTRY_STRATEGY_SPEC.md` | v130 |
| 신 전략 튜토리얼 | `docs/NEW_STRATEGY_TUTORIAL_v131.md` | v131 |
| 팀+에이전트 종합 | `docs/ARCHITECTURE_TEAM_AGENT_SPEC_v132.html` | v132 |

---

## 📚 기존 spec (v106 이전!)

| Spec | 위치 |
|------|------|
| Force SL 손실 한도 | `docs/spec/FORCE_SL_LOSS_LIMIT_SPEC_2026-06-24.md` |
| TP1 임계 옵션 | `docs/spec/TP1_THRESHOLD_OPTION_SPEC_2026-06-08.md` |
| Trailing retrace | `docs/spec/TRAILING_RETRACE_POLICY_SPEC_2026-06-08.md` |
| Crisis mode | `docs/spec/CRISIS_MODE_FINAL.md` |
| 개발 원칙 (헌법!) | `docs/spec/DEVELOPMENT_PRINCIPLES.md` |
| System Master | `docs/spec/SYSTEM_MASTER_SPEC.md` |
| ...외 다수 | `docs/spec/` |

---

## 🤖 에이전트 활용

```python
class RetryReentryAgent(BaseAgent):
    def __init__(self):
        super().__init__(team="entry")
        self.spec = self.memory.load_spec(
            "retry_after_liquidation_v131"
        )
    
    def execute(self):
        # spec 참조 = 정확 동작!
        trigger_pct = self.spec.get("default_trigger_pct")  # 10
        ...
```
