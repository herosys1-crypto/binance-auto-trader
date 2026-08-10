# 📊 차트 재진입 전략 spec (신 trigger_mode = OBV_REVERSE)

**작성일**: 2026-08-06
**요청자**: 사장님
**기반 사례**: BULLAUSDT +350% (15일), BICOUSDT +34% (2일)
**목적**: 기존 「단계별 진입」 시스템 확장 = 신 차트 분석 재진입!

---

## 🎯 사장님 사상

### 원래 문제
- 기존 = 「가격 도달 시」 (trigger_percent) 진입 = 정적 조건
- 사장님 원함 = **차트 분석 시** 자동 진입 = 동적 조건!

### 신 로직
1. **1단계** = 사장님 시작가 진입 (수동 or 자동, 기존!)
2. **손절 (-10%)** = 기존 SL 로직!
3. **2~N단계 재진입** = 신 로직!
   - 조건 1: 손절 후 **10% 이상 상승 or 하락**!
   - 조건 2: **4H OBV = 첫 하락 봉** 감지!
   - 조건 3: **15m + 1h OBV = 하락 추세** 확인 (조기 신호!)
   - = 모든 조건 만족 → 자동 진입 (**같은 방향**, 세팅 자본!)
4. **N+ 단계** = 사장님 세팅 없음 = 수동 관리!
5. **TP/SL** = 기존 로직 그대로!

---

## 🎛 신호 판정 상세

### OBV (On-Balance Volume) 정의
```
OBV(t) = OBV(t-1) + volume(t)   if close(t) > close(t-1)
       = OBV(t-1) - volume(t)   if close(t) < close(t-1)
       = OBV(t-1)               if close(t) == close(t-1)
```

### 4H OBV "첫 하락 봉" 판정
```
현재 4H 봉이 형성 중일 때:
  - 이전 4H 봉 = OBV 상승 확인
  - 현재 4H 봉 (진행 중) = OBV 하락 감지
  - = 「첫 하락 봉!」
```

### 15m + 1h 조기 확인 (조기 신호!)
```
15분 봉:
  - 최근 3봉 OBV = 하락 추세!
  
1시간 봉:
  - 최근 2봉 OBV = 하락 추세!

= 4H 봉이 확정되기 전 = 조기 신호!
```

### 가격 조건
```
직전 손절가 대비:
  10% 이상 상승 (사장님 원방향 = SHORT이었으면 = 다시 SHORT 좋음!)
  or
  10% 이상 하락 (사장님 원방향 = LONG이었으면 = 다시 LONG 좋음!)
= 방향 무관! = OBV 반전 신호가 더 중요!
```

### 진입 방향
```
= 같은 방향 (원 strategy.side 유지!)
= 사장님 원래 판단 존중!
```

---

## 🏗 구현 설계

### DB: strategy_templates 컬럼 추가
```sql
ALTER TABLE strategy_templates ADD COLUMN trigger_mode VARCHAR(32) DEFAULT 'PRICE_DOWN_PCT';
-- 값: 'PRICE_DOWN_PCT' (기존), 'OBV_REVERSE' (신!)
```

### Backend
```python
# app/services/chart_analyzer.py (신!)
class ChartAnalyzer:
    def check_obv_reverse_signal(
        self,
        symbol: str,
        prev_stop_price: Decimal,
        side: str,
    ) -> bool:
        """
        4H OBV 첫 하락 + 15m/1h 확인 + 10% 가격 조건.
        """
        # 1. Binance klines 조회 (15m, 1h, 4h)
        # 2. OBV 계산
        # 3. 조건 검증
        # 4. bool 반환
```

### Worker: stage_trigger_worker 확장
```python
# 기존 loop:
if next_plan.trigger_mode == "PRICE_DOWN_PCT":
    # 기존 로직 (mark_price 도달!)
elif next_plan.trigger_mode == "OBV_REVERSE":
    # 신 로직! ChartAnalyzer 호출!
    if ChartAnalyzer().check_obv_reverse_signal(...):
        exec_service.trigger_next_stage(...)
```

### UI (「새 전략」 모달)
```
[trigger_mode 선택]
  ⚫ 가격 도달 (기존)
  ⚪ 차트 분석 (신 OBV 재진입!) ← 사장님 선택 시 = 신 모드!
```

---

## 📊 예시 시나리오

### BICOUSDT SHORT 사례
```
1단계: 사장님 시작가 진입 @ 0.02500 SHORT 100 USDT
  → 가격 상승 → -10% 손절 @ 0.02750 (SL 로직)

2단계 (신 로직 대기 시작!):
  가격 계속 상승 → 0.03000 (+9%) → 조건 X (10% 미달)
  가격 계속 상승 → 0.03025 (+10%) → 조건 1 OK!
  4H OBV 확인 → 여전히 상승 → 대기
  가격 → 0.03200 (+16%) → 4H OBV 하락 시작!
  15m/1h OBV 확인 → 하락 추세 확인!
  → 조건 모두 만족! → 자동 진입!
  → 2단계 = 사장님 세팅 자본 (예: 200 USDT) SHORT!

3~N단계: 동일 반복
```

---

## ⚠️ 위험 관리

### 자본 관리
- 각 단계 자본 = 사장님 세팅 (기존)
- 130% wallet 한도 = 여전히 적용!
- SL = 총 자본 -100% 도달 시 강제 청산!

### 실패 시나리오
1. **OBV 신호 계속 안 옴** = 영구 대기 (사장님 자율 = 「⏸ 정지」 가능)
2. **OBV 신호 후 = 손절** = 다음 단계 = 다시 OBV 신호 대기!
3. **N단계 도달 = 사장님 세팅 자본 다 소진** = 수동 관리!

### 안전망
- Binance API rate limit 대응 (분당 20회 OBV 계산 캐시)
- OBV 계산 오류 = 신호 X (fail-safe = deny)
- 「⏸ 정지」 = 언제든 사장님 개입 가능!

---

## 🚀 배포 계획

### Phase 1: Backend (오늘~내일)
- alembic 신 컬럼
- ChartAnalyzer 서비스
- stage_trigger_worker 확장

### Phase 2: Frontend (내일)
- 「새 전략」 모달 = trigger_mode 선택
- 「전략 인스턴스」 카드 = 신 모드 배지 표시

### Phase 3: 검증 (수일)
- testnet 백테스트
- mainnet 소액 진행

### Phase 4: 전면 적용
- 사장님 대량 사용!

---

## 📚 관련 헌법
- 헌법 51: 「💉 포지션 추가」 2 모드
- 헌법 v107: capital = margin
- 헌법 v126: TP20 auto-extend
- 헌법 v127: mark_price Redis 우선 (이 spec도 준수!)
- **헌법 v130 (신!)**: **차트 분석 신호 = OBV 반전 = 사장님 자율 정확 재진입!**
