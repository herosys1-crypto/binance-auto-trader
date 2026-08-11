# 📜 Constitution = 사장님 절대 원칙 (51+ 헌법!)

**모든 에이전트가 준수해야 하는 절대 원칙!**

---

## 🔥 최우선 헌법 (v132 최종!)

| # | 원칙 | 파일 | 상태 |
|---|------|------|------|
| C01 | 메인넷 = 실 자금! | [C01_mainnet_real_capital.md](C01_mainnet_real_capital.md) | ⭐ |
| C02 | 사장님 사상 우선! | [C02_user_first.md](C02_user_first.md) | ⭐ |
| C03 | Silent bug 금지! | [C03_no_silent_bug.md](C03_no_silent_bug.md) | ⭐ |
| C04 | 검증 없는 코드 금지! | [C04_no_unvalidated_code.md](C04_no_unvalidated_code.md) | ⭐ |
| C05 | 대칭성 (UI↔Backend!) | [C05_symmetry.md](C05_symmetry.md) | ⭐ |
| C06 | 단일 진실 (Single Source!) | [C06_single_source.md](C06_single_source.md) | ⭐ |
| C07 | capital = margin (v107!) | [C07_capital_equals_margin.md](C07_capital_equals_margin.md) | ⭐ |
| C08 | 130% 자본 = 경고만! | [C08_130pct_warning_only.md](C08_130pct_warning_only.md) | ⭐ v131 |
| C09 | retry ON = 순차 진입! | [C09_retry_sequential_only.md](C09_retry_sequential_only.md) | ⭐ v131 |
| C10 | TP1_override = TP1만! | [C10_tp1_override_tp1_only.md](C10_tp1_override_tp1_only.md) | ⭐ v132 |
| C11 | branch 확인 필수! | [C11_branch_check_mandatory.md](C11_branch_check_mandatory.md) | ⭐ v132 |
| C12 | 레버리지 = 사장님 자율! | [C12_leverage_user_autonomy.md](C12_leverage_user_autonomy.md) | ⭐ v132 |
| C13 | 다음 단계 남으면 SL X! | [C13_sl_skip_if_next_stage.md](C13_sl_skip_if_next_stage.md) | ⭐ v130 |

---

## 📖 기타 헌법 (14~51+)

- C14~C18: 자동 검증 원칙 (auto_fix, audit worker)
- C19~C21: TP audit 원칙 (BEATUSDT #110!)
- C22~C30: 운영자 우선 (자동 현재가, 수정 모드 등)
- C31~C45: 사장님 옵션 (TP1/Trailing/Force SL 등)
- C46~C51: v127 대감사 원칙 (mark_price Redis 우선 등)

**모든 헌법 = 프로젝트 memory 참조 (`~/.claude/projects/*/memory/`)**

---

## ⚠ 위반 시 = 즉시 알림!

```python
class BaseAgent:
    def check_constitution(self, action):
        for rule in self.constitution:
            if not rule.validate(action):
                raise ConstitutionViolationError(rule.id)
```
