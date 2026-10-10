/**
 * 🧑‍⚖️ Fix 430 (2026-10-10 사장님) — 전략 운영팀 성적표 카드 (분석 전용, 버튼 없음).
 *
 * API: GET /api/v1/strategy-council/latest  (strategy_council 워커가 하루 1회 KST 09:40 갱신)
 * DOM: #strategy-council-card · #strategy-council-meta · #strategy-council-body
 * 숨김 탭이면 갱신하지 않는다. 값이 없으면 카드를 숨긴다.
 */
(function () {
  function f(x) {
    if (x === null || x === undefined || isNaN(Number(x))) return '—';
    const n = Number(x);
    return (n >= 0 ? '+' : '') + n.toFixed(2);
  }
  function c(x) {
    if (x === null || x === undefined || isNaN(Number(x))) return '#94a3b8';
    return Number(x) >= 0 ? '#22c55e' : '#ef4444';
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  }
  const B_NAME = { low: '시장폭 낮음', mid: '시장폭 중간', high: '시장폭 높음', '?': '모름' };
  const ST_COLOR = { '사용 후보': '#22c55e', '중지 후보': '#ef4444', '표본 부족': '#93c5fd', '관찰': '#94a3b8' };

  async function loadStrategyCouncil() {
    const card = document.getElementById('strategy-council-card');
    const meta = document.getElementById('strategy-council-meta');
    const body = document.getElementById('strategy-council-body');
    if (!card || !body) return;
    let d, lv = null;
    try {
      d = await api('/strategy-council/latest');
    } catch (e) {
      return;
    }
    try {
      lv = await api('/strategy-council/live-families');     // 🧑‍⚖️ Fix 436 가족별 실거래 (5분 캐시)
    } catch (e) {
      lv = null;
    }
    if (!d || d.empty || !d.D_walk) {
      card.classList.add('hidden');
      return;
    }
    card.classList.remove('hidden');
    const W = d.D_walk, T = W.total || {}, E = d.E_today || {};
    if (meta) {
      const at = d.at ? new Date(d.at).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '-';
      meta.textContent = `갱신 ${at} · 최근 ${d.window_days || '-'}일 · 지금 ${B_NAME[E.current_b] || '-'}`;
    }
    const cells = (E.cells || []).slice(0, 12).map(x =>
      `<tr><td>${esc(x.rule)}</td><td style="color:${x.side === 'LONG' ? '#22c55e' : '#ef4444'}">${esc(x.side)}</td>` +
      `<td>${esc(B_NAME[x.b] || x.b)}${x.b === E.current_b ? ' ◀' : ''}</td><td style="color:${c(x.edge)}">${f(x.edge)}</td><td>${x.n}</td></tr>`).join('');
    const ov = (d.B_overlap || []).map(x =>
      `<tr><td style="color:${x.side === 'LONG' ? '#22c55e' : '#ef4444'}">${esc(x.side)}</td><td>${x.k}${x.k >= 4 ? '+' : ''}개</td>` +
      `<td style="color:${c(x.edge)}">${f(x.edge)}</td><td>${x.n}</td></tr>`).join('');
    const st = (d.F_status || []).map(x =>
      `<span style="border:1px solid ${ST_COLOR[x.status] || '#94a3b8'}66;border-radius:6px;padding:1px 6px;margin:2px;display:inline-block;font-size:11px">` +
      `<b style="color:${ST_COLOR[x.status] || '#94a3b8'}">${esc(x.status)}</b> ${esc(x.rule)} ${esc(x.side)} <span style="color:${c(x.edge)}">${f(x.edge)}</span></span>`).join('');
    const th = 'style="text-align:left;color:#94a3b8;font-weight:normal;padding-right:8px"';
    // 🧑‍⚖️ Fix 436: 가족별 실거래 — 시스템 몫(가족 판단용) · 사람 💉 추가 몫 · 손실 차단기(최근 7일 가족 몫 / 기준)
    const fams = (lv && lv.families) || [];
    const brk = b => {
      if (!b || b.pnl === null || b.pnl === undefined) return '—';
      if (b.tripped) return '<b style="color:#ef4444">⛔ 막힘</b>';
      const pct = b.limit ? Math.min(100, Math.max(0, -Number(b.pnl) / Number(b.limit) * 100)) : 0;
      return `${f(b.pnl)} / −${esc(b.limit)} <span style="color:${pct >= 70 ? '#f97316' : '#94a3b8'}">(${pct.toFixed(0)}%)</span>`;
    };
    const liveRows = fams.map(x =>
      `<tr><td>${esc(x.label)}${x.mode === 'on' ? ' <b style="color:#22c55e">실주문</b>' : ''}</td><td>${x.closed}${x.open ? ' +' + x.open : ''}</td>` +
      `<td style="color:${c(x.system)}"><b>${f(x.system)}</b></td><td style="color:${c(x.human)}">${f(x.human)}${x.human_n ? ' (' + x.human_n + ')' : ''}</td>` +
      `<td>${x.unknown ? f(x.unknown) : '—'}</td><td>${brk(x.breaker)}</td></tr>`).join('');
    const liveHtml = fams.length
      ? `<div style="margin-top:8px;overflow-x:auto"><div style="font-size:12px;color:#c4b5fd">💵 가족별 실거래 최근 ${esc(lv.days)}일 (USDT · 가족 판단은 <b>시스템 몫</b> · 사람 💉 추가 몫은 따로)</div>` +
        `<table style="font-size:12px;width:100%"><tr><th ${th}>가족</th><th ${th}>끝남+진행</th><th ${th}>시스템 몫</th><th ${th}>사람 추가 몫(건)</th><th ${th}>모름</th><th ${th}>손실 차단기 7일</th></tr>${liveRows}</table></div>`
      : '';
    body.innerHTML =
      `<div style="font-size:12px;margin-bottom:6px">전진 검증 ${W.n_days}일 — 운영팀 선택 <b style="color:${c(T.sel)}">${f(T.sel)}</b> · 전체 ${f(T.all)} · 무작위 ${f(T.base)}` +
      ` · 선택&gt;전체 ${W.sel_gt_all_days}/${W.n_days}일 · 최악의 날 ${W.worst ? esc(W.worst.d) + ' <b style="color:#ef4444">' + f(W.worst.sel) + '</b>' : '—'}</div>` +
      `<div style="display:flex;flex-wrap:wrap;gap:12px">` +
      `<div style="flex:1 1 300px;min-width:0;overflow-x:auto"><div style="font-size:12px;color:#c4b5fd">▶ 오늘 쓸 칸 (무작위 대비 edge, ◀ = 지금 장세)</div>` +
      `<table style="font-size:12px;width:100%"><tr><th ${th}>규칙</th><th ${th}>방향</th><th ${th}>장세</th><th ${th}>edge</th><th ${th}>n</th></tr>${cells || '<tr><td colspan=5>없음</td></tr>'}</table></div>` +
      `<div style="flex:0 1 220px;min-width:0"><div style="font-size:12px;color:#c4b5fd">🤝 같은 방향 규칙이 겹칠 때</div>` +
      `<table style="font-size:12px;width:100%"><tr><th ${th}>방향</th><th ${th}>겹침</th><th ${th}>edge</th><th ${th}>n</th></tr>${ov}</table></div></div>` +
      liveHtml +
      `<details style="margin-top:6px"><summary style="cursor:pointer;font-size:12px;color:#c4b5fd">규칙 상태 ${(d.F_status || []).length}개 (새 전략은 「표본 부족」으로 시작)</summary><div style="margin-top:4px">${st}</div></details>` +
      `<div class="text-xs text-slate-500" style="margin-top:4px">※ 분석 전용 — 주문·설정을 바꾸지 않습니다. 켜기·끄기는 관제실에서 사장님이.</div>`;
  }

  if (typeof window !== 'undefined') {
    window.loadStrategyCouncil = loadStrategyCouncil;
    document.addEventListener('DOMContentLoaded', () => {
      setTimeout(loadStrategyCouncil, 3000);
      setInterval(() => { if (!document.hidden) loadStrategyCouncil(); }, 10 * 60000);
    });
  }
})();
