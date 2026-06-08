/**
 * 전략 행 액션 — 긴급 종료 / 보관 / 다음 단계 / 증거금 추가 (Phase 3 단계 3q, 2026-05-15).
 *
 * - emergencyStop(id)               : 모든 주문 취소 + 포지션 시장가 청산 (확정 손실 가능)
 * - deleteStrategy(id)              : soft delete (archive) — DB row 보존, UI 만 숨김
 * - triggerNextStage(id)            : 트리거 비율 무시, 현재가 시장가 즉시 진입
 * - addMargin(id, symbol, side)     : ISOLATED 모드 증거금 추가 (청산가 완화)
 *
 * 외부 의존 (script-scope 공유):
 *   - api, toast (전역 헬퍼)
 *   - refreshStrategies (strategies-list.js)
 */

async function emergencyStop(id) {
  if (!confirm(`⚠️ 긴급 종료\n\n전략 #${id} 의 모든 주문을 취소하고 포지션을 시장가로 청산합니다.\n\n실손실이 확정될 수 있습니다. 정말 진행할까요?`)) return;
  try {
    await api(`/strategies/${id}/stop`, {method: 'POST', body: {mode: 'emergency_stop', reason: '대시보드에서 긴급 종료'}});
    toast(`전략 #${id} 긴급 종료 요청 발송`, 'warning');
    refreshStrategies();
  } catch (err) { toast('긴급 종료 실패: ' + err.message, 'error'); }
}

// UX #17 (2026-04-29): 대기 상태 (한번도 체결 안 된) 종료 전략 영구 삭제
async function deleteStrategy(id) {
  // 2026-05-06 fix (#96 사례): hard delete → soft delete (archive).
  // realized_pnl 합계가 거래소 history 와 일치하도록 row 보존.
  const confirmMsg =
    `🗑 전략 #${id} 보관 처리 (archive)\n\n` +
    `[안전 변경 — 2026-05-06]\n` +
    `이전: DB 에서 영구 삭제 (cascade 로 orders 도 사라짐)\n` +
    `이제: archive (DB row 보존, UI 만 숨김)\n\n` +
    `효과:\n` +
    `  ✓ 거래소 영향 없음 (DB 만 처리)\n` +
    `  ✓ realized_pnl 통계 합계에 유지 (운영 손익 정확성)\n` +
    `  ✓ 필요 시 복원 가능 (별도 endpoint, 다음 PR)\n\n` +
    `진행할까요?`;
  if (!confirm(confirmMsg)) return;
  try {
    const r = await api(`/strategies/${id}`, {method: 'DELETE'});
    toast(r.message || `전략 #${id} 보관 처리 완료`, 'success');
    refreshStrategies();
  } catch (err) { toast('보관 처리 실패: ' + err.message, 'error'); }
}

// 2026-05-04 v2 (사용자 요청): 「▶ 다음 단계」 = 시장가 즉시 진입.
// 이전엔 LIMIT @ trigger_price 라 자동 워커와 동일 — 수동의 의미가 없었음.
// 이제: planned_capital 로 현재가 시장가 즉시 체결. is_triggered=True 마킹.
async function triggerNextStage(id) {
  if (!confirm(
    `▶ 전략 #${id} 다음 단계 시장가 즉시 진입\n\n` +
    `- 트리거 비율 무시, 현재가 MARKET 으로 즉시 체결\n` +
    `- planned_capital 기준 수량 재계산 (현재가 + 레버리지)\n` +
    `- stage_plan.is_triggered = True (트리거 우회 표시)\n\n` +
    `진행할까요?`
  )) return;
  try {
    const resp = await api(`/strategies/${id}/trigger-next-stage`, { method: 'POST' });
    toast(`✅ ${resp.message || '다음 단계 시장가 진입 요청 발송'}`, 'success');
    refreshStrategies();
  } catch (err) {
    toast(`다음 단계 진입 실패: ${err.message}`, 'error');
  }
}

// 🌟 2026-06-08 사장님 신 기능: 미진입 단계 trigger_price = 현재가 기준 재계산
// 사장님 명시: "포지션 유지하고 다음단계 진입을 할수 있게 현재가 기준으로 10%더 상승하면 진입하게 해줘"
async function recalcUntriggeredFromCurrent(id) {
  if (!confirm(
    `🔄 전략 #${id} 미진입 단계 진입가 재계산\n\n` +
    `- 진입한 단계 = 영향 X (사장님 자본 보호)\n` +
    `- 미진입 단계 trigger_price = 현재가 × 1.10, 1.21, 1.331, ...\n` +
    `- SHORT: 가격 +10% 상승 시 진입 / LONG: -10% 하락 시 진입\n` +
    `- trigger_percent = 10% 유지\n\n` +
    `진행할까요?`
  )) return;
  try {
    await api(`/strategies/${id}/recalc-untriggered-from-current`, { method: 'POST' });
    toast(`✅ 미진입 단계 재계산 완료 (현재가 기준 +10% 누적)`, 'success');
    refreshStrategies();
  } catch (err) {
    toast(`재계산 실패: ${err.message}`, 'error');
  }
}

// 2026-05-21 Phase 2 (사장님 요구 — #77/#78 사례 후속):
// MANUAL_CLEANUP_REQUIRED 상태에서 사장님이 거래소 UI 에서 직접 청산 완료 후
// 「✅ 처리 완료」 클릭 → STOPPED 전환 (자동 STOPPED 차단된 상태였음).
// 감사 추적 위해 RiskEvent 에 「사장님 직접 ack」 로그 남김.
async function acknowledgeManualCleanup(id) {
  const confirmMsg =
    `✅ 전략 #${id} 수동 청산 처리 완료 확인\n\n` +
    `이 작업은 「사장님이 거래소에서 직접 포지션을 청산했음」을 시스템에 알립니다.\n\n` +
    `효과:\n` +
    `  • status: MANUAL_CLEANUP_REQUIRED → STOPPED 전환\n` +
    `  • 감사 로그 기록 (자동 정리 vs 사장님 직접 처리 구분)\n` +
    `  • reconcile 다음 사이클이 거래소 잔재 포지션 0 재확인\n\n` +
    `※ 거래소에 포지션이 남아있는 상태에서 클릭하면 reconcile 이 다음 사이클에 \n` +
    `   orphan 으로 감지하여 알림을 보낼 수 있습니다. 청산 완료 후 클릭하세요.\n\n` +
    `진행할까요?`;
  if (!confirm(confirmMsg)) return;
  try {
    const resp = await api(`/strategies/${id}/acknowledge-manual-cleanup`, { method: 'POST' });
    toast(`✅ ${resp.message || `전략 #${id} 수동 청산 처리 완료 확인됨`}`, 'success');
    refreshStrategies();
  } catch (err) {
    toast(`수동 청산 처리 확인 실패: ${err.message}`, 'error');
  }
}

// 2026-05-04 (사용자 요청): 증거금 추가 — ISOLATED 모드 포지션 청산가 완화.
// prompt 로 USDT 금액 입력 → POST /strategies/{id}/add-margin → 결과 토스트.
// 거래소가 CROSS 모드면 backend 가 -4046 친절 에러 메시지로 거절.
async function addMargin(id, symbol, side) {
  const input = prompt(
    `🛡 증거금 추가\n\n전략 #${id} ${symbol} ${side}\n\n` +
    `추가할 증거금 (USDT, 양수 입력):\n\n` +
    `※ ISOLATED 모드 포지션만 가능. CROSS 모드면 거래소가 거절합니다.\n` +
    `※ 추가 후 거래소 UI 에서 새 청산가를 확인하세요.`,
    "10"
  );
  if (input === null) return;  // 취소
  const amount = parseFloat(input);
  if (isNaN(amount) || amount <= 0) {
    toast(`잘못된 금액: ${input}. 양수 USDT 값을 입력하세요.`, 'error');
    return;
  }
  try {
    const resp = await api(`/strategies/${id}/add-margin`, {
      method: 'POST',
      body: { amount: amount },
    });
    toast(`✅ ${resp.message || `증거금 ${amount} USDT 추가 완료`}`, 'success');
    refreshStrategies();
  } catch (err) {
    toast(`증거금 추가 실패: ${err.message}`, 'error');
  }
}
