// ⚖ v159 사장님 (2026-08-16): BB 중단 ±5% + 당일 최고 상승 순!
// 사장님: "15분 4시간봉 볼밴 중단 5% 아래위 종목을 당일 최고상승이 높은 순으로!"

(function() {
  'use strict';

  let _currentInterval = '4h';

  async function scanBBMiddle(interval = '4h') {
    _currentInterval = interval;
    try {
      const data = await api(`/bb-middle-scan/scan?interval=${interval}&proximity_pct=5&max_symbols=100`);
      renderBBMiddle(data);
    } catch (e) {
      console.warn('[bb-middle-scan] 실패:', e);
    }
  }

  function renderBBMiddle(data) {
    const listEl = document.getElementById('bb-middle-list');
    const countEl = document.getElementById('bb-middle-count');
    if (!listEl || !countEl) return;

    const symbols = (data && data.symbols) || [];
    countEl.textContent = String(symbols.length);

    if (symbols.length === 0) {
      listEl.innerHTML = `
        <div class="text-xs text-slate-400 text-center py-3">
          🕰️ ${_currentInterval} BB 중단 ±5% 근처 심볼 = 없음!
        </div>
      `;
      return;
    }

    const html = symbols.slice(0, 30).map((s, idx) => {
      const posColor = s.position === 'ABOVE' ? '#22c55e' : '#ef4444';
      const posIcon = s.position === 'ABOVE' ? '⬆️' : '⬇️';
      const posText = s.position === 'ABOVE' ? '중단 위' : '중단 아래';

      const distColor = Math.abs(s.dist_pct_from_middle) < 2 ? '#fbbf24' : '#94a3b8';
      const changeColor = s.change_24h >= 0 ? '#22c55e' : '#ef4444';
      const changeSign = s.change_24h >= 0 ? '+' : '';

      const rankIcon = idx === 0 ? '🥇' : idx === 1 ? '🥈' : idx === 2 ? '🥉' : `#${idx + 1}`;

      return `
        <div style="background:rgba(0,0,0,0.3);border:1px solid ${posColor};border-radius:6px;padding:6px 10px;cursor:pointer"
             onclick="openBinanceChart('${s.symbol}')"
             title="클릭 = 바이낸스 차트!">
          <div class="flex items-center justify-between mb-1">
            <span class="text-sm font-bold" style="color:${posColor}">
              <span style="color:#c4b5fd;font-size:0.85em">${rankIcon}</span>
              ${posIcon} ${s.symbol}
              <span class="text-xs text-slate-400 ml-1">| ${posText}</span>
            </span>
            <span class="text-xs font-bold" style="color:#fbbf24">
              📊 당일 상승 <span style="color:#22c55e">+${s.max_rise_pct_24h}%</span>
            </span>
          </div>
          <div class="text-xs text-slate-400 mb-1">
            현재: <span style="color:#fff">${s.current_price}</span>
            | 중단: <span style="color:#94a3b8">${s.middle}</span>
            | 이격: <span style="color:${distColor};font-weight:600">${s.dist_pct_from_middle > 0 ? '+' : ''}${s.dist_pct_from_middle}%</span>
          </div>
          <div class="text-xs text-slate-400">
            📈 24h: <span style="color:${changeColor}">${changeSign}${s.change_24h}%</span>
            | H: ${s.high_24h}
            | L: ${s.low_24h}
          </div>
          <div class="flex gap-1 mt-1">
            <button onclick="event.stopPropagation();openBinanceChart('${s.symbol}')"
                    class="text-xs font-bold px-2 py-1 rounded"
                    style="background:#fbbf24;color:#000;border:0;cursor:pointer">
              📈 바이낸스 차트
            </button>
            <button onclick="event.stopPropagation();openBBSymbolAnalysis('${s.symbol}', '${s.position}')"
                    class="text-xs font-bold px-2 py-1 rounded"
                    style="background:linear-gradient(135deg,#3b82f6,#8b5cf6);color:#fff;border:0;cursor:pointer">
              📊 상세 분석
            </button>
          </div>
        </div>
      `;
    }).join('');

    listEl.innerHTML = html;
  }

  // 심볼 클릭 = 바이낸스 차트!
  function openBinanceChart(sym) {
    const url = `https://www.binance.com/en/futures/${encodeURIComponent(sym)}`;
    window.open(url, `bnc_${sym}`, 'noopener');
  }

  // 상세 분석 창!
  function openBBSymbolAnalysis(sym, position) {
    // 중단 위면 = 이탈 시 SHORT 고려!
    // 중단 아래면 = 돌파 시 LONG 고려!
    const side = position === 'ABOVE' ? 'SHORT' : 'LONG';
    const url = `/static/analysis.html?symbol=${encodeURIComponent(sym)}&side=${side}`;
    window.open(url, `an_${sym}`, 'width=550,height=700,scrollbars=yes');
  }

  if (typeof window !== 'undefined') {
    window.scanBBMiddle = scanBBMiddle;
    window.openBinanceChart = openBinanceChart;
    window.openBBSymbolAnalysis = openBBSymbolAnalysis;
    document.addEventListener('DOMContentLoaded', () => {
      setTimeout(() => scanBBMiddle('4h'), 2500);
      setInterval(() => scanBBMiddle(_currentInterval), 60000);  // 60초 자동!
    });
  }
})();
