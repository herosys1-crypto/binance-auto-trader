/**
 * Trade History Modal — Phase 3 추가 분리 (2026-05-14).
 *
 * 「📊 거래 실적 상세」 모달 — 기간별 (오늘/7일/30일/전체) 진입/청산 + 실현 PnL.
 * 일별 합계 row 클릭 → 해당 날짜만 필터링.
 *
 * Backend endpoint:
 *   - GET /orders?limit=500
 *   - GET /strategies (PnL 계산에 strategy.side 등 필요)
 *
 * 의존성:
 *   - api()              → /static/js/api.js
 *   - fmtNum / fmtQty    → /static/js/helpers.js
 *   - DOM: #trade-history-modal, #th-summary, #th-daily, #th-orders
 *
 * 캐시 (모달 내부 상태):
 *   - _thCache.allFilled        : 모든 FILLED 주문
 *   - _thCache.strategiesById   : strategy id → strategy
 *   - _thCache.currentFilter    : 현재 일자 필터 ('YYYY-MM-DD' or null)
 */

async function openTradeHistoryModal() {
  // 모달 동적 생성 (한 번만)
  let modal = document.getElementById('trade-history-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'trade-history-modal';
    modal.className = 'hidden fixed inset-0 z-50 flex items-center justify-center';
    modal.style.cssText = 'background:rgba(0,0,0,0.7); padding:10px;';
    modal.innerHTML = `
      <div class="card rounded-xl p-4" style="max-width:1000px; width:100%; max-height:92vh; overflow-y:auto;">
        <div class="flex justify-between items-center mb-3">
          <h2 class="text-lg font-bold">📊 거래 실적 상세</h2>
          <button onclick="closeTradeHistoryModal()" class="text-slate-400 hover:text-white text-xl">✕</button>
        </div>
        <!-- 기간 필터 -->
        <div class="flex gap-2 mb-3 flex-wrap items-center">
          <span class="text-xs text-slate-300">기간:</span>
          <button class="btn-ghost btn text-xs" style="padding:4px 10px" onclick="loadTradeHistory(1)">오늘</button>
          <button class="btn-ghost btn text-xs" style="padding:4px 10px" onclick="loadTradeHistory(7)">7일</button>
          <button class="btn-ghost btn text-xs" style="padding:4px 10px" onclick="loadTradeHistory(30)">30일</button>
          <button class="btn-ghost btn text-xs" style="padding:4px 10px" onclick="loadTradeHistory(0)">전체</button>
          <span class="text-xs text-slate-500 ml-auto" id="th-summary">-</span>
        </div>
        <!-- 일별 합계 -->
        <div class="card rounded mb-3" style="background:#0f172a">
          <div class="card-header text-xs" style="padding:6px 10px">📅 일별 합계</div>
          <div class="overflow-auto" style="max-height:160px">
            <table class="min-w-max">
              <thead>
                <tr><th>날짜</th><th class="num">진입 건수</th><th class="num">청산 건수</th><th class="num">실현 PnL</th></tr>
              </thead>
              <tbody id="th-daily"><tr><td colspan="4" class="text-center text-slate-500 py-2 text-xs">로딩 중...</td></tr></tbody>
            </table>
          </div>
        </div>
        <!-- 거래 내역 (모든 ENTRY/EXIT 주문) -->
        <div class="card rounded">
          <div class="card-header text-xs" style="padding:6px 10px">📦 거래 내역 (최신순)</div>
          <div class="overflow-auto" style="max-height:380px">
            <table class="min-w-max">
              <thead>
                <tr>
                  <th>시각</th>
                  <th>전략 #</th>
                  <th>심볼</th>
                  <th>방향</th>
                  <th>단계/유형</th>
                  <th class="num">수량</th>
                  <th class="num">평균가</th>
                  <th class="num">실현 PnL</th>
                  <th>상태</th>
                </tr>
              </thead>
              <tbody id="th-orders"><tr><td colspan="9" class="text-center text-slate-500 py-2 text-xs">로딩 중...</td></tr></tbody>
            </table>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
  }
  modal.classList.remove('hidden');
  loadTradeHistory(7);  // 기본 7일
}

function closeTradeHistoryModal() {
  const m = document.getElementById('trade-history-modal');
  if (m) m.classList.add('hidden');
}

// 거래 실적 모달의 캐시 — 일별 필터링 시 재요청 안 하기 위해
let _thCache = { allFilled: [], strategiesById: {}, currentFilter: null };

async function loadTradeHistory(days) {
  try {
    // 동시에 /orders + /strategies 가져옴 (PnL 계산에 strategy.side, avg_entry_price 필요)
    const [orders, strategies] = await Promise.all([
      api('/orders?limit=500'),
      api('/strategies').catch(() => []),
    ]);
    _thCache.strategiesById = {};
    strategies.forEach(s => { _thCache.strategiesById[s.id] = s; });

    const cutoff = days > 0 ? new Date(Date.now() - days * 86400000) : null;
    const filtered = cutoff ? orders.filter(o => new Date(o.created_at) >= cutoff) : orders;
    const filled = filtered.filter(o => (o.status || '').toUpperCase() === 'FILLED');

    // 각 주문별 PnL — 백엔드의 정확한 계산 (cumulative entries before exit) 사용.
    // 2026-05-08 fix: 이전엔 strat.avg_entry_price 로 계산했는데 COMPLETED strategy 는
    // 그 값이 0 이라 모든 EXIT 가 거대한 음수로 표시되던 버그 (사용자 #113 VVVUSDT 보고).
    // /orders 가 이미 realized_pnl 정확히 계산해서 응답하므로 그것을 그대로 사용.
    const _EXIT_PURPOSES = new Set(['EXIT', 'TAKE_PROFIT', 'STOP_LOSS', 'EMERGENCY_CLOSE']);
    const annotated = filled.map(o => {
      const strat = _thCache.strategiesById[o.strategy_instance_id];
      let pnl = null;
      if (_EXIT_PURPOSES.has(o.purpose) && o.realized_pnl !== null && o.realized_pnl !== undefined) {
        pnl = Number(o.realized_pnl);
      }
      return { ...o, _pnl: pnl, _side_long_short: strat?.side };
    });
    _thCache.allFilled = annotated;
    _thCache.currentFilter = null;

    // 일별 합계
    const byDay = {};
    annotated.forEach(o => {
      const d = (o.created_at || '').slice(0, 10);
      if (!byDay[d]) byDay[d] = { date: d, entries: 0, exits: 0, pnl: 0 };
      if (o.purpose === 'ENTRY') byDay[d].entries++;
      else if (_EXIT_PURPOSES.has(o.purpose)) {
        byDay[d].exits++;
        if (o._pnl !== null) byDay[d].pnl += o._pnl;
      }
    });
    const days_arr = Object.values(byDay).sort((a, b) => b.date.localeCompare(a.date));
    const totalPnl = days_arr.reduce((s, d) => s + d.pnl, 0);
    document.getElementById('th-daily').innerHTML = days_arr.length === 0
      ? '<tr><td colspan="4" class="text-center text-slate-500 py-2 text-xs">데이터 없음</td></tr>'
      : days_arr.map(d => {
          const pnlCls = d.pnl > 0 ? 'pos' : (d.pnl < 0 ? 'neg' : 'text-slate-400');
          const pnlText = d.pnl !== 0 ? `${d.pnl > 0 ? '+' : ''}${d.pnl.toFixed(4)}` : '-';
          return `<tr class="row-clickable" onclick="filterTradeHistoryByDate('${d.date}')" title="클릭하면 ${d.date} 거래만 보기">
            <td>${d.date} 🔍</td>
            <td class="num">${d.entries}</td>
            <td class="num">${d.exits}</td>
            <td class="num ${pnlCls}">${pnlText}</td>
          </tr>`;
        }).join('') + `<tr style="border-top:2px solid #334155">
          <td><strong>합계</strong></td>
          <td class="num">${days_arr.reduce((s, d) => s + d.entries, 0)}</td>
          <td class="num">${days_arr.reduce((s, d) => s + d.exits, 0)}</td>
          <td class="num ${totalPnl > 0 ? 'pos' : (totalPnl < 0 ? 'neg' : 'text-slate-400')}"><strong>${totalPnl > 0 ? '+' : ''}${totalPnl.toFixed(4)}</strong></td>
        </tr>`;

    _renderTradeOrdersTable(annotated);
    document.getElementById('th-summary').textContent =
      `${days > 0 ? `최근 ${days}일` : '전체'} · FILLED ${annotated.length}건 · 일자 ${days_arr.length}개 · 실현 PnL ${totalPnl > 0 ? '+' : ''}${totalPnl.toFixed(4)} USDT`;
  } catch (e) {
    document.getElementById('th-orders').innerHTML =
      `<tr><td colspan="9" class="text-center text-red-400 py-2 text-xs">조회 실패: ${e.message}</td></tr>`;
  }
}

function filterTradeHistoryByDate(date) {
  // 일별 합계 row 클릭 시 해당 날짜만 거래 내역에 표시
  if (_thCache.currentFilter === date) {
    // 이미 필터링된 같은 날짜 다시 클릭 → 필터 해제
    _thCache.currentFilter = null;
    _renderTradeOrdersTable(_thCache.allFilled);
    document.getElementById('th-summary').textContent += ' (필터 해제)';
    return;
  }
  _thCache.currentFilter = date;
  const filtered = _thCache.allFilled.filter(o => (o.created_at || '').slice(0, 10) === date);
  _renderTradeOrdersTable(filtered);
  const dayPnl = filtered.filter(o => o._pnl !== null).reduce((s, o) => s + o._pnl, 0);
  document.getElementById('th-summary').textContent =
    `📅 ${date} 만 표시 · ${filtered.length}건 · 실현 PnL ${dayPnl > 0 ? '+' : ''}${dayPnl.toFixed(4)} USDT (다시 클릭하면 해제)`;
}

function _renderTradeOrdersTable(orders) {
  const _EXIT_PURPOSES = new Set(['EXIT', 'TAKE_PROFIT', 'STOP_LOSS', 'EMERGENCY_CLOSE']);
  const purposeMap = { ENTRY: '진입', TAKE_PROFIT: '익절', STOP_LOSS: '손절', EMERGENCY_CLOSE: '긴급청산', EXIT: '청산' };
  document.getElementById('th-orders').innerHTML = orders.length === 0
    ? '<tr><td colspan="9" class="text-center text-slate-500 py-2 text-xs">조건 맞는 주문 없음</td></tr>'
    : orders.slice(0, 300).map(o => {
      const sideKo = o.side === 'BUY' ? '🟢 매수' : '🔴 매도';
      const purpose = purposeMap[o.purpose] || o.purpose;
      const stage = o.stage_no ? `${o.stage_no}단계` : '';
      let pnlHtml = '<span class="text-slate-500">-</span>';
      if (o._pnl !== null && o._pnl !== undefined) {
        const cls = o._pnl > 0 ? 'pos' : (o._pnl < 0 ? 'neg' : '');
        pnlHtml = `<span class="${cls}">${o._pnl > 0 ? '+' : ''}${o._pnl.toFixed(4)}</span>`;
      }
      return `<tr>
        <td class="text-xs">${(o.created_at || '').replace('T', ' ').slice(0, 19)}</td>
        <td>#${o.strategy_instance_id || '-'}</td>
        <td class="font-mono text-blue-300">${o.symbol}</td>
        <td>${sideKo}</td>
        <td>${stage} ${purpose}</td>
        <td class="num">${o.executed_qty ? fmtQty(o.executed_qty) : '-'}</td>
        <td class="num">${o.avg_price ? fmtNum(o.avg_price) : '-'}</td>
        <td class="num">${pnlHtml}</td>
        <td>${o.status}</td>
      </tr>`;
    }).join('');
}
