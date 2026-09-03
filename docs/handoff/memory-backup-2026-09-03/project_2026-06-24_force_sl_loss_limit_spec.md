---
name: project-2026-06-24-force-sl-loss-limit-spec
description: 손실 한도 강제 청산 기능 기획서 작성 완료 — 사장님 검토 대기 (미구현/미커밋)
metadata: 
  node_type: memory
  type: project
  originSessionId: 3a7c8fc6-6afa-4af2-8926-abe6b890367e
---

🆕 2026-06-24 사장님 신규 기능 요청: **손실 한도 강제 청산 (Force SL / Loss-Limit Close)**.

**기획서**: `docs/spec/FORCE_SL_LOSS_LIMIT_SPEC_2026-06-24.md` (작성 완료, 작업 트리에 untracked).

**사장님 확정 사양**:
- 손실 기준 = **ROI** (레버리지 포함, 기존 SL과 동일 계산).
- 적용 범위 = **전역** (롱/숏 각각 한 번에 on/off + 임계값).
- 롱 = 기본 ON, -10% / 숏 = 기본 OFF, -10%. 선택지 {-5,-10,-15,-20}.

**기존 SL과 핵심 차이**: (1) -80~90% vs -10% 능동 손절 = 공존, (2) 기존은 모든 단계 진입 후만 / 신 기능은 아무 단계에서나 즉시(물타기 전 손절), (3) 발동=전량청산+미진입 LIMIT 취소+재진입 X+알림.

**안전 핵심**: mark_price 없으면 절대 청산 X ([[project_2026-06-22_stage_trigger_markprice_silent_block]] v51 단일 진실 적용). 자본 무관 ROI (BEATUSDT v4 사상).

**구현 위치(기획서 명시)**: system_settings 4키 + `risk_service.evaluate_force_stop_loss()` + `tp_sl_orchestrator._execute_force_stop_loss()` (기존 SL보다 먼저 평가) + `/admin/system/force-sl` API + UI 설정 섹션.

**현재 상태**: ✅ 구현 완료 + push. 브랜치 `feat/force-sl-loss-limit-2026-06-24` (origin/main 기반, 커밋 `2c88f53`). PR: https://github.com/herosys1-crypto/binance-auto-trader/pull/new/feat/force-sl-loss-limit-2026-06-24 (gh 미설치 → 웹 UI 생성). UI = 「💼 계정」 모달에 롱/숏 토글+임계값.

**구현 파일 8개**: risk_constants(4키+default+허용값) / system_settings_service(get_decimal+get_force_sl) / risk_service(force_sl_should_trigger 순수함수 + evaluate_force_stop_loss) / tp_sl_orchestrator(_execute_force_stop_loss, 기존SL보다 먼저 평가) / api/admin/operations(GET/PATCH /admin/settings/force-sl) / static/js/accounts-modal(UI) / test_force_stop_loss(8 통과) / 기획서.

**테스트**: 새 단위 8/8 통과. 기존 unit 380 통과. 단 기존 stale 실패 5개 발견(내 변경 무관 — origin/main도 동일 실패): test_risk_constants_centralization(DEFAULT_SL 50 기대인데 실제 90) + test_v7_short_exit_partial_stage 4개(v7 영구 비활성인데 옛 동작 기대). 별도 정리 필요.

**전략별 override 추가 (2026-06-24, 커밋 `bd4fe4d`)**: 사장님 "각 전략에 우선하는 방식". 전역 = 모든 전략 기본 + 전략별 override 우선 (NULL=전역 상속). alembic 0020 = strategy_instances.force_sl_enabled_override(Bool null)+force_sl_roi_override(Numeric null). resolve_force_sl() 순수함수. PATCH /strategies/{id}/force-sl (mode inherit/off/on+roi). UI = 전략 행 드롭다운 「강제:전역/끔/-5~-20%」. 테스트 13통과.

**⚠️ 미배포 (배포 절차 변경됨)**: PR 머지 후 — (1) `git pull`, (2) **`docker compose exec api alembic upgrade head` (0020 마이그레이션 필수!)**, (3) api+scheduler 재빌드/재시작. 마이그레이션 빠뜨리면 force_sl_*_override 컬럼 없어 500 에러. 기존 stale 테스트 5개는 여전히 무관 실패 (task_76c8dce4로 플래그됨).
