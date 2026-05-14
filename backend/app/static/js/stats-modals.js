/**
 * Stats / Notification 상세 모달 — Phase 3 추가 분리 (2026-05-14).
 *
 * index.html 에서 분리한 자기-완결적 UI 기능 두 가지:
 *
 * 1. openStatsBreakdownModal(view)
 *    - 「운영 통계 (전체 누적)」 패널 셀 클릭 → 띄움
 *    - view: 'strategies' | 'realized' | 'losses'
 *    - 손익 분류 + 라이프사이클 + summary 4 카드
 *    - 사용자 요청 (2026-05-06): 합계 패널의 산출 근거 가시화
 *
 * 2. openTpNotificationsModal(level, label)
 *    - 「운영 통계」 의 TP1~10 / 🌀TRAIL 셀 클릭 → 띄움
 *    - 해당 level 의 알림 목록 + body 노출 (최대 500건)
 *    - 사용자 요청 (2026-05-12): TP 카운트의 raw 알림 확인
 *
 * 의존성 (loaded earlier 또는 호출 시점에 존재):
 *   - api()         → /static/js/api.js
 *   - escapeHtml()  → index.html (helpers 섹션, 호출 시점에 정의됨)
 *   - selectStrategy() → index.html (호출 시점에 정의됨)
 *
 * HTML inline handler 사용:
 *   - onclick="closeStatsBreakdownModal()"
 *   - onclick="loadStatsBreakdown('strategies')"
 *   - onclick="closeTpNotificationsModal(); selectStrategy(...)"
 *   → top-level function 선언이 자동으로 window 부착되는 비-모듈 script 동작 사용.
 */

// ==================== 운영 통계 상세 모달 (2026-05-06 사용자 요청) ====================
// 「운영 통계 (전체 누적)」 패널의 6개 셀 클릭 시 띄움. strategy 별 분류 + 손익 상세.
// view: 'strategies' | 'realized' | 'losses'
async function openStatsBreakdownModal(view) {
  let modal = document.getElementById('stats-breakdown-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'stats-breakdown-modal';
    modal.className = 'hidden fixed inset-0 z-50 flex items-center justify-center';
    modal.style.cssText = 'background:rgba(0,0,0,0.7); padding:10px;';
    modal.innerHTML = `
      <div class="card rounded-xl p-4" style="max-width:1100px; width:100%; max-height:92vh; overflow-y:auto;">
        <div class="flex justify-between items-center mb-3">
          <h2 class="text-lg font-bold">📊 <span id="sb-title">운영 통계 상세</span></h2>
          <button onclick="closeStatsBreakdownModal()" class="text-slate-400 hover:text-white text-xl">✕</button>
        </div>
        <!-- view 탭 -->
        <div class="flex gap-2 mb-2 flex-wrap items-center">
          <span class="text-xs text-slate-300">분류:</span>
          <button class="btn-ghost btn text-xs sb-tab" data-view="strategies" onclick="loadStatsBreakdown('strategies')">전략 전체</button>
          <button class="btn-ghost btn text-xs sb-tab" data-view="realized" onclick="loadStatsBreakdown('realized')">실현 손익 발생</button>
          <button class="btn-ghost btn text-xs sb-tab" data-view="losses" onclick="loadStatsBreakdown('losses')">손실/감사</button>
          <span class="text-xs text-slate-500 ml-auto" id="sb-summary">-</span>
        </div>
        <!-- 2026-05-08: view 별 안내 (사용자 「전체/실현 차이」 혼란 해소) -->
        <div id="sb-view-note" class="hidden text-xs text-yellow-300 mb-2 p-1 rounded bg-slate-800/40"></div>
        <!-- 요약 -->
        <div class="card rounded mb-3" style="background:#0f172a">
          <div class="p-2 grid grid-cols-4 gap-2 text-center text-xs">
            <div><p class="text-slate-400">건수</p><p id="sb-count" class="text-base font-bold">-</p></div>
            <div><p class="text-slate-400">수익 strategy</p><p id="sb-profit" class="text-base font-bold pos">-</p></div>
            <div><p class="text-slate-400">손실 strategy</p><p id="sb-loss" class="text-base font-bold neg">-</p></div>
            <div><p class="text-slate-400">합계 손익</p><p id="sb-sum" class="text-base font-bold">-</p></div>
          </div>
        </div>
        <!-- 테이블 -->
        <div class="card rounded">
          <div class="card-header text-xs" style="padding:6px 10px">📋 strategy 목록</div>
          <div class="overflow-auto" style="max-height:520px">
            <table class="min-w-max">
              <thead>
                <tr>
                  <th>#</th>
                  <th>심볼</th>
                  <th>방향</th>
                  <th>상태</th>
                  <th class="num">단계</th>
                  <th class="num">실현 PnL</th>
                  <th class="num">미실현</th>
                  <th class="num">최대 손실%</th>
                  <th class="num">최대 이익%</th>
                  <th>분류</th>
                  <th>archive</th>
                  <th>시작</th>
                </tr>
              </thead>
              <tbody id="sb-rows"><tr><td colspan="12" class="text-center text-slate-500 py-2 text-xs">로딩 중...</td></tr></tbody>
            </table>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
  }
  modal.classList.remove('hidden');
  loadStatsBreakdown(view || 'strategies');
}

function closeStatsBreakdownModal() {
  const m = document.getElementById('stats-breakdown-modal');
  if (m) m.classList.add('hidden');
}

async function loadStatsBreakdown(view) {
  // tab 활성 표시
  document.querySelectorAll('#stats-breakdown-modal .sb-tab').forEach(b => {
    if (b.dataset.view === view) {
      b.classList.add('btn-primary');
      b.classList.remove('btn-ghost');
    } else {
      b.classList.add('btn-ghost');
      b.classList.remove('btn-primary');
    }
  });
  const titleMap = {
    strategies: '운영 통계 상세 — 전략 전체',
    realized: '운영 통계 상세 — 실현 손익 발생 strategy',
    losses: '운영 통계 상세 — 손실/감사',
  };
  document.getElementById('sb-title').textContent = titleMap[view] || '운영 통계 상세';
  // 2026-05-08: view 별 안내 — 「전체 vs 실현」 차이 사용자 혼란 해소
  const noteMap = {
    strategies: '모든 strategy 표시 (진행중 + 미체결 종료 + 청산 완료 모두)',
    realized: 'realized_pnl ≠ 0 인 strategy 만 (진행중 / 미진입 종료 STOPPED 는 제외)',
    losses: '감사 대상: 손실 / 큰 낙폭(-10%↓) / 수동정지 / 크라이시스 진입 strategy (OR 조건)',
  };
  const noteEl = document.getElementById('sb-view-note');
  if (noteEl) {
    noteEl.textContent = `💡 ${noteMap[view] || ''}`;
    noteEl.classList.remove('hidden');
  }

  try {
    const r = await api(`/admin/stats/breakdown?view=${encodeURIComponent(view)}`);
    document.getElementById('sb-count').textContent = r.count;
    document.getElementById('sb-profit').textContent = r.profit_count;
    document.getElementById('sb-loss').textContent = r.loss_count;
    const sumNum = Number(r.realized_pnl_sum || 0);
    const sumEl = document.getElementById('sb-sum');
    sumEl.textContent = (sumNum >= 0 ? '+' : '') + sumNum.toFixed(4) + ' USDT';
    sumEl.className = 'text-base font-bold ' + (sumNum > 0 ? 'pos' : sumNum < 0 ? 'neg' : '');
    const archivedNote = r.archived_count > 0 ? ` · 그 중 archive ${r.archived_count}` : '';
    document.getElementById('sb-summary').textContent =
      `view=${view} · ${r.count}건${archivedNote} · 합계 ${(sumNum >= 0 ? '+' : '') + sumNum.toFixed(4)} USDT`;

    const items = r.items || [];
    const rowsEl = document.getElementById('sb-rows');
    if (items.length === 0) {
      rowsEl.innerHTML = '<tr><td colspan="12" class="text-center text-slate-500 py-2 text-xs">데이터 없음</td></tr>';
      return;
    }
    const classBadge = (cls) => {
      if (cls === '수익') return '<span class="badge badge-green">수익</span>';
      if (cls === '손실') return '<span class="badge badge-red">손실</span>';
      if (cls === 'BREAKEVEN') return '<span class="badge badge-yellow">BREAKEVEN</span>';
      if (cls === '미진입_종료') return '<span class="badge badge-gray">미진입종료</span>';
      return '<span class="badge badge-blue">진행중</span>';
    };
    rowsEl.innerHTML = items.map(it => {
      const realized = Number(it.realized_pnl || 0);
      const unrl = Number(it.unrealized_pnl || 0);
      const realCls = realized > 0 ? 'pos' : realized < 0 ? 'neg' : 'text-slate-400';
      const unrlCls = unrl > 0 ? 'pos' : unrl < 0 ? 'neg' : 'text-slate-400';
      const sideKo = it.side === 'LONG' ? '🟢 LONG' : '🔴 SHORT';
      const archived = it.is_archived ? '📦' : '-';
      const startedAt = it.started_at ? it.started_at.replace('T', ' ').slice(0, 16) : (it.created_at ? it.created_at.replace('T', ' ').slice(0, 16) : '-');
      return `<tr>
        <td>#${it.id}</td>
        <td class="font-mono text-blue-300">${it.symbol}</td>
        <td>${sideKo}</td>
        <td class="text-xs">${it.status}</td>
        <td class="num">${it.current_stage || 0}</td>
        <td class="num ${realCls}">${realized > 0 ? '+' : ''}${realized.toFixed(4)}</td>
        <td class="num ${unrlCls}">${unrl !== 0 ? (unrl > 0 ? '+' : '') + unrl.toFixed(4) : '-'}</td>
        <td class="num">${it.max_loss_pct ?? '-'}</td>
        <td class="num">${it.max_profit_pct ?? '-'}</td>
        <td>${classBadge(it.classification)}${it.crisis_triggered ? ' 🛡' : ''}</td>
        <td class="text-center">${archived}</td>
        <td class="text-xs text-slate-400">${startedAt}</td>
      </tr>`;
    }).join('');
  } catch (e) {
    document.getElementById('sb-rows').innerHTML =
      `<tr><td colspan="12" class="text-center text-red-400 py-2 text-xs">조회 실패: ${e.message}</td></tr>`;
  }
}


// ==================== TP/TRAIL 알림 상세 모달 (2026-05-12 사용자 요청) ====================
// 「운영 통계」 의 TP1~10 / 🌀TRAIL 셀 클릭 시 띄움. 해당 level 의 알림 목록 + body 노출.
async function openTpNotificationsModal(level, label) {
  let modal = document.getElementById('tp-notif-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'tp-notif-modal';
    modal.className = 'hidden fixed inset-0 z-50 flex items-center justify-center';
    modal.style.cssText = 'background:rgba(0,0,0,0.7); padding:10px;';
    modal.innerHTML = `
      <div class="card rounded-xl p-4" style="max-width:1000px; width:100%; max-height:92vh; overflow-y:auto;">
        <div class="flex justify-between items-center mb-3">
          <h2 class="text-lg font-bold">📜 <span id="tpn-title">알림 상세</span></h2>
          <button onclick="closeTpNotificationsModal()" class="text-slate-400 hover:text-white text-xl">✕</button>
        </div>
        <div class="text-xs text-slate-400 mb-2" id="tpn-summary">-</div>
        <div class="overflow-auto" style="max-height:70vh">
          <div id="tpn-list" class="text-xs"><p class="text-slate-500 text-center py-4">로딩 중...</p></div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
  }
  modal.classList.remove('hidden');
  document.getElementById('tpn-title').textContent = `${label} (${level}) 알림 상세`;
  const listEl = document.getElementById('tpn-list');
  listEl.innerHTML = '<p class="text-slate-500 text-center py-4">로딩 중...</p>';
  try {
    const pattern = `%[${level} 익절%`;
    const data = await api(`/admin/notifications-by-title?title_like=${encodeURIComponent(pattern)}&limit=500`);
    document.getElementById('tpn-summary').textContent = `${level} 매칭 알림 ${data.length}건 (최신순, 최대 500건)`;
    if (!data.length) {
      listEl.innerHTML = `<p class="text-slate-500 text-center py-6">${level} 알림이 아직 없습니다.</p>`;
      return;
    }
    listEl.innerHTML = data.map(n => {
      const ts = new Date(n.ts);
      const tsStr = ts.toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
      const sideEmoji = n.side === 'SHORT' ? '📉' : (n.side === 'LONG' ? '📈' : '');
      const stratLink = n.strategy_id
        ? `<button onclick="closeTpNotificationsModal(); selectStrategy(${n.strategy_id})" class="text-blue-400 hover:underline">#${n.strategy_id}</button>`
        : '<span class="text-slate-500">-</span>';
      return `<div class="border-b border-slate-700 py-2 px-1 hover:bg-slate-800/30">
        <div class="flex gap-3 items-start">
          <div class="text-slate-500 font-mono whitespace-nowrap" style="min-width:120px">${tsStr}</div>
          <div class="whitespace-nowrap" style="min-width:140px">${stratLink} <span class="text-slate-300">${escapeHtml(n.symbol || '?')}</span> ${sideEmoji}</div>
          <div class="flex-1">
            <div class="text-slate-200 font-semibold mb-1">${escapeHtml(n.title)}</div>
            <pre class="text-slate-400 text-xs whitespace-pre-wrap font-mono" style="font-size:11px">${escapeHtml(n.body)}</pre>
          </div>
        </div>
      </div>`;
    }).join('');
  } catch (err) {
    listEl.innerHTML = `<p class="text-red-400 text-center py-4">조회 실패: ${escapeHtml(String(err.message || err))}</p>`;
  }
}

function closeTpNotificationsModal() {
  const m = document.getElementById('tp-notif-modal');
  if (m) m.classList.add('hidden');
}
