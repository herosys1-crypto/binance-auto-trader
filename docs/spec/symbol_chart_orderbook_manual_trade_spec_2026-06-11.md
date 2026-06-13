# 📊 심볼별 차트 + Order Book + 수동 거래 UI = 영구 spec (2026-06-11)

> **#22 옛 미해결 = 사장님 UX 강화 + critical 수동 거래!**
>
> 본 spec = 사장님 사상 + 영구 보존 = 시스템 진화의 영구 기록!

---

## 🛡 사장님 헌법 5대 원칙 (= 본 기능 적용!)

1. **메인넷 = 실자금** → 수동 거래 = 검증 X = 절대 금지!
2. **사장님 사상 우선** → UI = 사장님 직관 + 사장님 선택 = 절대 보존!
3. **silent bug 금지** → 주문 발송 = 결과 즉시 Telegram!
4. **검증 없는 코드 금지** → 수동 거래 = 다층 검증 = 자본 + 130% + 확인 모달!
5. **대칭성** → SHORT/LONG = 정확한 검증!

---

## 1. 핵심 사상 = 사장님 직관 UX!

### **사장님 = 「심볼 클릭」 = 즉시 모든 정보!**

```
사장님 = 「전략 인스턴스 카드」 = 「📊」 클릭
  ↓
모달 열림 = 3 컬럼!
  ↓
1. 좌: 차트 (= 1m/5m/15m/1h/1d!)
2. 중: Order Book (= 매수/매도 실시간!)
3. 우: 수동 거래 UI (= LIMIT/MARKET = 검증 + 확인!)
  ↓
사장님 = 즉시 모든 정보 = 자율 운영 가능!
```

---

## 2. Phase 1 = 라이브러리 선정!

### **차트 라이브러리 후보:**

| 라이브러리 | 장점 | 단점 | 결정 |
|---|---|---|---|
| **lightweight-charts** (TradingView) | ⭐⭐⭐ 가벼움 (35KB) + Binance 같은 UX + 무료 | CDN | ⭐ **추천!** |
| Chart.js | 범용 | 무거움 (200KB+) + 거래소 UX 부족 | ❌ |
| 자체 canvas | 완전 제어 | 개발 부담 | ❌ |

= **사장님 선택: lightweight-charts!**

CDN: `https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js`

### **Order Book = 자체 구현!**

- WebSocket: `wss://fstream.binance.com/ws/{symbol}@depth20@100ms`
- 매수 호가 = 녹색 = 점유율 bar!
- 매도 호가 = 적색 = 점유율 bar!

---

## 3. Phase 2 = 차트 컴포넌트 = spec!

### **3.1 endpoint:**

```python
GET /api/v1/market/kline?symbol=BEATUSDT&interval=1m&limit=200
```

= Binance USDⓢ-M Perpetual = `/fapi/v1/klines` 프록시!

### **3.2 사장님 = 시각 마커!**

```
✅ Entry 1단계 = 노란 점선 + 「1️⃣ Entry 6.31」
✅ Entry 2단계+ = 노란 점선 + 「2️⃣ Entry 8.73」
✅ SL = 적색 실선 + 「🛡 SL 5.97」
✅ TP1 = 녹색 점선 + 「🎯 TP1 +20%」
✅ TP2 = 녹색 점선 + 「🎯 TP2 +50%」
✅ 청산가 = 짙은 적색 + 「⚠️ Liq 4.50」
✅ 현재가 = 파랑 실선 + 「💰 7.94」
```

### **3.3 사장님 = 인터벌 변경!**

= 1m / 5m / 15m / 1h / 4h / 1d = 클릭!

---

## 4. Phase 3 = Order Book = spec!

### **4.1 WebSocket 통합!**

```javascript
const ws = new WebSocket(`wss://fstream.binance.com/ws/${symbol.toLowerCase()}@depth20@100ms`);
ws.onmessage = (e) => {
    const data = JSON.parse(e.data);
    // data.b = bids = 매수 호가
    // data.a = asks = 매도 호가
    render_orderbook(data);
};
```

### **4.2 UI:**

```
매도 호가 (= 적색 = top)
  7.95 = 1000 BEAT  ▓▓▓▓▓
  7.96 = 500 BEAT   ▓▓
  ...
현재가: 7.94 ⭐
매수 호가 (= 녹색 = bottom)
  7.93 = 2000 BEAT  ▓▓▓▓▓▓▓▓
  7.92 = 1500 BEAT  ▓▓▓▓▓▓
```

### **4.3 사장님 = 「가격 클릭」 = 자동!**

= 매수/매도 가격 클릭 → 수동 거래 UI = price 자동 채움!

---

## 5. Phase 4 = 수동 거래 UI = critical! ⭐⭐⭐

### **5.1 사장님 critical 사상:**

> **"수동 거래 = 사장님 = 직접 = 자율! = 자본 보호 = 100%!"**

### **5.2 다층 검증 (= 검증 X = 발송 X!):**

```
1. 사장님 옵션 검증
   ✓ 거래소 계정 선택
   ✓ 심볼 정확 (= STRATEGY 활성 심볼만!)
   ✓ side (BUY/SELL) 선택
   ✓ 주문 type (LIMIT/MARKET)
   ✓ 가격 (LIMIT 시!)
   ✓ 수량 (= step_size flooring!)

2. 자본 검증
   ✓ 사장님 wallet 잔액 ≥ 주문 마진
   ✓ 130% wallet 검증
   ✓ 사장님 strategy planned_capital ≤ 한도

3. silent bug 차단
   ✓ 주문 발송 = 결과 = Telegram 즉시!
   ✓ 실패 = traceback + 사장님 인지!

4. 사장님 확인 모달 ⭐⭐⭐
   ✓ "확실합니까?" = 사장님 critical = 더블 확인!
   ✓ 5초 timer = 「확인」 비활성화!
```

### **5.3 endpoint:**

```python
POST /api/v1/manual-trade/order
{
  "exchange_account_id": 2,
  "symbol": "BEATUSDT",
  "side": "BUY",
  "type": "LIMIT",
  "price": 7.94,
  "quantity": 100,
  "confirm_token": "abc123"  # = 사장님 확인 모달 = 신 생성!
}
```

`confirm_token` = 사장님 확인 = 서버 = redis 5초 TTL 검증!
= 외부 = 직접 호출 = 자동 X!

### **5.4 사장님 헌법 = 안전망:**

| 항목 | 사장님 보호 |
|---|---|
| 미체결 시 = 자동 취소 | 60초 timeout = 자동! |
| 결과 = Telegram | 즉시! |
| 실패 = 사장님 통제 | 자동 X! |
| 주문 발송 후 = strategy 영향 X | strategy 별도 관리! |

---

## 6. 사장님 직접 시나리오 (= 검증!)

### **시나리오 A: 사장님 = 차트 확인**

```
1. 「전략 인스턴스 카드」 = 「📊」 클릭
2. 모달 열림 = 차트 + Order Book + 수동 거래
3. 사장님 = 1h 클릭 = 1시간 차트!
4. 사장님 = Entry/SL/TP 마커 확인!
5. 사장님 = 시장 깊이 = Order Book!
```

### **시나리오 B: 사장님 = 수동 LIMIT 매수**

```
1. 사장님 = Order Book = 매수 가격 클릭
2. 수동 거래 UI = price 자동 채움 = 7.93!
3. 사장님 = 수량 입력 = 100 BEAT!
4. 사장님 = 「주문 발송」 클릭!
5. 확인 모달 = "확실합니까?" + 5초 timer!
6. 사장님 = 「확인」 (= 5초 후!)
7. POST /manual-trade/order = 발송!
8. Telegram 즉시 알림!
```

### **시나리오 C: 사장님 = 자본 부족 = 차단!**

```
1. 사장님 = 수동 LIMIT = 1000000 USDT 입력
2. 자본 검증 = wallet 잔액 부족!
3. 발송 X! = 사장님 알림: "wallet 부족!"
4. 사장님 = 안심 = 자본 보호!
```

---

## 7. 사장님 critical = 영구 보존!

본 spec = **사장님 = 자율 수동 거래 = 영구 안전!**

= UX 강화 + 수동 거래 = 100% 검증!

= **사장님 = 자율 운영 = 무한 진화!** 🛡✨🌟
