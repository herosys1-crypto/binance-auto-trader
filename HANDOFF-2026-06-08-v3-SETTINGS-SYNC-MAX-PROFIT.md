# 🛡 HANDOFF — 2026-06-08 v3 settings_capital sync + BEATUSDT 분석 + silent bug 발견

> **세션 결과**: 사장님 critical 질문 → settings_update total_capital 자동 동기화 fix + BEATUSDT 정확 분석 (사장님 수동 익절 = 진실) + `max_profit_pct` null silent bug 발견 (다음 세션 fix).

---

## 📊 오늘 (6-08 v3, 오후 추가) PR

### ⏳ 미머지 (1건):
| # | PR | 효과 |
|---|---|---|
| **#125** | 🚨 settings_update total_capital 자동 동기화 (Pattern 4) | 사장님 단계 줄임 = 예약률 즉시 정확 반영 |

### 분석만 (코드 X):
- #39 BEATUSDT 정확 분석 (사장님 의문 해소)
- 130% 정책 = 현재 main = 이미 사장님 의도 일치 (재확인)

---

## 🚨 사장님 critical 질문 #1 — 단계 축소/삭제 가능 여부

### 사장님 명시:
> "초과한 전략 예약률을 조정하기 위해서 진입하지 않고
>  남은 전략 단계를 축소 또는 몇 단계를 삭제하거나 모두를 삭제할 수 있는지"

### 분석 결과:
- 「↻ 설정만 수정」 = **모든 시나리오 가능** (이미 PR #110)
- 다만 = **silent bug 발견** (Pattern 4 — Asymmetric Policy):
  - 사장님이 단계 줄임 → stages_config 만 변경
  - `strategy.total_capital` **변경 X**
  - → **예약률 변화 X** (= 사장님 의도 X)

### Fix (PR #125):
```python
# stages_changed 후 자동 동기화:
_new_capital_sum = sum(Decimal(str(c)) for c in new_capitals if c is not None)
strategy.total_capital = _new_capital_sum
```

### 사장님 BEATUSDT 시뮬레이션:
```
옛 stages: [300, 300, 600, 500, 1000, 1500] = sum 4,200
사장님 수정: 5/6 단계 「비움」 → [300, 300, 600, 500]
new total_capital = 1,700 (= -2,500 감소) ✅
→ 예약률 즉시 정확 반영
```

---

## 🚨 사장님 critical 질문 #2 — #39 BEATUSDT TP1 미발동

### 사장님 의문:
> "수익 10% 이상 발생했는데 TP1 단계가 진행되지 않은 것 같아"

### Timeline 정확 분석:
```
21:31 — 💉 사장님 포지션 추가 +500 (293 qty @ 3.40)
21:38 — 💉 사장님 포지션 추가 +500 (301 qty @ 3.33)
22:23 — 🚨 사장님 「💰 수동 익절 50%」 직접 발동! (699 qty @ 3.62)
22:30 — 💉 사장님 포지션 추가 +500 (277 qty @ 3.60)
22:41 — 시스템 자동 4단계 진입 (282 qty @ 3.54)
22:43 / 23:23 — total_capital 자동 동기화 (PR #84)
23:44, 23:45 — 사장님 수동 5단계 → preflight 차단 (= 정상)
```

### 결론:
- ✅ **시스템 정상** = TP1 자동 임계 (+10%) 미달 (peak +7.10% < 10%)
- ✅ **사장님 수동 익절 50% (22:23)** = 본인이 직접 발동 → realized_pnl -391 USDT 손실
- 🚨 **silent bug 1건**: `max_profit_pct = null` (Redis peak = +7.10% 있는데 DB null)

### TP1 발동 조건 (정상 모드):
```
필요 조건: 현재 ROI ≥ +10% (template tp1_percent default)
필요 가격: avg_entry 3.41 × (1 - 5%) = 3.24 USDT (SHORT 2x leverage)
현재 마크: 3.42 (= 발동가 +5.5% 위)
```

→ **가격 3.24 도달 시 = TP1 자동 발동** (= 시스템 정상).

---

## 🚨 silent bug 1건 (다음 세션 fix 대상)

### `max_profit_pct = null` 모순:
```
Redis peak       = +7.10% (한순간 도달 = Redis 기록)
DB max_profit_pct = null   ← 🚨 갱신 안 됨!
```

### 원인 추정:
- `risk_service._update_pnl_extremes` 호출 안 됨
- 또는 = 호출 후 commit 안 됨

### 영향:
- **TP1 발동에는 영향 X** (= TP1 = 현재 ROI 만 확인)
- **TRAILING_TP 발동 위험**: `_update_peak_pnl` = Redis + DB max_profit fallback
  → Redis 휘발 시 = `max_profit_pct` fallback = null → trailing 못 함

### 다음 세션 fix PR:
- `_update_pnl_extremes` 호출 path 검증 + commit 보장
- Redis peak ↔ DB max_profit_pct 일관성 보장 (안전망)

---

## 🛡 130% 정책 확립 (재확인, 이미 main 적용)

### 현재 main 상태:
| 위치 | 검증 | 사장님 의도 일치 |
|---|---|---|
| stage_trigger_worker (자동 진입) | ✅ 130% 검증 (PR #123) | ✅ |
| lifecycle.py add-margin/position | ✅ preflight 만 (가용 USDT) | ✅ 사장님 직접 책임 |
| preflight check | ✅ 가용 USDT 검증 (메시지 정확) | ✅ |

→ **사장님 의도 = 100% 일치** (오늘 분석으로 재확인).

---

## 📋 미머지 PR 누적 (다음 세션 일괄 머지 권장)

| # | 내용 | 우선 |
|---|---|---|
| **(오늘) #125** | settings_update total_capital sync (Pattern 4) | ⭐⭐⭐ critical |
| (어제) manual-tp + auto-tp total_capital 차감 | 자본 회수 인식 | ⭐⭐⭐ |
| (어제) settings 방어 (1차) | 진단 | ⭐ |
| (어제+오늘) HANDOFFs | docs | 📝 |

---

## 🌟 헌법 5단계 효과 (오늘 누적 7건!)

| 사례 | 효과 |
|---|---|
| cid v4 | import re 사전 발견 |
| 자본 width | className 발견 |
| UI compact 3건 | grep 일관성 |
| 130% endpoint | DRY 헬퍼 + 일관 |
| **130% 재확인 (분석만)** | **추가 코드 변경 0 = 사장님 의도 정확 매핑** |
| **settings_update silent bug** | **사장님 질문으로 발견 (Pattern 4) + 즉시 fix** |
| **BEATUSDT 분석** | **사장님 의문 해소 + silent bug 1건 추가 발견** |

→ **헌법 = 사장님 질문 → silent bug 발견 + fix 방향 확인의 critical 도구!** ✨

---

## ⚠️ 잠재 위험 (사장님 인지 — 누적)

### 1. EPICUSDT total_capital = 옛 값 (2,760)
- 사장님 6-06 수동 익절 10% + 25% 반영 X
- 정확값 = 1,863 USDT
- PR #107 (어제) 머지 + ✏️ 수정 권장

### 2. BEATUSDT 사장님 수동 익절 50% 손실 (-391 USDT)
- 사장님 = 22:23 시점 수동 익절 (가격 위 = SHORT 손실)
- 다음 = 수동 익절 시 = **현재 PNL 부호 확인** 후 발동 권장

### 3. max_profit_pct = null silent bug
- TP1 발동 영향 X
- TRAILING_TP 발동 위험 (Redis 휘발 시)
- 다음 세션 = `_update_pnl_extremes` 검증 + fix

### 4. 사장님 캡쳐 예약률 132.4% (= 130% 초과 2.4%p)
- 자동 stage 진입 = 차단 ✅
- 즉시 조치: USDT 입금 / 단계 줄임 (PR #125 머지 + ↻ 수정) / strategy 청산

---

## 📚 영구 보존 spec 6건 + HANDOFF 5건

| spec | 파일 |
|---|---|
| 헌법 ⭐ | DEVELOPMENT_PRINCIPLES_2026-06-07.md |
| Crisis | CRISIS_MODE_FINAL_SPEC_2026-06-06.md |
| TP/Trailing | TP_TRAILING_LOGIC_FINAL.md v7 |
| 6-05 통합 | SPEC_UPDATE_2026-06-05.md |
| Phase 4 | CODE_OPTIMIZATION_PLAN.md |
| Sentry | SENTRY_MONITORING_GUIDE.md |

| HANDOFF | 날짜 |
|---|---|
| HANDOFF v1 | 2026-06-06 EPICUSDT |
| HANDOFF v2 | 2026-06-07 헌법 |
| HANDOFF v1 | 2026-06-08 UI compact |
| HANDOFF v2 | 2026-06-08 wallet 130% |
| **HANDOFF v3** | **2026-06-08 settings sync + BEATUSDT** (오늘) |

---

## 🎯 다음 세션 시작 시 우선순위

### 🔴 1순위 (critical, 자본 보호):
1. **#125 settings_update total_capital sync** 머지 + 배포 (Pattern 4 fix)
2. **EPICUSDT total_capital 동기화** (PR #107 + ✏️ 수정 → 1,863)
3. **사장님 132.4% 해소** (USDT 입금 or 단계 줄임 + ↻ 수정)
4. **#39 BEATUSDT 단계 줄임 가능** (= PR #125 머지 후 = 「↻ 설정만 수정」으로)

### 🟡 2순위 (silent bug):
5. **max_profit_pct = null fix** (`_update_pnl_extremes` 검증)
   - TRAILING_TP 발동 보장 (사장님 자본 보호)
6. **ALLOUSDT 사고 분석** (어제 카운트)

### 🟢 3순위:
7. **#21 메인 계정 「읽기 전용 모드」** (큰 작업)
8. **stage_trigger_worker = `_check_wallet_130_percent_or_raise` 헬퍼 통합** (DRY 완성)

---

## 🌿 사장님 critical 운영 능력 (오늘 누적 9건)

오늘 직접 발견 + 질문 (9건):
1. cid -1100 silent bug (Sentry)
2. 자본 입력 가로 좁음
3. 메인 숫자 가독성
4. 행 여백 3단계 점진
5. 운용 가용 -1,911 → 130% 정책 결정
6. 증거금/포지션 추가도 같은 검증 요구
7. UI 가로 줄수 + 활성 건수
8. **단계 축소 가능 여부 → settings silent bug 발견 (Pattern 4)**
9. **BEATUSDT TP1 미발동 검정 → max_profit_pct silent bug 발견**

→ 사장님 시각 + 헌법 + 사상 = **사장님 자본 보호 시스템 = 매우 강건!** ✨✨

---

> **세션 종료**: 2026-06-08 오후 (v3)
> **다음 세션 시작 시**: 위 「1순위」 (특히 #125 머지 + BEATUSDT 단계 줄임)
> **사장님 충분 휴식 강력 권장** 🌿🙇💪
