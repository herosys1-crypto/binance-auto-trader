# 개발 대기열 (2026-09-12, 사장님 「저장해뒀다가 한도 다시 설정되면 그때 모두 개발」)

사장님이 9/12 에 결정 2·3·4 를 전부 승인했다. 다음 세션은 이 문서대로 **묻지 말고 순서대로** 개발한다.
근거 데이터: 실전 7일(9/5~9/11) 손익 −1,162 중 약 −1,000 이 「추가」(수동 💉 + 자동 피라미딩 0/7)에서 났고,
가상매매 v2(98,461건) 채택 규칙은 SHORT confirm_peak_111·s2_hist_turn_down, LONG bottom_331·multiday_rebound_352(UP24)·surge_start_346(DOWN24).
(docs/spec/LEGACY_LADDER_RESTORE_2026-09-11.md · EXTERNAL_STRATEGIES_FUJIMOTO_MACH7_2026-09-12.md · PAPER_TRADING_LEARNING_2026-09-08.md 참고)

## 이미 끝난 것 (다시 하지 말 것)
- 결정 1: `pyramid_sides=LONG` VPS 적용 완료 (9/12 00:50 UTC, 재시작 불필요).
- Fix 367/367b/c/d 기존 방식 = 처음 방식 (배포 ea88614), Fix 368 후지모토·마하세븐 shadow 워커 + 가상 규칙 8개 (배포 d0194b0).

## 🔁 인계 메모 (2026-09-13 05:34 KST 스냅샷 — 다음 세션은 여기부터)
**상태: 대기열 2①·2② 구현 중 · 미커밋 · 미배포.** 이 메모는 작업 세션이 아닌 다른 세션이 `git diff` 를 읽고 적었다
(작업 세션은 05:33 까지 파일을 고치고 있었다). 시작 전에 `git status` / `git diff --stat` 로 이 뒤에 바뀐 게 있는지 먼저 볼 것.
- 변경 파일 (CRLF 유지): `workers/success_pyramiding_worker.py` +131 · `api/v1/strategies/lifecycle.py` +16 ·
  `scripts/verify_fix364_deploy.py` +69 (⑦절 신설) · 신규 `tests/test_queue2_loss_defense.py` (9 passed, 05:34).
- 2① 구현: `apply_manual_add_sl(db, si, *, avg_before, ref_price)` — 스위치 `manual_add_after_sl_enabled`(기본 0) · **이익 구간 추가만**
  (손실 구간은 커진 물량이 즉시 손절되므로 제외) · 인스턴스 손절이 명시적 True 일 때만 조임(False/None 존중 — Fix 323 `_sl_explicit`) ·
  이미 더 짧은 손절은 안 풂 · 범위 `pyramid_after_add_sl_scope`(obv 기본 = 기존 방식 제외). 엔드포인트는 주문 **전** 평단을 읽고 추가 뒤 호출.
- 2② 구현: `_breadth_gate_long` — LONG 만, `market_breadth_last` tag ≠ MKT_UP 이면 `breadth_not_up` 로 건너뜀 · 값 없음/60분 초과/파싱 실패 = 허용(fail-open) ·
  신규 키 `pyramid_breadth_max_age_min`(60, Claude가 정함). 워커 순서 = 방향 → 국면 → 최소 이동.
- 반박 검증(렌즈 3) **9/13 에 1회 돌았고** 반영 중이었다: 지정가 추가는 건너뛴다 · False override 존중 · 더 짧은 손절 유지 (주석에 기록됨).
- 🚨 **남은 결함 (다음 세션 첫 작업)**: `lifecycle.py` 가 `apply_manual_add_sl(..., order_type=payload.order_type)` 로 부르는데
  함수 시그니처에 `order_type` 이 **없다** → 실행 시 TypeError → `except` 가 삼켜 경고 로그만 남고 **손절이 영영 안 걸린다(조용한 실패)**.
  주석의 「지정가는 건너뛴다」도 코드에 아직 없다. 고칠 것: 시그니처에 `order_type=None` 추가 + LIMIT 이면 `(None, "limit_skip")` +
  테스트 추가(지정가 = 미적용, 그리고 **엔드포인트 호출 인자가 시그니처와 맞는지** `inspect.signature` 로 핀 — 지금 배선 테스트는 문자열 검사라 못 잡았다).
- 그 뒤 순서: 전체 pytest → 검사기 `--code-only` PASS → 커밋 (잡파일 `now()` 0바이트는 커밋하지 말고 지울 것) → 사장님 배포 →
  `verify_fix364_deploy.py` ⑦절 실효값·「지금 LONG 자동 추가 허용/보류」 확인 → 2 완료 표시 → 3A.

## 2. 손실 방어 2건 (코드 소, 약 1시간, 손절 로직 → 반박 검증 1회 15분)
### 2① 수동 「💉 포지션 추가」에도 추가 뒤 손절
- 설정 `manual_add_after_sl_enabled` 기본 **0** (Claude가 정함 — 켜는 건 사장님). 값 = `pyramid_after_add_sl_roi`(5) 그대로.
- 배선: `api/v1/strategies/lifecycle.py` add-position 엔드포인트가 `add_position_now` 성공 뒤, 설정이 1 이면
  `success_pyramiding_worker._apply_after_add_sl(db, si, commit=True)` 호출. 범위 `pyramid_after_add_sl_scope`(obv|all) 존중.
- 근거: BTR #4436 손절 −100 으로 7회 추가 −392 · SOPH #4479 −129 · USELESS #4434 −144 (전부 수동 추가, 손절 미조정).
- 테스트: 엔드포인트 핀 + 설정 OFF 면 호출 없음 + ON 이면 호출. 검사기 ⑤/⑥ 옆에 설정 실효값 한 줄.
### 2② LONG 자동 추가는 시장 국면 MKT_UP 일 때만
- 설정 `pyramid_require_breadth_up` 기본 **1** (Claude가 정함). `success_pyramiding_worker` 가 추가 직전 `market_breadth_last`(JSON {"tag": "MKT_UP"...})
  를 읽어 tag ≠ MKT_UP 이면 건너뛰고 사유 기록(`_record_block_reason` 형태 또는 로그). 값이 없으면(브레드스 미계산) **허용**(fail-open, 로그).
- 근거: 자동 피라미딩 지난주 0/7 (MKT_DOWN 주간), 가상 추가 lot 은 상승 국면 백필에서만 양수.

## 3. 자동 진입 규칙 (코드 중, 반나절 + 그림자 1주)
공통 골격: `external_strategies_worker` 를 「규칙 가족 러너」로 일반화한다 — 가족 = (설정 `{fam}_mode` off|shadow|on, 템플릿 접두사, strategy_type,
방향, 규칙 함수, 자본, 손절 가격 %, 전용 상한, 자리 필터). 진입은 `create_surge_position`, 피라미딩 제외 목록(single_entry_guard) 등록,
검사기 ⑥절에 가족별 모드·그림자 수 추가. 기본 shadow. 1주 그림자 뒤 가상 보고서 Δ·CV 확인하고 사장님이 on.
### 3A SHORT `s2_hist_turn_down` (가상 house Δ+0.18/UP24 +0.55, live Δ+1.71, CV 4/4)
- 규칙 함수 = `chart_learning._r_s2_hist_turn_down` (15m hist·종가만 필요 → RuleCtx 흉내 쉬움). 자본 10 (사장님 1단계) · 손절 = 실코드 기본(−25 ROI) 또는
  8봉 고점(정점) + 1% 가격 (Claude 후보) 중 설정으로 택1. UP24·UP35_DOWN24 자리 우선(house ✅).
### 3C 저점 LONG 워커의 다일 필터 문맥 뒤집기
- `long_bottom_detector_worker` 의 multiday(`is_pullback_rebound`) 경로가 24h ≤ −8% 만 고른다 → 가상은 DOWN24 −0.03, **UP24 +0.45(house)·LIVE_OK +0.47** 이 채택.
- 설정 `multiday_context` = `UP24`(기본, Claude가 정함) | `DOWN24`(옛) | `ANY`. 필터 한 줄 분기 + 로그 사유 + 테스트.
### 3B LONG `bottom_331` (house ALL Δ+0.56 · DOWN24 +0.74 · LIVE_OK +0.71, live LIVE_OK Δ+1.76)
- 규칙 함수 = `chart_events.is_bottom_reversal(kl15, kl4h)` (실매매 호출처 0곳 = 신설). 4h 봉 80개 추가 fetch 필요. 자본 10 · 손절 실코드 기본.
### 3D LONG `surge_start_346` DOWN24 직접 진입 (house DOWN24 Δ+0.59 ✅)
- 지금은 `momentum_phase.classify_surge_start` 가 거부권/핸드오프로만 쓰인다 → 가족 러너에 LONG 진입 가족으로 등록, 자리 필터 DOWN24(24h 변동 < 0).
- 주의: UP24 에선 Δ+0.14(미채택) → DOWN24 만.

## 4. 후지모토·마하세븐 실주문 (데이터 뒤 결정)
- 가상 보고서 규칙 표에서 `fujimoto_*`·`mach7_*` 의 Δ>0·CV 4/4·n≥100 확인 → 사장님이 `fujimoto_mode=on` / `mach7_mode=on`.
- 켜기 전 실주문 경로(2·3차 preserve 추가 + 손절 재환산, 2% 룰 크기) 반박 검증 1회(렌즈 3, 15분).
- `mach7_min_slope_pct`(0.5) 는 그림자 신호 분포 보고 보정.

## 5. 캡 재검토 (3 배포 1주 뒤)
- `sajangnim_top_short_daily_limit`(1, v219 사다리) · `pump_split_max_concurrent`(1): v219 사다리 건당 −3.8 이라 유지. 3A/3C 뒤 일주일 데이터로 2 여부 보고.

## 6. 작업 규칙 (사장님 9/11 「이렇게 오래 걸려야 하나」 반영)
- 반박 검증(워크플로)은 주문·손절·자본 로직 변경에 **1회**(렌즈 3~4, 20~30 에이전트, 15분). 화면·문서·검사기·후속 수정은 테스트+검사기로 끝내고 바로 배포.
- 배포 체인: `git pull` → `alembic upgrade head` **성공 확인** → `restart` (리비전 id ≤ 32자). 배포 뒤 `verify_fix364_deploy.py` PASS + 첫 사이클 로그.
- 리뷰 에이전트가 만드는 빈 잡파일(`backend/app/0`, `tuple[bool` 등)은 커밋 전 `git clean -n` 으로 확인.

## 7. 진행 기록 (2026-09-13, Claude)
- **2①** (커밋 5835d50) `manual_add_after_sl_enabled` 기본 0. 반박 검증(렌즈 3) 반영 = **시장가 · 이익 구간 · 인스턴스 손절 명시 ON** 인 추가에만 −5.
  지정가(체결가 모름·취소돼도 남음) / 강제청산 끔(False) / 전역 상속(None — override 를 만들면 stage_trigger `_sl_explicit` 가 바뀌어 단계 진입 재개) /
  이미 더 짧은 손절은 건드리지 않는다. 실측: USELESS #4434 초기 추가는 손실 구간(ROI −12~−22%) → 손실 구간 제외가 맞다.
  BTR #4436 은 기존 방식(PRICE_DOWN_PCT)이라 기본 `pyramid_after_add_sl_scope=obv` 에서는 대상이 아니다 (가족별 적용).
- **2②** (같은 커밋) `pyramid_require_breadth_up`=1 · `pyramid_breadth_allow_tags`=MKT_UP · `pyramid_breadth_max_age_min`=60 (값 없음·낡음 = 허용 + 사이클 경고).
  ⚠️ 재측정 (가상 LONG 추가 lot · 진입 시점 국면): MKT_UP +3.60 (n=216, 4조각 전부 +) · MKT_DOWN +0.84 (n=883) · MKT_FLAT +4.24 (n=97) ·
  국면 계산 전(9/10 이전) −3.36 (n=773) → 위 §2② 근거 「상승 국면에서만 양수」는 9/10 이후 표본으로 **확인되지 않는다**.
  승인된 기본(보수적)은 유지. 넓히기 = `pyramid_breadth_allow_tags=MKT_UP,MKT_FLAT` (또는 `MKT_UP,MKT_FLAT,MKT_DOWN`) 한 줄.
- **3C** `multiday_context` 기본 **DOWN24(옛 자리 = 배포해도 실진입 불변)** + `multiday_context_shadow`=UP24 (알람 키 없이 `multiday:shadow:UP24:*` 7일 기록).
  재측정 house Δ: 현행 자리(UP3D/UP5D + 24h ≤ −8%) −0.13 CV 2/4 (live −3.80 0/4) → UP24 +0.35 CV 4/4 (live −1.26).
  🚨 처음엔 UP24 를 실알람 기본으로 했다가 반박 검증(9/13)에서 되돌렸다: 알람 경로는 Fix 87 패턴 A skip 을 타지 않고 `_create_long_strategy` 직행이라
  **실진입이 된다**. 그런데 그 진입은 가상매매의 1회 진입이 아니라 Fix 315 단계 사다리(10/300/600 = 910 USDT) · LONG 피라미딩 · 손절 뒤 재진입 대상이고,
  UP24 발생량은 옛 자리의 5~7배(가상 실시간 9/9~9/12: 29~58/일 vs 7~11/일), 손실 쿨다운 없음. → 그림자 수를 보고 사장님이 `multiday_context=UP24` 로 켠다.
  알람 자리·태그는 제안 기록 `strategy_config.multiday_context / multiday_tag` 에 남겨 켠 뒤 자리별 사후 검증이 가능하다.
  참고: `macd_reversal_15m` 워커가 같은 알람 키를 패턴 없이 덮어쓴다(기존) — UP24 를 켜면 +5~15% 종목 알람 일부가 30분 막힌다(진입이 줄어드는 쪽).
- **반박 검증 (렌즈 2 — 3C 실행 영향 · 러너 주문 안전성, 9/13) 러너 반영**: 같은 심볼 반대 방향에 살아 있는 전략이 있으면 진입 안 함(`rf_allow_hedge`=0, 헤지 계정) ·
  전체 동시보유 상한 0(= 자동 진입 완전 OFF) 존중 · 그림자도 on 과 같은 검사(가격 이동·반대 방향·가드)를 돌리고 `would_enter`/`blocks` 기록, 막힌 그림자는
  쿨다운 안 걸고 그림자 쿨다운 키는 on 과 분리 · swing8 봉 조회 전 ban 확인 · 행 처리 표시 SET NX.
  보고만: rf 포지션은 전체 상한 범위가 `all` 이면 v219 칸을 차지할 수 있다(지금 VPS 범위 = v219 사다리만) · 손절 설정 커밋 실패해도 MARKET 이 나가는 기존 공용 약점.
- **3A·3B·3D** `app/services/rule_families.py` + `app/workers/rule_family_worker.py` (60초, 기본 shadow). 위 공통 골격의 「external_strategies_worker 일반화」 대신
  **신호 = 가상매매 실시간 진입 행(paper_trades, source=live)** 으로 정했다: 측정한 판정·자리 태그 코드를 그대로 쓰고, 100~150 심볼 봉을 한 번 더 받지 않으며(418 전력),
  가상 모듈은 여전히 주문 경로를 import 하지 않는다. 한계 = 가상매매가 멈추면 신호도 없다(검사기 ⑧ 「마지막 가상진입」).
  자리 기본 (재측정, 기준선 대비 Δ · CV): 3A UP24∪UP35_DOWN24 house +0.54 4/4 · live +1.38 4/4 / 3B **LIVE_OK** house +0.63 4/4 · live +1.02 4/4
  (DOWN24 는 house +0.74 이지만 live −0.82 1/4) / 3D DOWN24 house +0.57 4/4 · live +0.21 3/4. 자본 10 · 손절 ROI 25 · 전용 상한 2 · 쿨다운 4h · TP 15/20/25/30.
  on 전 확인: 그림자 기록(`rf:shadow:*`)의 `guards_ok` 비율과 가상 보고서 Δ·CV. 3A 손절 대안 `rf_s2_short_stop_mode=swing8`.
- 전체 스위트 28 실패는 main HEAD(8289bc1) 스냅샷에서도 같은 28 = 기존 결함 (별도 작업).
