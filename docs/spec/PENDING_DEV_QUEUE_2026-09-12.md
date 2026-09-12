# 개발 대기열 (2026-09-12, 사장님 「저장해뒀다가 한도 다시 설정되면 그때 모두 개발」)

사장님이 9/12 에 결정 2·3·4 를 전부 승인했다. 다음 세션은 이 문서대로 **묻지 말고 순서대로** 개발한다.
근거 데이터: 실전 7일(9/5~9/11) 손익 −1,162 중 약 −1,000 이 「추가」(수동 💉 + 자동 피라미딩 0/7)에서 났고,
가상매매 v2(98,461건) 채택 규칙은 SHORT confirm_peak_111·s2_hist_turn_down, LONG bottom_331·multiday_rebound_352(UP24)·surge_start_346(DOWN24).
(docs/spec/LEGACY_LADDER_RESTORE_2026-09-11.md · EXTERNAL_STRATEGIES_FUJIMOTO_MACH7_2026-09-12.md · PAPER_TRADING_LEARNING_2026-09-08.md 참고)

## 이미 끝난 것 (다시 하지 말 것)
- 결정 1: `pyramid_sides=LONG` VPS 적용 완료 (9/12 00:50 UTC, 재시작 불필요).
- Fix 367/367b/c/d 기존 방식 = 처음 방식 (배포 ea88614), Fix 368 후지모토·마하세븐 shadow 워커 + 가상 규칙 8개 (배포 d0194b0).

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
