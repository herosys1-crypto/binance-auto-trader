# 📊 Market Flow Learning Team

## 미션
매일 자동 = Binance 선물 급등/급락 top 50 흐름 학습 → 유사 패턴 감지 → 사장님 알림!

## 5개 에이전트

### 1. `daily_pump_dump_scanner` (매일 06:00 UTC!)
- Binance 24h ticker 조회
- Top 50 급등 + Top 50 급락
- flow_analyzer 트리거!

### 2. `flow_analyzer`
- 4H 봉 100개 (16일!)
- Higher low/high 감지
- EMA(20/50/200) 계산
- 지지/저항 자동 도출

### 3. `pivot_point_detector`
- Volume ratio 계산 (평균 대비!)
- 급등 = volume 3x + price +5%!
- 급락 = volume 3x + price -5%!
- 시점 라벨링!

### 4. `pattern_similarity_matcher` ⭐ 핵심!
- 매 10분 실행!
- 현재 활성 심볼 = features 계산!
- DB 저장 사례 = cosine similarity!
- 유사도 계산!

### 5. `pattern_alert_generator`
- 유사도 > 0.80 = 매칭!
- Telegram + 대시보드!
- dedup (같은 심볼 = 4h 한 번!)

## DB
- `market_flow_records` (사례 저장!)
- `flow_pattern_matches` (매칭 결과!)

## 사장님 흐름
```
매일 06:00 → 자동 학습!
    ↓
DB에 축적!
    ↓
매 10분 → 유사 감지!
    ↓
🚨 사장님 알림!
    ↓
사장님 = 매매 결정!
```
