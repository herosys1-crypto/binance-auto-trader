# C10. TP1_override = TP1만 override! (v132!)

## 원칙
사장님 TP1_pct_override 세팅 = TP1 임계값만 변경!
TP2~10 = template 원값 그대로!

## 사장님 사고 (원래!)
- 「TP1을 25%까지 대기하고 싶어!」
- = TP1 임계만 25%로 상향!
- = TP2/3/4 등 = 그대로 (15/20/25)!
- = 순차 발동!

## 옛 v105 (잘못!)
```python
tp_levels = [(label, max(_override, val)) for ...]
= 모든 TP 임계 = override 이상으로 강제!

예: TP1_override=25%, template=10/15/20/25!
→ TP1=25, TP2=25, TP3=25, TP4=25!
→ 25% 도달 = 4개 동시 발동!
→ 중복 청산 = 초과!
```

## 신 v132 (정확!)
```python
tp_levels = [
    (label, _override if idx == 0 else val)
    for idx, (label, val) in enumerate(tp_levels)
]
= TP1만 override, TP2~10 = template 그대로!
```

## 발동 예 (신 v132!)
- Template: TP1=10, TP2=15, TP3=20, TP4=25
- Override: TP1=25
- 신 tp_levels: TP1=25 / TP2=15 / TP3=20 / TP4=25

- 수익률 20% → TP3 발동! (template!)
- 수익률 25% → TP1 or TP4 발동! (순차!)

## 관련 fix
- v132 commit 3497d25 (TP1만 override!)
- #838 BMTUSDT 초과 청산 원인 fix!

## 관련
- SB023_tp1_override_all_tps
