/**
 * 🗾 Fix 465 — 일목 기준선 실험실 카드 (가상 전용, 읽기 전용).
 *
 * API: GET /api/v1/ichikijun-lab/board  → {at, since, champion, streak, board[]}
 * DOM: #ichikijun-lab-card · #ichikijun-lab-champion · #ichikijun-lab-streak · #ichikijun-lab-table · #ichikijun-lab-meta
 * 주문 버튼 없음. 처음 1번 + 10분마다, 숨김 탭이면 건너뛴다 (ema-pullback-board.js 와 같은 방식).
 */
(function () {
  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"]/g, c => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }
  function num(x, d) {
    if (x === null || x === undefined || isNaN(Number(x))) return '-';
    return Number(x).toFixed(d);
  }
  function signed(x, d) {
    if (x === null || x === undefined || isNaN(Number(x))) return '-';
    const n = Number(x);
    return (n >= 0 ? '+' : '') + n.toFixed(d);
  }
  function pct(x) {
    if (x === null || x === undefined || isNaN(Number(x))) return '-';
    const n = Number(x);
    return (n <= 1 ? n * 100 : n).toFixed(1) + '%';
  }
  function sideHtml(side) {
    const isLong = side === 'LONG';
    return `<b style="color:${isLong ? '#22c55e' : '#ef4444'}">${isLong ? 'LONG' : 'SHORT'}</b>`;
  }

  async function loadIchikijunLabBoard() {
    const card = document.getElementById('ichikijun-lab-card');
    const champEl = document.getElementById('ichikijun-lab-champion');
    const streakEl = document.getElementById('ichikijun-lab-streak');
    const tableEl = document.getElementById('ichikijun-lab-table');
    const metaEl = document.getElementById('ichikijun-lab-meta');
    if (!card || !champEl || !tableEl) return;
    let data;
    try {
      data = await api('/ichikijun-lab/board');
    } catch (e) {
      return;
    }
    data = data || {};
    const ch = data.champion;
    if (ch) {
      champEl.innerHTML = `🏆 <b>${esc(ch.variant)}</b> ${sideHtml(ch.side)} · 점수(무작위 대비 95% 아래 끝) <b>${signed(ch.score, 3)}R</b> · 승률 ${pct(ch.win)} · ${esc(ch.n)}건/${esc(ch.days)}일`;
    } else {
      champEl.textContent = '표본 쌓는 중 (자격: 진입일 20 · 30건)';
    }
    if (streakEl) {
      const st = data.streak || {};
      streakEl.textContent = st.count ? `도전자 연속 ${st.count}/3일${st.key ? ' · ' + st.key : ''}` : '도전자 연속 0/3일';
    }
    const rows = (data.board || []).slice(0, 10);
    if (!rows.length) {
      tableEl.innerHTML = '<div class="text-xs text-slate-400">아직 기록 없음</div>';
    } else {
      tableEl.innerHTML = `<table class="text-xs" style="width:100%;border-collapse:collapse">
        <thead><tr class="text-slate-400" style="text-align:left">
          <th>변형</th><th>방향</th><th>건수(날)</th><th>승률</th><th>비용 뒤 평균 R</th><th>무작위 대비</th><th>95% 아래 끝</th>
        </tr></thead><tbody>${rows.map(r => `<tr style="border-top:1px solid #33415555">
          <td>${esc(r.variant)}</td><td>${sideHtml(r.side)}</td>
          <td>${esc(r.n)} (${esc(r.days)})</td><td>${pct(r.win)}</td>
          <td>${signed(r.avg_r, 3)}</td><td>${signed(r.edge, 3)}</td>
          <td>${r.score === null || r.score === undefined ? '<span class="text-slate-400">표본 부족</span>' : signed(r.score, 3)}</td>
        </tr>`).join('')}</tbody></table>`;
    }
    if (metaEl) {
      const at = data.at ? new Date(data.at).toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '-';
      metaEl.textContent = `갱신 ${at}`;
    }
  }

  if (typeof window !== 'undefined') {
    window.loadIchikijunLabBoard = loadIchikijunLabBoard;
    document.addEventListener('DOMContentLoaded', () => {
      setTimeout(loadIchikijunLabBoard, 3000);
      setInterval(() => { if (!document.hidden) loadIchikijunLabBoard(); }, 600000);
    });
  }
})();
