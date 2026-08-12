// 🎓 v134 (2026-08-13 사장님!): TP/SL 조정 제안 + 학습 통계!
// = 활성 전략 = 심볼 흐름 분석 → 조정 제안!
// = 사장님 선택 = 조정! (차후 자동!)

(function() {
  'use strict';

  const KIND_COLORS = {
    'TP_DOWN': '#22c55e',
    'TP_UP': '#22c55e',
    'TRAIL_STRENGTHEN': '#f59e0b',
    'SL_REVIEW': '#ef4444',
  };

  const KIND_ICONS = {
    'TP_DOWN': '📉',
    'TP_UP': '📈',
    'TRAIL_STRENGTHEN': '🎯',
    'SL_REVIEW': '🚨',
  };

  async function scanTpSlAdvisor() {
    try {
      const data = await api('/trade-learning/tp-sl-advisor/scan');
      renderTpSlAdvisor(data);
    } catch (e) {
      console.warn('[tp-sl-advisor] scan 실패:', e);
    }
  }

  function renderTpSlAdvisor(data) {
    const listEl = document.getElementById('tp-sl-adv-list');
    const countEl = document.getElementById('tp-sl-adv-count');
    if (!listEl || !countEl) return;

    const suggestions = (data && data.suggestions) || [];
    countEl.textContent = String(suggestions.length);

    if (suggestions.length === 0) {
      listEl.innerHTML = `
        <div class="text-xs text-slate-400 text-center py-3">
          ✅ 현재 = 조정 제안 없음! (활성 포지션 = 정상 흐름!)
        </div>
      `;
      return;
    }

    const html = suggestions.map(s => {
      const sideColor = s.side === 'LONG' ? '#22c55e' : '#ef4444';
      const sideIcon = s.side === 'LONG' ? '🐂' : '🐻';
      const pnlColor = s.pnl_pct >= 0 ? '#22c55e' : '#ef4444';
      const pnlSign = s.pnl_pct >= 0 ? '+' : '';

      const proposalsHtml = (s.proposals || []).map(p => {
        const kColor = KIND_COLORS[p.kind] || '#94a3b8';
        const kIcon = KIND_ICONS[p.kind] || '💡';
        return `
          <div style="border-left:3px solid ${kColor};padding:4px 8px;margin:4px 0;background:rgba(0,0,0,0.2)">
            <div class="text-xs" style="color:${kColor};font-weight:600">${kIcon} ${p.kind}</div>
            <div class="text-xs text-slate-300 mt-1">${p.reason}</div>
            <div class="text-xs text-blue-300 mt-1">💡 ${p.action}</div>
          </div>
        `;
      }).join('');

      return `
        <div style="background:rgba(0,0,0,0.3);border:1px solid ${sideColor};border-radius:6px;padding:8px 10px;cursor:pointer"
             onclick="openStrategyAnalysis(${s.strategy_id}, '${s.symbol}', '${s.side}')"
             title="클릭 = 활성 전략 상세 분석 새 창!">
          <div class="flex items-center justify-between mb-1">
            <span class="text-sm font-bold" style="color:${sideColor}">
              ${sideIcon} ${s.symbol} ${s.side}
              <span class="text-xs text-slate-400 ml-1">| #${s.strategy_id} | ${s.status}</span>
            </span>
            <span class="text-xs font-bold" style="color:${pnlColor}">
              ${pnlSign}${s.pnl_pct.toFixed(2)}%
              <span class="text-xs text-slate-400 ml-1">(피크 +${s.max_profit_pct.toFixed(1)}%)</span>
            </span>
          </div>
          ${proposalsHtml}
          <div class="mt-2">
            <button onclick="event.stopPropagation();openStrategyAnalysis(${s.strategy_id}, '${s.symbol}', '${s.side}')"
                    class="text-xs font-bold px-3 py-1 rounded"
                    style="background:linear-gradient(135deg,#3b82f6,#8b5cf6);color:#fff;border:0;cursor:pointer">
              📊 상세 분석 + 조치
            </button>
          </div>
        </div>
      `;
    }).join('');

    listEl.innerHTML = html;
  }

  // 활성 전략 = 새 창 상세 분석!
  function openStrategyAnalysis(strategyId, symbol, side) {
    const url = `/static/analysis.html?strategy_id=${strategyId}&symbol=${encodeURIComponent(symbol)}&side=${side}`;
    window.open(url, '_blank', 'width=800,height=900,scrollbars=yes');
  }

  async function loadLearningSummary() {
    const el = document.getElementById('learning-summary');
    if (!el) return;
    try {
      const data = await api('/trade-learning/summary?days=30');
      const winPct = data.win_rate || 0;
      const winColor = winPct >= 60 ? '#22c55e' : winPct >= 40 ? '#fbbf24' : '#ef4444';
      const pnlColor = (data.total_pnl_pct || 0) >= 0 ? '#22c55e' : '#ef4444';
      const pnlSign = (data.total_pnl_pct || 0) >= 0 ? '+' : '';

      let html = `
        <div style="border-top:1px solid #334155;padding-top:8px">
          <div style="color:#a78bfa;font-weight:600;margin-bottom:4px">🎓 최근 30일 학습 통계</div>
          <div>총 거래: <span style="color:#fff">${data.total}</span> | 승률: <span style="color:${winColor}">${winPct}%</span> | 누적 PnL: <span style="color:${pnlColor}">${pnlSign}${data.total_pnl_pct}%</span></div>
          <div>승 ${data.wins} / 패 ${data.losses} / 무 ${data.breakeven} | 평균: <span style="color:${pnlColor}">${pnlSign}${data.avg_pnl_pct}%</span></div>
      `;
      if (data.top_symbols && data.top_symbols.length > 0) {
        html += '<div style="margin-top:4px;color:#c4b5fd">📊 TOP 심볼:</div>';
        data.top_symbols.slice(0, 5).forEach(t => {
          const color = t.total_pnl_pct >= 0 ? '#22c55e' : '#ef4444';
          const sign = t.total_pnl_pct >= 0 ? '+' : '';
          html += `<div>&nbsp;&nbsp;${t.symbol}: ${t.count}건 / 승률 ${t.win_rate}% / <span style="color:${color}">${sign}${t.total_pnl_pct}%</span></div>`;
        });
      }
      html += '</div>';
      el.innerHTML = html;
      el.style.display = 'block';
    } catch (e) {
      console.warn('[learning] summary 실패:', e);
      el.innerHTML = '<div style="color:#ef4444">학습 통계 로드 실패!</div>';
      el.style.display = 'block';
    }
  }

  if (typeof window !== 'undefined') {
    window.scanTpSlAdvisor = scanTpSlAdvisor;
    window.openStrategyAnalysis = openStrategyAnalysis;
    window.loadLearningSummary = loadLearningSummary;
    document.addEventListener('DOMContentLoaded', () => {
      setTimeout(scanTpSlAdvisor, 3000);
      setInterval(scanTpSlAdvisor, 120000);  // 2분마다!
    });
  }
})();
