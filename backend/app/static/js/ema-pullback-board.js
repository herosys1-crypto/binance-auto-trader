/**
 * 🗓 Fix 424 (2026-10-09 사장님) — EMA 추세 눌림 「진입 준비」·「진입 신호」 카드 (일봉 기준).
 *
 * API: GET /api/v1/ema-pullback/board  (emapb_watch 워커가 15분마다 갱신)
 * DOM: #ema-pullback-card · #ema-pullback-count · #ema-pullback-list · #ema-pullback-meta
 * 알림 전용 — 주문 버튼 없음. 숨김 탭이면 갱신하지 않는다 (Fix 418 과 같은 방식).
 */
(function () {
  function fmt(x) {
    if (x === null || x === undefined || isNaN(Number(x))) return '-';
    const n = Number(x);
    return Math.abs(n) >= 100 ? n.toFixed(2) : Number(n.toPrecision(5)).toString();
  }

  async function loadEmaPullbackBoard() {
    const card = document.getElementById('ema-pullback-card');
    const countEl = document.getElementById('ema-pullback-count');
    const listEl = document.getElementById('ema-pullback-list');
    const metaEl = document.getElementById('ema-pullback-meta');
    if (!card || !countEl || !listEl) return;
    let data;
    try {
      data = await api('/ema-pullback/board');
    } catch (e) {
      return;
    }
    const items = (data && data.items) || [];
    countEl.textContent = String(items.length);
    if (metaEl) {
      const at = data && data.at ? new Date(data.at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }) : '-';
      metaEl.textContent = `${(data && data.interval) || '1d'} 기준 · 갱신 ${at}`;
    }
    if (!items.length) {
      card.classList.add('hidden');
      listEl.innerHTML = '';
      return;
    }
    card.classList.remove('hidden');
    listEl.innerHTML = items.map(it => {
      const isLong = it.side === 'LONG';
      const color = isLong ? '#22c55e' : '#ef4444';
      const sig = it.kind === 'signal';
      const badge = sig ? '✅ 진입 신호' : '⏳ 진입 준비';
      const extra = sig
        ? `거래량 ×${Number(it.vol_ratio || 0).toFixed(2)}${it.confluence ? ' · 지표 겹침' : ''}`
        : `EMA20 대비 ${Number(it.dist_pct || 0) >= 0 ? '+' : ''}${Number(it.dist_pct || 0).toFixed(2)}%`;
      return `<div style="border:1px solid ${color}55;border-radius:6px;padding:4px 8px;font-size:12px;background:${color}14">
        <b style="color:${color}">${isLong ? '🟢 LONG' : '🔴 SHORT'}</b> <b>${(it.symbol || '').replace('USDT', '')}</b>
        <span style="color:${sig ? '#facc15' : '#93c5fd'}">${badge}</span><br>
        <span class="text-slate-400">${sig ? '종가' : '현재가'} ${fmt(it.price)} · EMA20 ${fmt(it.ema20)} · 손절 ${fmt(it.stop)} · ${extra}</span>
      </div>`;
    }).join('');
  }

  if (typeof window !== 'undefined') {
    window.loadEmaPullbackBoard = loadEmaPullbackBoard;
    document.addEventListener('DOMContentLoaded', () => {
      setTimeout(loadEmaPullbackBoard, 2500);
      setInterval(() => { if (!document.hidden) loadEmaPullbackBoard(); }, 60000);
    });
  }
})();
