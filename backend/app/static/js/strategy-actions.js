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
    if (typeof loadBalance === 'function') loadBalance();  // 🌟 즉시 잔액 갱신
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
    if (typeof loadBalance === 'function') loadBalance();  // 🌟 즉시 잔액 갱신 (reserved 변경)
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
    if (typeof loadBalance === 'function') loadBalance();  // 🌟 즉시 잔액 갱신 (마진 lock)
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
    if (typeof loadBalance === 'function') loadBalance();  // 🌟 즉시 잔액 갱신
  } catch (err) {
    toast(`재계산 실패: ${err.message}`, 'error');
  }
}

// 🌟 2026-06-08 사장님 신 기능 (옵션 B): 미진입 단계 추가/수정 (= 4~10단계 신 추가)
// 사장님 명시: "4~10단계 추가 = 현재가 기준 신 trigger"
// 사장님이 입력 = stage_no + 자본 (= 트리%는 10% 고정)
// 신 trigger = 현재가 × 1.10^N (= 사장님 자본 보호 + 의도 정확)
function openAddUntriggeredStagesModal(id, symbol, side, currentStage) {
  const startStage = (currentStage || 0) + 1;
  if (startStage > 10) {
    toast(`⚠️ 이미 10단계 모두 진입 — 추가 불가`, 'error');
    return;
  }

  // 동적 단계 입력 행
  let rowsHtml = '';
  for (let n = startStage; n <= 10; n++) {
    rowsHtml += `
      <tr>
        <td class="text-center text-slate-300" style="padding:4px">${n}단계</td>
        <td><input type="number" id="add-stage-capital-${n}" placeholder="자본 (USDT)" min="0" step="1" class="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-sm" style="width:100%"></td>
        <td><input type="number" id="add-stage-pct-${n}" value="10" min="1" max="100" step="0.1" class="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-sm" style="width:60px"></td>
      </tr>
    `;
  }

  const modalHtml = `
    <div id="add-stages-modal-backdrop" style="position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:9999;display:flex;align-items:center;justify-content:center" onclick="if(event.target.id==='add-stages-modal-backdrop')closeAddUntriggeredStagesModal()">
      <div style="background:#1e293b;border-radius:8px;padding:20px;max-width:520px;width:90%;max-height:80vh;overflow-y:auto">
        <h3 style="font-size:16px;font-weight:bold;margin-bottom:8px;color:#10b981">➕ 미진입 단계 추가/수정 — #${id} ${symbol} ${side}</h3>
        <p style="font-size:12px;color:#94a3b8;margin-bottom:12px">
          진입 단계 (1~${currentStage}) = 절대 보존 (사장님 자본 보호)<br>
          신 단계 trigger = 현재가 × 1.10^N (${side === 'SHORT' ? '가격 상승' : '가격 하락'} 시 진입)
        </p>
        <table style="width:100%;border-collapse:collapse;margin-bottom:12px">
          <thead>
            <tr style="border-bottom:1px solid #334155;font-size:12px;color:#94a3b8">
              <th style="text-align:center;padding:4px;width:50px">단계</th>
              <th style="text-align:left;padding:4px">자본 (USDT)</th>
              <th style="text-align:left;padding:4px;width:80px">트리%</th>
            </tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button onclick="closeAddUntriggeredStagesModal()" class="btn-ghost btn text-xs" style="padding:6px 16px">취소</button>
          <button onclick="submitAddUntriggeredStages(${id})" class="btn-success btn text-xs" style="padding:6px 16px;background:#10b981;color:white">➕ 적용</button>
        </div>
      </div>
    </div>
  `;
  document.body.insertAdjacentHTML('beforeend', modalHtml);
}

function closeAddUntriggeredStagesModal() {
  const m = document.getElementById('add-stages-modal-backdrop');
  if (m) m.remove();
}

// 🌟 2026-06-08 사장님 신 기능: 미체결 LIMIT 주문 시각 + 개별 취소
// 사장님 명시: "「💉 포지션 추가」 지정가 진입예정 어디서 관리?" → 신 모달
async function openOpenOrdersModal(id, symbol, side) {
  let data;
  try {
    data = await api(`/strategies/${id}/open-orders`);
  } catch (err) {
    toast(`미체결 주문 조회 실패: ${err.message}`, 'error');
    return;
  }
  const orders = data.orders || [];
  const fmt = (n) => n != null ? Number(n).toLocaleString('en-US', {maximumFractionDigits: 8}) : '-';
  const rowsHtml = orders.length === 0
    ? `<tr><td colspan="6" class="text-center py-4 text-slate-400">미체결 주문 없음</td></tr>`
    : orders.map(o => `
        <tr style="border-bottom:1px solid #334155">
          <td style="padding:6px;text-align:center">
            ${o.stage_no != null ? `<span class="text-blue-300">${o.stage_no}단계</span>` : `<span class="text-purple-300">💉 추가</span>`}
          </td>
          <td style="padding:6px;text-align:center">
            <span class="${o.side === 'SELL' ? 'text-red-400' : 'text-green-400'}">${o.side}</span>
          </td>
          <td style="padding:6px;text-align:center">${o.order_type}</td>
          <td style="padding:6px;text-align:right;font-family:monospace">${fmt(o.price || o.trigger_price)}</td>
          <td style="padding:6px;text-align:right;font-family:monospace">${fmt(o.orig_qty)}</td>
          <td style="padding:6px;text-align:center">
            <button onclick="cancelOpenOrder(${id}, ${o.id}, this)" class="btn-danger btn text-xs" style="padding:3px 8px;background:#dc2626;color:white">❌ 취소</button>
          </td>
        </tr>
      `).join('');

  const modalHtml = `
    <div id="open-orders-modal-backdrop" style="position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:9999;display:flex;align-items:center;justify-content:center" onclick="if(event.target.id==='open-orders-modal-backdrop')closeOpenOrdersModal()">
      <div style="background:#1e293b;border-radius:8px;padding:20px;max-width:640px;width:90%;max-height:80vh;overflow-y:auto">
        <h3 style="font-size:16px;font-weight:bold;margin-bottom:8px;color:#3b82f6">📋 미체결 주문 — #${id} ${symbol} ${side}</h3>
        <p style="font-size:12px;color:#94a3b8;margin-bottom:12px">
          총 ${orders.length}건 (= 자동 단계 LIMIT + 「💉 포지션 추가」 LIMIT). 개별 취소 가능.
        </p>
        <table style="width:100%;border-collapse:collapse;margin-bottom:12px">
          <thead>
            <tr style="border-bottom:1px solid #475569;font-size:12px;color:#94a3b8">
              <th style="text-align:center;padding:6px">단계</th>
              <th style="text-align:center;padding:6px">방향</th>
              <th style="text-align:center;padding:6px">유형</th>
              <th style="text-align:right;padding:6px">가격</th>
              <th style="text-align:right;padding:6px">수량</th>
              <th style="text-align:center;padding:6px">액션</th>
            </tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button onclick="closeOpenOrdersModal()" class="btn-ghost btn text-xs" style="padding:6px 16px">닫기</button>
        </div>
      </div>
    </div>
  `;
  document.body.insertAdjacentHTML('beforeend', modalHtml);
}

function closeOpenOrdersModal() {
  const m = document.getElementById('open-orders-modal-backdrop');
  if (m) m.remove();
}

async function cancelOpenOrder(strategyId, orderId, btn) {
  if (!confirm(`주문 #${orderId} 를 취소하시겠습니까?\n\n거래소 호출 = 즉시 취소\n사장님 자본 = 영향 X (= 미체결만 취소)`)) return;
  try {
    btn.disabled = true;
    btn.textContent = '취소 중...';
    await api(`/strategies/${strategyId}/open-orders/${orderId}`, { method: 'DELETE' });
    toast(`✅ 주문 #${orderId} 취소 완료`, 'success');
    closeOpenOrdersModal();
    refreshStrategies();
    if (typeof loadBalance === 'function') loadBalance();  // 🌟 즉시 잔액 갱신 (미체결 취소 = margin release)
  } catch (err) {
    toast(`취소 실패: ${err.message}`, 'error');
    if (btn) { btn.disabled = false; btn.textContent = '❌ 취소'; }
  }
}

async function submitAddUntriggeredStages(id) {
  const stages = [];
  for (let n = 1; n <= 10; n++) {
    const capInput = document.getElementById(`add-stage-capital-${n}`);
    if (!capInput) continue;
    const cap = parseFloat(capInput.value || '0');
    if (cap > 0) {
      const pctInput = document.getElementById(`add-stage-pct-${n}`);
      const pct = parseFloat(pctInput?.value || '10');
      stages.push({ stage_no: n, planned_capital: cap, trigger_percent: pct });
    }
  }
  if (stages.length === 0) {
    toast(`⚠️ 자본 입력된 단계가 없습니다`, 'error');
    return;
  }

  // 🌟 2026-06-08 사장님 안전: 신 trigger 가격 사전 미리보기 (= 사장님 자본 보호)
  // 현재가 = strategy 의 mark_price 또는 = window._strategiesById 에서 조회
  const strategy = (window._strategiesById || {})[id];
  let currentPrice = 0;
  let side = 'SHORT';
  if (strategy) {
    side = (strategy.side || 'SHORT').toUpperCase();
    // 마크가 = avg + pnl/qty (LONG) | avg - pnl/qty (SHORT)
    const qty = Math.abs(Number(strategy.current_position_qty || 0));
    const avg = Number(strategy.avg_entry_price || 0);
    const pnl = Number(strategy.unrealized_pnl || 0);
    if (qty > 0 && avg > 0) {
      currentPrice = side === 'LONG' ? (avg + pnl/qty) : (avg - pnl/qty);
    }
  }
  // Binance positions cache fallback
  if (!currentPrice && window._binancePositionsCache && strategy) {
    const bp = (window._binancePositionsCache[strategy.exchange_account_id]?.positions || {})[strategy.symbol];
    if (bp && bp.mark_price) currentPrice = Number(bp.mark_price);
  }

  const direction = side === 'SHORT' ? 1.10 : 0.90;
  const sortedStages = [...stages].sort((a,b) => a.stage_no - b.stage_no);
  const previewLines = sortedStages.map((s, i) => {
    const N = i + 1;
    const newTrigger = currentPrice > 0 ? (currentPrice * Math.pow(direction, N)).toFixed(8) : '?';
    return `  ${s.stage_no}단계: 자본 ${s.planned_capital} USDT, 트리 ${s.trigger_percent}% → 신 진입가 ${newTrigger}`;
  });

  const confirmMsg =
    `➕ 미진입 단계 ${stages.length}개 추가/수정\n\n` +
    `📊 현재가 (Binance): ${currentPrice > 0 ? currentPrice.toFixed(8) : '?'} ${side}\n` +
    `📐 신 진입가 = 현재가 × ${side === 'SHORT' ? '1.10' : '0.90'}^N\n\n` +
    previewLines.join('\n') +
    `\n\n✅ 진입 단계 = 절대 보존 (사장님 자본 보호)\n` +
    `✅ 거래소 호출 X (= 청산 X)\n\n` +
    `진행할까요?`;
  if (!confirm(confirmMsg)) return;

  try {
    await api(`/strategies/${id}/add-untriggered-stages`, {
      method: 'POST',
      body: { stages: stages },
    });
    toast(`✅ ${stages.length}개 단계 추가/수정 완료!`, 'success');
    closeAddUntriggeredStagesModal();
    refreshStrategies();
    if (typeof loadBalance === 'function') loadBalance();  // 🌟 즉시 잔액 갱신 (미진입 = reserved 증가)
  } catch (err) {
    toast(`추가 실패: ${err.message}`, 'error');
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
    if (typeof loadBalance === 'function') loadBalance();  // 🌟 즉시 잔액 갱신 (수동 청산 = margin release)
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
    if (typeof loadBalance === 'function') loadBalance();  // 🌟 즉시 잔액 갱신 (증거금 추가 = margin lock)
  } catch (err) {
    toast(`증거금 추가 실패: ${err.message}`, 'error');
  }
}
