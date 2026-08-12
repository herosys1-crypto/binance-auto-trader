// 🎓 v135 (2026-08-13 사장님!): 예측 학습 통계 카드!
// = 예측 후 = 실제 변동 학습 → 심볼별 성공률!
// = 다음 예측 confidence 조정 사이클!

(function() {
  'use strict';

  async function loadPredictionStats() {
    const contentEl = document.getElementById('pred-stats-content');
    const badgeEl = document.getElementById('pred-stats-badge');
    if (!contentEl) return;
    try {
      const data = await api('/trade-learning/prediction-stats?days=30');
      renderPredictionStats(data);
      if (badgeEl) {
        badgeEl.textContent = `${data.success_rate}%`;
        const rate = Number(data.success_rate || 0);
        badgeEl.style.background = rate >= 60 ? '#22c55e' : rate >= 40 ? '#f59e0b' : '#ef4444';
      }
    } catch (e) {
      console.warn('[prediction-stats] load 실패:', e);
      contentEl.innerHTML = '<div class="text-red-400 text-center py-3">❌ 로드 실패</div>';
    }
  }

  function renderPredictionStats(data) {
    const contentEl = document.getElementById('pred-stats-content');
    if (!contentEl) return;

    if (!data || data.total === 0) {
      contentEl.innerHTML = `
        <div class="text-slate-400 text-center py-3">
          📊 아직 예측 데이터 없음! (「🎯 지금 실행」 클릭 후 = 4시간 대기 → outcome 학습!)
        </div>
      `;
      return;
    }

    const rateColor = (r) => r >= 60 ? '#22c55e' : r >= 40 ? '#f59e0b' : '#ef4444';

    let html = `
      <div class="grid grid-cols-2 gap-2 mb-2">
        <div style="background:rgba(0,0,0,0.3);padding:6px 8px;border-radius:4px">
          <div style="color:#94a3b8;font-size:10px">전체 예측</div>
          <div style="color:#fff;font-weight:600">${data.total}건 <span style="color:${rateColor(data.success_rate)};font-size:12px">(${data.success_rate}%)</span></div>
          <div style="color:#94a3b8;font-size:10px">✅${data.success} ❌${data.fail} ⏳${data.pending} ⏰${data.expired}</div>
        </div>
        <div style="background:rgba(0,0,0,0.3);padding:6px 8px;border-radius:4px">
          <div style="color:#94a3b8;font-size:10px">Side별</div>
          <div>
            <span style="color:#22c55e">🐂 ${data.long_success_rate}%</span>
            <span style="color:#94a3b8;margin:0 4px">|</span>
            <span style="color:#ef4444">🐻 ${data.short_success_rate}%</span>
          </div>
          <div style="color:#94a3b8;font-size:10px">
            L:${data.long_success}/${data.long_success + data.long_fail}
            S:${data.short_success}/${data.short_success + data.short_fail}
          </div>
        </div>
      </div>
    `;

    // TOP 심볼!
    if (data.top_symbols && data.top_symbols.length > 0) {
      html += `<div style="color:#22c55e;font-weight:600;margin-bottom:2px">🏆 성공률 TOP:</div>`;
      html += `<div class="flex flex-wrap gap-1 mb-2">`;
      data.top_symbols.slice(0, 5).forEach(s => {
        html += `<span style="background:rgba(34,197,94,0.15);color:${rateColor(s.rate)};padding:2px 6px;border-radius:3px;font-size:10px">
          ${s.symbol} ${s.rate}%<span style="color:#94a3b8"> (${s.wins}/${s.count})</span>
        </span>`;
      });
      html += `</div>`;
    }

    // BOTTOM 심볼!
    if (data.bottom_symbols && data.bottom_symbols.length > 0) {
      html += `<div style="color:#ef4444;font-weight:600;margin-bottom:2px">📉 성공률 BOTTOM:</div>`;
      html += `<div class="flex flex-wrap gap-1">`;
      data.bottom_symbols.slice(0, 5).forEach(s => {
        html += `<span style="background:rgba(239,68,68,0.15);color:${rateColor(s.rate)};padding:2px 6px;border-radius:3px;font-size:10px">
          ${s.symbol} ${s.rate}%<span style="color:#94a3b8"> (${s.wins}/${s.count})</span>
        </span>`;
      });
      html += `</div>`;
    }

    // 학습 사이클 안내!
    html += `
      <div style="margin-top:8px;padding-top:6px;border-top:1px solid #334155;color:#94a3b8;font-size:10px">
        <span style="color:#c4b5fd">💡 학습 사이클</span>: 예측 → 4h 후 실제 가격 확인 → 성공/실패 → 심볼별 성공률 → 다음 예측 confidence 조정!
        <br>
        기준: LONG +1.5% 이상 = SUCCESS / SHORT -1.5% 이하 = SUCCESS / 24h 지나면 = EXPIRED
      </div>
    `;

    contentEl.innerHTML = html;
  }

  async function runOutcomeNow() {
    if (typeof toast === 'function') toast('🔄 예측 outcome 확인 중...', 'info');
    try {
      const result = await api('/trade-learning/prediction-outcome/run-now', { method: 'POST' });
      if (typeof toast === 'function') {
        toast(`✅ 완료! 신 성공 ${result.success || 0} / 실패 ${result.fail || 0}`, 'success');
      }
      // 통계 새로고침!
      setTimeout(loadPredictionStats, 500);
    } catch (e) {
      if (typeof toast === 'function') toast('❌ 실패: ' + (e.message || e), 'error');
    }
  }

  if (typeof window !== 'undefined') {
    window.loadPredictionStats = loadPredictionStats;
    window.runOutcomeNow = runOutcomeNow;
    document.addEventListener('DOMContentLoaded', () => {
      setTimeout(loadPredictionStats, 3500);
      setInterval(loadPredictionStats, 5 * 60 * 1000);  // 5분마다!
    });
  }
})();
