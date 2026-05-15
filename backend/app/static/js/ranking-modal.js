/**
 * Ranking Modal (시장 순위 모달) — Phase 3 추가 분리 (2026-05-14).
 *
 * 사용자 요청 (2026-05-06): 「📈 시장 순위」 — 24h/2~7d/1w/2w/1m/3m/6m/1y 변동률
 * 상승/하락 top 30. 빠른 작업 패널 + 새 전략 모달의 시작가 영역에서 호출.
 *
 * Backend endpoint: GET /symbols/ranking?period=...&direction=...&limit=30
 *
 * 의존성:
 *   - api(), toast()         → /static/js/api.js
 *   - fmtNum()                → /static/js/helpers.js
 *   - renderWhitelistBadge()  → index.html (호출 시점에 정의됨)
 *   - refreshCmMarketInfo()   → index.html (신규 전략 모달 함수)
 *   - DOM: #symbol-ranking-modal, .sr-period, .sr-dir, #sr-title, #sr-summary, #sr-rows,
 *          #cm-symbol, #cm-start-price, #create-modal
 */

async function openSymbolRankingModal(direction) {
  let modal = document.getElementById('symbol-ranking-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'symbol-ranking-modal';
    modal.className = 'hidden fixed inset-0 z-50 flex items-center justify-center';
    modal.style.cssText = 'background:rgba(0,0,0,0.7); padding:10px;';
    modal.innerHTML = `
      <div class="card rounded-xl p-4" style="max-width:900px; width:100%; max-height:92vh; overflow-y:auto;">
        <div class="flex justify-between items-center mb-3">
          <h2 class="text-lg font-bold">📈 <span id="sr-title">시장 순위</span></h2>
          <button onclick="closeSymbolRankingModal()" class="text-slate-400 hover:text-white text-xl">✕</button>
        </div>
        <!-- 방향 toggle -->
        <div class="flex gap-2 mb-3 flex-wrap items-center">
          <span class="text-xs text-slate-300">방향:</span>
          <button class="btn-ghost btn text-xs sr-dir" data-dir="gainers" onclick="loadSymbolRanking(null, 'gainers')">📈 상승 top</button>
          <button class="btn-ghost btn text-xs sr-dir" data-dir="losers" onclick="loadSymbolRanking(null, 'losers')">📉 하락 top</button>
          <span class="text-xs text-slate-500 ml-auto" id="sr-summary">-</span>
        </div>
        <!-- 기간 탭 -->
        <div class="flex gap-1 mb-3 flex-wrap items-center">
          <span class="text-xs text-slate-300 mr-1">기간:</span>
          <button class="btn-ghost btn text-xs sr-period" data-period="1d" onclick="loadSymbolRanking('1d', null)">1d</button>
          <button class="btn-ghost btn text-xs sr-period" data-period="2d" onclick="loadSymbolRanking('2d', null)">2d</button>
          <button class="btn-ghost btn text-xs sr-period" data-period="3d" onclick="loadSymbolRanking('3d', null)">3d</button>
          <button class="btn-ghost btn text-xs sr-period" data-period="4d" onclick="loadSymbolRanking('4d', null)">4d</button>
          <button class="btn-ghost btn text-xs sr-period" data-period="5d" onclick="loadSymbolRanking('5d', null)">5d</button>
          <button class="btn-ghost btn text-xs sr-period" data-period="6d" onclick="loadSymbolRanking('6d', null)">6d</button>
          <button class="btn-ghost btn text-xs sr-period" data-period="7d" onclick="loadSymbolRanking('7d', null)">7d</button>
          <span class="text-slate-700">|</span>
          <button class="btn-ghost btn text-xs sr-period" data-period="1w" onclick="loadSymbolRanking('1w', null)">1w</button>
          <button class="btn-ghost btn text-xs sr-period" data-period="2w" onclick="loadSymbolRanking('2w', null)">2w</button>
          <button class="btn-ghost btn text-xs sr-period" data-period="1m" onclick="loadSymbolRanking('1m', null)">1m</button>
          <button class="btn-ghost btn text-xs sr-period" data-period="3m" onclick="loadSymbolRanking('3m', null)">3m</button>
          <button class="btn-ghost btn text-xs sr-period" data-period="6m" onclick="loadSymbolRanking('6m', null)">6m</button>
          <button class="btn-ghost btn text-xs sr-period" data-period="1y" onclick="loadSymbolRanking('1y', null)">1y</button>
        </div>
        <!-- 테이블 -->
        <div class="card rounded">
          <div class="card-header text-xs" style="padding:6px 10px">📋 순위 (USDT/USDC perpetual)</div>
          <div class="overflow-auto" style="max-height:520px">
            <table class="min-w-max">
              <thead>
                <tr><th>순위</th><th>심볼</th><th class="num">현재가</th><th class="num">변동률</th><th class="num">24h 거래대금</th><th>액션</th></tr>
              </thead>
              <tbody id="sr-rows"><tr><td colspan="6" class="text-center text-slate-500 py-2 text-xs">로딩 중...</td></tr></tbody>
            </table>
          </div>
        </div>
        <p class="text-xs text-slate-500 mt-2">📌 1d 는 모든 USDT/USDC perpetual, 그 외 기간은 24h 거래대금 top 50 만 정확 계산. Redis 캐시: 1d=60s, 1w=5m, 1m=30m.</p>
      </div>
    `;
    document.body.appendChild(modal);
  }
  modal.classList.remove('hidden');
  // 상태: 마지막 선택 보존 (없으면 default)
  if (!window._srState) window._srState = { period: '1d', direction: 'gainers' };
  if (direction) window._srState.direction = direction;
  loadSymbolRanking(window._srState.period, window._srState.direction);
}

function closeSymbolRankingModal() {
  const m = document.getElementById('symbol-ranking-modal');
  if (m) m.classList.add('hidden');
}

async function loadSymbolRanking(period, direction) {
  if (!window._srState) window._srState = { period: '1d', direction: 'gainers' };
  if (period) window._srState.period = period;
  if (direction) window._srState.direction = direction;
  const p = window._srState.period;
  const d = window._srState.direction;

  // 활성 표시
  document.querySelectorAll('#symbol-ranking-modal .sr-period').forEach(b => {
    if (b.dataset.period === p) {
      b.classList.add('btn-primary'); b.classList.remove('btn-ghost');
    } else {
      b.classList.add('btn-ghost'); b.classList.remove('btn-primary');
    }
  });
  document.querySelectorAll('#symbol-ranking-modal .sr-dir').forEach(b => {
    if (b.dataset.dir === d) {
      b.classList.add(d === 'gainers' ? 'btn-success' : 'btn-danger'); b.classList.remove('btn-ghost');
    } else {
      b.classList.add('btn-ghost'); b.classList.remove('btn-success', 'btn-danger');
    }
  });
  const titleMap = {
    '1d': '24시간', '2d': '2일', '3d': '3일', '4d': '4일', '5d': '5일', '6d': '6일', '7d': '7일',
    '1w': '1주', '2w': '2주', '1m': '1개월', '3m': '3개월', '6m': '6개월', '1y': '1년',
  };
  const dirKo = d === 'gainers' ? '📈 상승' : '📉 하락';
  document.getElementById('sr-title').textContent = `시장 순위 — ${titleMap[p] || p} ${dirKo}`;

  try {
    const r = await api(`/symbols/ranking?period=${encodeURIComponent(p)}&direction=${encodeURIComponent(d)}&limit=30`);
    document.getElementById('sr-summary').textContent =
      `${r.count}건 · cache=${r.cached ? 'hit' : 'miss'}`;
    const rowsEl = document.getElementById('sr-rows');
    if (!r.items || r.items.length === 0) {
      rowsEl.innerHTML = '<tr><td colspan="6" class="text-center text-slate-500 py-2 text-xs">데이터 없음</td></tr>';
      return;
    }
    // 새 전략 모달이 열려있는 상태인가? (모달 안 모달)
    const createModalOpen = !document.getElementById('create-modal').classList.contains('hidden');
    rowsEl.innerHTML = r.items.map((it, i) => {
      const chg = Number(it.change_pct);
      const cls = chg > 0 ? 'pos' : chg < 0 ? 'neg' : '';
      const sign = chg > 0 ? '+' : '';
      const vol = Number(it.quote_volume);
      const volStr = vol > 1e9 ? (vol/1e9).toFixed(2) + 'B' : vol > 1e6 ? (vol/1e6).toFixed(1) + 'M' : vol.toFixed(0);
      // 새 전략 모달이 열려있으면 「선택」 버튼, 아니면 정보 표시만
      const action = createModalOpen
        ? `<button class="btn-success btn text-xs" style="padding:3px 10px" onclick="selectSymbolFromRanking('${it.symbol}', '${it.last_price}')">↑ 선택</button>`
        : `<span class="text-slate-500 text-xs">-</span>`;
      return `<tr>
        <td>${i + 1}</td>
        <td class="font-mono text-blue-300">${it.symbol}${renderWhitelistBadge(it.symbol)}</td>
        <td class="num">${fmtNum(it.last_price)}</td>
        <td class="num ${cls}">${sign}${chg.toFixed(2)}%</td>
        <td class="num text-slate-400 text-xs">${volStr} USDT</td>
        <td>${action}</td>
      </tr>`;
    }).join('');
  } catch (e) {
    document.getElementById('sr-rows').innerHTML =
      `<tr><td colspan="6" class="text-center text-red-400 py-2 text-xs">조회 실패: ${e.message}</td></tr>`;
  }
}

// 새 전략 모달이 열려있을 때 ranking 모달의 「선택」 버튼 클릭 → 심볼 + 시작가 채움
function selectSymbolFromRanking(symbol, lastPrice) {
  const symInp = document.getElementById('cm-symbol');
  const startInp = document.getElementById('cm-start-price');
  if (symInp) symInp.value = symbol;
  // 심볼 변경 후 시세 갱신 (시작가 자동 채움 함수 호출)
  if (typeof refreshCmMarketInfo === 'function') {
    refreshCmMarketInfo();
  } else if (startInp) {
    startInp.value = lastPrice;
  }
  closeSymbolRankingModal();
  toast(`✅ ${symbol} 선택됨 — 시작가 자동 채움`, 'success');
}
