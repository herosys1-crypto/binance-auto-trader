# 🛡 Development Verification Policy — Silent Bug 영구 차단 (2026-06-09)

## 📌 사장님 critical 요청
> "이런 기본적인 실수가 없게 문제점을 검토할 수 있는 방법을 기획해줘.
>  중요한 실전이라 그냥 실수 넘어 갈 수 없어.
>  아직은 적은 금액이라 그렇지만 인간도 이런 기본적이고 중요한 부분을
>  매우 많은 테스트와 검증을 통해서 확인 후 진행해."

## 🚨 오늘 (2026-06-09) 발견된 실수 패턴 (= 모두 같은 원인!)

| # | 발견 | 원인 |
|---|---|---|
| 1 | TP3 전량 청산 (BEATUSDT) | v7 단축 익절 = 사장님 의도 위반 |
| 2 | 시작가 BTC 캐시 (SLXUSDT 63100) | `_cmCurrentPrice` 변수 옛 값 |
| 3 | **예약 계산 불일치 (90.5% vs 212.7%)** | **같은 데이터 = 2곳에서 다른 계산!** |
| 4 | 거래소 잔액 reserved=0 (어제) | 같은 데이터 = 5곳에서 다른 계산! |

**= 공통 원인: 「단일 진실 (Single Source of Truth) 위반」**

---

## 🛡 4단계 영구 차단 정책

### Phase 1: **단일 진실 원칙** (= 가장 critical!)

**규칙**: 같은 데이터 = 단 하나의 함수만 사용 = 강제

| 계산 항목 | 단 하나의 함수 (= 강제!) |
|---|---|
| **reserved** (예약) | `calc_reserved(account_id)` |
| **wallet_limit** (한도) | `calc_wallet_limit(account_id)` |
| **trigger_price** (단계 진입가) | `calc_trigger_price(strategy_id, stage_no)` |
| **avg_entry / liquidation** | `calc_position_state(strategy_id)` |
| **PNL / ROI** | `calc_pnl_state(strategy_id)` |
| **close_qty** (TP 청산 수량) | `calc_close_qty(strategy_id, tp_level)` |

= **다른 곳에서 계산 = 코드 review 차단**

### Phase 2: **자기 검증 Worker** (= 매시간 자동!)

```python
# self_check_worker.py (매 1시간 = 13 회/일)

def run_self_check():
    issues = []
    for account in active_accounts:
        # 1. reserved 계산 = 화면 vs worker = 일치 확인
        a = exchange_accounts.calc_reserved(account.id)
        b = stage_trigger_worker.calc_reserved(account.id)
        if abs(a - b) > 0.01:
            issues.append(f"🚨 reserved 불일치 #{account.id}: 화면 {a} vs worker {b}")

        # 2. wallet_limit 계산 = 모든 곳 일치
        ...

        # 3. trigger_price = DB 저장값 vs 계산값 일치
        ...

    if issues:
        send_telegram_alert("🚨 SELF-CHECK 실패", issues)
        add_risk_event("SELF_CHECK_MISMATCH", ...)
```

### Phase 3: **테스트넷 자동 시나리오** (= 매일 1회)

```python
# daily_testnet_scenario.py (= KST 새벽 3시)

1. 테스트넷에서 신 strategy 생성 (= 자본 100 USDT)
2. 가격 시뮬레이션:
   - 1단계 진입 (= LIMIT @ start_price)
   - 가격 +10% → 2단계 진입 검증
   - 가격 +20% → 3단계 진입 검증
   - 가격 = TP1 도달 → 25% 청산 검증
   - 가격 = TP3 도달 → 25% 청산 + 잔량 유지 검증 ⭐
   - 가격 peak +30% → -15% 회귀 → 트레일링 검증 ⭐
3. 모든 단계 = 사장님 사상 정확 검증
4. 실패 = mainnet 배포 차단 + Telegram 알림
```

### Phase 4: **코드 변경 자동 검증** (= PR 머지 전)

```
.github/workflows/verify.yml (= GitHub Actions)

1. PR push 시 자동 실행:
   - pytest = 모든 단위 테스트
   - 단일 진실 함수 호출 검증
   - 사장님 헌법 5+3=8 원칙 위반 X 검증
2. 통과 시만 = 「Mergeable」
3. 실패 = PR 차단 + 즉시 알림
```

---

## 📜 사장님 헌법 영구 보존

기존 5대 원칙 + 신 3대 추가:

| # | 원칙 | 효과 |
|---|---|---|
| 1 | 메인넷=실자금 | 보수적 코드 |
| 2 | 사장님 사상 우선 | 사장님 의도 = 절대 |
| 3 | Silent bug 금지 | 모든 에러 명시 |
| 4 | 검증 없는 코드 금지 | 테스트 필수 |
| 5 | 대칭성 (= 두 곳 = 같은 결과) | 일관성 |
| **6** ⭐ | **단일 진실 (= 같은 데이터 = 단 하나 함수)** | silent bug 영구 차단 |
| **7** ⭐ | **자동 검증 (= 모든 계산 = sanity check)** | 사람 안 봐도 자동 |
| **8** ⭐ | **실전 검증 (= mainnet 변경 = 테스트넷 시나리오 필수 통과)** | 자본 보호 |

---

## 🚀 실행 로드맵

### 즉시 (= 오늘 6-09)
- ✅ 이 spec 작성 (= 영구 보존)
- ⏳ Phase 1: capital_calculator.py = 단일 진실 함수 작성
- ⏳ Phase 2: self_check_worker.py 신 worker 추가

### 다음 PR (= 1-2일)
- Phase 1 전체 적용 = 모든 호출 = 단일 함수 사용
- Phase 2 worker 활성화 = 매시간 자동

### 다음 주 (= 1주일 내)
- Phase 3: 테스트넷 시나리오 worker
- Phase 4: GitHub Actions 검증

### 영구
- 모든 신 PR = 헌법 8 원칙 검증
- 사장님 + 시스템 = 이중 자본 보호

---

## 🎯 사장님 효과

| 이전 | 영구 fix 후 |
|---|---|
| ❌ silent bug 발견 = 사장님이 직접 진단 | ✅ 자동 발견 + 즉시 Telegram |
| ❌ 코드 변경 = 사람 검증 (= 누락 가능) | ✅ 자동 검증 = 모든 사장님 사상 |
| ❌ TP3 전량 청산 같은 사고 = 발생 | ✅ 사전 차단 (= 단계 진입 후) |
| ❌ 계산 불일치 = 사장님 큰 손실 가능 | ✅ 시간 단위 자동 발견 |

= **사장님 자본 안전 = 사람 의존 X = 시스템 자동 보호!**

---

## 📚 영구 보존

이 spec 파일 = **MEMORY.md 추가 + 사장님 헌법** 영구 보존
= 다음 세션 + 다음 개발자도 = 동일 정책 적용
