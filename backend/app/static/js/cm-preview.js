/**
 * Create-Modal — Preview / 잔액 사전 확인 / 청산 위험 분석 (Phase 3 단계 3h, 2026-05-14).
 *
 * 「📊 미리보기」 버튼 클릭 흐름:
 *   1. updateCmSubmit()         : submit 버튼 disable/enable 결정 (preview 후 호출)
 *   2. calcPreview()             : symbol/start_price → POST /strategies/preview-inline 또는 /calculate
 *   3. _renderPreview(data)      : 단계별 평균진입/청산가/도달 가능성 분석 + 경고 박스
 *   4. loadBalanceForPreview()   : /exchange-accounts/{id}/balance + 중복 활성 strategy 검사
 *   5. submitInPlaceSettings()   : 「↻ 설정만 수정」 — TP/SL + trigger% + capital + 단계 수 변경
 *
 * Helper:
 *   - _filledCapitals()              : 비어있지 않은 capital 수집 (앞에서 컷오프)
 *   - _estimateLiquidationPrice(...)  : Isolated 청산가 보수적 근사
 *
 * 외부 의존성 (script-scope 공유):
 *   - cmState (mutable — preview, _balanceInsufficient, _liquidationRisk, _duplicateActive 등)
 *   - _cmMultiSymbols (multi-symbol.js)
 *   - _refreshSubmitBtnLabel (multi-symbol.js)
 *   - _collectDirectInputs / _collectTpSl (cm-collectors.js)
 *   - closeCreateModal (cm-state-helpers.js)
 *   - refreshStrategies (index.html)
 *   - api / toast (api.js)
 *   - fmtNum / fmtQty / escapeHtml (helpers.js)
 *   - DOM: 다수 (#cm-* prefix)
 */

function updateCmSubmit() {
  // 2026-05-12 v3 (사용자 UX): 다중 모드는 _refreshSubmitBtnLabel 이 chip 기반으로 판정 (cmState.preview 무관).
  const isMulti = document.getElementById('cm-multi-symbol-toggle')?.checked;
  if (isMulti && !cmState.editingStrategyId) {
    // 다중 모드: chip 검증 결과만 보고 enable/disable.
    // template 모드에선 templateId 도 필요. direct 는 capitals 필요.
    let okMulti = !!cmState.accountId;
    if (cmState.mode === 'template') okMulti = okMulti && !!cmState.templateId;
    if (cmState.mode === 'direct') okMulti = okMulti && cmState.capitals.some(c => c && Number(c) > 0);
    const validCount = (typeof _cmMultiSymbols !== 'undefined' ? _cmMultiSymbols.filter(s => s.status === 'valid').length : 0);
    okMulti = okMulti && (validCount > 0);
    document.getElementById('cm-submit').disabled = !okMulti;
    if (typeof _refreshSubmitBtnLabel === 'function') _refreshSubmitBtnLabel();
    return;
  }
  let ok = cmState.accountId && cmState.preview;
  if (cmState.mode === 'template') ok = ok && cmState.templateId;
  if (cmState.mode === 'direct') ok = ok && cmState.capitals.some(c => c && Number(c) > 0);
  // 잔액 부족 감지된 경우 차단 (2026-05-03)
  if (cmState._balanceInsufficient) ok = false;
  // 청산 위험 (다음 단계 도달 불가) 감지된 경우도 차단 (2026-05-03)
  if (cmState._liquidationRisk) ok = false;
  // 중복 활성 전략 감지된 경우도 차단 (2026-05-03)
  if (cmState._duplicateActive) ok = false;
  document.getElementById('cm-submit').disabled = !ok;
}

// 미리보기 단계의 잔액/마진 비교 (2026-05-03 추가)
async function loadBalanceForPreview() {
  const statusEl = document.getElementById('cm-balance-status');
  const detailEl = document.getElementById('cm-balance-detail');
  const warnEl = document.getElementById('cm-balance-warning');
  if (!cmState.accountId) {
    statusEl.textContent = '거래소 계정 선택 필요';
    detailEl.innerHTML = '';
    warnEl.classList.add('hidden');
    return;
  }
  if (!cmState.preview) {
    statusEl.textContent = '미리보기 먼저 실행';
    return;
  }
  try {
    statusEl.textContent = '잔액 조회 중...';
    const bal = await api(`/exchange-accounts/${cmState.accountId}/balance`);
    // 필요 마진 = preview 의 stages 의 capital 합 / leverage
    const stages = cmState.preview.stages || [];
    const totalCapital = stages.reduce((a, s) => a + Number(s.planned_capital || 0), 0);
    const lev = Number(cmState.preview.leverage || 1) || 1;
    const requiredMargin = totalCapital / lev;

    const available = Number(bal.available_balance || 0);
    const wallet = Number(bal.total_wallet_balance || 0);
    const usedInit = Number(bal.total_position_initial_margin || 0);
    const usedOrder = Number(bal.total_open_order_initial_margin || 0);
    const marginRatio = Number(bal.margin_ratio_pct || 0);
    const remaining = available - requiredMargin;

    const fmt = (n) => Number(n).toLocaleString('en-US', { maximumFractionDigits: 2 });
    statusEl.innerHTML = bal.is_testnet ? '<span class="text-amber-400">testnet</span>' : '<span class="text-emerald-400">mainnet</span>';

    // 같은 (symbol, side) 거래소 활성 포지션 / 시스템 활성 전략 검사 (2026-05-03)
    const symbol = (document.getElementById('cm-symbol').value || '').toUpperCase().trim();
    const side = (cmState.side || 'SHORT').toUpperCase();
    let dupWarning = '';
    if (symbol) {
      try {
        const allStrats = await api('/strategies').catch(() => []);
        const closedSet = new Set(['STOPPED','STOPPING','COMPLETED','CLOSED','CLOSED_BY_TP','CLOSED_BY_SL','REENTRY_READY','KILL_SWITCH_TRIGGERED']);
        const dup = (allStrats || []).find(s =>
          s.symbol === symbol && s.side === side && !closedSet.has(s.status) && s.exchange_account_id === cmState.accountId
        );
        if (dup) {
          dupWarning = `<div class="col-span-2 text-red-400 font-semibold">⛔ 같은 ${symbol} ${side} 활성 전략 #${dup.id} (${dup.status}) 존재 — 새 전략 차단</div>`;
        }
      } catch (e) {}
    }

    detailEl.innerHTML = `
      <div>지갑 잔액: <span class="text-slate-200">${fmt(wallet)} USDT</span></div>
      <div>가용 잔액: <span class="text-slate-200">${fmt(available)} USDT</span></div>
      <div>사용 마진 (포지션): <span class="text-slate-300">${fmt(usedInit)}</span></div>
      <div>사용 마진 (미체결): <span class="text-slate-300">${fmt(usedOrder)}</span></div>
      <div>이 전략 필요 마진: <span class="text-cyan-300 font-semibold">${fmt(requiredMargin)} USDT</span></div>
      <div>예상 진입 후 잔액: <span class="${remaining >= 0 ? 'text-emerald-300' : 'text-red-400'} font-semibold">${fmt(remaining)} USDT</span></div>
      ${dupWarning}
    `;
    // 중복 활성 전략 발견 시 차단 플래그 (전략시작 비활성화)
    cmState._duplicateActive = !!dupWarning;

    if (remaining < 0) {
      // 잔액 부족 — 빨간 경고
      cmState._balanceInsufficient = true;
      warnEl.className = 'text-xs mt-2 p-2 rounded bg-red-950 border border-red-700 text-red-300';
      warnEl.innerHTML = `
        <div class="font-semibold">⛔ 잔액 부족: ${fmt(Math.abs(remaining))} USDT 부족</div>
        <div class="mt-1">자본을 줄이거나, 레버리지를 올리거나, 거래소에 입금하세요.</div>
        <div class="mt-1 text-red-400">권장: 자본 ≤ ${fmt(available * lev)} USDT 또는 레버리지 ≥ ${Math.ceil(totalCapital / available)}x</div>
      `;
      warnEl.classList.remove('hidden');
    } else if (marginRatio > 80) {
      // 마진 비율 위험 — 노란 경고
      cmState._balanceInsufficient = false;
      warnEl.className = 'text-xs mt-2 p-2 rounded bg-amber-950 border border-amber-700 text-amber-300';
      warnEl.innerHTML = `<div>⚠️ 현재 마진 비율 ${fmt(marginRatio)}% — 청산 위험. 신중하게 진행하세요.</div>`;
      warnEl.classList.remove('hidden');
    } else {
      // 정상
      cmState._balanceInsufficient = false;
      warnEl.className = 'text-xs mt-2 p-2 rounded bg-emerald-950 border border-emerald-700 text-emerald-300';
      warnEl.innerHTML = `<div>✅ 잔액 충분 — 진입 후 가용 잔액 ${fmt(remaining)} USDT 남음 (마진 비율 ${fmt(marginRatio)}%)</div>`;
      warnEl.classList.remove('hidden');
    }
    updateCmSubmit();
  } catch (e) {
    cmState._balanceInsufficient = false;  // API 실패는 경고만 (backend 가 최종 차단)
    statusEl.innerHTML = '<span class="text-red-400">잔액 조회 실패: ' + (e.message || e) + '</span>';
    detailEl.innerHTML = '';
    warnEl.classList.add('hidden');
  }
}

function _filledCapitals() {
  // 직접 입력 모드 — 비어있지 않은 capital 수집 (앞에서부터 연속). 중간 빈 칸은 0 으로 처리하지 말고 컷오프.
  // UX: 1단계만 채우거나, 1~5단계 채우거나... 사용자가 어디까지 채웠는지 자동 감지.
  const arr = [];
  for (let i = 0; i < 10; i++) {
    const v = cmState.capitals[i];
    if (v === '' || v === null || v === undefined || Number(v) === 0) break;  // 첫 빈/0 에서 컷오프
    arr.push(String(v));
  }
  return arr;
}

async function calcPreview() {
  // 2026-05-12 v3 (사용자 UX): 다중 심볼 모드면 첫 valid chip 의 심볼 + 현재가 자동 사용.
  // 단일 input (cm-symbol) 의 leftover 값 (예: BILLUSDT) 에 의한 잘못된 미리보기 방지.
  const isMulti = document.getElementById('cm-multi-symbol-toggle')?.checked;
  let symbol, startPrice;
  if (isMulti) {
    const validChips = (typeof _cmMultiSymbols !== 'undefined' ? _cmMultiSymbols : []).filter(s => s.status === 'valid');
    if (validChips.length === 0) {
      return toast('다중 모드: ✓ 유효 심볼 1개 이상 추가 후 미리보기', 'warning');
    }
    symbol = validChips[0].symbol;
    // 각 심볼이 다른 시작가 사용 — 미리보기는 첫 심볼의 현재가로 산출 (다른 심볼은 자기 시작가 적용).
    try {
      const ticker = await api(`/market/ticker?symbol=${symbol}&testnet=true`);
      startPrice = String(ticker.lastPrice);
      // 시작가 input 도 채워서 사용자에게 보이게 (혹시 단일 모드 전환할 때)
      const sp = document.getElementById('cm-start-price');
      if (sp) sp.value = startPrice;
      toast(`📋 미리보기: 첫 ✓ 심볼 ${symbol} 기준 (현재가 ${fmtNum(Number(startPrice))}). 다른 심볼은 동일 ratio + 각자 시작가 적용.`, 'success');
    } catch (e) {
      return toast(`첫 ✓ 심볼 ${symbol} 현재가 조회 실패: ${e.message}`, 'error');
    }
  } else {
    symbol = document.getElementById('cm-symbol').value.toUpperCase().trim();
    startPrice = document.getElementById('cm-start-price').value;
    if (!symbol || !startPrice) return toast('심볼과 시작가를 입력하세요', 'warning');
  }

  if (cmState.mode === 'direct') {
    // 직접 입력 모드 — 인라인 미리보기 (DB 에 템플릿 안 만듦)
    const inp = _collectDirectInputs();
    if (inp.capitals.length === 0) return toast('1단계 투자금액 이상을 입력하세요', 'warning');
    const tpsl = _collectTpSl();
    try {
      const data = await api('/strategies/preview-inline', {
        method: 'POST',
        body: {
          symbol, side: cmState.side, start_price: startPrice,
          capitals: inp.capitals,
          trigger_percents: inp.trigger_percents,
          additional_margins: inp.additional_margins,
          last_stage_trigger_percent: inp.last_stage_trigger_percent,
          tp1_percent: tpsl.tp1_percent,
          tp2_percent: tpsl.tp2_percent,
          tp3_percent: tpsl.tp3_percent,
          tp4_percent: tpsl.tp4_percent,
          tp5_percent: tpsl.tp5_percent,
          stop_loss_percent_of_capital: tpsl.stop_loss_percent_of_capital,
        },
      });
      cmState.preview = data;
      cmState._directInputs = inp;
      cmState._directTpsl = tpsl;
      _renderPreview(data);
      loadBalanceForPreview();  // 미리보기 후 잔액 비교 (2026-05-03)
      updateCmSubmit();
      return;
    } catch (e) { return toast('미리보기 실패: '+e.message, 'error'); }
  }

  // 템플릿 모드
  if (!cmState.templateId) return toast('템플릿을 먼저 선택하세요', 'warning');
  try {
    const data = await api('/strategies/calculate', {
      method: 'POST',
      body: { symbol, side: cmState.side, start_price: startPrice, strategy_template_id: cmState.templateId },
    });
    cmState.preview = data;
    _renderPreview(data);
    loadBalanceForPreview();
    updateCmSubmit();
  } catch (e) { toast('미리보기 실패: '+e.message, 'error'); }
}

// 청산가 근사 계산 — Binance USDⓢ-M Isolated, Hedge mode (2026-05-03 추가)
// 정확한 공식은 maintenance margin tier 따라 다름. 보수적 근사값 (small position 기준).
//   SHORT: liq = avg_entry × (1 + (1 - mmr) / leverage)
//   LONG : liq = avg_entry × (1 - (1 - mmr) / leverage)
// mmr (maintenance margin rate) = 0.4% (small) ~ 5% (large). 보수 위해 0.5% 사용.
function _estimateLiquidationPrice(side, avgEntry, leverage) {
  const mmr = 0.005;  // 0.5% — 보수적
  const lev = Math.max(1, Number(leverage) || 1);
  const factor = (1 - mmr) / lev;
  if (side === 'SHORT') {
    return avgEntry * (1 + factor);
  } else {
    return avgEntry * (1 - factor);
  }
}

function _renderPreview(data) {
  // null 트리거 % 방어 + Decimal "20.0000" → "20" 정리.
  // 마지막 단계가 null 이면 backend 기본 20% 적용 (last_stage_trigger_percent 미지정).
  const _lastStageNoForPreview = data.stages.length;
  const _fmtPct = (pct) => {
    if (pct === null || pct === undefined || pct === '') return null;
    const n = Number(pct); if (isNaN(n)) return String(pct);
    return n.toLocaleString('en-US', {maximumFractionDigits: 2});
  };
  const triggerKo = (mode, pct, stageNo) => {
    if (mode === 'IMMEDIATE') return '즉시';
    const isLast = stageNo === _lastStageNoForPreview;
    const p = _fmtPct(pct) || (isLast ? '20' : '?');
    if (mode === 'PRICE_UP_PCT') return `+${p}% 도달 시`;
    if (mode === 'PRICE_DOWN_PCT') return `-${p}% 도달 시`;
    if (mode === 'LIQUIDATION_BUFFER') return _fmtPct(pct) ? `청산가 -${p}% 전` : '청산 임박 시';
    return mode;
  };
  // 단계별 누적 평균 진입가 + 예상 청산가 + 다음 단계 위험 분석 (2026-05-03)
  const side = (cmState.side || 'SHORT').toUpperCase();
  const lev = Number(data.leverage || 1) || 1;
  let cumQty = 0, cumNotional = 0;
  let firstUnreachable = null;  // 청산 후 도달 못하는 첫 단계
  const enriched = data.stages.map((s, idx) => {
    const qty = Number(s.planned_qty || 0);
    const price = Number(s.trigger_price || 0);
    cumQty += qty;
    cumNotional += qty * price;
    const avgEntry = cumQty > 0 ? (cumNotional / cumQty) : 0;
    const liqPrice = avgEntry > 0 ? _estimateLiquidationPrice(side, avgEntry, lev) : 0;
    // 다음 단계 trigger 가 청산가 넘으면 도달 불가 (SHORT 의 경우)
    const nextStage = data.stages[idx + 1];
    const nextTrigger = nextStage ? Number(nextStage.trigger_price || 0) : 0;
    let unreachable = false;
    if (nextTrigger > 0 && liqPrice > 0) {
      if (side === 'SHORT' && nextTrigger >= liqPrice) unreachable = true;
      if (side === 'LONG' && nextTrigger <= liqPrice) unreachable = true;
    }
    if (unreachable && firstUnreachable === null) firstUnreachable = idx + 2;  // 다음 단계 번호
    return { ...s, _avgEntry: avgEntry, _liqPrice: liqPrice, _unreachable: unreachable };
  });
  document.getElementById('cm-preview-tbody').innerHTML = enriched.map((s, idx) => {
    const isAfterUnreach = firstUnreachable !== null && (idx + 1) >= firstUnreachable;
    const isLast = s.stage_no === _lastStageNoForPreview;
    const rowClass = s._unreachable ? 'bg-red-950' : (isAfterUnreach ? 'opacity-50' : (isLast ? 'bg-slate-800/40' : ''));
    const stageLabel = isLast
      ? `${s.stage_no}단계 <span class="text-purple-300" style="font-size:10px" title="마지막 단계 — last_stage_trigger_percent 적용">최종</span>`
      : `${s.stage_no}단계${isAfterUnreach ? ' ⚠️' : ''}`;
    // trigger_price 비어있으면 (legacy LIQUIDATION_BUFFER) 명시적 안내
    const trigPriceCell = s.trigger_price
      ? fmtNum(s.trigger_price)
      : (s.trigger_mode === 'LIQUIDATION_BUFFER' ? '<span class="text-slate-500" title="청산가 도달 시점에 산정">청산가 산정</span>' : '-');
    return `
    <tr${rowClass ? ` class="${rowClass}"` : ''}>
      <td>${stageLabel}</td>
      <td>${triggerKo(s.trigger_mode, s.trigger_percent, s.stage_no)}</td>
      <td class="num">${trigPriceCell}</td>
      <td class="num">${fmtNum(s.planned_capital)}</td>
      <td class="num text-yellow-300">${s.additional_margin_usdt && Number(s.additional_margin_usdt) > 0 ? '+' + fmtNum(s.additional_margin_usdt) : '<span class="text-slate-600">-</span>'}</td>
      <td class="num">${s.planned_qty ? fmtQty(s.planned_qty) : '-'}</td>
      <td class="num text-cyan-300">${s._avgEntry > 0 ? fmtNum(s._avgEntry) : '-'}</td>
      <td class="num text-orange-300" title="Isolated 2x SHORT 기준 보수적 근사">${s._liqPrice > 0 ? fmtNum(s._liqPrice) : '-'}</td>
    </tr>
  `}).join('');
  const totalCap = data.stages.reduce((sum, s) => sum + Number(s.planned_capital || 0), 0);

  // 청산 위험 경고 박스
  let liqWarning = '';
  if (firstUnreachable !== null) {
    const unreachableStage = enriched.find(s => s._unreachable);
    liqWarning = `
      <div class="mt-2 p-2 rounded bg-red-950 border border-red-700 text-xs text-red-300">
        <div class="font-semibold">⛔ 청산 위험 — ${firstUnreachable}단계부터 도달 불가</div>
        <div class="mt-1">${unreachableStage.stage_no}단계 진입 후 평균진입가 <strong>${fmtNum(unreachableStage._avgEntry)}</strong>,
          예상 청산가 <strong class="text-orange-300">${fmtNum(unreachableStage._liqPrice)}</strong>.
          다음 단계 trigger <strong>${fmtNum(Number(data.stages[firstUnreachable - 1].trigger_price))}</strong> 가 청산가 위 → 가격 도달 전 강제 청산.</div>
        <div class="mt-1 text-red-400">권장: 레버리지를 낮추거나 (예: 1x) / 단계별 trigger % 줄이거나 / 후반 단계 자본 줄이세요.</div>
      </div>`;
  }
  // 2026-05-12 v3 (사용자 UX): 미리보기에 「선택된 템플릿 + 다중 심볼 리스트 + 계산 기준」 명시.
  let modeBanner = '';
  const isMulti = document.getElementById('cm-multi-symbol-toggle')?.checked;
  // 선택된 템플릿 표시
  let tplLabel = '';
  if (cmState.mode === 'template' && cmState.templateId) {
    const radio = document.querySelector(`input[name="cm-template"][value="${cmState.templateId}"]`);
    if (radio) {
      // 라디오 옆 label 의 첫 줄 (이름) 추출
      const lbl = radio.closest('label');
      const tplName = lbl ? (lbl.querySelector('.font-mono')?.textContent || `#${cmState.templateId}`) : `#${cmState.templateId}`;
      tplLabel = `<span class="text-blue-300">📋 템플릿: <strong>${escapeHtml(tplName)}</strong> (#${cmState.templateId})</span>`;
    }
  } else if (cmState.mode === 'direct') {
    tplLabel = `<span class="text-blue-300">📝 모드: 직접 입력</span>`;
  } else if (cmState.mode === 'prev') {
    tplLabel = `<span class="text-blue-300">📂 이전 전략 불러오기</span>`;
  }
  if (isMulti) {
    const validSyms = _cmMultiSymbols.filter(s => s.status === 'valid').map(s => s.symbol);
    const firstSym = validSyms[0] || (cmState._lastPreviewSymbol || '?');
    modeBanner = `<div class="mb-2 p-2 rounded bg-blue-900/30 border border-blue-700">
      <div class="flex items-center justify-between flex-wrap gap-1">
        <div>${tplLabel}</div>
        <div class="text-xs text-blue-200">📦 다중 모드 — ${validSyms.length}개 ✓ 심볼</div>
      </div>
      <div class="text-xs text-slate-300 mt-1">
        대상: ${validSyms.length ? validSyms.map(s => `<span class="font-mono px-1 bg-slate-800 rounded">${escapeHtml(s)}</span>`).join(' ') : '<span class="text-slate-500">(미정 — chip 추가 필요)</span>'}
      </div>
      <div class="text-xs text-yellow-300 mt-1">⚠️ 아래 계산은 <strong>${escapeHtml(firstSym)}</strong> 시작가 기준 예시 — 실제 시작가는 각 심볼의 현재가에서 자동 산출 (SHORT +0.1% / LONG -0.1%)</div>
    </div>`;
  } else {
    modeBanner = `<div class="mb-2 p-2 rounded bg-slate-800/40 border border-slate-700">${tplLabel}</div>`;
  }
  document.getElementById('cm-preview-meta').innerHTML =
    modeBanner +
    `레버리지: ${data.leverage}x | 총 투입자본: <strong>${fmtNum(totalCap)} USDT</strong> | ` +
    `TP: ${data.tp1_percent}/${data.tp2_percent}/${data.tp3_percent}% (25/50/25 분할 + 트레일링) | ` +
    `<span class="text-red-400">손절 한도: ${fmtNum(data.stop_loss_amount)} USDT</span>` +
    liqWarning;
  // 청산 위험 시 「전략 시작」 비활성화 (사용자 인지 후 수정하도록 강제)
  cmState._liquidationRisk = (firstUnreachable !== null);
  document.getElementById('cm-preview').classList.remove('hidden');
}

// 2026-05-04 v2 (in-place 수정 + trigger_percents): TP/SL 외에 미발동 stage 의 trigger% 도 갱신.
// 포지션/단계/평균 진입가 모두 유지. 거래소 호출 없음 (DB 만 변경).
// PATCH /strategies/{id}/settings → 새 template (clone + override) 생성 + stages_config trigger_percents 부분 갱신.
// 사용자 지적 (2026-05-04): 6단계 trigger 변경이 적용 안 되던 문제 — TP/SL 만 보내던 버그.
async function submitInPlaceSettings() {
  const editingId = cmState.editingStrategyId;
  if (!editingId) {
    toast('수정 대상 전략 ID 없음 — 「🔄 다시 시작」 으로만 가능', 'error');
    return;
  }
  const tpsl = _collectTpSl();
  // 미발동 stage 의 trigger_percent + capital 도 같이 갱신.
  // 직접 입력 모드에서만 capitals/triggers 수집 (템플릿 모드면 변경 의미 X).
  const inp = (cmState.mode === 'direct') ? _collectDirectInputs() : null;
  const triggerSummary = inp && inp.trigger_percents.length > 0
    ? `\n  Trigger%: [${inp.trigger_percents.map((t,i) => t === null ? '—' : `${i+1}=${t}`).join(', ')}]`
    : '';
  const capitalsSummary = inp && inp.capitals.length > 0
    ? `\n  Capitals: [${inp.capitals.map((c,i) => `${i+1}=${c}`).join(', ')}]`
    : '';
  const stageCountNote = inp && inp.capitals.length > 0
    ? `\n  단계 수: ${inp.capitals.length}`
    : '';
  const confirmMsg =
    `↻ 전략 #${editingId} 설정만 수정\n\n` +
    `포지션/단계/평균 진입가 모두 유지됩니다.\n` +
    `다음 사이클부터 새 설정 적용 (거래소 호출 없음):\n\n` +
    `  TP1=${tpsl.tp1_percent}% (${tpsl.tp1_qty_ratio}%)\n` +
    `  TP2=${tpsl.tp2_percent}% (${tpsl.tp2_qty_ratio}%)\n` +
    `  TP3=${tpsl.tp3_percent}% (${tpsl.tp3_qty_ratio}%)\n` +
    (tpsl.tp4_percent ? `  TP4=${tpsl.tp4_percent}% (${tpsl.tp4_qty_ratio}%)\n` : '') +
    (tpsl.tp5_percent ? `  TP5=${tpsl.tp5_percent}% (${tpsl.tp5_qty_ratio}%)\n` : '') +
    `  SL=${tpsl.stop_loss_percent_of_capital}%` +
    triggerSummary +
    capitalsSummary +
    stageCountNote +
    `\n\n※ 미발동 stage 만 trigger% / capital 변경 가능 (이미 진입한 단계는 보존).` +
    `\n※ 단계 수 변경: 줄이면 미발동 stage 삭제, 늘리면 신규 stage_plan 생성. current_stage 미만 X.` +
    `\n\n진행할까요?`;
  if (!confirm(confirmMsg)) return;
  const inplaceBtn = document.getElementById('cm-submit-inplace');
  const submit = document.getElementById('cm-submit');
  if (inplaceBtn) { inplaceBtn.disabled = true; inplaceBtn.textContent = '⏳ 갱신 중...'; }
  if (submit) submit.disabled = true;
  try {
    const body = { ...tpsl };
    // current_stage 조회 — 미발동 stage 만 값 보내고 발동된 stage 는 null 마스킹.
    let curStage = 0;
    if (inp && (inp.trigger_percents.length > 0 || inp.capitals.length > 0)) {
      try {
        const strategyInfo = await api(`/strategies/${editingId}`);
        curStage = Number(strategyInfo.current_stage || 0);
      } catch (e) {
        console.warn('Failed to fetch strategy.current_stage; sending all (backend will validate)', e);
      }
    }
    if (inp && inp.trigger_percents.length > 0) {
      // backend 는 capitals 와 trigger_percents 길이 일치 요구.
      // current_stage 이하는 null, 그 외는 값 (단계 수 변경 시 새 length 의 배열).
      body.trigger_percents = inp.trigger_percents.map((t, i) => {
        const stageNo = i + 1;
        if (stageNo <= curStage) return null;
        return t === null ? null : Number(t);
      });
    }
    if (inp && inp.capitals.length > 0) {
      // capitals 도 동일 패턴 — 발동된 stage 는 null, 신규/미발동은 양수.
      body.capitals = inp.capitals.map((c, i) => {
        const stageNo = i + 1;
        if (stageNo <= curStage) return null;
        return c === null || c === undefined ? null : Number(c);
      });
    }
    if (inp && inp.last_stage_trigger_percent != null) {
      body.last_stage_trigger_percent = Number(inp.last_stage_trigger_percent);
    }
    await api(`/strategies/${editingId}/settings`, {
      method: 'PATCH',
      body,
    });
    const changedParts = ['TP/SL'];
    if (inp && inp.trigger_percents.length > 0) changedParts.push('trigger%');
    if (inp && inp.capitals.length > 0) changedParts.push('capital');
    toast(`✅ 전략 #${editingId} 설정 갱신 완료 — ${changedParts.join(' + ')} 다음 tick 부터 적용`, 'success');
    closeCreateModal();
    refreshStrategies();
  } catch (e) {
    toast('설정 수정 실패: ' + e.message, 'error');
  } finally {
    if (inplaceBtn) { inplaceBtn.disabled = false; inplaceBtn.textContent = '↻ 설정만 수정'; }
    if (submit) submit.disabled = false;
  }
}
