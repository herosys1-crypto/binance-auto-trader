// 🚀 v133d (2026-08-13 사장님!): 급등락 실시간 진입 카드!
// = 5분 1.5%+ or 1h 3%+ 심볼 감지!
// = 30초마다 자동 새로고침!

(function() {
  'use strict';

  const TYPE_LABELS = {
    'pump_live': '🚀 5분 급등',
    'dump_live': '📉 5분 급락',
    'pump_1h': '🚀 1h 급등',
    'dump_1h': '📉 1h 급락',
  };

  async function scanLivePumpDump() {
    try {
      const data = await api('/live-pump-dump/scan?threshold_5m=1.5&threshold_1h=3');
      renderLivePumpDump(data);
    } catch (e) {
      console.warn('[live-pd] scan 실패:', e);
    }
  }

  function renderLivePumpDump(data) {
    const listEl = document.getElementById('live-pd-list');
    const countEl = document.getElementById('live-pd-count');
    if (!listEl || !countEl) return;

    const alerts = (data && data.alerts) || [];
    countEl.textContent = String(alerts.length);

    if (alerts.length === 0) {
      listEl.innerHTML = `
        <div class="text-xs text-slate-400 text-center py-3">
          🕰️ 실시간 급등락 심볼 = 지금 없음! (30초마다 자동 스캔!)
        </div>
      `;
      return;
    }

    const html = alerts.map((a, idx) => {
      const side = a.side || 'LONG';
      const sideColor = side === 'LONG' ? '#22c55e' : '#ef4444';
      const sideIcon = side === 'LONG' ? '🐂' : '🐻';
      const typeLabel = TYPE_LABELS[a.type] || a.type;
      const confPct = ((a.confidence || 0) * 100).toFixed(0);
      const rankIcon = idx === 0 ? '🥇' : idx === 1 ? '🥈' : idx === 2 ? '🥉' : `#${idx + 1}`;

      // 신뢰도 배지!
      let confBadge = '💧';
      let confColor = '#94a3b8';
      if (a.confidence >= 0.85) { confBadge = '🔥'; confColor = '#ef4444'; }
      else if (a.confidence >= 0.75) { confBadge = '⭐'; confColor = '#f59e0b'; }
      else if (a.confidence >= 0.65) { confBadge = '✨'; confColor = '#fbbf24'; }

      const change5m = a.change_5m !== null && a.change_5m !== undefined ? `${a.change_5m > 0 ? '+' : ''}${a.change_5m}%` : '-';
      const change1h = a.change_1h !== null && a.change_1h !== undefined ? `${a.change_1h > 0 ? '+' : ''}${a.change_1h}%` : '-';

      // 즉시 진입용 config!
      const cfg = {
        leverage: 2,
        capitals: [300, 500],
        trigger_percents: [null, 10],
        tp1_percent: 10, tp2_percent: 15, tp3_percent: 20, tp4_percent: 25,
        tp1_qty_ratio: 10, tp2_qty_ratio: 15, tp3_qty_ratio: 20, tp4_qty_ratio: 25,
        tp1_pct_override: 25,
        force_sl_enabled_override: true,
        force_sl_roi_override: 15,
        stop_loss_percent_of_capital: 90,
        start_price: null,
        symbol: a.symbol,
        side: side,
      };

      return `
        <div style="background:rgba(0,0,0,0.3);border:2px solid ${sideColor};border-radius:6px;padding:8px 10px;box-shadow:0 0 12px ${sideColor}66;animation:pulse 2s infinite;cursor:pointer"
             onclick="openSuggestionAnalysis('${a.symbol}', '${side}', 0)"
             title="클릭 = 상세 분석 새 창!">
          <div class="flex items-center justify-between mb-1">
            <span class="text-sm font-bold" style="color:${sideColor}">
              <span style="color:#c4b5fd;font-size:0.85em">${rankIcon}</span>
              ${sideIcon} ${a.symbol} ${side}
              <span class="text-xs text-slate-400 ml-1">| ${typeLabel}</span>
            </span>
            <span class="text-xs font-bold" style="color:${confColor}">
              ${confBadge} ${confPct}%
            </span>
          </div>
          <div class="text-xs text-slate-400 mb-1">
            📊 5분: <span style="color:${sideColor};font-weight:600">${change5m}</span>
            &nbsp;|&nbsp;
            1h: <span style="color:${sideColor}">${change1h}</span>
            &nbsp;|&nbsp;
            💰 ${a.price || '?'}
          </div>
          <div class="text-xs text-blue-300 mb-2" style="font-style:italic">
            💡 ${a.reason}
          </div>
          <div class="flex gap-2">
            <button onclick="event.stopPropagation();executeSuggestion(0, '${a.symbol}', '${side}', '${encodeURIComponent(JSON.stringify(cfg))}')"
                    class="text-xs font-bold px-3 py-1 rounded"
                    style="background:linear-gradient(135deg,#059669,#22c55e);color:#fff;border:0;cursor:pointer"
                    title="세팅 modal 열기 = 즉시 진입!">
              ▶ 즉시 진입
            </button>
            <button onclick="event.stopPropagation();openSuggestionAnalysis('${a.symbol}', '${side}', 0)"
                    class="text-xs font-bold px-3 py-1 rounded"
                    style="background:linear-gradient(135deg,#3b82f6,#8b5cf6);color:#fff;border:0;cursor:pointer">
              📊 상세 분석
            </button>
          </div>
        </div>
      `;
    }).join('');

    listEl.innerHTML = html;
  }

  if (typeof window !== 'undefined') {
    window.scanLivePumpDump = scanLivePumpDump;
    document.addEventListener('DOMContentLoaded', () => {
      setTimeout(scanLivePumpDump, 2000);  // 초기 로드 = 2초 후!
      setInterval(scanLivePumpDump, 60000);  // 60초 폴링 (API 부담!)
    });
  }
})();
