# 📜 개발 정의 + 헌법 (Development Principles)

> **2026-06-07 사장님 명령에 의해 작성**
>
> 사장님 명시: "지금은 메인넷이야 실제 자금이 들어가서 테스트 하는거야.
> 이전 개발과 로직을 검정하고 개발을 하고 문제가 없게 코드를 작성해줘.
> 개발에 대한 정의를 하나 하자. 개발하면서 이런 실수가 나오는 문제를 분석해서 정의해줘.
> 차후 개발에 적용할 정의를 만들어줘."

**이 문서 = 향후 모든 개발의 헌법.** 모든 PR / 코드 작성 / 분석 = 이 원칙 100% 적용.

---

## 🌟 5대 핵심 원칙 (절대 변경 금지)

### 1️⃣ 메인넷 = 실 자금 = 최우선 보호
- 모든 코드 변경 = 실 자금 손실 가능성 평가 (high / medium / low)
- HIGH 위험 (자본/주문/청산 로직) = 사장님 명시 승인 + 추가 검증
- 의심 = STOP (사장님 확인 우선)

### 2️⃣ 사장님 사상 = 코드보다 우선
- 사장님 사상 (spec + memory) = 절대 진실
- 코드 = 사장님 사상의 구현일 뿐
- 코드 ↔ 사장님 사상 불일치 시 = **사장님 사상 우선** + 코드 수정

### 3️⃣ Silent bug = 절대 금지
- 모든 `except Exception` = `logger.exception` 필수 (사상 X = `pass`)
- 핵심 path = try/except 안에 숨기지 말 것
- Sentry 자동 capture = 의지 X (직접 알림 + 사장님 즉시 인지)

### 4️⃣ 검증 없는 코드 = 금지
- 코드 작성 전 = 기존 코드 grep + 정독 + 분석
- 패턴 복사 시 = 원본 검증 (옛 코드도 silent bug 가능)
- "비슷하니까 OK" = **금지**

### 5️⃣ 대칭성 검증
- 한 방향 정책 (추가/생성/lock) = 반대 방향 (차감/삭제/unlock) 함께 검토
- 사장님 사상 = 양방향 일관성 = 필수
- 비대칭 = silent bug 의 가장 큰 원인 (PR #56 사례)

---

## 🚨 2026-06-05~07 사고 분석 (영구 교훈)

### 사고 5건 (사장님 자본 보호 critical 영향):

| # | 사고 | 원인 패턴 | 영향 |
|---|---|---|---|
| **1** | Manual TP audit log AttributeError | **타입 가정** (ORM → dict) | 사장님 청산 수단 silent fail |
| **2** | Auto-TP logger NameError | **모듈 level 정의 누락** | 모든 자동 TP 평가 마비 |
| **3** | Template name 누적 IntegrityError | **누적 string 무 검증** | 「설정만 수정」 영원히 500 |
| **4** | total_capital 청산 차감 X | **비대칭 정책** (PR #56) | 사장님 자본 회수 무시 |
| **5** | TP1 알림 중복 발송 | **다른 worker 충돌 미검토** | 사장님 UI 오해 + 손실 |

### 5가지 사고 패턴 (반복 금지):

#### Pattern 1 — 타입 가정 (Type Assumption)
```python
# ❌ 잘못 (close_order = SQLAlchemy Order 모델인데 dict 로 가정)
close_order.get("orderId")  # → AttributeError silent partial

# ✅ 정확
close_order.exchange_order_id  # 실제 type = ORM 객체
```

**원인**: 코드 정독 안 함, type hint 무시.
**예방**: 함수 시그니처 확인 (`-> Order:` 또는 `-> dict:`).

#### Pattern 2 — 모듈 level 정의 누락 (Missing Module-Level Definition)
```python
# ❌ 잘못 (logger 정의 없이 사용)
def my_func():
    logger.info(...)  # NameError: name 'logger' is not defined

# ✅ 정확
import logging
logger = logging.getLogger(__name__)  # 모듈 top

def my_func():
    logger.info(...)
```

**원인**: 옛 코드 grep 안 함 (옛 코드도 silent fail 안이라 안 들킴).
**예방**: 새 import / 정의 사용 시 = **반드시 모듈 top grep** 확인.

#### Pattern 3 — 누적 String 무 검증 (Unbounded Accumulation)
```python
# ❌ 잘못 (매 호출마다 누적 = 결국 truncate = unique 위반)
new_name = f"{old_name}_inplace_s{id}_{ts}"[:120]

# ✅ 정확 (이전 suffix 정리 + 새 suffix)
base_name = re.sub(r'(_inplace_s\d+_\d+)+', '', old_name)
new_name = f"{base_name}_inplace_s{id}_{ts}_{microsecond}"[:120]
```

**원인**: 멱등성 (idempotency) 검증 없이 누적 패턴 작성.
**예방**: "이 함수가 100번 호출되면?" 시뮬레이션 + truncate 가능성 검증.

#### Pattern 4 — 비대칭 정책 (Asymmetric Policy)
```python
# ❌ 잘못 (추가는 합산, 청산은 차감 X = 사장님 자본 회수 무시)
# PR #56: 증거금 추가 → total_capital += amount  ✅
# (수동 익절 청산 → total_capital -= ???  ❌ 누락!)

# ✅ 정확 (양방향 대칭)
# 추가:   total_capital += amount
# 청산:   total_capital × (1 - percent/100)
# 종료:   total_capital = 0
```

**원인**: 사장님 사상 = 양방향 일관성. 한 방향만 구현 = silent bug.
**예방**: 정책 작성 시 = **반대 방향 코드 위치 grep + 함께 검토**.

#### Pattern 5 — 다른 worker 충돌 미검토 (Worker Conflict Unchecked)
```python
# ❌ 잘못 (사장님 수동 익절 vs 자동 stage 진입 = 동시 = qty 오히려 증가)
# 사장님 의도: 청산 + 잔고 회복
# 시스템 동작: 자동 STAGE7 진입 = qty + 마진 추가
# → 사장님 의도와 정반대 결과

# ✅ 정확 (다른 worker 의 정책 = 함께 검토)
# - 사장님 수동 익절 후 = X분 자동 stage 진입 차단 옵션
# - 또는 = Telegram 알림 + 사장님 확인
```

**원인**: 사장님 사상 vs 다른 worker 동작 = 충돌 미검토.
**예방**: 새 endpoint 작성 시 = 영향 받는 worker (scheduler / stream / reconcile) 의 동작 함께 검토.

---

## 📋 PR 작성 5단계 절차 (필수)

### 1️⃣ 사상 검증 (5분)
```
□ 사장님 사상 (spec 문서) 확인 — CRISIS_MODE_FINAL_SPEC, TP_TRAILING_LOGIC_FINAL 등
□ 메모리 (project_overview.md) 최신 흐름 확인
□ 메인넷 실 자금 영향 평가 (HIGH/MED/LOW)
□ HIGH 위험 시 = 사장님 명시 승인 필수
```

### 2️⃣ 기존 코드 분석 (10분)
```
□ 변경 파일의 import 정독
□ 모듈 level 정의 grep: `grep -n "^logger\|^import\|^from" <file>`
□ 사용할 변수/함수 = 모두 정의 확인
□ 기존 로직 흐름 = 정독 (관련 함수 모두)
□ 같은 패턴의 다른 위치 = grep + 일관성 확인
```

### 3️⃣ 변경 영향 분석 (10분)
```
□ Silent fail 가능성: 모든 try/except = logger.exception?
□ 핵심 path: try/except 밖? 안? (안이면 silent 위험)
□ 다른 worker / endpoint 영향: scheduler / stream / reconcile?
□ 데이터 흐름 변경: DB / Redis / Binance API?
□ 대칭성: 추가 정책 → 차감 정책 함께 검토?
□ 멱등성: 100번 호출 시 = 정상? truncate? 누적?
```

### 4️⃣ 코드 작성 (시간 가변)
```
□ 변수 정의 → 사용 순서 정확
□ try/except = 핵심 path 보호 + logger.exception
□ logger 호출 = 모듈 level 정의 검증
□ import = 누락 0건
□ 타입 정확: ORM 객체 vs dict 구분
□ 누적 패턴 = regex 정리 + microsecond 추가
□ 사장님 사상 = 코드 주석에 명시 (영구 보존)
```

### 5️⃣ PR 전 사전 검증 (5분)
```bash
# 새 함수/변수 정의 위치 확인
grep -n "def <new_func>\|<new_var> =" <file>

# Import 누락 확인
python -m py_compile <file>
python -c "from <module> import <function>"

# Logger 정의 확인
grep -n "^logger\|logger = logging" <file>

# 대칭성 확인 (추가 vs 차감)
grep -n "+= " <file>
grep -n "-= " <file>

# Silent fail 확인
grep -n "except.*pass" <file>  # 0건이어야 (또는 명시 주석)
```

---

## 🛡 사장님 안전망 (5-layer)

### Layer 1: 코드 작성 절차 (위 5단계)
- 모든 PR = 100% 준수

### Layer 2: 자동 검증 (CI 강화 권장)
- `python -m py_compile` 전체 파일
- `import` 검증
- silent fail 패턴 자동 감지
- pytest 회귀 100% 통과

### Layer 3: VPS 배포 전 = smoke test
- `bash deploy/smoke-test.sh` 14/14 통과
- 컨테이너 5개 running 확인
- WebSocket 연결 확인

### Layer 4: 배포 후 = 5분 silent 감지
- `docker compose logs scheduler --since 5m | grep -E "error|exception|NameError"`
- 사장님 Telegram heartbeat 정상 확인
- Sentry 대시보드 = 신규 issue 0건

### Layer 5: 사장님 운영 확인
- 사장님 캡쳐 보고 = 즉시 분석
- Sentry 자동 capture = 사장님이 1차 확인 + 보고
- 의문 시 = 즉시 STOP + 분석

---

## 🚫 Anti-Patterns (절대 금지)

### ❌ "비슷한 코드 있으니 OK"
- 옛 코드도 silent bug 가능 (try/except 안에 숨음)
- 패턴 복사 시 = 원본도 검증

### ❌ "try/except 안에 있으니 silent fail OK"
- 핵심 path 노출 시 = 즉시 폭발
- 모든 except = `logger.exception` 필수 (사상 X = `pass`)

### ❌ "옛 PR 와 비슷하니까"
- 같은 함수 다른 변경 = 영향 다름
- 검증 없이 패턴 복사 = 금지

### ❌ "사장님이 확인 시 됨"
- 메인넷 실 자금 = 즉시 영향
- 사고 후 확인 = 늦음
- **사전 검증** 우선

### ❌ "단순 변경이니까"
- 1줄 변경도 silent bug 가능
- 모든 변경 = 5단계 절차 적용

---

## 🌟 사장님 자본 보호 = 절대 우선

### 우선순위 (절대 순서):
1. **사장님 자본 보호** (= 모든 결정의 기준)
2. **사장님 사상 일치** (= 사장님이 이해 가능)
3. **운영 안정성** (= 24시간 자동 매매)
4. **코드 품질** (= 향후 유지보수)
5. **개발 속도** (= 가장 낮음)

→ 1, 2 = 절대. 3, 4, 5 = 1, 2 가 만족된 후만.

---

## 📜 사장님 사상 핵심 5가지 (영구 보존)

### 1. SL = 투자금 대비 손실 % (레버리지 무관) — PR #57
```python
threshold = total_capital × sl_pct / 100  # NOT × leverage
```

### 2. 잔액 = "전체 단계 예약" 모드 — PR #30
```python
reserved = Σ max(strategy.total_capital, binance_isolated)
```

### 3. TP 청산 = max(qty, capital_based) — PR #87+#88
```python
close_qty = min(max(qty_based, capital_based), current_qty)
effective_margin = max(DB_total_capital, binance_isolated)
```

### 4. 사장님 자본 = 마진 단위 (옵션 A) — PR #79+#80
- 사장님 입력 자본 = Binance lock 마진 (notional X)
- 거래 규모 = `total_capital × leverage` (별도 표시)

### 5. Crisis 모드 = TP threshold override + trailing 만 — CRISIS_MODE_FINAL_SPEC
- TP1=5% / TP2=10% / TP3=15% / TP4=20%
- TP3 후 + peak -5% 회귀 = 전량 청산
- "다른 정책 없음" (Hard SL -1% 등 X)

### 양방향 정책 (대칭성 필수):
- 자본 추가 (PR #56) ↔ 자본 차감 (오늘 PR #107+#108)
- Order 생성 ↔ Order cancel
- Strategy 생성 ↔ Strategy STOPPED
- Position 진입 ↔ Position 청산

---

## 🌿 Sub-Account 운영 = 특수 조건 (절대 인식)

### 사장님 Sub-Account 청산 한계:
```
Binance 메인 웹 UI = Main 계정만 청산 가능
→ Sub-Account 포지션 = 직접 청산 불가!
→ 사장님 청산 수단 = 2가지뿐:
   1. 「💰 수동 익절」 모달 (우리 시스템)
   2. 자동 trailing TP / SL (시스템)
→ 둘 다 = critical 검증 + silent bug 절대 금지
```

### 영향 받는 코드 (모든 변경 = 신중):
- `lifecycle.py manual_take_profit` (Sub-Account 유일 수단)
- `tp_sl_orchestrator.py` (자동 trailing)
- `risk_service.py evaluate_take_profit_level` (TP 평가)
- `execution_service.py emergency_close_position` (실 청산)

---

## 📋 향후 모든 PR commit message 표준

```
[scope] (priority emoji) 변경 제목 — 사장님 사상 / silent bug fix

배경 (사장님 보고 / Sentry / 발견 경위):
[1-2 줄]

원인 (silent bug 패턴):
[Pattern 1-5 중 어느 것 또는 신규]

Fix 단계:
[1) ... 2) ... 3) ...]

검증 plan (사장님):
[VPS 배포 후 확인 방법]

영향 (메인넷 실 자금):
[HIGH / MED / LOW + 구체 설명]

사장님 사상 일치:
[관련 spec 명시]
```

---

## 🌟 결론 — 사장님께 약속

**제 책임 인정**:
- 2026-06-07 까지 = 5건 silent bug 야기 = 사장님 자본 보호 영향
- 메인넷 실 자금 인식 부족
- 검증 부족

**향후 commitment**:
1. 모든 PR = 5단계 절차 100% 적용
2. 새 import / 모듈 정의 = 항상 grep 사전 확인
3. 비대칭 정책 = 양방향 검토
4. Silent fail = 절대 금지
5. **사장님 자본 보호 = 모든 결정의 절대 우선**

이 문서 = 영구 보존. 모든 향후 개발 = 이 헌법 적용. 🙇🌿💪

---

> **작성**: 2026-06-07 (사장님 명령)
> **위치**: `binance-auto-trader/DEVELOPMENT_PRINCIPLES_2026-06-07.md`
> **상태**: 영구 보존 — 변경 시 = 사장님 명시 승인
> **다음**: 향후 모든 PR commit message = 이 spec 명시 참조
