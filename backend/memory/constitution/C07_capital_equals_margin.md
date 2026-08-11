# C07. capital = margin (v107!)

## 원칙
사장님이 세팅한 「자본」 = 증거금 (margin)!
포지션 크기 (notional) = capital × leverage!

## 사장님 사고
- 자본 100 USDT + 레버리지 5x = 500 USDT 포지션!
- 자본 = 증거금 = 내가 위험 감수!
- 포지션 = 실 크기 = 5배!

## 공식
```
qty = (capital × leverage) / entry_price
notional = qty × entry_price = capital × leverage
```

## 예시 (BMTUSDT SHORT 5x!)
- 1단계 자본 100 USDT
- 진입가 0.03777
- qty = (100 × 5) / 0.03777 = 13,241 (반올림 13,266)
- 포지션 = 13,266 × 0.03777 = 500 USDT (=100×5!)

## 에이전트 적용
- Entry Team = capital × leverage 계산!
- Capital Team = margin 관리!
- UI = capital 표시 (margin 개념 명확!)

## 관련
- C08 (130% 경고)
- C12 (레버리지 자율)
