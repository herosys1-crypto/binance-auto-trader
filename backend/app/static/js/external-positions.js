/**
 * 외부 포지션 카드 — 도구가 추적 안 하는 거래소 포지션 표시 (2026-05-21 사장님 요구).
 *
 * 배경 (#77 PHB +157 / RONIN +26 사례 후속):
 *   사장님이 거래소 UI 에서 직접 진입한 포지션 (도구 밖) 이 대시보드에 안 보여서
 *   운영 시 인지 못 함. 이제 「📊 외부 포지션」 카드로 별도 표시.
 *
 * 동작:
 *   - 「🔄 새로고침」 클릭 시 GET /positions/external 호출 (rate limit 부담 고려)
 *   - 결과 0건이면 「외부 포지션 없음 — 모두 도구 추적 중」 표시
 *   - 자동 관리 X — 단순 가시성. 사장님이 거래소에서 직접 처리.
 *
 * 외부 의존:
 *   - api, toast (api.js)
 *   - fmtNum, fmtQty, fmtPnL (helpers.js)
 *   - DOM: #external-positions-tbody, #external-positions-status
 */

async function refreshExternalPositions() {
  const tbody = document.getElementById('external-positions-tbody');
  const statusEl = document.getElementById('external-positions-status');
  if (!tbody || !statusEl) return;

  statusEl.textContent = '⏳ 거래소 조회 중...';
  tbody.innerHTML = '';

  try {
    const data = await api('/positions/external');
    if (!Array.isArray(data) || data.length === 0) {
      statusEl.innerHTML = '<span class="text-emerald-400">✓ 외부 포지션 없음 — 모든 거래소 포지션이 도구 추적 중.</span>';
      tbody.innerHTML = '<tr><td colspan="7" class="text-center text-slate-500 py-3 text-xs">외부 포지션 없음</td></tr>';
      return;
    }

    // 총 미실현 PnL 합계
    let totalPnL = 0;
    data.forEach(p => { totalPnL += Number(p.unrealized_pnl || 0); });
    const pnlClass = totalPnL > 0 ? 'pos' : totalPnL < 0 ? 'neg' : '';
    statusEl.innerHTML = (
      `<span class="text-amber-400">⚠️ 외부 포지션 ${data.length}건 — </span>` +
      `<span class="${pnlClass} font-semibold">합계 PnL ${fmtPnL(totalPnL)} USDT</span>` +
      `<span class="text-slate-500 text-xs"> · 도구 밖에서 사장님이 직접 진입 (자동 청산/관리 X)</span>`
    );

    tbody.innerHTML = data.map(p => {
      const qtyNum = Number(p.position_amt || 0);
      const qtyClass = qtyNum < 0 ? 'neg' : 'pos';
      const pnlNum = Number(p.unrealized_pnl || 0);
      const pnlClass2 = pnlNum > 0 ? 'pos' : pnlNum < 0 ? 'neg' : '';
      const sideBadge = p.side === 'LONG'
        ? '<span class="badge badge-green">🟢 LONG</span>'
        : '<span class="badge badge-red">🔴 SHORT</span>';
      const priceStack = `<div class="text-xs leading-tight">
        <span class="text-slate-300" title="평단가">${p.entry_price ? fmtNum(p.entry_price) : '-'}</span><br>
        <span class="text-cyan-300" title="마크가">${p.mark_price ? fmtNum(p.mark_price) : '-'}</span>
      </div>`;
      const marginInfo = `<div class="text-xs leading-tight">
        <span class="text-slate-300">${p.leverage ? p.leverage + 'x' : '-'}</span><br>
        <span class="text-slate-500" style="font-size:10px">${p.margin_type || '-'}</span>
      </div>`;
      return `<tr>
        <td class="text-xs"><span class="text-slate-400">${escapeHtml(p.account_label || '')}</span></td>
        <td class="font-mono text-blue-300 text-xs">${escapeHtml(p.symbol)}</td>
        <td>${sideBadge}</td>
        <td class="num"><span class="${qtyClass} font-semibold text-xs">${fmtQty(qtyNum)}</span></td>
        <td class="num">${priceStack}</td>
        <td class="num"><span class="${pnlClass2} font-semibold text-xs">${fmtPnL(pnlNum)}</span></td>
        <td class="num">${marginInfo}</td>
      </tr>`;
    }).join('');
  } catch (err) {
    statusEl.innerHTML = `<span class="text-red-400">❌ 조회 실패: ${escapeHtml(err.message || String(err))}</span>`;
    tbody.innerHTML = '';
    toast('외부 포지션 조회 실패: ' + (err.message || err), 'error');
  }
}
