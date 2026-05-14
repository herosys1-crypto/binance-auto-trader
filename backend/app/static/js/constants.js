/**
 * Frontend constants — Status maps + terminal status set.
 *
 * 2026-05-14 Phase 3 분리: index.html 5,875 줄 monolith 에서 분리.
 * 점진적 모듈화의 첫 단계 — pure 데이터만 (함수 없음, 의존성 없음).
 *
 * 정책 history:
 *   - 옵션 C 1~10단계 동적 (2026-04-30) — STAGE1~STAGE10 모두 매핑
 *   - TP1~10 확장 (2026-05-06) — TP6~10 도 PARTIAL 추가
 *   - 트레일링 v5 (2026-05-12) — TRAILING_ARMED 추가
 *   - 크라이시스 (2026-05-07) — CRISIS_TP1_DONE 추가
 *
 * 라벨은 의미 명확화:
 *   STAGE_X_OPEN_PENDING → "X단계 주문 발송됨, 체결 대기" (LIMIT 미체결)
 *   STAGE_X_OPEN         → "X단계 보유 중" (체결됨, 다음 단계 trigger 대기)
 *   STAGE_X_FILLED       → 호환용 (legacy, 현재 stream_service 가 STAGE_X_OPEN 으로 직행)
 *
 * 사용:
 *   <script src="/static/js/constants.js"></script>  // index.html 본문 script 보다 먼저 로드
 *   STATUS_MAP['STAGE1_OPEN'].ko  // → "1단계 보유 중"
 */

// 전역으로 노출 (index.html 의 inline script 가 직접 참조).
// ES module 미사용 — 이 프로젝트는 단일 페이지 + 전역 함수 패턴 유지.

const STATUS_MAP = {
  'WAITING':                    { ko: '대기 중',              sig: 'gray',   icon: '⚪' },
  // 1~10단계 진입 (PENDING + OPEN). FILLED 는 legacy 호환.
  'STAGE1_OPEN_PENDING':        { ko: '1단계 주문 발송됨',     sig: 'yellow', icon: '⏳' },
  'STAGE1_OPEN':                { ko: '1단계 보유 중',        sig: 'green',  icon: '🟢' },
  'STAGE1_FILLED':              { ko: '1단계 진입 완료',      sig: 'green',  icon: '✅' },
  'STAGE2_OPEN_PENDING':        { ko: '2단계 주문 발송됨',     sig: 'yellow', icon: '⏳' },
  'STAGE2_OPEN':                { ko: '2단계 보유 중',        sig: 'green',  icon: '🟢' },
  'STAGE2_FILLED':              { ko: '2단계 진입 완료',      sig: 'green',  icon: '✅' },
  'STAGE3_OPEN_PENDING':        { ko: '3단계 주문 발송됨',     sig: 'yellow', icon: '⏳' },
  'STAGE3_OPEN':                { ko: '3단계 보유 중',        sig: 'green',  icon: '🟢' },
  'STAGE3_FILLED':              { ko: '3단계 진입 완료',      sig: 'green',  icon: '✅' },
  'STAGE4_OPEN_PENDING':        { ko: '4단계 주문 발송됨',     sig: 'yellow', icon: '⏳' },
  'STAGE4_OPEN':                { ko: '4단계 보유 중',        sig: 'green',  icon: '🟢' },
  'STAGE4_FILLED':              { ko: '4단계 진입 완료',      sig: 'green',  icon: '✅' },
  'STAGE5_OPEN_PENDING':        { ko: '5단계 주문 발송됨',     sig: 'yellow', icon: '⏳' },
  'STAGE5_OPEN':                { ko: '5단계 보유 중',        sig: 'green',  icon: '🟢' },
  'STAGE6_OPEN_PENDING':        { ko: '6단계 주문 발송됨',     sig: 'yellow', icon: '⏳' },
  'STAGE6_OPEN':                { ko: '6단계 보유 중',        sig: 'green',  icon: '🟢' },
  'STAGE7_OPEN_PENDING':        { ko: '7단계 주문 발송됨',     sig: 'yellow', icon: '⏳' },
  'STAGE7_OPEN':                { ko: '7단계 보유 중',        sig: 'green',  icon: '🟢' },
  'STAGE8_OPEN_PENDING':        { ko: '8단계 주문 발송됨',     sig: 'yellow', icon: '⏳' },
  'STAGE8_OPEN':                { ko: '8단계 보유 중',        sig: 'green',  icon: '🟢' },
  'STAGE9_OPEN_PENDING':        { ko: '9단계 주문 발송됨',     sig: 'yellow', icon: '⏳' },
  'STAGE9_OPEN':                { ko: '9단계 보유 중',        sig: 'green',  icon: '🟢' },
  'STAGE10_OPEN_PENDING':       { ko: '10단계 주문 발송됨',    sig: 'yellow', icon: '⏳' },
  'STAGE10_OPEN':               { ko: '10단계 보유 중',       sig: 'green',  icon: '🟢' },
  'ACTIVE':                     { ko: '진행 중',              sig: 'green',  icon: '🟢' },
  // TP 익절 — 부분/전체. PARTIAL 은 잔량 보유 중, FILLED 는 legacy.
  'TP1_FILLED':                 { ko: '1차 익절 체결',         sig: 'green',  icon: '💎' },
  'TP2_FILLED':                 { ko: '2차 익절 체결',         sig: 'green',  icon: '💎' },
  'TP3_FILLED':                 { ko: '3차 익절 체결',         sig: 'green',  icon: '💎' },
  'TP4_FILLED':                 { ko: '4차 익절 체결',         sig: 'green',  icon: '💎' },
  'TP5_FILLED':                 { ko: '5차 익절 체결',         sig: 'green',  icon: '💎' },
  'TP1_DONE_PARTIAL':           { ko: '1차 익절 (잔량 보유)', sig: 'green',  icon: '💎' },
  'TP2_DONE_PARTIAL':           { ko: '2차 익절 (잔량 보유)', sig: 'green',  icon: '💎' },
  'TP3_DONE_PARTIAL':           { ko: '3차 익절 (잔량 보유)', sig: 'green',  icon: '💎' },
  'TP4_DONE_PARTIAL':           { ko: '4차 익절 (잔량 보유)', sig: 'green',  icon: '💎' },
  'TP5_DONE_PARTIAL':           { ko: '5차 익절 (잔량 보유)', sig: 'green',  icon: '💎' },
  'TP2_DONE':                   { ko: '2차 익절 완료',         sig: 'green',  icon: '💎' },
  'TRAILING_ARMED':             { ko: '트레일링 발동 대기',     sig: 'green',  icon: '📈' },
  // 크라이시스 복구 모드
  'CRISIS_TP1_DONE':            { ko: '🚨 크라이시스 TP1 완료', sig: 'yellow', icon: '🛡' },
  // 자동 재진입 사이클
  'REENTRY_DONE':               { ko: '재진입 완료',           sig: 'green',  icon: '🔄' },
  'REENTRY_FAILED':             { ko: '재진입 실패',           sig: 'red',    icon: '⚠️' },
  // 종료 상태
  'COMPLETED':                  { ko: '✅ 정상 종료 (전체 익절)', sig: 'green',  icon: '🎯' },
  'REENTRY_READY':              { ko: '재진입 대기 (수동 시작 또는 자동)', sig: 'gray', icon: '🔄' },
  'CLOSED':                     { ko: '정상 종료',            sig: 'gray',   icon: '✓' },
  'CLOSED_BY_TP':               { ko: '익절 종료',            sig: 'green',  icon: '💎' },
  'CLOSED_BY_SL':               { ko: '손절 종료',            sig: 'red',    icon: '🛑' },
  'STOPPING':                   { ko: '종료 중 (청산 진행)',  sig: 'yellow', icon: '⏸' },
  'STOPPED':                    { ko: '수동 종료',            sig: 'gray',   icon: '⏹' },
  'LIQUIDATION_IMMINENT':       { ko: '⚠️ 청산 임박',         sig: 'red',    icon: '🚨' },
  'KILL_SWITCH_TRIGGERED':      { ko: '🚨 긴급 정지 (Kill-Switch)', sig: 'red', icon: '🛑' },
};

const ORDER_STATUS_MAP = {
  'NEW':              { ko: '대기',     sig: 'yellow' },
  'PARTIALLY_FILLED': { ko: '부분 체결', sig: 'yellow' },
  'FILLED':           { ko: '체결 완료', sig: 'green' },
  'CANCELED':         { ko: '취소',     sig: 'gray' },
  'EXPIRED':          { ko: '만료',     sig: 'gray' },
  'REJECTED':         { ko: '거부',     sig: 'red' },
};

const PURPOSE_MAP = {
  'ENTRY':            '진입',
  'TAKE_PROFIT':      '익절',
  'STOP_LOSS':        '손절',
  'EMERGENCY_CLOSE':  '긴급 청산',
};

// Backend `_CLOSED_STATUSES` (services/strategy_service.py, api/v1/strategies.py) + STOPPING.
// 2026-05-04 v3 (사용자 피드백): "종료 숨김" 은 진행 중 전략만 보이게 — STOPPING (종료 중)
// 도 사용자 관점에선 "끝낸 거" 라 숨겨야 함. backend 의 race-window 보호 (STOPPING 도
// active 로 보고 신규 진입 차단) 는 그대로 유지하되 프론트에서는 정리 진행 중 행을
// 가린다. duplicate-prevention 에러 메시지가 offending strategy id 알려주므로 사용자가
// 어떤 행이 막는지 알 수 있음.
const TERMINAL_STATUSES = ['STOPPED', 'STOPPING', 'COMPLETED', 'CLOSED', 'CLOSED_BY_SL', 'CLOSED_BY_TP', 'REENTRY_READY', 'KILL_SWITCH_TRIGGERED'];
