# Fix 367 — 「➕ 새 전략 (기존 방식)」 = 처음 방식 (2026-09-11)

## 0. 사장님 지시 (verbatim, 2026-09-11)

> 새전략 기존 방식은 손절없고 단계별 트리거에 다음단계 포지션 진입할수 있게 해주 처음 개발한 것과 그의 동일해
> tp1 익절은 +25% 부터 포지션진입한 금액의 25%부터 익절 할 수 있게 설정해줘 과거로 돌악가는것과 같아

읽기: 화면 「➕ 새 전략 (기존 방식)」 로 만드는 전략은 처음 개발한 방식으로 돌아간다.
① 강제손절 없음 ② 단계는 사장님이 정한 가격 트리거에 닿으면 다음 단계 진입 ③ TP1 = +25% ROI 에서 포지션의 25% 익절.

## 1. 무엇이 막고 있었나 (실측)

| 항목 | 9/10 까지 (Fix 362) | 처음 방식 |
|---|---|---|
| 새 인스턴스 `tp1_pct_override` | 15 (v147) → 사다리 10/15/20… 이 +5 이동 = 15/20/25… | **25** → +15 이동 = 25/30/35… (Fix 184 이동 규칙 그대로) |
| 새 인스턴스 강제손절 | ON −25 (`force_sl_roi_new_default`) | **끔** (`force_sl_enabled_override=False`, roi 0) |
| TP1 청산 비율 | 모달 기본 25% (템플릿 `tp1_qty_ratio`) | 그대로 25% |
| 단계 진입 판정 | 가격만 (Fix 232) | 그대로 |

왜 3단계에 못 가나: 2배 레버리지에서 2단계 트리거 −10% = ROI −20% 는 −25% 손절보다 먼저 오지만,
3단계 트리거 −20% = ROI −40% 는 **손절이 먼저** 온다. Fix 322 가 「손절 ROI 를 명시한 전략은 단계 게이트 면제」
이므로 2단계 뒤 −25% 에서 전량 청산 → 3단계는 영원히 안 온다. 손절을 끄면 사다리가 끝까지 간다.

## 2. 변경 (가족 = 모달 + 가격 트리거 + fixed/scheduled 만)

- `app/services/strategy_service.py`
  - 모듈 함수 `legacy_manual_family(trigger_mode, capital_management_mode, entry_origin)`:
    `entry_origin == "manual_modal"` **and** 템플릿 `trigger_mode ∈ {PRICE_DOWN_PCT, PRICE_UP_PCT}`(없으면 PRICE_DOWN_PCT)
    **and** `capital_management_mode ∈ {fixed, scheduled}` 일 때만 True.
  - `create_strategy_instance(..., entry_origin=None)`: 가족이면 `SystemSettingsService.get_legacy_ladder_defaults()`
    → `(tp1, fs_on, fs_roi)`; 아니면 종전 `(TP1_PCT_DEFAULT=15, True, force_sl_roi_new_default=25)`.
  - 생성 뒤 로그 `[Fix367] 기존 방식 새 전략 #… TP1 +25% · 강제손절 없음 (템플릿 TP1 청산 25%)`.
  - 판정의 템플릿 부분은 `legacy_manual_template(trigger_mode, capital_management_mode, strategy_type)` —
    **strategy_type 이 `DYNAMIC_*`**(모달·다중심볼·저장 템플릿) 이어야 한다. 퍼프 터미널(`terminal_manual`)·AUTO_BB·PUMPSPLIT 은 아니다.
    생성 시(strategy_service)와 런타임(stage_trim)이 같은 함수를 쓴다.
- `app/services/stage_trim.py` (Fix 367b): `is_legacy_manual_instance(db, strategy)` + `legacy_manual_excluded(db)`;
  `trim_enabled` 가 기존 방식이면 False → 단계 전환(`_trim_before_stage`)·손절 단계 게이트(`_stage_gate_exempt` 의 Fix304 면제)·
  강제손절 시 부분정리 모두 기존 방식엔 안 붙는다. 이미 살아 있는 기존 방식 #4478 RAYSOL·#4480 KAT(손절 −25 ON) 도
  손절이 나면 **잔량 10 부분정리가 아니라 전량 청산**으로 바뀐다 (처음 방식).
- `app/api/v1/strategies/crud.py`: `POST /strategies` 만 `entry_origin=ENTRY_ORIGIN_MANUAL` 을 넘긴다.
  워커 6곳(surge_ladder / managed_symbols / auto_bb / auto_reentry / ladder_restart / pump_split)은 안 넘긴다 = 가족 밖.
- `app/core/risk_constants.py` 설정 키
  | 키 | 기본 | 출처 |
  |---|---|---|
  | `legacy_ladder_tp1_pct` | 25 | 사장님 verbatim |
  | `legacy_ladder_force_sl_enabled` | 0 (끔) | 사장님 「손절없고」 |
  | `stage_trim_exclude_legacy_manual` | 1 (제외) | Claude가 정함 — 사장님 「단계별 트리거에 다음단계 포지션 진입」 |
  | `LEGACY_LADDER_TP1_MAX` (코드 상수) | 300 | Claude가 정함 — 목록 드롭다운 최댓값 |
  TP1 설정이 0 이하·300 초과·파싱 실패면 25 (새 전략 전체 TP 를 설정 한 줄로 조용히 끄지 못하게, Fix 362c 와 같은 이유).
  강제손절을 켜면(1) ROI 는 Fix 362 기본(`force_sl_roi_new_default`) 으로 돌아간다.
- `app/services/system_settings_service.py`: `get_legacy_ladder_defaults()`.
- `cm-submit.js`: 생성 토스트가 **서버 응답값**(`tp1_pct_override`, `force_sl_enabled_override`) 을 보여준다
  (「➕ 기존 방식 (처음 방식: TP1 +25% · 강제손절 없음)」). `index.html` 버튼 설명 갱신.
- `scripts/verify_fix364_deploy.py` ⑤절: 코드 핀 11개 + 설정 실효값 3개(`stage_trim_before_next_enabled` 포함)
  + 최근 기존 방식 인스턴스 5건에 `✔Fix367` / `(배포 전 생성)` 표시.

## 3. 끔의 의미 (소비처 전수)

| 소비처 | 동작 |
|---|---|
| `risk_service.resolve_force_sl` | `override_enabled=False` → 전역 LONG ON(−5) 이 켜져 있어도 **끔** |
| `risk_service._stage_gate_exempt` (Fix 322) | roi 0 은 「손절 명시」가 아님 → 템플릿 손절(자본 대비 %, 모달 80)은 옛 규칙대로 **모든 단계 진입 후에만** |
| 전략 목록 드롭다운 | `force_sl_enabled_override === false` → 「강제:끔」 표시. 사장님이 거기서 언제든 켤 수 있다 |
| Fix 362c 2단계 워커(`if roi is None`) | roi 가 0 이라 None 이 아님 → 덮어쓰지 않는다 |
| Fix 364 `pyramid_after_add_sl` | 범위 기본 `obv` → 기존 방식엔 안 붙는다 (`all` 로 바꾸면 붙는다) |
| Fix 304 단계 정리 `stage_trim_before_next_enabled` | VPS 실효값 **1(ON)** 이었다 (9/3 사장님 「기본전략도 10 남기고 청산 후 다음 단계」). 그대로면 기존 방식이 손실 중 2단계 트리거에 닿을 때 먼저 잔량 10 으로 부분 손절한다 = 「손절없고 트리거에 다음단계」가 아니다 → **Fix 367b**: `stage_trim.trim_enabled` 가 기존 방식(`is_legacy_manual_instance`)이면 False. 설정 `stage_trim_exclude_legacy_manual`(기본 1, Claude가 정함) 로 되돌린다. OBV 자동·v219 사다리·볼밴 분할은 그대로 |

## 4. 바뀌지 않는 것

- 📊 OBV 자동(OBV_REVERSE): TP1 15 · 1단계 손절 25 · Fix 364 단계 손절 25/15/25/25 · Fix 365 프로브 — 그대로.
- 자동 워커(볼밴 분할·v219 사다리·급등 사다리·저점 LONG 등): `entry_origin` 을 안 넘기므로 그대로.
- **이미 만들어진** 기존 방식 인스턴스: 저장된 값(TP1 15 / −25) 유지. 목록의 「TP1」·「강제」 드롭다운으로 개별 변경.
- `live-pump-dump-alerts.js` 급등락 알림 진입(cfg TP1 15 / SL 25)은 별도 가족 — 손대지 않았다.

## 5. 되돌리기 (재시작 불필요)

```
legacy_ladder_force_sl_enabled = 1     → 새 기존 방식도 Fix 362 기본(−25)
legacy_ladder_tp1_pct = 15             → TP1 15
stage_trim_exclude_legacy_manual = 0   → 기존 방식도 Fix 304 대로 다음 단계 전 잔량 10 정리
```

## 6. 검증

- `tests/test_fix367_legacy_ladder_defaults.py` 10건 + `test_fix362_force_sl_new_default.py` 핀 갱신; 관련 묶음(stage_trim·stage_gate_exempt·partial_stop_loss·Fix 363~365) 180 passed. 전체 단위 스위트의 실패 31건은 HEAD 와 동일(로컬 DB 없음 = 배포 전부터).
- 배포 후 `docker compose exec -T scheduler python scripts/verify_fix364_deploy.py` ⑤절 PASS, 새로 만든 기존 방식 인스턴스가 `✔Fix367`.
