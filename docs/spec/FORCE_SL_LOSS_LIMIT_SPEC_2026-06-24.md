# 📜 사장님 사상 — 손실 한도 강제 청산 (Force Stop-Loss / Loss-Limit Close) 정책 (2026-06-24)

> **사장님 명시 (2026-06-24)**:
> > "모든 롱포지션으로 진입해서 손실이 -10% 가 발생하면 강제로 청산하는 옵션을 만들어줘.
> > 기본을 -10%로 하고 -5% -10% -15% -20% 이렇게 선택할 수 있게. 기능 활성화와 비활성화도 만들어줘.
> > 숏포지션은 비활성화를 기본으로 하고 같은 트리거를 만들어서 선택할 수 있게."

> **사장님 확정 (2026-06-24 — 기획 단계 질의응답)**:
> - **손실 기준 = ROI** (= 레버리지 포함, 내 증거금의 %). 기존 SL과 동일한 계산.
> - **적용 범위 = 전역** (= 롱 전체 한 번에 on/off+임계값, 숏 전체 한 번에 on/off+임계값).

이 문서 = 영구 보존. 향후 모든 관련 코드 변경 = 이 spec 100% 적용.
관련 문서: [[DEVELOPMENT_PRINCIPLES]] (헌법) · BEATUSDT SL v4 (= 기존 SL ROI 사상) · v51 mark_price 단일 진실 fix.

---

## 🌟 1. 사장님 사상 핵심 (절대 변경 금지)

### 한 줄 정의
**열려 있는 포지션의 ROI 손실이 사장님이 정한 한도(-5/-10/-15/-20%)에 도달하면, 자동으로 전량 시장가 청산하고 그 전략을 종료한다. 롱/숏 각각 전역 on/off + 임계값을 가진다.**

### 🌟 1-A. 전역 + 전략별 override (2026-06-24 추가)
> **사장님 명시 (2026-06-24)**:
> > "각각 전략에 따라 다르게 하고 싶은데 가능할까? 모두에게 같은 적용을 하는데 각각의 전략에 우선하는 방식으로 만들어줘."

**= 전역 설정이 모든 전략의 기본값 + 전략별 override 가 있으면 그게 우선 (NULL = 전역 상속).**

| 우선순위 | 출처 | 의미 |
|---------|------|------|
| 1 (높음) | 전략별 override (`strategy_instances.force_sl_*_override`) | 값이 있으면 무조건 이게 적용 |
| 2 (낮음) | 전역 설정 (`system_settings.force_sl_*`) | 전략 override 가 NULL 일 때 fallback |

해석 (side 별 전역 기준):
```
g_enabled, g_roi = 전역(side)
enabled   = override_enabled if override_enabled is not None else g_enabled
threshold = override_roi     if override_roi     is not None else g_roi
```
- 전략 드롭다운 3택: **전역**(override 해제=NULL,NULL) / **끔**(enabled=False) / **-5~-20%**(enabled=True+roi).
- 예: 숏 전역 OFF 인데 특정 숏 전략만 「-15%」 선택 → 그 전략만 강제 청산 ON.
- 예: 롱 전역 ON -10% 인데 특정 롱만 「끔」 → 그 전략만 비활성.

### 기존 SL(-80~90%)과의 관계 = "더 빡빡한 추가 안전망"
| 구분 | 기존 SL (template) | 신 손실 한도 강제 청산 (이 spec) |
|------|------|------|
| 기준 | ROI (평단×레버리지) | ROI (평단×레버리지) — **동일 계산** |
| 기본 한도 | -80~90% (청산 직전) | **-10%** (롱 기본 ON) / -10% (숏 기본 OFF) |
| 발동 시점 | **모든 단계 진입 후에만** | **아무 단계에서나 (열려 있으면 즉시)** ← 핵심 차이 |
| 설정 위치 | template (전략 생성 시) | **전역 system_settings (롱/숏 각각)** |
| 켜고 끄기 | 항상 ON | **운영자 토글 (롱 ON / 숏 OFF 기본)** |
| 목적 | 청산 직전 최후 방어 | 사장님이 정한 손실선에서 능동 손절 |

➡️ **둘은 공존한다.** 신 강제 청산이 더 빡빡하므로(작은 손실에서 발동) 켜져 있으면 먼저 발동. 꺼져 있으면(숏 기본) 기존 SL이 그대로 최후 방어.

---

## 📐 2. 정책 동작 시나리오

전제: ROI = `가격변동% × 레버리지`.
- LONG: `(현재가 - 평단) / 평단 × 100 × 레버리지`
- SHORT: `(평단 - 현재가) / 평단 × 100 × 레버리지`
설정값(예: -10)에 대해 **`ROI <= -10` 이면 발동**.

### 시나리오 A — 롱, 기본 ON, 한도 -10% (사장님 기본값)
```
설정: force_sl_long_enabled = true, force_sl_long_roi = 10
포지션: BTCUSDT LONG, 평단 100, 레버리지 2x
현재가 97 → 가격변동 -3% × 2 = ROI -6%   → -6 > -10  → 유지 (청산 X)
현재가 95 → 가격변동 -5% × 2 = ROI -10%  → -10 <= -10 → 🛑 전량 시장가 청산 + 전략 종료
```

### 시나리오 B — 숏, 기본 OFF (사장님 기본값)
```
설정: force_sl_short_enabled = false
포지션: XRPUSDT SHORT, ROI -25% 까지 하락
→ 신 강제 청산 = 비활성 = 발동 X
→ 기존 template SL(-80~90%) 만 최후 방어로 동작
```

### 시나리오 C — 숏, 운영자가 켜고 한도 -15% 선택
```
설정: force_sl_short_enabled = true, force_sl_short_roi = 15
포지션: XRPUSDT SHORT, 평단 0.50, 2x
현재가 0.5375 → 가격변동(숏 손실) -7.5% × 2 = ROI -15% → 🛑 전량 청산 + 종료
```

### 시나리오 D — 1단계만 진입한 상태에서 급락 (핵심 차이!)
```
설정: 롱 ON, -10%. 전략은 4단계 중 1단계만 진입.
현재가 급락 → ROI -10% 도달
기존 SL = "모든 단계 진입 후에만" → 발동 X (추가 진입 기다림)
신 강제 청산 = "아무 단계에서나" → 🛑 즉시 청산
  ⚠️ 이건 사장님 의도된 동작: DCA(물타기) 전에 손절선에서 끊음.
  → 발동 시 미진입 단계 LIMIT 주문도 전부 취소 + 자동 진입 중단.
```

### 시나리오 E — 가격 정보 없음 (안전 최우선!)
```
Redis 실시간 mark_price 캐시 miss (스트림 일시 끊김 등)
→ ROI 계산 불가
→ ❌ 절대 청산하지 않음 (= 잘못된/없는 데이터로 강제 청산 = 최악의 사고)
→ 그냥 이번 cycle skip, 다음 cycle 재시도. (v51 단일 진실 원칙과 동일)
```

---

## 🏗 3. 기술 설계

### 3-1. 전역 설정 (system_settings 테이블, 키-값)
기존 `SystemSettingsService` ([system_settings_service.py](../../backend/app/services/system_settings_service.py)) 그대로 사용. 4개 키 신설:

| 키 | 타입 | 기본값 | 의미 |
|----|------|--------|------|
| `force_sl_long_enabled` | bool | `true` | 롱 강제 청산 활성 (사장님 기본 ON) |
| `force_sl_long_roi` | int | `10` | 롱 발동 ROI 한도 (양수 저장, ROI<=-값 시 발동). 허용 {5,10,15,20} |
| `force_sl_short_enabled` | bool | `false` | 숏 강제 청산 활성 (사장님 기본 OFF) |
| `force_sl_short_roi` | int | `10` | 숏 발동 ROI 한도. 허용 {5,10,15,20} |

- row 없으면 코드 default 사용 (backward-compat — 기존 `get_bool` 패턴).
- `get_decimal(key, default)` 헬퍼를 `SystemSettingsService` 에 추가 (현재 `get`/`get_bool` 만 존재).
- 허용값 검증: API 에서 `{5,10,15,20}` 외 값이면 400 + spec 참조 메시지.

### 3-2. 평가 로직 — `risk_service.py` 신 메서드
`evaluate_force_stop_loss(strategy_id) -> bool` 신설. 기존 `evaluate_stop_loss` ([risk_service.py:55](../../backend/app/services/risk_service.py#L55)) 와 **ROI 계산식은 100% 동일**, 단 차이점:
1. **단계 게이트 없음** — `current_stage < total_stages` 체크 제거 (아무 단계에서나 발동).
2. **전역 설정에서 한도/활성 읽음** — strategy.side 에 맞는 `force_sl_{long|short}_*` 사용.
3. **mark_price 소스 = Redis 실시간 캐시** (`get_mark_price(symbol)`), miss 시 `latest_position.mark_price` fallback, **둘 다 없으면 False (청산 금지)**. ← v51 단일 진실 정렬.

```
side = strategy.side
enabled = settings.get_bool(f"force_sl_{side.lower()}_enabled", default=(side=="LONG"))
if not enabled: return False
threshold = settings.get_decimal(f"force_sl_{side.lower()}_roi", default=10)   # 양수
mark = get_mark_price(symbol) or latest_position.mark_price
if not mark or not avg_entry or avg_entry<=0: return False                      # 안전 게이트
roi = price_change_pct(side, avg_entry, mark) * leverage
return roi <= -threshold
```

### 3-3. 실행 경로 — `tp_sl_orchestrator.py`
- 평가 순서: **신 강제 청산을 기존 SL 보다 먼저** 검사 (더 빡빡하므로).
  ```
  if risk_service.evaluate_force_stop_loss(sid):  # 신 — 먼저
      _execute_force_stop_loss(strategy); return
  if risk_service.evaluate_stop_loss(sid):        # 기존 -80~90%
      _execute_stop_loss(strategy); return
  ```
- `_execute_force_stop_loss`:
  1. `execution_service.emergency_close_position(sid, quantity=전량)` ([execution_service.py:194](../../backend/app/services/execution_service.py#L194)) — 전량 시장가 reduceOnly.
  2. 미진입 단계 LIMIT 주문 전부 취소 (자동 진입 worker 가 다시 안 쏘게).
  3. 전략 status → **종료(STOPPED)**, 재진입 X (REENTRY_READY 아님). 신 close reason `FORCE_SL`.
  4. `RiskEvent(event_type="FORCE_STOP_LOSS_TRIGGERED", severity="CRITICAL")` + Telegram 알림 (사장님 즉시 인지).

### 3-4. API
- GET `/api/v1/admin/system/force-sl` — 현재 4개 값 반환 (UI 초기 로드).
- PATCH `/api/v1/admin/system/force-sl` — `{side, enabled, roi}` 갱신. 허용값 검증 + `RiskEvent` audit (기존 tp1-threshold/trailing-retrace PATCH 패턴 미러링).

### 3-5. UI (설정 화면)
- 「손실 한도 강제 청산」 섹션. 롱/숏 2블록.
- 각 블록: 활성 토글(체크박스) + 한도 라디오/드롭다운 (-5 / -10 / -15 / -20%).
- 기본 표시: 롱 = ON, -10% / 숏 = OFF, -10%.
- 사장님 옵션 A (영구): 실시간 변경 = confirm 모달 X (= 기존 정책 일치).

---

## 🛡 4. Critical Constraints (= 영구!)

❌ **금지 1**: mark_price 없음/stale 일 때 청산. 가격을 모르면 절대 강제 청산하지 않는다 (시나리오 E). 잘못된 데이터로 실자금 청산 = 최악의 사고. (v51 silent bug 교훈)
❌ **금지 2**: 자본(total_capital) 기준 한도 계산. ROI = 평단×레버리지 만 사용 (BEATUSDT v4 사상 — 자본 변경 시 한도 변경되는 silent bug 금지).
❌ **금지 3**: 발동 후 재진입(REENTRY). 강제 청산 = 손절 의사 = 종료. 다시 들어가면 사장님 의도 위반.
❌ **금지 4**: 발동 시 미진입 LIMIT 주문 방치. 반드시 취소 (안 하면 청산 후 자동 진입이 다시 포지션 만듦).
❌ **금지 5**: silent 청산. 모든 발동 = RiskEvent + Telegram (헌법 8번 — 사장님 즉시 인지).

✅ **필수 1**: 롱/숏 독립 설정. 한쪽만 켜져 있어도 정상.
✅ **필수 2**: 전역 설정이 모든 해당 side 활성 전략에 즉시 적용 (다음 cycle, ≤10s). 재시작 불필요.
✅ **필수 3**: 기존 template SL(-80~90%)과 공존. 신 기능 OFF여도 기존 SL은 최후 방어로 동작.
✅ **필수 4**: 부분 청산 아님 — 항상 전량(full close). is_full_close 검증 (STOPPING silent bug 차단).
✅ **필수 5**: 발동 후 거래소 실제 포지션 0 검증 (emergency_close 의 기존 verify-retry 경로 재사용).

---

## ✅ 5. 검증 (= 자동 테스트!)

```python
def test_force_sl_long_default_on_triggers_at_minus10():
    """사장님 기본: 롱 ON, -10%. ROI -10% 도달 시 발동."""
    # 평단 100, 현재가 95, 2x → 가격 -5% × 2 = ROI -10%
    assert evaluate_force_stop_loss(side="LONG", avg=100, mark=95, lev=2,
                                    enabled=True, threshold=10) is True

def test_force_sl_long_not_triggered_above_threshold():
    """ROI -6% (한도 -10% 미달) → 유지."""
    assert evaluate_force_stop_loss(side="LONG", avg=100, mark=97, lev=2,
                                    enabled=True, threshold=10) is False

def test_force_sl_short_default_off_never_triggers():
    """사장님 기본: 숏 OFF → ROI -25% 여도 발동 X."""
    assert evaluate_force_stop_loss(side="SHORT", avg=0.5, mark=0.5625, lev=2,
                                    enabled=False, threshold=10) is False

def test_force_sl_short_on_minus15_triggers():
    """숏 ON, -15%: 평단 0.50 → 0.5375 = 숏 손실 -7.5% × 2 = -15% → 발동."""
    assert evaluate_force_stop_loss(side="SHORT", avg=0.50, mark=0.5375, lev=2,
                                    enabled=True, threshold=15) is True

def test_force_sl_fires_at_any_stage():
    """1단계만 진입한 상태에서도 발동 (기존 SL과 차이)."""
    assert evaluate_force_stop_loss(side="LONG", avg=100, mark=95, lev=2,
                                    enabled=True, threshold=10, current_stage=1, total_stages=4) is True

def test_force_sl_no_markprice_never_closes():
    """가격 없음 → 절대 청산 X (안전 최우선, 시나리오 E)."""
    assert evaluate_force_stop_loss(side="LONG", avg=100, mark=None, lev=2,
                                    enabled=True, threshold=10) is False
```

E2E: 강제 청산 발동 → (1) 거래소 포지션 0, (2) 미진입 LIMIT 취소됨, (3) status=STOPPED·재진입 X, (4) RiskEvent+Telegram 1건.

---

## 🗂 6. 구현 체크리스트 (PR 시)
- [ ] `SystemSettingsService.get_decimal()` 헬퍼 추가
- [ ] 4개 키 default 상수 정의 (`risk_constants.py` 또는 전용 모듈)
- [ ] `risk_service.evaluate_force_stop_loss()` 신설 (ROI 동일, 단계 게이트 없음, Redis mark)
- [ ] `tp_sl_orchestrator._execute_force_stop_loss()` + 평가 순서 (기존 SL보다 먼저)
- [ ] 미진입 LIMIT 취소 + status STOPPED + close reason `FORCE_SL`
- [ ] GET/PATCH `/admin/system/force-sl` API + 허용값 검증 + RiskEvent audit
- [ ] UI 설정 섹션 (롱/숏 토글 + 임계값)
- [ ] 단위 테스트 6종 + E2E 1종
- [ ] 배포: `api`(API/orchestrator) + `scheduler`(worker) 둘 다

---

## 📌 영구 보존
이 사상 = 2026-06-24 부터 모든 관련 코드 = 100% 준수.
모순 발견 시 = 사장님 명시(상단 인용) 우선 (이 문서 = 기술 translation).
핵심 불변식: **ROI 기준 · 전역 롱/숏 독립 · 롱 기본 ON(-10%) / 숏 기본 OFF · 가격 없으면 청산 금지 · 발동=전량 종료+재진입 X+알림.**
