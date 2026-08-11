# 🏗 10개 팀 + 40+ 에이전트 (Phase D MVP!)

**v132 완성 = 팀 폴더 구조 MVP + 예시 에이전트!**

---

## 📁 팀 구조

```
app/agents/
├── entry_team/         # ⚔️ 진입! (stage_trigger, retry, market, manual)
├── tp_team/            # 🎯 익절! (orchestrator, trailing, tp1_override, crisis)
├── sl_team/            # 🛑 손절! (sl, force_sl, liquidation_risk, exhausted)
├── monitoring_team/    # 📊 감시! (mark_price, reconciler, zombie, self_check)
├── alert_team/         # 🚨 알람! (reentry, pump_bb, tp_miss, telegram)
├── capital_team/       # ⚙️ 자본! (calculator, daily_loss, kill_switch, margin)
├── analysis_team/      # 📈 분석! (chart, ranking, pnl, stats)
├── maintenance_team/   # 🔧 유지! (alembic, redis, telegram_retry, setting)
├── ui_team/            # 🎨 UI! (dashboard, list, modal, alert_card)
└── audit_team/         # 📚 감사! (spec, silent_bug, intent, auto_fix)
```

---

## 🎯 Phase D 상태

### ✅ 완료 (지금!):
- 10 팀 폴더 생성!
- 각 팀 `__init__.py` (미션 + 에이전트 리스트!)
- Entry Team `README.md` 상세!
- 예시 에이전트: `entry_team/stage_trigger_agent.py`

### ⏳ 다음 세션 (Phase D 계속!):
- 나머지 팀 = README 상세!
- 각 팀 = 실 에이전트 파일 (wrapper → 마이그레이션!)
- 팀 간 통신 프로토콜!
- scheduler_runner = 신 에이전트 등록!

---

## 🔄 팀 간 상호작용 예

```python
# Entry Team = 진입 완료!
entry_result = StageTriggerAgent().execute(...)

# → Monitoring Team = 감시 시작!
monitor = SelfCheckAgent()
monitor.watch(entry_result.strategy_id)

# → Alert Team = 사장님 알림!
alert = TelegramNotifierAgent()
alert.send_stage_entered(entry_result)
```

---

## 📌 리팩터링 원칙 (안전!)

1. **기존 워커 = 100% 유지!** (실 mainnet!)
2. **신 에이전트 = wrapper!** (기존 호출!)
3. **점진적 마이그레이션!** (하나씩!)
4. **자동 헌법 검증 추가!**
5. **테스트 = 각 마이그레이션마다!**

---

## 🎁 완성 시 = 사장님 자율 매매!

- ✅ 10 팀 = 명확 역할!
- ✅ 40+ 에이전트 = 자동!
- ✅ 4계층 메모리 = 사장님 사상 100%!
- ✅ 헌법 자동 검증!
- ✅ Silent bug 재발 방지!
