/**
 * 🗾 Fix 465 — 일목 기준선 실험실 카드 (가상 전용, 읽기 전용).
 *
 * API: GET /api/v1/ichikijun-lab/board  → {at, since, champion, streak, board[]}
 * 🗾 Fix 466: 응답의 applied(적용 결과) → #ichikijun-lab-applied
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

  // 🏁 Fix 471 — 검증 통과 관문 G1~G7 (읽기 전용 표시, 판정은 서버)
  const GATE_TEXT = {
    G1: '진입일 60일 이상 · 100건 이상',
    G2: '무작위 대비 99.9% 아래 끝 > 0',
    G3: '비용 뒤 평균 R > 0',
    G4: '앞·뒤 절반 둘 다 +',
    G5: '최고 5일을 빼도 +',
    G6: 'BTC 상승·하락 장세 둘 다 +',
    G7: '실주문 vs 가상 차이 ≥ -0.3R (실주문 10건 이상일 때만)',
  };
  function gateTitle(promo) {
    const g = (promo && promo.gates) || {};
    return Object.keys(GATE_TEXT).map(k => {
      const v = g[k];
      return `${k} ${v === true ? '✓' : (v === false ? '✗' : '–')} ${GATE_TEXT[k]}`;
    }).join('\n');
  }
  function passedCount(promo) {
    const g = (promo && promo.gates) || {};
    return Object.keys(g).filter(k => g[k] === true).length;
  }
  function statusBadge(promo) {
    if (!promo) return '<span class="text-slate-400">-</span>';
    const st = promo.status;
    const color = st === '검증 통과' ? '#22c55e' : (st === '탈락' ? '#ef4444' : '#94a3b8');
    return `<span title="${esc(gateTitle(promo))}" style="color:${color};font-weight:600;cursor:help">${esc(st || '-')}</span>`;
  }
  function renderPromoLine(el, board) {
    if (!el) return;
    const withPromo = (board || []).filter(r => r && r.promo);
    if (!withPromo.length) { el.style.display = 'none'; el.innerHTML = ''; return; }
    el.style.display = '';
    const passed = withPromo.filter(r => r.promo.status === '검증 통과');
    if (passed.length) {
      el.innerHTML = '🏁 <b>검증 통과</b> ' + passed.map(r =>
        `${esc(r.variant)} ${sideHtml(r.side)} ${esc(r.n)}건/${esc(r.days)}일 평균 ${signed(r.avg_r, 3)}R`).join(' · ');
      return;
    }
    // 가장 가까운 줄: G1 을 넘은 줄 우선, 그 안에서 통과 관문이 많은 줄
    const best = withPromo.slice().sort((a, b) => {
      const a1 = (a.promo.gates || {}).G1 === true ? 1 : 0;
      const b1 = (b.promo.gates || {}).G1 === true ? 1 : 0;
      return (b1 - a1) || (passedCount(b.promo) - passedCount(a.promo));
    })[0];
    const miss = ((best.promo.detail || {}).missing || []).join(', ') || '-';
    el.innerHTML = `🏁 검증 통과 후보 아직 없음 — 가장 가까운 줄: ${esc(best.variant)} ${sideHtml(best.side)} (남은 관문: ${esc(miss)})`;
  }

  // 🗾 Fix 466 — 적용 결과: 일목 신호 예약 인스턴스의 실주문 R vs 같은 진입 실험실 R (읽기 전용)
  function renderApplied(el, applied) {
    if (!el) return;
    const rows = (applied && applied.rows) || [];
    const sm = (applied && applied.summary) || {};
    if (!rows.length) {
      el.innerHTML = '<div class="text-xs text-slate-400">아직 일목 신호 예약 없음</div>';
      return;
    }
    const line = `적용 ${esc(sm.instances)}건 · 진입 ${esc(sm.entered)} · 끝남 ${esc(sm.finished)} · 실주문 평균 ${signed(sm.live_avg_r, 3)}R · 같은 진입 실험실 평균 ${signed(sm.lab_avg_r, 3)}R (짝 ${esc(sm.paired)}) · 차이 ${signed(sm.diff_avg_r, 3)}R · 실현 합계 ${signed(sm.pnl_sum, 2)} USDT`;
    el.innerHTML = `<div class="text-xs" style="color:#e9d5ff">📋 적용 결과 — ${line}</div>
      <div style="max-height:220px;overflow:auto;margin-top:4px"><table class="text-xs" style="width:100%;border-collapse:collapse">
      <thead><tr class="text-slate-400" style="text-align:left">
        <th>#id</th><th>심볼</th><th>방향</th><th>변형</th><th>상태</th><th>실주문 R</th><th>실험실 R</th><th>차이</th><th>표식</th>
      </tr></thead><tbody>${rows.map(r => `<tr style="border-top:1px solid #33415555">
        <td>#${esc(r.id)}</td><td>${esc(r.symbol)}</td><td>${sideHtml(r.side)}</td>
        <td title="${esc(r.entry_signal)}">${esc(r.variant || r.entry_signal)}</td><td>${esc(r.status)}</td>
        <td>${signed(r.live_r, 3)}</td><td>${signed(r.lab_r, 3)}</td><td>${signed(r.diff, 3)}</td>
        <td>${esc((r.flags || []).join(' · '))}</td>
      </tr>`).join('')}</tbody></table></div>`;
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
    // 🏁 Fix 471 — index.html 을 건드리지 않고 JS 가 챔피언 줄 위에 한 줄 + 설명 아래 작은 글씨를 만든다
    let promoEl = document.getElementById('ichikijun-lab-promo');
    if (!promoEl && champEl.parentNode) {
      promoEl = document.createElement('div');
      promoEl.id = 'ichikijun-lab-promo';
      promoEl.className = 'text-xs';
      promoEl.style.cssText = 'color:#bbf7d0;margin-bottom:4px';
      champEl.parentNode.insertBefore(promoEl, champEl);
    }
    if (!document.getElementById('ichikijun-lab-promo-note') && champEl.parentNode) {
      const note = document.createElement('div');
      note.id = 'ichikijun-lab-promo-note';
      note.className = 'text-slate-400';
      note.style.cssText = 'font-size:10px;margin:2px 0';
      note.textContent = '🏁 검증 통과 = 우연이 아니라는 증거가 충분한 줄(실주문은 사장님 승인) · 100% 확실한 전략은 없다';
      champEl.parentNode.insertBefore(note, promoEl || champEl);
    }
    renderPromoLine(promoEl, data.board);
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
          <th>변형</th><th>방향</th><th>건수(날)</th><th>승률</th><th>비용 뒤 평균 R</th><th>무작위 대비</th><th>95% 아래 끝</th><th>관문</th>
        </tr></thead><tbody>${rows.map(r => `<tr style="border-top:1px solid #33415555">
          <td>${esc(r.variant)}</td><td>${sideHtml(r.side)}</td>
          <td>${esc(r.n)} (${esc(r.days)})</td><td>${pct(r.win)}</td>
          <td>${signed(r.avg_r, 3)}</td><td>${signed(r.edge, 3)}</td>
          <td>${r.score === null || r.score === undefined ? '<span class="text-slate-400">표본 부족</span>' : signed(r.score, 3)}</td>
          <td>${statusBadge(r.promo)}</td>
        </tr>`).join('')}</tbody></table>`;
    }
    renderApplied(document.getElementById('ichikijun-lab-applied'), data.applied);
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
