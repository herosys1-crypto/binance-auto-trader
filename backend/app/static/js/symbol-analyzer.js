// 🔎 v134a (2026-08-13 사장님!): 심볼 분석기!
// = 심볼 수동 입력 → 즉시 분석 새 창!
// = 활성 포지션 quick 버튼 → 즉시 분석 새 창!

(function() {
  'use strict';

  // 수동 입력 = 심볼 분석!
  function analyzeSymbolNow() {
    const inputEl = document.getElementById('sym-analyze-input');
    const sideEl = document.getElementById('sym-analyze-side');
    if (!inputEl || !sideEl) return;

    let symbol = (inputEl.value || '').trim().toUpperCase();
    if (!symbol) {
      if (typeof toast === 'function') toast('❌ 심볼 입력 필요!', 'error');
      return;
    }
    // USDT 자동 추가!
    if (!symbol.endsWith('USDT') && !symbol.includes('/')) {
      symbol = symbol + 'USDT';
    }

    const side = sideEl.value || 'LONG';
    const url = `/static/analysis.html?symbol=${encodeURIComponent(symbol)}&side=${side}`;
    window.open(url, '_blank', 'width=550,height=700,scrollbars=yes');
  }

  // 활성 포지션 심볼 quick 버튼 로드!
  async function loadActiveSymbolsForAnalyzer() {
    const listEl = document.getElementById('sym-active-list');
    if (!listEl) return;

    try {
      const strategies = await api('/strategies?limit=200');
      const openStatuses = new Set([
        'STAGE_1_OPEN', 'STAGE_2_OPEN', 'STAGE_3_OPEN',
        'STAGE_4_OPEN', 'STAGE_5_OPEN', 'STAGE_6_OPEN',
        'STAGE_7_OPEN', 'STAGE_8_OPEN', 'STAGE_9_OPEN',
        'STAGE_10_OPEN',
      ]);
      // 활성 = position != 0 + open status!
      const active = (Array.isArray(strategies) ? strategies : []).filter(s => {
        const qty = Number(s.current_position_qty || 0);
        return openStatuses.has(s.status) && Math.abs(qty) > 0;
      });

      if (active.length === 0) {
        listEl.innerHTML = '<span class="text-xs text-slate-500">활성 포지션 없음</span>';
        return;
      }

      const html = active.map(s => {
        const sideColor = s.side === 'LONG' ? '#22c55e' : '#ef4444';
        const sideIcon = s.side === 'LONG' ? '🐂' : '🐻';
        // 🚨 v147b fix: `/strategies` 응답에는 unrealized_pnl_pct 가 **없습니다**.
        //    옛 코드 `Number(s.unrealized_pnl_pct || 0)` = 모든 심볼이 항상 **+0.0%** 로 표시됨
        //    (= 사장님이 「다 본전이네」로 오해할 수 있는 silent bug)
        //    → strategies-list.js 가 채우는 Binance 실시간 포지션 캐시에서 roi_pct 를 읽고,
        //      없으면 숫자를 **지어내지 말고 '-'** 로 표시합니다.
        const _acct = (window._binancePositionsCache || {})[s.exchange_account_id] || {};
        const _bp = (_acct.positions || {})[s.symbol];
        const pnl = (_bp && _bp.roi_pct !== null && _bp.roi_pct !== undefined)
          ? Number(_bp.roi_pct) : null;
        const hasPnl = pnl !== null && isFinite(pnl);
        const pnlColor = !hasPnl ? '#94a3b8' : (pnl >= 0 ? '#22c55e' : '#ef4444');
        const pnlText = !hasPnl ? '-' : `${pnl >= 0 ? '+' : ''}${pnl.toFixed(1)}%`;
        return `
          <button onclick="openActiveStrategyAnalysis(${s.id}, '${s.symbol}', '${s.side}')"
                  style="background:rgba(0,0,0,0.4);border:1px solid ${sideColor};color:#fff;padding:3px 8px;border-radius:4px;font-size:11px;cursor:pointer"
                  title="클릭 = 활성 전략 상세 분석 새 창!">
            ${sideIcon} <span style="font-weight:600">${s.symbol}</span>
            <span style="color:${pnlColor};margin-left:4px">${pnlText}</span>
          </button>
        `;
      }).join('');

      listEl.innerHTML = html;
    } catch (e) {
      console.warn('[symbol-analyzer] active 로드 실패:', e);
      listEl.innerHTML = '<span class="text-xs text-slate-500">로드 실패</span>';
    }
  }

  // 활성 전략 = 상세 분석 새 창!
  function openActiveStrategyAnalysis(strategyId, symbol, side) {
    const url = `/static/analysis.html?strategy_id=${strategyId}&symbol=${encodeURIComponent(symbol)}&side=${side}`;
    window.open(url, '_blank', 'width=550,height=700,scrollbars=yes');
  }

  // 🔎 v134c: 신 전략 modal의 심볼 + 방향 = 즉시 분석!
  function openCreateModalAnalysis() {
    try {
      const symInput = document.getElementById('cm-symbol');
      let symbol = symInput ? (symInput.value || '').trim().toUpperCase() : '';
      if (!symbol) {
        if (typeof toast === 'function') toast('❌ 심볼 입력 필요!', 'error');
        return;
      }
      if (!symbol.endsWith('USDT') && !symbol.includes('/')) {
        symbol = symbol + 'USDT';
      }
      // side = cmState.side (cm-state-helpers.js!)
      let side = 'LONG';
      try {
        if (typeof window.cmState !== 'undefined' && window.cmState.side) {
          side = window.cmState.side;
        }
      } catch (_e) { /* fallback = LONG */ }

      const url = `/static/analysis.html?symbol=${encodeURIComponent(symbol)}&side=${side}`;
      window.open(url, '_blank', 'width=550,height=700,scrollbars=yes');
    } catch (e) {
      console.warn('[create-modal] analysis 열기 실패:', e);
    }
  }

  // 🌟 v134d: analysis.html에서 호출 = 새 전략 modal 자동 열기 + symbol/side fill!
  async function openCreateModalWithSymbol(symbol, side) {
    try {
      if (typeof window.openCreateModal !== 'function') {
        console.warn('[openCreateModalWithSymbol] openCreateModal 없음!');
        return;
      }
      // 1. 새 전략 modal 열기!
      await window.openCreateModal();
      // 2. 지연 후 = symbol + side 세팅! (modal DOM ready 대기!)
      setTimeout(() => {
        try {
          const symInput = document.getElementById('cm-symbol');
          if (symInput) {
            symInput.value = (symbol || '').toUpperCase();
            // change/input 이벤트 발생 = validation trigger!
            symInput.dispatchEvent(new Event('change', { bubbles: true }));
            symInput.dispatchEvent(new Event('input', { bubbles: true }));
          }
          // side 설정!
          if (typeof window.setCmSide === 'function' && side) {
            window.setCmSide(side.toUpperCase());
          }
          // 시장 정보 로드!
          if (typeof window.loadCmMarketInfo === 'function') {
            window.loadCmMarketInfo();
          }
          // toast!
          if (typeof window.toast === 'function') {
            window.toast(`✅ 분석 완료 심볼 자동 fill: ${symbol} ${side}`, 'success');
          }
        } catch (e) {
          console.warn('[openCreateModalWithSymbol] fill 실패:', e);
        }
      }, 500);
    } catch (e) {
      console.warn('[openCreateModalWithSymbol] modal 열기 실패:', e);
    }
  }

  // 🌟 v134f: postMessage listener = 분석 창의 「세팅 후 진입」 자동 처리!
  function _handleCreateModalMessage(event) {
    try {
      const data = event && event.data;
      if (!data || data.type !== 'CREATE_MODAL_WITH_SYMBOL') return;
      const sym = data.symbol;
      const side = data.side || 'LONG';
      if (!sym) return;
      openCreateModalWithSymbol(sym, side);
    } catch (e) {
      console.warn('[postMessage] handler 실패:', e);
    }
  }

  // 🌟 v134f: localStorage 감지 = 페이지 로드 시 = pendingCreateModal 자동 처리!
  function _checkPendingCreateModal() {
    try {
      const raw = localStorage.getItem('pendingCreateModal');
      if (!raw) return;
      const data = JSON.parse(raw);
      // 5분 이내만 처리!
      if (!data || !data.symbol || (Date.now() - (data.ts || 0)) > 5 * 60 * 1000) {
        localStorage.removeItem('pendingCreateModal');
        return;
      }
      // 삭제 후 처리 (중복 방지!)
      localStorage.removeItem('pendingCreateModal');
      openCreateModalWithSymbol(data.symbol, data.side || 'LONG');
    } catch (e) {
      console.warn('[pendingCreateModal] 처리 실패:', e);
    }
  }

  if (typeof window !== 'undefined') {
    window.analyzeSymbolNow = analyzeSymbolNow;
    window.loadActiveSymbolsForAnalyzer = loadActiveSymbolsForAnalyzer;
    window.openActiveStrategyAnalysis = openActiveStrategyAnalysis;
    window.openCreateModalAnalysis = openCreateModalAnalysis;  // 🔎 v134c!
    window.openCreateModalWithSymbol = openCreateModalWithSymbol;  // 🌟 v134d!
    // postMessage listener = 항상 등록! (v134f 3중 안전!)
    window.addEventListener('message', _handleCreateModalMessage);
    document.addEventListener('DOMContentLoaded', () => {
      setTimeout(loadActiveSymbolsForAnalyzer, 2500);
      setInterval(loadActiveSymbolsForAnalyzer, 60000);  // 60초마다 새로고침!
      // 페이지 로드 시 = localStorage pending 확인!
      setTimeout(_checkPendingCreateModal, 1500);
    });
  }
})();
