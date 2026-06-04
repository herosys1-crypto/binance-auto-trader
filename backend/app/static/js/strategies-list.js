/**
 * Strategies list panel — refresh + archive toggle + restore (Phase 3 단계 3m, 2026-05-15).
 *
 * 「🎯 전략 인스턴스」 panel 의 모든 액션 + state.
 *
 * 함수:
 *   - toggleShowArchivedStrategies()    : localStorage 저장 + 목록 갱신
 *   - _initArchiveToggleFromStorage()    : 페이지 진입 시 체크박스 복원
 *   - restoreStrategy(id)                : archived 전략 UI 목록에 다시 표시
 *   - refreshStrategies()                : 메인 전략 목록 fetch + 카드 렌더 (~244줄)
 *   - refreshExchangeAccounts()          : (legacy no-op, 별도 카드 없음)
 *
 * State (이 모듈 소유):
 *   - _showArchivedStrategies : 「📦 보관 보기」 체크박스 상태 (localStorage 동기화)
 *
 * 외부 의존성 (script-scope 공유):
 *   - api / toast (api.js)
 *   - statusInfo / sideBadge / fmtNum / fmtQty / fmtPnL / escapeHtml /
 *     renderStageBar / renderTpBar / setMetric (helpers.js)
 *   - renderWhitelistBadge (dashboard-refresh.js)
 *   - selectStrategy / triggerNextStage / addMargin / addPosition / stopStrategy /
 *     emergencyStop / deleteStrategy / editStrategy / restartStrategy (index.html)
 *   - _computeIsolatedLiqPrice (indicators.js)
 *   - DOM: #strategies-tbody, #show-archived, #metric-active*, #metric-active-symbols
 */

// refreshExchangeAccounts — legacy no-op (별도 카드 없음, 시스템 카드 detail 표시).
async function refreshExchangeAccounts() {
  try {
    await api('/exchange-accounts');
  } catch (err) { /* 무시 */ }
}

// 2026-06-01 (사장님 요구): 전략 인스턴스 행 아래 Binance 실데이터 인라인 비교 표시.
// account_id 별 snapshot 캐시 — refreshStrategies() 가 동시 fetch 후 _binanceCompareRow 가 읽음.
// Backend 30초 캐시 + Frontend in-memory cache → API 부담 최소화.
let _binancePositionsCache = {};  // { [accountId]: { fetched_at, positions: {symbol: {...}} } }

async function _fetchBinancePositionsForAccounts(accountIds) {
  if (!accountIds || accountIds.length === 0) return;
  const uniqueIds = [...new Set(accountIds)];
  await Promise.all(uniqueIds.map(async (id) => {
    try {
      const data = await api(`/exchange-accounts/${id}/binance-positions`);
      _binancePositionsCache[id] = data;
    } catch (e) {
      // 실패 시 stale cache 유지 (사장님이 stale 시각 보고 인지)
      console.warn(`[binance-compare] account=${id} fetch fail:`, e.message);
    }
  }));
}

// 우리 행 1줄 + 그 아래 Binance 비교 1줄 (colspan=9). Binance UI 컬럼명 동일.
// 2026-06-02 보강: 우리 DB vs Binance 차이 자동 감지 → 차이 발견 시 빨강 배경 + ⚠ 강조.
// 임계 = sync_health_monitor 와 동일 (수량 1%, 진입가 0.1%, uPnL 1 USDT).
function _binanceCompareRow(s) {
  const acctData = _binancePositionsCache[s.exchange_account_id];
  if (!acctData) {
    return `<tr class="bg-slate-900/40"><td colspan="9" class="text-xs text-slate-500 py-1 px-3">📊 Binance: 로딩 중...</td></tr>`;
  }
  const bp = (acctData.positions || {})[s.symbol];
  const ts = acctData.fetched_at
    ? new Date(acctData.fetched_at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
    : '-';
  // CASE A: Binance 에 포지션 없음 — 우리 DB 와 큰 차이 (가장 위험)
  if (!bp) {
    return `<tr class="bg-red-900/40 border-l-4 border-red-500">
      <td colspan="9" class="text-xs py-1 px-3 font-mono">
        <span class="text-red-300 font-bold">📊 Binance: ⚠ 거래소에 포지션 없음 — 큰 차이!</span>
        <span class="text-slate-400 ml-3">(우리 DB 만 있음 — 청산됐거나 다른 계정)</span>
        <span class="text-slate-500 ml-3">⏱ ${ts}</span>
      </td>
    </tr>`;
  }
  // CASE B: 양쪽 다 있음 — 필드별 차이 계산
  const ourQty = Number(s.current_position_qty || 0);
  const ourEntry = Number(s.avg_entry_price || 0);
  const ourUpnl = Number(s.unrealized_pnl || 0);
  const bnQty = Number(bp.size);
  const bnEntry = Number(bp.entry_price);
  const bnUpnl = Number(bp.unrealized_pnl);

  // sync_health_monitor 와 동일 임계
  const qtyDiffPct = ourQty !== 0 ? Math.abs((ourQty - bnQty) / ourQty * 100) : (bnQty !== 0 ? 100 : 0);
  const entryDiffPct = ourEntry > 0 ? Math.abs((ourEntry - bnEntry) / ourEntry * 100) : 0;
  const upnlDiff = Math.abs(ourUpnl - bnUpnl);
  const qtyMismatch = qtyDiffPct > 1.0;       // 수량 1% 이상 차이
  const entryMismatch = entryDiffPct > 0.1;   // 진입가 0.1% 이상 차이
  const upnlMismatch = upnlDiff > 1.0;        // 미실현 1 USDT 이상 차이
  const mismatchCount = (qtyMismatch?1:0) + (entryMismatch?1:0) + (upnlMismatch?1:0);
  const hasAnyMismatch = mismatchCount > 0;

  const roi = Number(bp.roi_pct);
  const upnl = Number(bp.unrealized_pnl);
  const roiCls = roi > 0 ? 'pos' : roi < 0 ? 'neg' : 'text-slate-400';
  const upnlSign = upnl >= 0 ? '+' : '';
  const roiSign = roi >= 0 ? '+' : '';
  const marginDisp = bp.margin ? `${Number(bp.margin).toFixed(2)} USDT` : '-';

  // 배경 + 헤더 — 차이 있으면 빨강, 없으면 회색 + ✓
  const rowBg = hasAnyMismatch ? 'bg-red-900/30 border-l-4 border-red-500' : 'bg-slate-900/40';
  const header = hasAnyMismatch
    ? `<span class="text-red-400 font-bold" title="차이 ${mismatchCount}건 — 호버로 우리 DB 값 확인">📊 Binance: ⚠ 차이 ${mismatchCount}건</span>`
    : `<span class="text-cyan-400 font-semibold">📊 Binance:</span> <span class="text-green-400 text-xs">✓ 일치</span>`;

  // 필드별 강조 — 차이 있는 필드만 빨강 + ⚠ + tooltip 으로 우리 DB 값
  const sizeCls = qtyMismatch ? 'text-red-400 font-bold' : (upnl>=0?'pos':'neg');
  const sizeWarn = qtyMismatch ? `<span class="text-red-400 ml-1" title="우리 DB: ${ourQty} (차이 ${qtyDiffPct.toFixed(1)}%)">⚠</span>` : '';
  const entryCls = entryMismatch ? 'text-red-400 font-bold' : 'text-slate-200';
  const entryWarn = entryMismatch ? `<span class="text-red-400 ml-1" title="우리 DB: ${ourEntry} (차이 ${entryDiffPct.toFixed(3)}%)">⚠</span>` : '';
  const pnlCls = upnlMismatch ? 'text-red-400 font-bold' : roiCls;
  const pnlWarn = upnlMismatch ? `<span class="text-red-400 ml-1" title="우리 DB: ${ourUpnl.toFixed(2)} USDT (차이 ${upnlDiff.toFixed(2)} USDT)">⚠</span>` : '';

  return `<tr class="${rowBg}">
    <td colspan="9" class="text-xs text-slate-300 py-1 px-3 font-mono">
      ${header}
      <span class="text-slate-500 ml-2">Size</span> <span class="${sizeCls}">${bp.size}</span>${sizeWarn}
      <span class="text-slate-600">|</span>
      <span class="text-slate-500">Entry</span> <span class="${entryCls}">${bp.entry_price}</span>${entryWarn}
      <span class="text-slate-600">|</span>
      <span class="text-slate-500">BE</span> ${bp.break_even_price}
      <span class="text-slate-600">|</span>
      <span class="text-slate-500">Mark</span> ${bp.mark_price}
      <span class="text-slate-600">|</span>
      <span class="text-slate-500">Margin</span> ${marginDisp} <span class="text-slate-500" style="font-size:10px">(${bp.margin_mode})</span>
      <span class="text-slate-600">|</span>
      <span class="text-slate-500">PNL</span> <span class="${pnlCls}">${upnlSign}${upnl.toFixed(2)} USDT</span>${pnlWarn}
      <span class="${roiCls}">(${roiSign}${roi.toFixed(2)}%)</span>
      <span class="text-slate-500 ml-3" title="Binance 호출 시각 (30초 캐시)">⏱ ${ts}</span>
    </td>
  </tr>`;
}

// 2026-05-06 (C-full Step 3): archived 보기 토글. localStorage 저장.
let _showArchivedStrategies = localStorage.getItem('show_archived_strategies') === 'true';

function toggleShowArchivedStrategies() {
  // 체크박스 직접 클릭 (DOM 이벤트) 시 호출 — 체크박스 state 가 source of truth.
  const cb = document.getElementById('show-archived');
  _showArchivedStrategies = cb ? cb.checked : !_showArchivedStrategies;
  localStorage.setItem('show_archived_strategies', _showArchivedStrategies ? 'true' : 'false');
  refreshStrategies();
}

// 페이지 로드 시 체크박스 상태 복원 (showDashboard 후 호출).
function _initArchiveToggleFromStorage() {
  const cb = document.getElementById('show-archived');
  if (cb) cb.checked = _showArchivedStrategies;
}

async function restoreStrategy(id) {
  if (!confirm(`↻ 전략 #${id} 복원\n\narchive 상태 → UI 목록에 다시 표시.\nstatus 그대로 유지 (여전히 종료 상태).\n\n진행할까요?`)) return;
  try {
    const r = await api(`/strategies/${id}/restore`, { method: 'POST' });
    toast(r.message || `전략 #${id} 복원 완료`, 'success');
    refreshStrategies();
  } catch (e) { toast('복원 실패: ' + e.message, 'error'); }
}

// 2026-06-03 신규: 정렬 dropdown 변경 시 호출 — localStorage 저장 + 즉시 재정렬
function onStrategiesSortChange() {
  const sel = document.getElementById('strategies-sort-by');
  if (sel) {
    localStorage.setItem('strategies_sort_by', sel.value);
    refreshStrategies();  // 즉시 재정렬 표시
  }
}

// 2026-06-03 신규: 계정별 필터 dropdown 변경 시 호출 — 다중 Sub-Account 운영 시
function onStrategiesAccountFilterChange() {
  const sel = document.getElementById('strategies-account-filter');
  if (sel) {
    localStorage.setItem('strategies_account_filter', sel.value);
    refreshStrategies();
  }
}

// 2026-06-03 신규: 전역 strategies 인덱스 (id → strategy) — 「최근 활동」 카드의 계정 필터용.
// refreshStrategies 가 매번 갱신. 다른 모듈 (dashboard-refresh) 이 활용.
window._strategiesById = {};

async function refreshStrategies() {
  try {
    const url = '/strategies' + (_showArchivedStrategies ? '?include_archived=true' : '');
    const data = await api(url);
    // 인덱스 갱신 (activity 필터용)
    window._strategiesById = {};
    for (const s of data) {
      window._strategiesById[s.id] = s;
    }
    const active = data.filter(s => !TERMINAL_STATUSES.includes((s.status || '').toUpperCase()) && !s.is_archived);
    let totalUnrealized = 0;
    let totalMarginUsed = 0;  // 마진 합 = sum(capital / leverage) — 사용자 실제 사용 자본
    active.forEach(s => {
      const pnl = Number(s.unrealized_pnl || 0);
      const cap = Number(s.total_capital || 0);
      const lev = Number(s.leverage || 1) || 1;
      totalUnrealized += pnl;
      if (cap > 0 && lev > 0) totalMarginUsed += cap / lev;
    });
    // 전체 ROI % = 총 USD 손익 / 총 마진 × 100 (사용자 실제 자본 대비 수익률)
    const overallRoiPct = totalMarginUsed > 0 ? (totalUnrealized / totalMarginUsed * 100) : 0;

    setMetric('active', active.length + '건',
      active.length === 0 ? '진행 중인 전략 없음' : `전체 ${data.length}건 중`,
      active.length === 0 ? 'gray' : 'green');

    const pnlSig = totalUnrealized > 0 ? 'green' : totalUnrealized < 0 ? 'red' : 'gray';
    const pnlEl = document.getElementById('metric-pnl');
    const roiSign = overallRoiPct > 0 ? '+' : '';
    pnlEl.innerHTML = `${fmtPnL(totalUnrealized)} USDT <span class="text-xs font-normal">(${roiSign}${overallRoiPct.toFixed(2)}%)</span>`;
    pnlEl.className = 'text-2xl font-bold ' + (totalUnrealized > 0 ? 'pos' : totalUnrealized < 0 ? 'neg' : '');
    setSignal('card-pnl', pnlSig);

    const tbody = document.getElementById('strategies-tbody');
    if (data.length === 0) {
      tbody.innerHTML = '<tr><td colspan="9" class="text-center text-slate-500 py-3 text-xs">전략 없음</td></tr>';
      return;
    }

    // 위험 신호 감지 (청산 임박, 손절 종료, 크라이시스 모드, STOPPING 갇힘, 수동 청산 요청)
    const danger = data.find(s => ['LIQUIDATION_IMMINENT', 'KILL_SWITCH_TRIGGERED'].includes((s.status || '').toUpperCase()));
    const crisisActive = data.find(s => s.crisis_mode_triggered_at && !TERMINAL_STATUSES.includes((s.status || '').toUpperCase()));
    // 2026-05-21 Phase 2: MANUAL_CLEANUP_REQUIRED — 사장님 명시적 처리 대기 (최고 우선순위).
    const manualCleanup = data.find(s => (s.status || '').toUpperCase() === 'MANUAL_CLEANUP_REQUIRED');
    // 2026-05-21 Phase 1: STOPPING 갇힘 감지 (#77/#78 재발 방지) — 5분 초과 시 표시.
    const stuckStopping = data.find(s => {
      if ((s.status || '').toUpperCase() !== 'STOPPING') return false;
      if (!s.updated_at) return false;
      const ageMs = Date.now() - new Date(s.updated_at).getTime();
      return ageMs >= STOPPING_STUCK_THRESHOLD_MS;
    });
    if (danger) {
      showAlert(`전략 #${danger.id} ${danger.symbol} ${danger.side} — 즉시 확인 필요`, statusInfo(danger.status).ko);
    } else if (manualCleanup) {
      showAlert(
        `🆘 수동 청산 요청: 전략 #${manualCleanup.id} ${manualCleanup.symbol} ${manualCleanup.side}`,
        `시스템이 자동 청산하지 못해 사장님 직접 처리 대기 중. 거래소 UI 에서 직접 청산 후 「✅ 처리 완료」 클릭 필요. TP/SL 평가 차단됨.`
      );
    } else if (stuckStopping) {
      const ageMin = Math.floor((Date.now() - new Date(stuckStopping.updated_at).getTime()) / 60000);
      showAlert(
        `🔴 종료 갇힘: 전략 #${stuckStopping.id} ${stuckStopping.symbol} ${stuckStopping.side} — ${ageMin}분째 STOPPING`,
        `emergency_close 실패 후 정지 — 곧 MANUAL_CLEANUP_REQUIRED 전환됨. 「🛑 긴급 종료」 재시도 또는 거래소 UI 직접 청산.`
      );
    } else if (crisisActive) {
      const stage2 = !!crisisActive.crisis_first_tp_done_at;
      const detail = stage2
        ? `Stage 2 보호 활성 — 트레일링 -5% + 빠른 손절 -1% 동작 중. 최대 손실: ${fmtNum(crisisActive.max_loss_pct)}% / 피크 후 PnL 추적 중.`
        : `Stage 1 — TP1 임계 +5% 활성. 최대 손실: ${fmtNum(crisisActive.max_loss_pct)}% 도달했으니 회복 시 빠른 익절 예정.`;
      showAlert(`🚨 크라이시스 모드 활성 — 전략 #${crisisActive.id} ${crisisActive.symbol} ${crisisActive.side}`, detail);
    } else {
      hideAlert();
    }

    // 2026-06-03 신규: 계정별 dropdown 동적 채움 + localStorage 복원
    const accountFilter = localStorage.getItem('strategies_account_filter') || 'all';
    const accSelEl = document.getElementById('strategies-account-filter');
    if (accSelEl) {
      const uniqAccIds = [...new Set(data.map(s => s.exchange_account_id).filter(Boolean))].sort((a,b)=>a-b);
      // 옵션 재구성 (전체 + 각 계정)
      const curVal = accSelEl.value || accountFilter;
      accSelEl.innerHTML = `<option value="all">전체 (${data.length}건)</option>` +
        uniqAccIds.map(id => {
          const cnt = data.filter(s => s.exchange_account_id === id).length;
          return `<option value="${id}">계정 #${id} (${cnt}건)</option>`;
        }).join('');
      // 선택값 복원
      accSelEl.value = uniqAccIds.includes(Number(curVal)) || curVal === 'all' ? curVal : 'all';
    }
    // 계정 필터 적용
    let filteredByAccount = data;
    if (accountFilter !== 'all') {
      filteredByAccount = data.filter(s => String(s.exchange_account_id) === String(accountFilter));
    }

    // 종료된 전략 숨김 토글
    const hideTerm = document.getElementById('hide-terminated')?.checked;
    let visible = filteredByAccount;
    if (hideTerm) visible = filteredByAccount.filter(s => !TERMINAL_STATUSES.includes((s.status || '').toUpperCase()));
    const hiddenCount = filteredByAccount.length - visible.length;
    if (visible.length === 0 && hiddenCount > 0) {
      tbody.innerHTML = `<tr><td colspan="9" class="text-center text-slate-500 py-3 text-xs">진행 중인 전략 없음 (종료 ${hiddenCount}건 숨김)</td></tr>`;
      return;
    }

    // 2026-06-03 신규: 사장님 정렬 옵션 — localStorage 저장. 위험 strategy 우선 확인 가능.
    const sortBy = localStorage.getItem('strategies_sort_by') || 'default';
    const _selSort = document.getElementById('strategies-sort-by');
    if (_selSort && _selSort.value !== sortBy) _selSort.value = sortBy;
    const _slProgress = (s) => {
      const cap = Number(s.total_capital || 0);
      const slPct = Number(s.stop_loss_percent_of_capital || 0);
      const pnl = Number(s.unrealized_pnl || 0);
      const slThr = (cap > 0 && slPct > 0) ? cap * slPct / 100 : 0;
      return (slThr > 0 && pnl < 0) ? (Math.abs(pnl) / slThr * 100) : 0;
    };
    const sorted = [...visible].sort((a, b) => {
      const aTerm = TERMINAL_STATUSES.includes((a.status || '').toUpperCase()) ? 1 : 0;
      const bTerm = TERMINAL_STATUSES.includes((b.status || '').toUpperCase()) ? 1 : 0;
      // 활성 우선 (항상)
      if (aTerm !== bTerm) return aTerm - bTerm;
      // 사장님 선택 정렬
      switch (sortBy) {
        case 'sl_progress_desc': return _slProgress(b) - _slProgress(a);  // 🚨 SL 임박
        case 'pnl_asc': return Number(a.unrealized_pnl || 0) - Number(b.unrealized_pnl || 0);  // 📉 손실 큰 순
        case 'pnl_desc': return Number(b.unrealized_pnl || 0) - Number(a.unrealized_pnl || 0);  // 📈 이익 큰 순
        case 'stage_desc': return (b.current_stage || 0) - (a.current_stage || 0);  // 📊 단계 많은 순
        case 'created_desc': return new Date(b.created_at || 0) - new Date(a.created_at || 0);
        case 'created_asc': return new Date(a.created_at || 0) - new Date(b.created_at || 0);
        default: return b.id - a.id;  // 기본
      }
    });

    // 2026-06-01 (사장님 요구): 비활성 종료 행은 Binance 비교 X. active 만 fetch.
    // 표시될 strategies 중 active 의 account_id 모음 → 병렬 fetch (Backend 30초 캐시).
    const activeAccountIds = sorted
      .filter(s => !TERMINAL_STATUSES.includes((s.status || '').toUpperCase()))
      .map(s => s.exchange_account_id)
      .filter(Boolean);
    await _fetchBinancePositionsForAccounts(activeAccountIds);

    tbody.innerHTML = sorted.map(s => {
      const info = statusInfo(s.status);
      // 단계 진행도 + TP 진행도 두 줄 stack — 분모는 template 의 활성 단계/TP 수 (동적).
      // backend 응답의 total_active_stages / total_active_tps 사용. 옛 backend 호환: fallback 4.
      const totalStages = s.total_active_stages || 4;
      const totalTps = s.total_active_tps || 4;
      // 2026-05-03 fix: backend 의 실제 발동 카운트 (tp_triggered_count) 우선 사용.
      // 옛 backend 면 status 추론 fallback. 종료 사유 (last_close_reason) 도 표시.
      const tpCount = (s.tp_triggered_count !== undefined && s.tp_triggered_count !== null)
        ? s.tp_triggered_count
        : _tpCountFromStatus(s, totalTps);
      const closeReason = s.last_close_reason || 'NONE';
      const stageBar = s.current_stage > 0 ? renderStageBar(s.current_stage, totalStages) : '<span class="text-slate-500">대기</span>';
      const tpBar = renderTpBar(tpCount, totalTps, closeReason);
      const stage = `<div class="text-xs leading-tight"><span class="text-slate-400" style="font-size:10px">진입</span> ${stageBar}<br><span class="text-slate-400" style="font-size:10px">익절</span> ${tpBar}</div>`;
      const pnlNum = Number(s.unrealized_pnl || 0);
      const sCap = Number(s.total_capital || 0);
      const sLev = Number(s.leverage || 1) || 1;
      const sQtyNum = Number(s.current_position_qty || 0);
      const sQtyAbs = Math.abs(sQtyNum);
      const sAvg = Number(s.avg_entry_price || 0);
      const hasPosition = sQtyAbs > 0 && sAvg > 0;
      // 마크 가격 = avg + pnl/qty (LONG) | avg - pnl/qty (SHORT)
      const sMark = hasPosition ? (s.side === 'LONG' ? sAvg + pnlNum/sQtyAbs : sAvg - pnlNum/sQtyAbs) : 0;
      // 청산예정가 = isolated 계산 (체결 평단 기반)
      const MMR = 0.005;
      const sLiq = hasPosition && sLev > 0 ? (s.side === 'SHORT' ? sAvg * (1 + 1/sLev - MMR) : sAvg * (1 - 1/sLev + MMR)) : 0;

      // 2026-05-04 v3 (Binance ROI 일치): 두 가지 ROI 분리.
      //   포지션 ROI = pnl / 현재_사용_마진 × 100  ← Binance UI 와 일치 (실제 진입한 부분만).
      //   전략 ROI   = pnl × leverage / total_capital × 100  ← 전체 전략 자본 대비.
      const positionNotional = hasPosition ? sQtyAbs * sAvg : 0;
      const positionMargin = positionNotional > 0 && sLev > 0 ? positionNotional / sLev : 0;
      const positionRoi = positionMargin > 0 ? (pnlNum / positionMargin * 100) : 0;
      const strategyRoi = sCap > 0 ? (pnlNum * sLev / sCap * 100) : 0;
      // 2026-06-05 옵션 A (사장님 사상 정확 반영):
      // total_capital = 사장님 입력 「자본」 = 마진 단위 (PR #57 SL 계산식 확정)
      //   = "투자금 대비 손실 %" 의 기준 (index.html L826 사장님 사상 명시)
      //   예: 자본 200 + 증거금 50 + 포지션 100 → total_capital = 350 → SL = 350×80% = -280 USDT
      // 「계획 마진」 = total_capital (그대로) — 사장님이 입력한 자본 = 거래소 lock 목표
      // 「거래 규모 (notional)」 = total_capital × leverage — 사장님 강조 "자본 2000 + 2x = 4000"
      // 이전: plannedMargin = sCap / sLev (잘못 — ÷ leverage 가 사장님 사상 위반)
      const plannedMargin = sCap > 0 ? sCap : 0;
      const plannedNotional = sCap > 0 && sLev > 0 ? sCap * sLev : 0;

      // 평단/마크/청산 — 3 줄 stack (Binance 스타일)
      const priceStack = hasPosition
        ? `<div class="text-xs leading-tight"><span class="text-slate-300" title="평단가">${fmtNum(sAvg)}</span><br><span class="text-cyan-300" title="마크가">${fmtNum(sMark)}</span><br><span class="text-red-300" title="청산예정">${fmtNum(sLiq)}</span></div>`
        : '<span class="text-slate-500">-</span>';
      // 수량/마진 — 2 줄 stack + 「💰 증거금 추가」 버튼 (포지션 보유 시).
      // 마진은 「현재 사용 마진 / 계획 총 마진」 형식.
      // 1단계만 진입한 다단계 전략은 둘이 다름 (e.g. 10.58 / 3275 USDT).
      // 2026-05-04 (사용자 요청): 증거금 추가 버튼을 가시성 높은 위치 + 명확한 라벨로
      // 마진 옆에 직접 노출 (이전 액션 컬럼의 🛡 아이콘만 — 발견 어려움 개선).
      const addMarginBtnInQty = hasPosition
        ? `<button onclick="event.stopPropagation(); addMargin(${s.id}, '${s.symbol}', '${s.side}')"
                  class="btn-warning btn text-xs mt-1"
                  style="padding:2px 6px;font-size:10px;line-height:1.2"
                  title="증거금 추가 — ISOLATED 모드 포지션의 청산가 완화 (CROSS 면 거래소 거절)">💰 증거금 추가</button>`
        : '';
      // 2026-05-04 (사용자 요청): 「💉 포지션 추가」 — ad-hoc 자유 금액 시장가/지정가 진입.
      // isTerminal 이 아직 정의 전이라 (line 1581) inline 으로 status 체크.
      const _activeForAddPos = !TERMINAL_STATUSES.includes((s.status || '').toUpperCase());
      const addPositionBtn = _activeForAddPos
        ? `<button onclick="event.stopPropagation(); openAddPositionModal(${s.id}, '${s.symbol}', '${s.side}', ${s.leverage || 1})"
                  class="btn-primary btn text-xs mt-1 ml-1"
                  style="padding:2px 6px;font-size:10px;line-height:1.2"
                  title="포지션 추가 (ad-hoc) — 자유 금액 시장가/지정가 즉시 진입. qty + 평단 갱신, stage 진행 X. v4 안전망: 사용 시 max_loss 임계 도달하면 Crisis 발동 (stage 미완료라도)">💉 포지션 추가</button>`
        : '';
      // 2026-06-05 옵션 A (사장님 사상): total_capital = 사장님 자본 = 마진 단위
      // 표시:
      //   📦 수량 = 포지션 수량
      //   🔒 현재 마진 = qty × 평단 ÷ lev (Binance 실 lock)
      //   💼 사장님 자본 = total_capital (마진 의도, SL 계산 기준)
      //   📊 거래 규모 = total_capital × leverage (notional)
      //   진입률 = 현재 마진 ÷ 사장님 자본 (모든 단계 진입까지 %)
      const entryPct = plannedMargin > 0 ? (positionMargin / plannedMargin * 100) : 0;
      const entryColor = entryPct >= 95 ? 'text-green-400' : entryPct >= 50 ? 'text-yellow-400' : 'text-slate-300';
      const planTooltip = `💼 사장님 자본: ${plannedMargin.toFixed(2)} USDT (= 마진 lock 목표)\n   strategy 생성 시 입력 — SL 한도 기준 (사장님 사상 PR #57)\n   "투자금 대비 손실 %" = 자본 × sl_pct/100\n\n📊 거래 규모: ${plannedNotional.toFixed(2)} USDT (= 자본 × ${sLev}x)\n   모든 단계 진입 + 거래소 표시 notional value\n\n🔒 현재 마진 (Binance lock): ${positionMargin.toFixed(2)} USDT\n   = 수량 ${sQtyAbs.toFixed(0)} × 평단 ${sAvg.toFixed(4)} ÷ ${sLev}x\n\n📈 진입률: ${entryPct.toFixed(1)}% (현재 ÷ 자본)\n   100% = 모든 단계 진입 완료\n   100% 초과 = 사장님이 증거금/포지션 추가 후 자본 자동 합산 (PR #56)`;
      const qtyStack = hasPosition
        ? `<div class="text-xs leading-tight">
            <div title="포지션 수량 (절대값 = 실제 보유, 부호 = 방향)"><span class="text-slate-400" style="font-size:10px">📦 수량</span> <span class="${sQtyNum<0?'neg':'pos'} font-semibold">${fmtQty(sQtyNum)}</span></div>
            <div title="${planTooltip}">
              <span class="text-slate-400" style="font-size:10px">🔒 마진</span>
              <span class="text-slate-200">${positionMargin.toFixed(2)}</span>
              <span class="text-slate-500" style="font-size:10px">/ <span class="text-slate-300">${plannedMargin.toFixed(2)}</span> USDT</span>
              <span class="${entryColor} ml-1" style="font-size:10px">${entryPct.toFixed(0)}%</span>
            </div>
            <div style="font-size:10px" title="${planTooltip}">
              <span class="text-slate-500">📊 거래규모</span>
              <span class="text-slate-400">${plannedNotional.toFixed(0)} USDT</span>
              <span class="text-slate-600">(자본 ${plannedMargin.toFixed(0)} × ${sLev}x)</span>
            </div>
            ${addMarginBtnInQty}${addPositionBtn}
          </div>`
        : `<div class="text-xs leading-tight">
            <span class="text-slate-500">- (미진입)</span><br>
            <span class="text-slate-400" style="font-size:10px" title="${planTooltip}">💼 자본 ${plannedMargin > 0 ? plannedMargin.toFixed(2)+' USDT' : '-'}</span>
            <br><span class="text-slate-600" style="font-size:9px">📊 거래규모 ${plannedNotional.toFixed(0)} (= 자본 × ${sLev}x)</span>
            ${addPositionBtn ? '<br>'+addPositionBtn : ''}
          </div>`;
      // PnL/ROI — 4 줄 stack: PnL + 포지션 ROI + 전략 ROI + 🆕 SL 한도 시각 (2026-06-03)
      const posSign = positionRoi > 0 ? '+' : '';
      const stratSign = strategyRoi > 0 ? '+' : '';
      const posTooltip = `포지션 ROI = pnl ÷ 현재 사용 마진 × 100 (Binance UI 와 일치). 마진=${positionMargin.toFixed(2)} USDT`;
      const stratTooltip = `전략 ROI = pnl × 레버리지 ÷ 전체 전략 자본 × 100 (전체 단계 모두 진입 시 = 포지션 ROI). 자본=${sCap.toFixed(2)} USDT, lev=${sLev}x`;
      // 2026-06-03 SL 한도 시각화 (사장님 사상 PR #57: 레버리지 무관, 투자금 × sl_pct / 100)
      // 사장님이 SL 발동까지 얼마나 남았는지 즉시 인지 — 운영 안전 핵심.
      const slPctNum = Number(s.stop_loss_percent_of_capital || 0);
      const slThreshold = (sCap > 0 && slPctNum > 0) ? sCap * slPctNum / 100 : 0;
      // SL 까지 진행률 (0% = 안전, 100% = 발동 직전, > 100% = 한도 초과 발동 임박)
      const slProgressPct = (slThreshold > 0 && pnlNum < 0) ? (Math.abs(pnlNum) / slThreshold * 100) : 0;
      const slRemainingUsd = slThreshold + pnlNum;  // pnlNum 음수면 작아짐
      let slClass = 'text-slate-500';
      let slIcon = '';
      if (slProgressPct >= 80) { slClass = 'text-red-400 font-bold'; slIcon = '🚨 '; }
      else if (slProgressPct >= 50) { slClass = 'text-orange-400'; slIcon = '⚠ '; }
      else if (slProgressPct >= 30) { slClass = 'text-yellow-400'; }
      else if (slProgressPct > 0) { slClass = 'text-slate-400'; }
      const slTooltip = slThreshold > 0
        ? `SL 한도: -${slThreshold.toFixed(2)} USDT (투자금 ${sCap.toFixed(2)} × ${slPctNum}%, 레버리지 무관 — 사장님 사상 PR #57). 진행률 ${slProgressPct.toFixed(1)}% (남은 ${slRemainingUsd.toFixed(2)} USDT). 모든 단계 진입 후 발동.`
        : 'SL 정보 없음';
      const slDisplay = slThreshold > 0
        ? `<br><span class="${slClass} text-xs" style="font-size:10px" title="${slTooltip}">${slIcon}SL ${slProgressPct.toFixed(0)}% (-${slThreshold.toFixed(0)} USDT)</span>`
        : '';
      const pnl = hasPosition
        ? `<div class="text-xs leading-tight">
            <span class="${pnlNum>0?'pos':pnlNum<0?'neg':''} font-semibold" title="미실현 손익 (USDT)">${fmtPnL(pnlNum)}</span><br>
            <span class="${positionRoi>0?'pos':positionRoi<0?'neg':'text-slate-400'} text-xs" title="${posTooltip}">${posSign}${positionRoi.toFixed(2)}%</span><br>
            <span class="${strategyRoi>0?'pos':strategyRoi<0?'neg':'text-slate-500'} text-xs" style="font-size:10px; opacity:0.7" title="${stratTooltip}">전략 ${stratSign}${strategyRoi.toFixed(2)}%</span>${slDisplay}
          </div>`
        : '<span class="text-slate-500">-</span>';

      // 호환용 alias (기존 변수 사용 위치 보존)
      const entry = priceStack;
      const qty = qtyStack;
      const isTerminal = TERMINAL_STATUSES.includes((s.status || '').toUpperCase());
      // UX #17 (2026-04-29): 종료 상태이고 한번도 체결 안 된 전략 (대기 단계) 에는 삭제 버튼 노출
      const neverEntered = (s.current_stage || 0) === 0 && (!s.avg_entry_price || Number(s.avg_entry_price) === 0);
      // 2026-05-04 v2 (재진입 UX): 1단계 이상 체결됐던 종료 전략 (COMPLETED/REENTRY_READY/STOPPED 등)
      // 에는 "🔄 다시 시작" 버튼 노출 — 같은 설정으로 새 전략 즉시 생성. (이전엔 「🟢 새 전략 시작」
      // 모달 → "이전 전략 불러오기" 탭 → 선택 3단계 — 너무 번거로움)
      // 2026-05-04: 증거금 추가 버튼은 수량/마진 column 으로 이동 (위 addMarginBtnInQty).
      // 「▶ 다음 단계 즉시 진입」 — 활성 strategy + 다음 단계 미발동 시. trigger_price 무시, planned_capital 그대로.
      // 2026-05-04 (사용자 피드백): 액션 버튼 컴팩트화 — 아이콘만 + nowrap + flex inline.
      const totalStagesForBtn = s.total_active_stages || 4;
      const canTriggerNext = !isTerminal && (s.current_stage || 0) < totalStagesForBtn;
      const btnStyle = "padding:3px 6px;font-size:11px;white-space:nowrap;line-height:1.3";
      const triggerNextBtn = canTriggerNext
        ? `<button onclick="event.stopPropagation(); triggerNextStage(${s.id})" class="btn-ghost btn text-xs" style="${btnStyle}" title="현재가에서 다음 단계 즉시 진입 (trigger_price 무시, 사전 계획된 자본 그대로)">▶</button>`
        : '';
      // 2026-05-06 (C-full Step 3): archived row 는 「↻ 복원」 단독 표시.
      // 2026-05-21 Phase 2: MANUAL_CLEANUP_REQUIRED 는 「✅ 수동 청산 처리 완료」 + 긴급종료 재시도.
      const isManualCleanup = (s.status || '').toUpperCase() === 'MANUAL_CLEANUP_REQUIRED';
      let stopBtn;
      if (s.is_archived) {
        stopBtn = `<button onclick="event.stopPropagation(); restoreStrategy(${s.id})" class="btn-ghost btn text-xs" style="${btnStyle}" title="archive 해제 — UI 목록에 다시 표시 (status 그대로)">↻ 복원</button>`;
      } else if (isManualCleanup) {
        // 사장님이 거래소에서 직접 청산 후 ack 하는 흐름. 「긴급 종료」 재시도도 함께 노출.
        stopBtn = `<div class="flex flex-wrap gap-1" style="max-width:160px">
            <button onclick="event.stopPropagation(); emergencyStop(${s.id})" class="btn-danger btn text-xs" style="${btnStyle}" title="긴급 종료 재시도 (시장가 청산 — 거래소 거절 시 status 유지)">🛑 재시도</button>
            <button onclick="event.stopPropagation(); acknowledgeManualCleanup(${s.id})" class="btn-success btn text-xs" style="${btnStyle};background:#16a34a;color:white" title="거래소에서 직접 청산 완료 — STOPPED 전환 (감사 로그 기록)">✅ 처리 완료</button>
          </div>`;
      } else if (isTerminal) {
        stopBtn = neverEntered
          ? `<button onclick="event.stopPropagation(); deleteStrategy(${s.id})" class="btn-danger btn text-xs" style="${btnStyle}" title="전략 보관 (archive — DB row 보존, UI 숨김, 손익 통계 유지)">🗑</button>`
          : `<div class="flex flex-wrap gap-1" style="max-width:130px">
              <button onclick="event.stopPropagation(); restartStrategy(${s.id})" class="btn-ghost btn text-xs" style="${btnStyle}" title="같은 설정으로 새 전략 시작 (이 전략은 그대로 보존)">🔄</button>
              <button onclick="event.stopPropagation(); deleteStrategy(${s.id})" class="btn-danger btn text-xs" style="${btnStyle}" title="전략 보관 (archive — DB row 보존, UI 숨김, 손익 통계 유지)">🗑</button>
            </div>`;
      } else {
        stopBtn = `<div class="flex flex-wrap gap-1" style="max-width:130px">
            <button onclick="event.stopPropagation(); editStrategy(${s.id})" class="btn-ghost btn text-xs" style="${btnStyle}" title="설정 수정 (in-place 또는 종료+재시작)">✏️</button>
            ${triggerNextBtn}
            <button onclick="event.stopPropagation(); stopStrategy(${s.id})" class="btn-warning btn text-xs" style="${btnStyle}" title="미체결 주문만 취소 (포지션 유지)">⏸</button>
            <button onclick="event.stopPropagation(); emergencyStop(${s.id})" class="btn-danger btn text-xs" style="${btnStyle}" title="긴급 종료 (포지션 시장가 청산)">🛑</button>
          </div>`;
      }
      const startPx = s.start_price && Number(s.start_price) > 0
        ? `<span class="text-yellow-400" title="운영자가 입력한 1단계 LIMIT 가격">${fmtNum(s.start_price)}</span>`
        : '<span class="text-slate-500">-</span>';

      // 크라이시스 모드 배지 (2026-06-03 보강: 정확한 의미 + 임계값 표시)
      // Stage1 = max_loss_pct 임계 (default -50%) 도달 → TP 임계 자동 낮춤 (10/15/20/30 → 5/10/15/20)
      // Stage2 = TP1 발동 후 → 트레일링 -5% + 빠른 손절 -1% (보호 강화)
      // SL (사용자 -80%) 과 독립적 — 크라이시스는 청산 X (TP 임계만 조정)
      let modeBadge;
      if (s.crisis_mode_triggered_at) {
        if (s.crisis_first_tp_done_at) {
          modeBadge = '<span class="badge badge-red" title="크라이시스 Stage 2 — TP1 익절 후 보호 강화 활성. 트레일링 -5% + 빠른 손절 -1%. SL(사용자 설정)과 독립적">🛡 크라이시스 Stage 2 (보호)</span>';
        } else {
          modeBadge = '<span class="badge badge-yellow" title="크라이시스 Stage 1 — max_loss_pct 임계 도달 → TP 임계 자동 낮춤 (5/10/15/20%). 손절(SL) 미발동, TP 만 빠르게 회복 익절 시도">🚨 크라이시스 Stage 1 (TP 임계↓)</span>';
        }
      } else {
        modeBadge = '<span class="badge badge-gray" title="정상 모드 — 사용자 설정 TP + SL 그대로 작동">정상</span>';
      }

      // 최대 손실/이익
      const maxLoss = s.max_loss_pct !== null && s.max_loss_pct !== undefined
        ? `<span class="text-red-400">${fmtNum(s.max_loss_pct)}%</span>`
        : '<span class="text-slate-500">-</span>';
      const maxProfit = s.max_profit_pct !== null && s.max_profit_pct !== undefined
        ? `<span class="text-green-400">+${fmtNum(s.max_profit_pct)}%</span>`
        : '<span class="text-slate-500">-</span>';
      const maxCell = `<div class="text-xs leading-tight">${maxLoss}<br>${maxProfit}</div>`;

      // 2026-05-21 STOPPING 갇힘 배지 — updated_at 5분 초과면 「⚠️ 갇힘 N분」 표시.
      // reconcile 이 자동 정리 못 하는 케이스 (포지션 잔재) — 사장님이 인지해야 함.
      let stuckBadge = '';
      if ((s.status || '').toUpperCase() === 'STOPPING' && s.updated_at) {
        const ageMs = Date.now() - new Date(s.updated_at).getTime();
        if (ageMs >= STOPPING_STUCK_THRESHOLD_MS) {
          const ageMin = Math.floor(ageMs / 60000);
          stuckBadge = `<span class="badge badge-red" title="STOPPING 상태가 ${ageMin}분째 지속 — emergency_close 실패. TP/SL 평가도 차단됨. 「🛑 긴급 종료」 재시도 또는 거래소 UI 에서 직접 청산.">⚠️ 갇힘 ${ageMin}분</span>`;
        }
      }
      // 상태 셀에 모드 배지 + 최대손익 tooltip 까지 합쳐 9 컬럼으로 압축.
      const stateCell = `
        <div class="flex flex-col gap-1" title="모드: ${modeBadge.replace(/<[^>]+>/g,'').trim()} / 진입요청가: ${s.start_price ? fmtNum(s.start_price) : '-'} / 최대 손실: ${s.max_loss_pct !== null && s.max_loss_pct !== undefined ? fmtNum(s.max_loss_pct)+'%' : '-'} / 최대 이익: ${s.max_profit_pct !== null && s.max_profit_pct !== undefined ? '+'+fmtNum(s.max_profit_pct)+'%' : '-'}">
          <span class="badge badge-${info.sig}">${info.icon} ${info.ko}</span>
          ${stuckBadge}
          ${s.crisis_mode_triggered_at ? modeBadge : ''}
        </div>`;
      // 진입일시 (created_at) — 짧게 MM/DD HH:MM 형식
      const createdShort = s.created_at ? (() => {
        const d = new Date(s.created_at);
        const pad = (n) => String(n).padStart(2, '0');
        return `${pad(d.getMonth()+1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
      })() : '-';
      // 2026-06-01 (사장님 요구): 활성 전략만 Binance 비교 행 표시 (종료된 전략 비교 무의미).
      const showBinanceCompare = !isTerminal && s.exchange_account_id;
      return `<tr class="row-clickable" onclick="selectStrategy(${s.id})">
        <td>#${s.id}</td>
        <td class="font-mono">
          <div class="text-xs leading-tight">
            <a href="https://www.binance.com/en/futures/${s.symbol}" target="_blank" rel="noopener"
               onclick="event.stopPropagation()"
               class="text-blue-300 hover:text-blue-100 hover:underline"
               title="🔗 ${s.symbol} — 바이낸스 선물 차트 새 탭 열기">${s.symbol}</a>${renderWhitelistBadge(s.symbol)}<br>
            <span class="text-slate-500" style="font-size:10px" title="전략 생성 일시">${createdShort}</span>
          </div>
        </td>
        <td>${sideBadge(s.side, s.leverage)}</td>
        <td>${stateCell}</td>
        <td>${stage}</td>
        <td class="num">${entry}</td>
        <td class="num">${qty}</td>
        <td class="num">${pnl}</td>
        <td>${stopBtn}</td>
      </tr>${showBinanceCompare ? _binanceCompareRow(s) : ''}`;
    }).join('');
  } catch (err) { toast('전략 조회 실패: ' + err.message, 'error'); }
}

