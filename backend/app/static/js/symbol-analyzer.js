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
        const pnl = Number(s.unrealized_pnl_pct || 0);
        const pnlColor = pnl >= 0 ? '#22c55e' : '#ef4444';
        const pnlSign = pnl >= 0 ? '+' : '';
        return `
          <button onclick="openActiveStrategyAnalysis(${s.id}, '${s.symbol}', '${s.side}')"
                  style="background:rgba(0,0,0,0.4);border:1px solid ${sideColor};color:#fff;padding:3px 8px;border-radius:4px;font-size:11px;cursor:pointer"
                  title="클릭 = 활성 전략 상세 분석 새 창!">
            ${sideIcon} <span style="font-weight:600">${s.symbol}</span>
            <span style="color:${pnlColor};margin-left:4px">${pnlSign}${pnl.toFixed(1)}%</span>
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

  if (typeof window !== 'undefined') {
    window.analyzeSymbolNow = analyzeSymbolNow;
    window.loadActiveSymbolsForAnalyzer = loadActiveSymbolsForAnalyzer;
    window.openActiveStrategyAnalysis = openActiveStrategyAnalysis;
    window.openCreateModalAnalysis = openCreateModalAnalysis;  // 🔎 v134c!
    window.openCreateModalWithSymbol = openCreateModalWithSymbol;  // 🌟 v134d!
    document.addEventListener('DOMContentLoaded', () => {
      setTimeout(loadActiveSymbolsForAnalyzer, 2500);
      setInterval(loadActiveSymbolsForAnalyzer, 60000);  // 60초마다 새로고침!
    });
  }
})();
