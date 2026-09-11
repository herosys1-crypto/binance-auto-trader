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

왜 처음 방식이 아니었나 (VPS 실효 설정 = 강제손절 −25 ON + 단계 정리 `stage_trim_before_next_enabled=1`):
2배 레버리지에서 2단계 트리거 −10% = ROI −20% 는 −25% 손절보다 먼저 오지만, 3단계 트리거 −20% = ROI −40% 는 **손절이 먼저** 온다.
Fix 322 가 「손절 ROI 를 명시한 전략은 단계 게이트 면제」이므로 2단계 뒤 −25% 에서 손절이 나가고(정리 ON 이면 잔량 10 만 남는 부분손절,
Fix 326), 3단계는 그 뒤 트리거에 닿아야 들어간다 = 「부분손절 후 다음 단계」(Fix 304/362 사상)이지 사장님이 말한 처음 사다리
(손절 없이 트리거마다 얹는다)가 아니다. 손절과 정리를 그 가족에서 빼면 사다리가 처음 방식대로 간다.

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
- **Fix 367c — 가족 표식 `strategy_instances.entry_profile`** (alembic 0039, String(20) NULL): 생성 시 가족이면 `'legacy_manual'`.
  런타임 판정 `stage_trim.is_legacy_manual_instance` 는 **이 표식만** 본다(템플릿 추정 없음). 반박 검증이 잡은 대로, 템플릿으로 추정하면
  배포 **전**에 만든 살아 있는 #4478 RAYSOL·#4480 KAT(손절 −25 ON)까지 정리 제외가 소급돼 손절이 「잔량 10 부분정리」에서
  「전량 청산」으로 바뀌었다 → 표식이 NULL 인 옛 인스턴스는 **옛 동작 그대로**. 응답 `StrategyDetailResponse.entry_profile` 로 노출.
- `app/services/stage_trim.py` (Fix 367b): `is_legacy_manual_instance(db, strategy)` + `legacy_manual_excluded(db)`;
  `trim_enabled` 가 표식 인스턴스면 False → 단계 전환(`_trim_before_stage`)·손절 단계 게이트(`_stage_gate_exempt` 의 Fix304 면제)·
  강제손절 시 부분정리 모두 새 기존 방식엔 안 붙는다. 로그는 debug(15초마다 여러 소비처가 부른다).
- TP1 청산 비율 25%: 모달 `openCreateModal` 이 직전 전략 blueprint 를 자동 복원하면서 TP1 청산 칸을 그 템플릿 값(auto_bb/OBV = 10)으로
  덮던 것(반박 검증 C7)을 고쳐, 기존 방식 신규 모달은 blueprint 복원 뒤 TP1 청산 = **25** 로 시작한다(OBV 모달은 `_pendingObv` 로 제외).
  서버는 강제로 덮지 않고(모달에서 고친 값 = 사장님 뜻) 설정 `legacy_ladder_tp1_qty_ratio`(25) 와 다르면 경고 로그 + 검사기 ⚠.
- `multi-symbol.js`: 템플릿 POST 에 `trigger_mode` 를 안 실어 「📊 OBV 자동」 모달의 다중 심볼 전략이 서버 기본 PRICE_DOWN_PCT(가격 사다리)
  로 저장되던 누락(반박 검증 C8; Fix 367 뒤엔 그것이 기존 방식 가족으로 판정돼 손절 없음까지 붙음) → 단일 경로와 같게 전송.
- `app/api/v1/strategies/crud.py`: `POST /strategies` 만 `entry_origin=ENTRY_ORIGIN_MANUAL` 을 넘긴다.
  워커 6곳(surge_ladder / managed_symbols / auto_bb / auto_reentry / ladder_restart / pump_split)은 안 넘긴다 = 가족 밖.
- `app/core/risk_constants.py` 설정 키
  | 키 | 기본 | 출처 |
  |---|---|---|
  | `legacy_ladder_tp1_pct` | 25 | 사장님 verbatim |
  | `legacy_ladder_force_sl_enabled` | 0 (끔) | 사장님 「손절없고」 |
  | `stage_trim_exclude_legacy_manual` | 1 (제외) | Claude가 정함 — 사장님 「단계별 트리거에 다음단계 포지션 진입」 |
  | `legacy_ladder_tp1_qty_ratio` | 25 | 사장님 verbatim 「포지션진입한 금액의 25%」 — 모달 기본·경고 기준(강제 아님) |
  | `LEGACY_LADDER_TP1_MAX` (코드 상수) | 300 | Claude가 정함 — 목록 드롭다운 최댓값 |
  TP1 설정이 0 이하·300 초과·파싱 실패·NaN/Infinity 면 25 (새 전략 전체 TP 를 설정 한 줄로 조용히 끄지 못하게, Fix 362c 와 같은 이유).
  강제손절을 켜면(1) ROI 는 Fix 362 기본(`force_sl_roi_new_default`) 으로 돌아간다.
- `app/services/system_settings_service.py`: `get_legacy_ladder_defaults()`.
- `cm-submit.js`: 생성 토스트가 **서버 응답값**(`tp1_pct_override`, `force_sl_enabled_override`) 을 보여준다
  (「➕ 기존 방식 (처음 방식: TP1 +25% · 강제손절 없음)」). `index.html` 버튼 설명 갱신.
- `scripts/verify_fix364_deploy.py` ⑤절: 코드 핀 19개 + 설정 실효값 5개(`stage_trim_before_next_enabled` 포함)
  + 최근 기존 방식(모달·가격·DYNAMIC_*) 인스턴스 5건에 표식(`✔Fix367` / 표식 없음 = 배포 전 생성)·TP1 청산 ⚠·단계정리 적용/제외 표시.
  FAIL 은 「표식 인스턴스인데 제외 설정이 켜진 상태에서 정리가 적용될 때」만 (되돌리기 `=0` 이면 FAIL 아님).

## 3. 끔의 의미 (소비처 전수)

| 소비처 | 동작 |
|---|---|
| `risk_service.resolve_force_sl` | `override_enabled=False` → 전역 LONG ON(−5) 이 켜져 있어도 **끔** |
| `risk_service._stage_gate_exempt` (Fix 322) | roi 0 은 「손절 명시」가 아님 → 템플릿 손절(자본 대비 %, 모달 80)은 옛 규칙대로 **모든 단계 진입 후에만** |
| 전략 목록 드롭다운 | `force_sl_enabled_override === false` → 「강제:끔」 표시. 사장님이 거기서 언제든 켤 수 있다 |
| Fix 362c 2단계 워커(`if roi is None`) | roi 가 0 이라 None 이 아님 → 덮어쓰지 않는다 |
| Fix 364 `pyramid_after_add_sl` | 범위 기본 `obv` → 기존 방식엔 안 붙는다 (`all` 로 바꾸면 붙는다) |
| Fix 304 단계 정리 `stage_trim_before_next_enabled` | VPS 실효값 **1(ON)** 이었다 (9/3 사장님 「기본전략도 10 남기고 청산 후 다음 단계」). 그대로면 기존 방식이 손실 중 2단계 트리거에 닿을 때 먼저 잔량 10 으로 부분 손절한다 = 「손절없고 트리거에 다음단계」가 아니다 → **Fix 367b**: `stage_trim.trim_enabled` 가 표식(`entry_profile='legacy_manual'`) 인스턴스면 False. 설정 `stage_trim_exclude_legacy_manual`(기본 1, Claude가 정함) 로 되돌린다. OBV 자동·v219 사다리·볼밴 분할·배포 전 인스턴스는 그대로 |
| 「🔄 청산 후 재진입」 체크박스(v131) | 켜면 stage 워커의 retry 분기가 「청산 후만 진입」으로 동작한다(정리 OFF·손절 미명시일 때 정상 가격 트리거 진입을 건너뜀 — 2026-08-10 사장님 「1단계 청산하고 0인 상태에서 2단계」 verbatim 의 설계). 배포 전엔 Fix 362 의 −25 명시가 이 분기를 우회(Fix 323)했지만, 손절 없는 새 기존 방식에서는 체크박스 본래 뜻대로 간다. 기본은 꺼져 있다. 사다리를 트리거마다 얹으려면 체크하지 말 것 |

## 4. 바뀌지 않는 것

- 📊 OBV 자동(OBV_REVERSE): TP1 15 · 1단계 손절 25 · Fix 364 단계 손절 25/15/25/25 · Fix 365 프로브 — 그대로.
- 자동 워커(볼밴 분할·v219 사다리·급등 사다리·저점 LONG 등): `entry_origin` 을 안 넘기므로 그대로.
- **이미 만들어진** 기존 방식 인스턴스(#4478 RAYSOL·#4480 KAT 포함): 저장된 값(TP1 15 / −25) 유지, 표식 NULL 이라 단계 정리도 옛 동작.
  목록의 「TP1」·「강제」 드롭다운으로 개별 변경 가능(표식은 안 생기므로 정리 제외는 새 전략에만).
- 급등락 알림 「▶ 즉시 진입」·추천 카드 「✏ 세팅 후 진입」은 **같은 모달·같은 POST /strategies** 를 타므로 Fix 367 뒤엔 **같은 가족**이다
  (TP1 25 · 강제손절 없음). `live-pump-dump-alerts.js` cfg 의 `tp1_pct_override: 15 / force_sl_roi_override: 25` 는 Fix 367 이전부터
  어디에도 전송되지 않던 표시용 값이고, 추천 카드 「강제 SL -N%」 문구는 프로필 값이라 실제와 다르다 — 생성 직후 토스트와 목록의 「강제:끔」이 실제 값.
  그 경로는 TP1 청산 칸을 프로필 값(10)으로 채우므로 25 가 아니면 경고 로그·검사기 ⚠ 로 보인다.

## 5. 되돌리기 (재시작 불필요)

```
legacy_ladder_force_sl_enabled = 1     → 새 기존 방식도 Fix 362 기본(−25)
legacy_ladder_tp1_pct = 15             → TP1 15
stage_trim_exclude_legacy_manual = 0   → 기존 방식도 Fix 304 대로 다음 단계 전 잔량 10 정리
```

## 6. 검증

- `tests/test_fix367_legacy_ladder_defaults.py` 10건 + `test_fix362_force_sl_new_default.py` 핀 갱신; 관련 묶음(stage_trim·stage_gate_exempt·partial_stop_loss·Fix 363~365) 통과. 전체 단위 스위트의 실패 31건은 HEAD 와 동일(로컬 DB 없음 = 배포 전부터).
- 반박 검증(9/11, 렌즈 8 → 후보 41 → 반박자 2명씩): 확정 34건은 6주제 — ① 런타임 판정이 템플릿 추정이라 배포 전 인스턴스에 소급(→ 표식 컬럼)
  ② TP1 청산 25 가 blueprint 자동 복원에 덮임(→ 모달 기본 25 + 경고) ③ OBV 다중심볼 템플릿 trigger_mode 누락(→ 전송) ④ 급등락 알림 진입도 같은 가족(→ 문서 정정)
  ⑤ 검사기 ✔ 판정 TP1==25 하드코딩·되돌리기 시 거짓 FAIL(→ 표식·설정 기준) ⑥ 설정 NaN 이면 500(→ is_finite). 반박 7건(재진입 체크박스 = v131 설계 등).
- 배포: `alembic upgrade head`(0039) 필요.
- 배포 후 `docker compose exec -T scheduler python scripts/verify_fix364_deploy.py` ⑤절 PASS, 새로 만든 기존 방식 인스턴스가 `✔Fix367`.
