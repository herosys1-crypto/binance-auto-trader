# ⚙ Defaults = 신 default 설정 (v132 최종!)

**신 전략 만들 때 = 자동 적용!**

---

## 📊 신 default 목록

| 항목 | 값 | 파일 | 버전 |
|------|-----|------|------|
| 레버리지 | 2x | [leverage_2x.md](leverage_2x.md) | v132 최종 |
| TP1 qty | 10% | [tp_qty_gradient.md](tp_qty_gradient.md) | v130 |
| TP2 qty | 15% | (same) | v130 |
| TP3 qty | 20% | (same) | v130 |
| TP4 qty | 25% | (same) | v130 |
| TP1_override | 25% | [tp1_override_25.md](tp1_override_25.md) | v130 |
| 강제 SL | -15% | [force_sl_15pct.md](force_sl_15pct.md) | v130 |
| 시작가 없음 | MARKET 진입 | [market_entry_default.md](market_entry_default.md) | v130 |
| 재진입 트리거 | 10% | [retry_trigger_10pct.md](retry_trigger_10pct.md) | v131 |
| 트리거 % (2단계) | +10% | (stage_config) | v130 |
| 트리거 % (3+단계) | +20% | (stage_config) | v130 |

---

## 🎯 신 전략 만들 때 자동 세팅

1. 「+ 새 전략」 클릭!
2. 이전 전략 자동 로드 (편의성!)
3. 레버리지 = **강제 2x!** (신 default!)
4. TP qty = **10/15/20/25** 자동!
5. TP1_override = **25%** 자동!
6. 강제 SL = **-15%** 자동!
7. 사장님 = 필요 시 변경!

---

## ⚠ 사장님 override

- 사장님 = 언제든 변경 가능!
- 「↺ 기본값」 = 신 default 즉시 복원!
- 자율 = 100% 존중!
