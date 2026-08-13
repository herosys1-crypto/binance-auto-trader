// 🚀 v133d (2026-08-13 사장님!): 급등락 실시간 진입 카드!
// v147: **15분봉 20% 전후(17.5~22.5%)** 급등만 추격 LONG / 급락은 진입 비권장!
//       (옛 5분 1.5% / 1h 3% 추격 = 실측상 근거 없어 폐기)
// = 30초마다 자동 새로고침!

(function() {
  'use strict';

  const TYPE_LABELS = {
      'pump_15m': '🚀 15m 20% 급등',
      'dump_15m_avoid': '🚫 15m 급락 (비권장)',
    'pump_live': '🚀 5분 급등',
    'dump_live': '📉 5분 급락',
    'pump_1h': '🚀 1h 급등',
    'dump_1h': '📉 1h 급락',
  };

  async function scanLivePumpDump() {
    try {
      const data = await api('/live-pump-dump/scan?max_symbols=60&include_dump=true');
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
      // 🚨 v147 CRITICAL: side 가 null 이면 = **진입 비권장**(급락).
      //    옛 코드 `a.side || 'LONG'` 는 null 을 LONG 으로 둔갑시켜
      //    실측상 기대값 없는 급락에 「즉시 진입」 버튼을 띄웠습니다!
      const entrySide = a.side || null;
      const canEnter = entrySide === 'LONG' || entrySide === 'SHORT';
      const sideColor = !canEnter ? '#64748b' : (entrySide === 'LONG' ? '#22c55e' : '#ef4444');
      const sideIcon = !canEnter ? '🚫' : (entrySide === 'LONG' ? '🐂' : '🐻');
      const typeLabel = TYPE_LABELS[a.type] || a.type;
      const confPct = ((a.confidence || 0) * 100).toFixed(0);
      const rankIcon = idx === 0 ? '🥇' : idx === 1 ? '🥈' : idx === 2 ? '🥉' : `#${idx + 1}`;

      let confBadge = '💧';
      let confColor = '#94a3b8';
      if (a.confidence >= 0.85) { confBadge = '🔥'; confColor = '#ef4444'; }
      else if (a.confidence >= 0.75) { confBadge = '⭐'; confColor = '#f59e0b'; }
      else if (a.confidence >= 0.65) { confBadge = '✨'; confColor = '#fbbf24'; }

      const chg = (a.change_pct !== null && a.change_pct !== undefined)
        ? `${a.change_pct > 0 ? '+' : ''}${Number(a.change_pct).toFixed(1)}%` : '-';
      const evNet = (a.expected_value_after_fee_pct !== null && a.expected_value_after_fee_pct !== undefined)
        ? `${a.expected_value_after_fee_pct > 0 ? '+' : ''}${a.expected_value_after_fee_pct}%` : null;

      // 진입 config — v147 기본값과 일치시킴 (TP1 15% / SL 50%)
      const cfg = canEnter ? {
        leverage: 2,
        capitals: [300, 500],
        trigger_percents: [null, 10],
        tp1_percent: 10, tp2_percent: 15, tp3_percent: 20, tp4_percent: 25,
        tp1_qty_ratio: 10, tp2_qty_ratio: 15, tp3_qty_ratio: 20, tp4_qty_ratio: 25,
        tp1_pct_override: 15,                 // v147 (옛 25)
        force_sl_enabled_override: true,
        force_sl_roi_override: 15,
        stop_loss_percent_of_capital: 50,     // v147 (옛 90)
        start_price: null,
        symbol: a.symbol,
        side: entrySide,
      } : null;

      // 상세 분석은 급락도 열 수 있게 (관찰용) — 방향은 SHORT 관점
      const analysisSide = entrySide || 'SHORT';

      const metricsRow = canEnter
        ? `<div class="text-xs text-slate-400 mb-1">
             🎯 TP <span style="color:#22c55e">+${a.tp_pct}%</span> / SL <span style="color:#ef4444">-${a.sl_pct}%</span>
             &nbsp;|&nbsp; TP선착 ${a.tp_first_rate ?? '-'}%
             ${evNet ? `&nbsp;|&nbsp; 기대값(수수료후) <span style="color:#f59e0b">${evNet}</span>` : ''}
             ${a.sample_n ? `<span style="color:#64748b"> (표본 ${a.sample_n}건)</span>` : ''}
           </div>`
        : `<div class="text-xs mb-1" style="color:#f59e0b">
             ⚠️ 실측상 급락은 양방향 모두 기대값이 없어 <b>진입 버튼을 제공하지 않습니다</b>.
           </div>`;

      return `
        <div style="background:rgba(0,0,0,0.3);border:2px solid ${sideColor};border-radius:6px;padding:8px 10px;${canEnter ? `box-shadow:0 0 12px ${sideColor}66;animation:pulse 2s infinite;` : 'opacity:0.75;'}cursor:pointer"
             onclick="openSuggestionAnalysis('${a.symbol}', '${analysisSide}', 0)"
             title="클릭 = 상세 분석 새 창!">
          <div class="flex items-center justify-between mb-1">
            <span class="text-sm font-bold" style="color:${sideColor}">
              <span style="color:#c4b5fd;font-size:0.85em">${rankIcon}</span>
              ${sideIcon} ${a.symbol} ${canEnter ? entrySide : '진입 비권장'}
              <span class="text-xs text-slate-400 ml-1">| 15m ${a.window || ''} ${chg}</span>
            </span>
            <span class="text-xs font-bold" style="color:${confColor}">
              ${canEnter ? `${confBadge} ${confPct}%` : ''}
            </span>
          </div>
          ${metricsRow}
          <div class="text-xs text-blue-300 mb-2" style="font-style:italic">
            💡 ${a.verdict || a.reason || ''}
          </div>
          <div class="flex gap-2">
            ${canEnter ? `
            <button onclick="event.stopPropagation();confirmLiveEntry('${a.symbol}', '${entrySide}', '${encodeURIComponent(JSON.stringify(cfg))}')"
                    class="text-xs font-bold px-3 py-1 rounded"
                    style="background:linear-gradient(135deg,#059669,#22c55e);color:#fff;border:0;cursor:pointer"
                    title="추천 이유 확인 → 진입!">
              ▶ 즉시 진입
            </button>` : ''}
            <button onclick="event.stopPropagation();openSuggestionAnalysis('${a.symbol}', '${analysisSide}', 0)"
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

  // 🌟 v135a (2026-08-13 사장님!): 즉시 진입 = 이유 확인 모달!
  async function confirmLiveEntry(symbol, side, cfgEncoded) {
    // 기존 모달 삭제!
    const oldModal = document.getElementById('live-entry-confirm-modal');
    if (oldModal) oldModal.remove();

    // 로딩 모달 즉시 표시!
    const modal = document.createElement('div');
    modal.id = 'live-entry-confirm-modal';
    modal.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.75);z-index:9999;display:flex;align-items:center;justify-content:center;padding:16px';
    modal.innerHTML = `
      <div style="background:#0f172a;border:2px solid ${side === 'LONG' ? '#22c55e' : '#ef4444'};border-radius:8px;padding:16px;max-width:500px;width:100%;max-height:90vh;overflow-y:auto;box-shadow:0 0 30px ${side === 'LONG' ? '#22c55e88' : '#ef444488'}">
        <div style="text-align:center;color:#fff;padding:20px">
          📡 <span style="color:${side === 'LONG' ? '#22c55e' : '#ef4444'};font-weight:bold">${symbol} ${side}</span> 분석 중...
        </div>
      </div>
    `;
    document.body.appendChild(modal);

    // 분석 API 호출!
    let analysis = null;
    try {
      analysis = await api(`/analysis/symbol/${encodeURIComponent(symbol)}?side=${side}`);
    } catch (e) {
      console.warn('[confirmLiveEntry] 분석 실패:', e);
    }

    // 모달 내용 업데이트!
    renderConfirmModal(modal, symbol, side, cfgEncoded, analysis);
  }

  function renderConfirmModal(modal, symbol, side, cfgEncoded, analysis) {
    const sideColor = side === 'LONG' ? '#22c55e' : '#ef4444';
    const sideIcon = side === 'LONG' ? '🐂' : '🐻';
    const sideLabel = side === 'LONG' ? '롱 (상승 기대!)' : '숏 (하락 기대!)';

    let reasonHtml = '';
    let verdictHtml = '';

    if (analysis && !analysis.price_error) {
      const j = analysis.judgment || {};
      const signals = j.signals || [];
      const score = j.score || 0;
      const verdict = j.verdict || '판단 없음';
      const vColor = j.color || '#94a3b8';

      // 지표 요약!
      const rsi = analysis.rsi_15m;
      const obv = analysis.obv_15m || {};
      const macd = analysis.macd_15m || {};
      const vol = analysis.volume_15m || {};
      const changes = analysis.changes || {};

      verdictHtml = `
        <div style="text-align:center;padding:10px;border-radius:6px;background:${vColor}22;border:2px solid ${vColor};color:${vColor};font-weight:bold;font-size:14px;margin-bottom:10px">
          ${verdict} (score ${score})
        </div>
      `;

      // 이유 설명 (상세하지만 간략!)
      let explanation = `<strong style="color:${sideColor}">${sideIcon} ${symbol}</strong>을 <strong style="color:${sideColor}">${sideLabel}</strong>로 진입하는 이유:<br><br>`;

      const reasons = [];
      // 시장 현황!
      if (analysis.change_24h !== undefined) {
        const c24 = Number(analysis.change_24h);
        const c24Color = c24 >= 0 ? '#22c55e' : '#ef4444';
        reasons.push(`24시간 변동 <span style="color:${c24Color}">${c24 >= 0 ? '+' : ''}${c24.toFixed(2)}%</span>`);
      }
      if (changes.change_5m !== null && changes.change_5m !== undefined) {
        const c5 = Number(changes.change_5m);
        const c5Color = c5 >= 0 ? '#22c55e' : '#ef4444';
        reasons.push(`5분 <span style="color:${c5Color}">${c5 >= 0 ? '+' : ''}${c5}%</span>`);
      }
      if (changes.change_1h !== null && changes.change_1h !== undefined) {
        const c1 = Number(changes.change_1h);
        const c1Color = c1 >= 0 ? '#22c55e' : '#ef4444';
        reasons.push(`1시간 <span style="color:${c1Color}">${c1 >= 0 ? '+' : ''}${c1}%</span>`);
      }
      if (reasons.length) {
        explanation += `📈 <strong>시장 현황:</strong> ${reasons.join(' | ')}<br><br>`;
      }

      // 기술 지표!
      let indics = [];
      if (rsi !== null && rsi !== undefined) {
        const rsiState = rsi > 70 ? '<span style="color:#ef4444">과매수</span>' : rsi < 30 ? '<span style="color:#22c55e">과매도</span>' : '중립';
        indics.push(`RSI <strong>${rsi}</strong> (${rsiState})`);
      }
      if (obv.trend) {
        const oColor = obv.trend === 'UP' ? '#22c55e' : obv.trend === 'DOWN' ? '#ef4444' : '#94a3b8';
        const oLabel = obv.trend === 'UP' ? '상승 (매수 압력!)' : obv.trend === 'DOWN' ? '하락 (매도 압력!)' : '횡보';
        indics.push(`OBV <span style="color:${oColor}">${oLabel}</span>`);
      }
      if (macd.trend) {
        const mColor = macd.trend === 'BULLISH' ? '#22c55e' : macd.trend === 'BEARISH' ? '#ef4444' : '#94a3b8';
        const mLabel = macd.trend === 'BULLISH' ? 'Bullish (매수!)' : macd.trend === 'BEARISH' ? 'Bearish (매도!)' : '중립';
        indics.push(`MACD <span style="color:${mColor}">${mLabel}</span>`);
      }
      if (vol.spike_ratio) {
        const spike = Number(vol.spike_ratio);
        const spikeLabel = spike >= 2 ? '<span style="color:#22c55e">폭증!</span>' : spike >= 1.5 ? '<span style="color:#22c55e">급증</span>' : spike < 0.5 ? '<span style="color:#ef4444">급감</span>' : '정상';
        indics.push(`Volume <strong>${spike}x</strong> (${spikeLabel})`);
      }
      if (indics.length) {
        explanation += `📊 <strong>기술 지표:</strong> ${indics.join(' | ')}<br><br>`;
      }

      // 신호 상세!
      if (signals.length) {
        explanation += `📋 <strong>판단 신호:</strong><br>`;
        signals.forEach(s => {
          explanation += `&nbsp;&nbsp;• ${s}<br>`;
        });
      }

      reasonHtml = `<div style="background:rgba(30,41,59,0.6);padding:10px;border-radius:6px;font-size:12px;line-height:1.6">${explanation}</div>`;
    } else {
      reasonHtml = `<div style="text-align:center;color:#ef4444;padding:10px">❌ 분석 실패! 그래도 진입하시겠습니까?</div>`;
    }

    modal.innerHTML = `
      <div style="background:#0f172a;border:2px solid ${sideColor};border-radius:8px;padding:14px;max-width:520px;width:100%;max-height:92vh;overflow-y:auto;box-shadow:0 0 30px ${sideColor}88">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid #334155">
          <div style="color:${sideColor};font-weight:bold;font-size:15px">
            ${sideIcon} ${symbol} ${side} 진입 확인
          </div>
          <button onclick="document.getElementById('live-entry-confirm-modal').remove()"
                  style="background:#7c3aed;color:#fff;padding:4px 10px;border:0;border-radius:4px;cursor:pointer;font-size:12px">
            ✕ 취소
          </button>
        </div>

        ${verdictHtml}
        ${reasonHtml}

        <div style="margin-top:12px;display:flex;gap:8px;justify-content:center">
          <button onclick="proceedLiveEntry('${symbol}', '${side}', '${cfgEncoded}')"
                  style="background:linear-gradient(135deg,#059669,${sideColor});color:#fff;padding:8px 18px;border:0;border-radius:5px;cursor:pointer;font-weight:bold;font-size:13px">
            ▶ 진입 진행 (세팅 modal 열기!)
          </button>
          <button onclick="document.getElementById('live-entry-confirm-modal').remove()"
                  style="background:#475569;color:#fff;padding:8px 18px;border:0;border-radius:5px;cursor:pointer;font-size:13px">
            ❌ 취소
          </button>
        </div>
        <div style="text-align:center;margin-top:8px;font-size:10px;color:#94a3b8">
          💡 「진입 진행」 클릭 = 신 전략 modal 자동 열림 + symbol/side 자동 fill!
        </div>
      </div>
    `;
  }

  // 진입 진행 = 세팅 modal 열기!
  function proceedLiveEntry(symbol, side, cfgEncoded) {
    const modal = document.getElementById('live-entry-confirm-modal');
    if (modal) modal.remove();
    // 기존 executeSuggestion 호출!
    if (typeof window.executeSuggestion === 'function') {
      window.executeSuggestion(0, symbol, side, cfgEncoded);
    }
  }

  if (typeof window !== 'undefined') {
    window.scanLivePumpDump = scanLivePumpDump;
    window.confirmLiveEntry = confirmLiveEntry;
    window.proceedLiveEntry = proceedLiveEntry;
    document.addEventListener('DOMContentLoaded', () => {
      setTimeout(scanLivePumpDump, 2000);  // 초기 로드 = 2초 후!
      setInterval(scanLivePumpDump, 60000);  // 60초 폴링 (API 부담!)
    });
  }
})();
