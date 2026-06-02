/**
 * Ranking Page (시장 순위 별도 페이지) — Phase 3 추가 분리 (2026-05-14).
 *
 * 사용자 요청 (2026-05-06): #ranking hash 진입 → 24h/2~7d/1w/2w/1m/3m/6m/1y 변동률
 * 상승/하락 top 종목 + 「↑ 새 전략」 빠른 진입.
 *
 * Backend endpoint: GET /symbols/ranking?period=...&direction=...&limit=...
 *
 * 의존성:
 *   - api()                  → /static/js/api.js
 *   - renderWhitelistBadge() → index.html (helpers, 호출 시점)
 *   - fmtNum()                → index.html (helpers)
 *   - navigateTo()            → index.html (page navigation)
 *   - openCreateModal()       → index.html (신규 전략 모달)
 *   - refreshCmMarketInfo()   → index.html (모달 시세 갱신)
 *   - toast()                 → /static/js/api.js
 *   - DOM: #page-ranking, .rp-period, .rp-dir, #rp-limit, #rp-summary, #rp-rows
 */

async function loadRankingPage(period, direction) {
  if (!window._rpState) window._rpState = { period: '1d', direction: 'gainers' };
  if (period) window._rpState.period = period;
  if (direction) window._rpState.direction = direction;
  const p = window._rpState.period;
  const d = window._rpState.direction;
  const lim = Number(document.getElementById('rp-limit').value) || 30;

  // 활성 표시
  document.querySelectorAll('#page-ranking .rp-period').forEach(b => {
    if (b.dataset.period === p) {
      b.classList.add('btn-primary'); b.classList.remove('btn-ghost');
    } else {
      b.classList.add('btn-ghost'); b.classList.remove('btn-primary');
    }
  });
  document.querySelectorAll('#page-ranking .rp-dir').forEach(b => {
    if (b.dataset.dir === d) {
      b.classList.add(d === 'gainers' ? 'btn-success' : 'btn-danger'); b.classList.remove('btn-ghost');
    } else {
      b.classList.add('btn-ghost'); b.classList.remove('btn-success', 'btn-danger');
    }
  });

  try {
    const r = await api(`/symbols/ranking?period=${encodeURIComponent(p)}&direction=${encodeURIComponent(d)}&limit=${lim}`);
    document.getElementById('rp-summary').textContent =
      `${r.count}건 · cache=${r.cached ? 'hit' : 'miss'} · period=${p} · ${d === 'gainers' ? '📈 상승' : '📉 하락'}`;
    const rowsEl = document.getElementById('rp-rows');
    if (!r.items || r.items.length === 0) {
      rowsEl.innerHTML = '<tr><td colspan="6" class="text-center text-slate-500 py-3 text-xs">데이터 없음</td></tr>';
      return;
    }
    rowsEl.innerHTML = r.items.map((it, i) => {
      const chg = Number(it.change_pct);
      const cls = chg > 0 ? 'pos' : chg < 0 ? 'neg' : '';
      const sign = chg > 0 ? '+' : '';
      const vol = Number(it.quote_volume);
      const volStr = vol > 1e9 ? (vol/1e9).toFixed(2) + 'B' : vol > 1e6 ? (vol/1e6).toFixed(1) + 'M' : vol.toFixed(0);
      // 새 전략 시작 link — 페이지에선 「↑ 새 전략」 으로 표시 (모달 열림 + 심볼 자동 채움)
      const action =
        `<button class="btn-success btn text-xs" style="padding:3px 10px"
          onclick="startNewStrategyFromRanking('${it.symbol}', '${it.last_price}')">↑ 새 전략</button>`;
      // 2026-06-02 (사장님 요구): 심볼 클릭 → Binance 선물 차트 새 탭. 매 클릭마다 별도 탭.
      const symbolLink = `<a href="https://www.binance.com/en/futures/${it.symbol}" target="_blank" rel="noopener"
            class="text-blue-300 hover:text-blue-100 hover:underline"
            title="🔗 ${it.symbol} — 바이낸스 선물 차트 새 탭 열기">${it.symbol}</a>`;
      return `<tr>
        <td>${i + 1}</td>
        <td class="font-mono">${symbolLink}${renderWhitelistBadge(it.symbol)}</td>
        <td class="num">${fmtNum(it.last_price)}</td>
        <td class="num ${cls}">${sign}${chg.toFixed(2)}%</td>
        <td class="num text-slate-400 text-xs">${volStr} USDT</td>
        <td>${action}</td>
      </tr>`;
    }).join('');
  } catch (e) {
    document.getElementById('rp-rows').innerHTML =
      `<tr><td colspan="6" class="text-center text-red-400 py-3 text-xs">조회 실패: ${e.message}</td></tr>`;
  }
}

// 페이지에서 「↑ 새 전략」 → 새 전략 모달 열기 + 심볼/시작가 자동 채움
function startNewStrategyFromRanking(symbol, lastPrice) {
  // dashboard 로 이동 후 새 전략 모달 호출
  navigateTo('dashboard');
  if (typeof openCreateModal === 'function') {
    openCreateModal();
    setTimeout(() => {
      const symInp = document.getElementById('cm-symbol');
      const startInp = document.getElementById('cm-start-price');
      if (symInp) symInp.value = symbol;
      if (typeof refreshCmMarketInfo === 'function') {
        refreshCmMarketInfo();
      } else if (startInp) {
        startInp.value = lastPrice;
      }
    }, 100);
  }
  toast(`✅ ${symbol} — 새 전략 모달 자동 열림`, 'success');
}
