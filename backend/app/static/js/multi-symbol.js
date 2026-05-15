/**
 * 「📦 다중 심볼 모드」 — Phase 3 추가 분리 (2026-05-14).
 *
 * 사용자 UX (2026-05-12): 「+ 새 전략」 모달 한 곳에서 단일/다중 심볼 둘 다 자연스럽게 선택.
 * Chip 방식 1개씩 추가 + 즉시 비동기 검증 (v3 — 사용자 UX 요청).
 *
 * 함수:
 *   - toggleMultiSymbolMode()       : 단일 ↔ 다중 모드 토글 (UI + state)
 *   - addSymbolChip()                : 입력 → chip 추가 + 비동기 /symbols/{sym} 검증
 *   - removeSymbolChip(symbol)       : chip 제거
 *   - _renderMultiSymbolChips()       : chip 영역 렌더 + summary
 *   - submitCreateMulti()            : ✓ valid 심볼 모두에 strategy 동시 생성 (batch)
 *   - _refreshSubmitBtnLabel()        : submit 버튼 텍스트 갱신 (multi/single 차별)
 *
 * 외부 의존성 (index.html 의 create-modal 섹션 또는 기타 모듈):
 *   - cmState                         : create-modal 의 전역 state (let)
 *   - updateCmSubmit()                : submit 버튼 disable/enable
 *   - _collectTpSl()                  : TP/SL 입력 수집
 *   - _collectDirectInputs()          : direct 모드 입력 수집
 *   - _defaultLeverageForSide(side)   : 기본 leverage
 *   - closeCreateModal()              : 모달 닫기
 *   - refreshStrategies / refreshTemplates : 목록 갱신
 *   - api / toast                     : /static/js/api.js
 *   - escapeHtml / fmtNum             : /static/js/helpers.js
 *
 * State (전역 — script-scope 공유):
 *   - _cmMultiSymbols : [{symbol, status: 'valid'|'invalid'|'pending', reason}]
 */

let _cmMultiSymbols = [];  // [{symbol, status: 'valid'|'invalid'|'pending', reason}]

function toggleMultiSymbolMode() {
  const isMulti = document.getElementById('cm-multi-symbol-toggle').checked;
  const single = document.getElementById('cm-symbol');
  const container = document.getElementById('cm-multi-container');
  const preview = document.getElementById('cm-multi-preview');
  const countLabel = document.getElementById('cm-symbol-count');
  // 2026-05-12 (사용자 UX): 시작가 영역 안내문도 모드별 변경.
  const startPriceLabel = document.getElementById('cm-start-price-mode-label');
  const startPriceHint = document.getElementById('cm-start-price-hint');
  if (isMulti) {
    single.classList.add('hidden');
    container.classList.remove('hidden');
    preview.classList.remove('hidden');
    countLabel.classList.remove('hidden');
    _cmMultiSymbols = [];
    _renderMultiSymbolChips();
    if (startPriceLabel) startPriceLabel.textContent = '(다중 모드 — 미리보기용 첫 심볼 가격 자동 채움)';
    if (startPriceHint) startPriceHint.innerHTML = '<span class="text-blue-300">📦 다중 모드: 시작가는 각 심볼 현재가가 자동 적용됩니다 (SHORT +0.1% / LONG -0.1%). 미리보기 클릭 시 첫 ✓ 심볼 기준 계산.</span>';
  } else {
    single.classList.remove('hidden');
    container.classList.add('hidden');
    preview.classList.add('hidden');
    countLabel.classList.add('hidden');
    _cmMultiSymbols = [];
    if (startPriceLabel) startPriceLabel.textContent = '(LIMIT 1단계 가격)';
    if (startPriceHint) startPriceHint.textContent = 'SHORT: 현재가보다 약간 위 / LONG: 현재가보다 약간 아래 추천 (위 버튼으로 자동 채움 가능)';
  }
  _refreshSubmitBtnLabel();
  updateCmSubmit();
}

async function addSymbolChip() {
  const input = document.getElementById('cm-multi-add-input');
  const raw = (input.value || '').toUpperCase().trim();
  if (!raw) return;
  if (_cmMultiSymbols.find(s => s.symbol === raw)) {
    toast(`${raw} 이미 추가됨`, 'warning');
    input.value = '';
    return;
  }
  if (_cmMultiSymbols.length >= 50) {
    toast('최대 50개', 'error');
    return;
  }
  // pending 상태로 즉시 추가 (UI 즉시 반영)
  _cmMultiSymbols.push({ symbol: raw, status: 'pending', reason: '검증 중...' });
  input.value = '';
  _renderMultiSymbolChips();
  _refreshSubmitBtnLabel();
  updateCmSubmit();
  // 비동기 검증 — /symbols/{symbol} 호출 (404 면 invalid)
  try {
    const symInfo = await api(`/symbols/${raw}`);
    const idx = _cmMultiSymbols.findIndex(s => s.symbol === raw);
    if (idx < 0) return;  // 사용자가 그 사이 제거
    if (symInfo && symInfo.symbol === raw) {
      _cmMultiSymbols[idx] = { symbol: raw, status: 'valid', reason: '거래소 등록 OK' };
    } else {
      _cmMultiSymbols[idx] = { symbol: raw, status: 'invalid', reason: '심볼 정보 응답 이상' };
    }
  } catch (e) {
    const idx = _cmMultiSymbols.findIndex(s => s.symbol === raw);
    if (idx < 0) return;
    const errMsg = String(e.message || '');
    const reason = errMsg.includes('404') || errMsg.toLowerCase().includes('not found')
      ? '거래소에 없는 심볼' : errMsg.slice(0, 80);
    _cmMultiSymbols[idx] = { symbol: raw, status: 'invalid', reason };
  }
  _renderMultiSymbolChips();
  _refreshSubmitBtnLabel();
  updateCmSubmit();
  input.focus();  // 다음 심볼 입력 위해 포커스 유지
}

function removeSymbolChip(symbol) {
  _cmMultiSymbols = _cmMultiSymbols.filter(s => s.symbol !== symbol);
  _renderMultiSymbolChips();
  _refreshSubmitBtnLabel();
  updateCmSubmit();
}

function _renderMultiSymbolChips() {
  const container = document.getElementById('cm-multi-chips');
  if (!container) return;
  if (!_cmMultiSymbols.length) {
    container.innerHTML = '<span class="text-slate-500 text-xs italic">아직 추가된 심볼이 없습니다 — 아래에서 입력</span>';
  } else {
    container.innerHTML = _cmMultiSymbols.map(s => {
      const cls = s.status === 'valid' ? 'bg-green-900 border-green-600 text-green-200'
                : s.status === 'invalid' ? 'bg-red-900 border-red-600 text-red-200'
                : 'bg-slate-700 border-slate-500 text-slate-300';
      const ic = s.status === 'valid' ? '✓' : s.status === 'invalid' ? '✗' : '⏳';
      return `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded border text-xs ${cls}" title="${escapeHtml(s.reason)}">
        <span>${ic}</span>
        <span class="font-mono">${escapeHtml(s.symbol)}</span>
        <button onclick="removeSymbolChip('${escapeHtml(s.symbol).replace(/'/g, "\\'")}')" class="hover:text-white" style="font-weight:bold" title="제거">×</button>
      </span>`;
    }).join('');
  }
  const validCount = _cmMultiSymbols.filter(s => s.status === 'valid').length;
  const invalidCount = _cmMultiSymbols.filter(s => s.status === 'invalid').length;
  const pendingCount = _cmMultiSymbols.filter(s => s.status === 'pending').length;
  const previewEl = document.getElementById('cm-multi-preview');
  if (previewEl) {
    previewEl.innerHTML = _cmMultiSymbols.length === 0
      ? '<span class="text-slate-500">심볼 추가하세요</span>'
      : `<span class="text-green-400">✓ ${validCount} 유효</span> · <span class="text-red-400">✗ ${invalidCount} 무효</span>${pendingCount ? ` · <span class="text-slate-400">⏳ ${pendingCount} 검증중</span>` : ''} <span class="text-slate-500">(전략 시작 시 ✓ 만 사용)</span>`;
  }
}

async function submitCreateMulti() {
  // 다중 심볼 모드 — chip 검증된 ✓ valid 심볼만 사용 (사용자 UX v3, 2026-05-12)
  const symbols = _cmMultiSymbols.filter(s => s.status === 'valid').map(s => s.symbol);
  if (!symbols.length) { toast('✓ 유효한 심볼이 1개 이상 필요 (chip 으로 추가 + 검증)', 'error'); return; }
  if (symbols.length > 50) { toast('한 번에 최대 50개', 'error'); return; }
  if (!cmState.accountId) { toast('거래소 계정 선택 필요', 'error'); return; }
  // template 결정: template 모드면 cmState.templateId 사용, direct/prev 면 _quick_ 자동 생성.
  let templateId = cmState.templateId;
  const lvInpEl = document.getElementById('cm-leverage');
  const leverageFromInput = lvInpEl && lvInpEl.value ? Number(lvInpEl.value) : _defaultLeverageForSide(cmState.side);
  if (cmState.mode === 'direct') {
    // direct 모드 → _quick_ 자동 생성 (단일 모드와 동일 패턴)
    try {
      const ts = new Date().toISOString().replace(/[^0-9]/g, '').slice(0, 14);
      const inp = cmState._directInputs || _collectDirectInputs();
      const tpsl = cmState._directTpsl || _collectTpSl();
      const _tpFields = {};
      for (let n = 1; n <= 10; n++) {
        _tpFields[`tp${n}_percent`] = tpsl[`tp${n}_percent`];
        _tpFields[`tp${n}_qty_ratio`] = tpsl[`tp${n}_qty_ratio`];
      }
      const tplCreated = await api('/admin/strategy-templates', {
        method: 'POST',
        body: {
          name: `_quick_${ts}`,
          strategy_type: cmState.side === 'SHORT' ? 'DYNAMIC_SHORT' : 'DYNAMIC_LONG',
          side: cmState.side, leverage: leverageFromInput,
          capitals: inp.capitals, trigger_percents: inp.trigger_percents,
          additional_margins: inp.additional_margins,
          last_stage_trigger_percent: inp.last_stage_trigger_percent,
          ..._tpFields,
          stop_loss_percent_of_capital: tpsl.stop_loss_percent_of_capital,
          crisis_max_loss_threshold: tpsl.crisis_max_loss_threshold,
          reentry_policy: 'manual_ready',
        },
      });
      templateId = tplCreated.id;
    } catch (e) { toast('템플릿 자동 생성 실패: ' + e.message, 'error'); return; }
  } else if (cmState.mode === 'template' && !templateId) {
    toast('「📋 템플릿 선택」 모드에서 템플릿을 먼저 선택하세요', 'error');
    return;
  } else if (cmState.mode === 'prev' && !templateId) {
    toast('「📂 이전 전략 불러오기」 모드는 직접 입력으로 자동 전환되니 다시 시도하세요', 'error');
    return;
  }
  // 시작가 결정 모드 (현재가 기준 약간 위/아래 — SHORT/LONG 진입 유리)
  const offsetPct = cmState.side === 'SHORT' ? 0.001 : -0.001;  // SHORT: +0.1% / LONG: -0.1%
  const confirmMsg = `🚀 ${symbols.length}개 심볼에 동시 전략 시작\n\n` +
    `심볼: ${symbols.join(', ')}\n` +
    `방향: ${cmState.side === 'SHORT' ? '📉 숏' : '📈 롱'}\n` +
    `레버리지: ${leverageFromInput}x\n` +
    `시작가: 각 심볼 현재가 ${offsetPct > 0 ? '+' : ''}${(offsetPct*100).toFixed(2)}% (${cmState.side === 'SHORT' ? 'SHORT' : 'LONG'} 진입 유리)\n\n` +
    `각 심볼당 1개 strategy 생성 → 1단계 LIMIT 발사. 진행할까요? (testnet 거래소면 실거래 발생)`;
  if (!confirm(confirmMsg)) return;
  const submit = document.getElementById('cm-submit');
  submit.disabled = true;
  submit.textContent = '⏳ 진행 중...';
  // 2026-05-12 v3 (사용자 보고 「성공인데 전략 없음」): 진행 표시를 modal 내 별도 영역에
  // 강조 표시 (cm-balance-check 는 미리보기 잔액 체크용이라 조용히 묻힘 가능).
  // 모달 footer 위에 명시적 결과 패널 만들기.
  let progEl = document.getElementById('cm-batch-progress');
  if (!progEl) {
    progEl = document.createElement('div');
    progEl.id = 'cm-batch-progress';
    progEl.className = 'mt-3 p-3 rounded border border-blue-700 bg-slate-900 text-xs';
    // 모달 footer 의 위 (취소/저장/시작 버튼 위) 에 삽입
    const footerBtnRow = document.querySelector('#create-modal .flex.justify-end.gap-2.pt-3');
    if (footerBtnRow) footerBtnRow.parentNode.insertBefore(progEl, footerBtnRow);
  }
  progEl.style.display = 'block';
  progEl.innerHTML = '<div class="text-slate-400">⏳ 진행 중...</div>';
  console.log('[batch] start', { symbols, templateId, side: cmState.side, accountId: cmState.accountId, leverage: leverageFromInput });
  const results = [];
  for (let i = 0; i < symbols.length; i++) {
    const sym = symbols[i];
    try {
      const tickerData = await api(`/market/ticker?symbol=${sym}&testnet=true`).catch(() => null);
      const lastPrice = tickerData && tickerData.lastPrice ? Number(tickerData.lastPrice) : null;
      if (!lastPrice || lastPrice <= 0) {
        results.push({ symbol: sym, status: 'fail', message: '현재가 조회 실패 (심볼 invalid?)' });
      } else {
        const startPrice = lastPrice * (1 + offsetPct);
        console.log(`[batch] ${sym} POST /strategies`, { exchange_account_id: cmState.accountId, strategy_template_id: templateId, side: cmState.side, start_price: String(startPrice) });
        let created;
        try {
          created = await api('/strategies', {
            method: 'POST',
            body: {
              exchange_account_id: cmState.accountId,
              strategy_template_id: templateId,
              symbol: sym, side: cmState.side, start_price: String(startPrice),
              leverage_override: leverageFromInput,
            },
          });
          console.log(`[batch] ${sym} created`, created);
        } catch (createErr) {
          console.error(`[batch] ${sym} create failed`, createErr);
          results.push({ symbol: sym, status: 'fail', message: `생성 실패: ${createErr.message}` });
          continue;  // start 시도 안 함
        }
        try {
          await api(`/strategies/${created.id}/start`, { method: 'POST' });
          console.log(`[batch] ${sym} #${created.id} started`);
          results.push({ symbol: sym, status: 'ok', strategy_id: created.id, message: `#${created.id} 시작 완료 (시작가 ${fmtNum(startPrice)})` });
        } catch (startErr) {
          console.error(`[batch] ${sym} #${created.id} start failed`, startErr);
          results.push({ symbol: sym, status: 'partial', strategy_id: created.id, message: `#${created.id} 생성 — 시작 실패: ${startErr.message}` });
        }
      }
    } catch (e) {
      console.error(`[batch] ${sym} unexpected error`, e);
      results.push({ symbol: sym, status: 'fail', message: e.message });
    }
    // 진행 갱신 (강조 색상)
    const okN = results.filter(r => r.status === 'ok').length;
    const failN = results.filter(r => r.status === 'fail').length;
    const partN = results.filter(r => r.status === 'partial').length;
    progEl.innerHTML = `<div class="font-semibold mb-2 text-blue-300">📦 다중 전략 생성 진행 ${i+1}/${symbols.length}</div>
      <div class="mb-2"><span class="text-green-400">✅ ${okN} 성공</span> · <span class="text-yellow-400">⚠️ ${partN} 부분</span> · <span class="text-red-400">❌ ${failN} 실패</span></div>` +
      results.map(r => {
        const ic = r.status === 'ok' ? '✅' : r.status === 'partial' ? '⚠️' : '❌';
        const cls = r.status === 'ok' ? 'text-green-300' : r.status === 'partial' ? 'text-yellow-300' : 'text-red-300';
        return `<div class="${cls}">${ic} ${escapeHtml(r.symbol)}: ${escapeHtml(r.message)}</div>`;
      }).join('');
  }
  submit.disabled = false;
  _refreshSubmitBtnLabel();
  refreshStrategies();
  refreshTemplates();
  const ok = results.filter(r => r.status === 'ok').length;
  const failTotal = results.filter(r => r.status === 'fail').length;
  const partial = results.filter(r => r.status === 'partial').length;
  // 명확한 토스트 메시지
  let toastMsg, toastType;
  if (ok === symbols.length) {
    toastMsg = `🚀 batch 완료: ${ok}/${symbols.length} 모두 성공 — 「🎯 전략 인스턴스」 패널 확인`;
    toastType = 'success';
  } else if (ok > 0) {
    toastMsg = `⚠️ batch 부분 성공: ${ok}/${symbols.length} (실패 ${failTotal}, 부분 ${partial}). 위 결과 패널 확인`;
    toastType = 'warning';
  } else {
    toastMsg = `❌ batch 실패: 0/${symbols.length} 성공 — 위 결과 패널에서 에러 메시지 확인`;
    toastType = 'error';
  }
  toast(toastMsg, toastType);
  // 모두 성공이면 모달 자동 닫기 (실패 있으면 사용자가 결과 확인 후 직접 닫음)
  if (ok === symbols.length) setTimeout(closeCreateModal, 2500);
}

function _refreshSubmitBtnLabel() {
  // 라벨 (text) 만 업데이트 — disabled 는 updateCmSubmit() 가 단독 관리.
  const submit = document.getElementById('cm-submit');
  if (!submit || cmState.editingStrategyId) return;  // 수정 모드는 별도 라벨
  const isMulti = document.getElementById('cm-multi-symbol-toggle')?.checked;
  if (isMulti) {
    const validCount = (typeof _cmMultiSymbols !== 'undefined' ? _cmMultiSymbols.filter(s => s.status === 'valid').length : 0);
    submit.textContent = validCount > 1
      ? `🚀 ${validCount}개 전략 동시 시작`
      : validCount === 1
        ? '🚀 1개 전략 시작'
        : '🚀 ✓ 유효 심볼 추가 필요';
  } else {
    submit.textContent = '🚀 전략 시작';
  }
}
