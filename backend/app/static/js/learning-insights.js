// 🧠 v136 (2026-08-13 사장님!): 학습 인사이트 카드!
// = Learning Team 결과 표시!
// = 심볼별 성공 패턴 + 놓친 기회!

(function() {
  'use strict';

  const LEVEL_COLORS = {
    'info': '#22c55e',
    'warn': '#f59e0b',
    'error': '#ef4444',
  };
  const LEVEL_ICONS = {
    'info': '✅',
    'warn': '⚠️',
    'error': '🚨',
  };

  async function loadLearningInsights() {
    const contentEl = document.getElementById('learning-insights-content');
    const badgeEl = document.getElementById('learning-badge');
    if (!contentEl) return;

    try {
      const data = await api('/trade-learning/insights');
      renderInsights(data);
      if (badgeEl) {
        const cnt = (data.insights || []).length;
        badgeEl.textContent = cnt > 0 ? `${cnt}건` : '대기';
        badgeEl.style.background = cnt > 0 ? '#ec4899' : '#475569';
      }
    } catch (e) {
      console.warn('[learning-insights] load 실패:', e);
      contentEl.innerHTML = '<div class="text-red-400 text-center py-3">❌ 로드 실패</div>';
    }
  }

  function renderInsights(data) {
    const contentEl = document.getElementById('learning-insights-content');
    if (!contentEl) return;

    if (!data || !data.generated_at) {
      contentEl.innerHTML = `
        <div class="text-slate-400 text-center py-3">
          🎓 아직 학습 사이클 미실행! (「🎓 지금 학습」 클릭 or 4시간 대기!)
        </div>
      `;
      return;
    }

    let html = '';

    // 인사이트!
    if (data.insights && data.insights.length > 0) {
      html += `<div style="color:#f9a8d4;font-weight:600;margin-bottom:4px">💡 자동 발견 인사이트:</div>`;
      data.insights.forEach(i => {
        const color = LEVEL_COLORS[i.level] || '#94a3b8';
        html += `
          <div style="background:rgba(0,0,0,0.3);border-left:3px solid ${color};padding:4px 8px;margin-bottom:3px;border-radius:3px;font-size:11px;color:#e2e8f0">
            ${i.text}
          </div>
        `;
      });
    }

    // TOP 거래 심볼!
    if (data.top_trade_symbols && data.top_trade_symbols.length > 0) {
      html += `<div style="color:#22c55e;font-weight:600;margin-top:6px;margin-bottom:2px">🏆 최고 수익 심볼 (실거래):</div>`;
      html += `<div class="flex flex-wrap gap-1 mb-1">`;
      data.top_trade_symbols.slice(0, 5).forEach(s => {
        const pnl = s.pnl_sum;
        const color = pnl >= 0 ? '#22c55e' : '#ef4444';
        const sign = pnl >= 0 ? '+' : '';
        html += `<span style="background:rgba(34,197,94,0.15);color:${color};padding:2px 6px;border-radius:3px;font-size:10px">
          ${s.symbol} ${sign}${pnl.toFixed(1)}% <span style="color:#94a3b8">(${s.wins}승/${s.losses}패)</span>
        </span>`;
      });
      html += `</div>`;
    }

    // TOP 예측 심볼!
    if (data.top_pred_symbols && data.top_pred_symbols.length > 0) {
      html += `<div style="color:#a78bfa;font-weight:600;margin-top:4px;margin-bottom:2px">🎯 최고 예측 심볼:</div>`;
      html += `<div class="flex flex-wrap gap-1 mb-1">`;
      data.top_pred_symbols.slice(0, 5).forEach(s => {
        const color = s.rate >= 60 ? '#22c55e' : s.rate >= 40 ? '#f59e0b' : '#ef4444';
        html += `<span style="background:rgba(167,139,250,0.15);color:${color};padding:2px 6px;border-radius:3px;font-size:10px">
          ${s.symbol} ${s.rate}% <span style="color:#94a3b8">(${s.total}건)</span>
        </span>`;
      });
      html += `</div>`;
    }

    // 놓친 기회!
    if (data.big_moves_missed && data.big_moves_missed.length > 0) {
      html += `<div style="color:#f59e0b;font-weight:600;margin-top:4px;margin-bottom:2px">💡 놓친 기회 (진입 X 심볼 = 큰 변동):</div>`;
      html += `<div class="flex flex-wrap gap-1 mb-1">`;
      data.big_moves_missed.slice(0, 8).forEach(m => {
        const ch = m.change_24h;
        const color = ch >= 0 ? '#22c55e' : '#ef4444';
        const sign = ch >= 0 ? '+' : '';
        const sideIcon = m.side_would_have === 'LONG' ? '🐂' : m.side_would_have === 'SHORT' ? '🐻' : '➖';
        html += `<span style="background:rgba(245,158,11,0.15);color:${color};padding:2px 6px;border-radius:3px;font-size:10px">
          ${sideIcon} ${m.symbol} ${sign}${ch.toFixed(1)}%
        </span>`;
      });
      html += `</div>`;
    }

    // 마지막 실행 시각!
    if (data.generated_at) {
      const dt = new Date(data.generated_at);
      html += `<div style="margin-top:6px;padding-top:4px;border-top:1px solid #334155;color:#94a3b8;font-size:10px;text-align:center">
        마지막 학습: ${dt.toLocaleString('ko-KR')}
      </div>`;
    }

    contentEl.innerHTML = html || '<div class="text-slate-400 text-center py-2">아직 인사이트 없음!</div>';
  }

  async function runLearningCycleNow() {
    if (typeof toast === 'function') toast('🎓 학습 사이클 실행 중... (수십초 소요!)', 'info');
    try {
      const result = await api('/trade-learning/learning-cycle/run-now', { method: 'POST' });
      if (typeof toast === 'function') {
        const cnt = (result && result.insights_count) || 0;
        toast(`✅ 학습 완료! 인사이트 ${cnt}건 생성!`, 'success');
      }
      setTimeout(loadLearningInsights, 500);
    } catch (e) {
      if (typeof toast === 'function') toast('❌ 실패: ' + (e.message || e), 'error');
    }
  }

  if (typeof window !== 'undefined') {
    window.loadLearningInsights = loadLearningInsights;
    window.runLearningCycleNow = runLearningCycleNow;
    document.addEventListener('DOMContentLoaded', () => {
      setTimeout(loadLearningInsights, 4000);
      setInterval(loadLearningInsights, 5 * 60 * 1000);  // 5분마다!
    });
  }
})();
