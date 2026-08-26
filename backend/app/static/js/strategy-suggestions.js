/**
 * 🎯 전략 제안 UI (v132 신!)
 *
 * 사장님 요구 (2026-08-11):
 * - 매일 자동 생성 전략 제안!
 * - 기본 = 수동 (사장님 결정!)
 * - 자동 옵션 (차후!)
 * - 유지/삭제 관리!
 * - 만들어진 시간 표기!
 *
 * API:
 *   GET  /strategy-suggestions
 *   DELETE /strategy-suggestions/{id}
 *   POST /strategy-suggestions/{id}/execute
 *   GET/PUT /strategy-suggestions/settings
 */

// 🌟 v132 필터 상태 (전역!)
let _sugSideFilter = 'ALL';  // ALL / LONG / SHORT
let _cachedSuggestions = [];

// 🌟 v162 사장님 (2026-08-16): BB 이탈 SUSTAINED 자동 진입 개수 옵션!
// 🌟 v181 사장님 (2026-08-19): 「세팅 계속 유지!」 = localStorage backup!
const _AUTO_BB_LIMIT_LS_KEY = 'auto_bb_limit_backup_v181';

async function saveAutoBBLimit(v) {
  const numV = Number(v);
  // v181: localStorage backup 즉시 저장! (API 실패해도 유지!)
  try { localStorage.setItem(_AUTO_BB_LIMIT_LS_KEY, String(numV)); } catch (_e) {}
  try {
    await api('/strategy-suggestions/auto-bb-limit', {
      method: 'PUT',
      body: { limit: numV },
    });
    if (typeof toast === 'function') {
      toast(numV > 0
        ? `✅ 자동 진입 = ${numV}개/일 = ON! (계속 유지!)`
        : `✅ 자동 진입 = OFF (수동!)`, 'success');
    }
  } catch (e) {
    if (typeof toast === 'function') toast('❌ 저장 실패: ' + (e.message || e), 'error');
    console.warn('[saveAutoBBLimit] API 실패 = localStorage backup 유지:', e);
  }
}

async function loadAutoBBLimit() {
  const el = document.getElementById('auto-bb-daily-limit');
  // 🌟 v181/v182 사장님: 「계속 유지!」 = localStorage backup 무조건 우선!
  // v181: `el.value === '0'` 조건 = 매번 실패 (초기 로드 시 = 옛 값!)
  // v182: 조건 제거! 무조건 backup 있으면 = 즉시 복원!
  try {
    const backup = localStorage.getItem(_AUTO_BB_LIMIT_LS_KEY);
    if (el && backup !== null && backup !== '') {
      el.value = backup;  // v182: 무조건 복원!
    }
  } catch (_e) {}
  try {
    const r = await api('/strategy-suggestions/auto-bb-limit');
    if (el && r && typeof r.limit !== 'undefined') {
      el.value = String(r.limit);
      // v181: API 성공 = localStorage 갱신!
      try { localStorage.setItem(_AUTO_BB_LIMIT_LS_KEY, String(r.limit)); } catch (_e) {}
    }
    // v163: 상태 표시!
    const statusEl = document.getElementById('auto-bb-status');
    if (statusEl && r && typeof r.limit !== 'undefined') {
      const used = r.daily_used || 0;
      const remaining = r.remaining || 0;
      const active = r.active || 0;
      const stopLoss = r.stopped_loss || 0;
      const profit = r.stopped_profit || 0;
      if (r.limit === 0) {
        statusEl.textContent = '';
      } else {
        statusEl.textContent = ` ${used}/${r.limit} (활성${active}+손절${stopLoss}, 익절${profit}✅)`;
        statusEl.title = `자동 진입 = ${used}건 사용중 / ${r.limit}건 한도\n활성: ${active}건, 손절: ${stopLoss}건 (카운트!)\n익절: ${profit}건 (카운트 X = 재진입 가능!)`;
      }
    }
  } catch (e) {
    // 🌟 v181: API 실패 = 조용히 유지! (localStorage backup!)
    console.warn('[loadAutoBBLimit] API 실패 = localStorage backup 유지:', e && e.message);
  }
}

// 🎯 v218 사장님 (2026-08-22): 최근 자동 진입 outcome 렌더!
// 사장님 verbatim: "자동 제안도 활성 손절 익절을 알수 있게 해주고
//                  지금 상태를 파악해줘 손실이 좀 있는것 같아"
async function loadRecentAutoOutcomes() {
  try {
    const r = await api('/strategy-suggestions/recent-auto?hours=24');
    const el = document.getElementById('auto-recent-outcomes');
    if (!el) return;
    const s = r.summary || {};
    const items = r.items || [];
    const losses = r.losses || [];

    // 요약 배지 (사장님 즉시 파악!)
    const summaryHtml = `
      <div style="display:flex; gap:8px; flex-wrap:wrap; margin:6px 0; font-size:11px;">
        <span style="background:#10b981; color:#000; padding:2px 8px; border-radius:8px;">
          🟢 활성 ${s.active || 0} (${(s.active_pnl_sum >= 0 ? '+' : '') + (s.active_pnl_sum || 0).toFixed(2)})
        </span>
        <span style="background:#ef4444; color:#fff; padding:2px 8px; border-radius:8px;">
          🔴 손절 ${s.stop_loss || 0} (${(s.loss_sum || 0).toFixed(2)})
        </span>
        <span style="background:#a78bfa; color:#000; padding:2px 8px; border-radius:8px;">
          ✅ 익절 ${s.take_profit || 0} (+${(s.profit_sum || 0).toFixed(2)})
        </span>
        <span style="background:${(s.net_pnl || 0) >= 0 ? '#10b981' : '#ef4444'}; color:${(s.net_pnl || 0) >= 0 ? '#000' : '#fff'}; padding:2px 8px; border-radius:8px; font-weight:bold;">
          💰 순 ${(s.net_pnl || 0) >= 0 ? '+' : ''}${(s.net_pnl || 0).toFixed(2)} USDT
        </span>
      </div>`;

    // 손실 심볼 리스트 (사장님 즉시 파악!)
    let lossesHtml = '';
    if (losses.length > 0) {
      lossesHtml = `
        <div style="background:#7f1d1d; padding:6px 8px; border-radius:6px; margin:4px 0; font-size:11px;">
          <div style="font-weight:bold; color:#fca5a5; margin-bottom:2px;">🚨 손실 심볼 ${losses.length}건:</div>
          ${losses.map(l => `
            <div style="color:#fecaca; margin-left:8px;">
              🔴 ${l.symbol} ${l.side} = ${l.pnl.toFixed(2)} USDT
            </div>`).join('')}
        </div>`;
    }

    // 최근 진입 결과 리스트!
    let itemsHtml = '';
    if (items.length > 0) {
      itemsHtml = `
        <details style="margin-top:6px; font-size:11px;">
          <summary style="cursor:pointer; color:#a78bfa;">📋 최근 24h 자동 진입 ${items.length}건 (클릭 확장!)</summary>
          <div style="max-height:200px; overflow-y:auto; margin-top:4px; padding:4px; background:#1e293b; border-radius:4px;">
            ${items.map(i => {
              const icon = i.outcome_status === 'ACTIVE' ? '🟢' :
                           i.outcome_status === 'TAKE_PROFIT' ? '✅' :
                           i.outcome_status === 'STOP_LOSS' ? '🔴' : '⏳';
              const pnl = i.realized_pnl != null ? ` = ${i.realized_pnl.toFixed(2)}` :
                          i.unrealized_pnl != null ? ` (활성 ${i.unrealized_pnl >= 0 ? '+' : ''}${i.unrealized_pnl.toFixed(2)})` : '';
              const pnlColor = (i.realized_pnl || i.unrealized_pnl || 0) >= 0 ? '#10b981' : '#ef4444';
              const time = i.executed_at ? new Date(i.executed_at).toLocaleTimeString('ko-KR', {hour:'2-digit', minute:'2-digit'}) : '';
              return `<div style="color:${pnlColor}; padding:1px 4px;">
                ${icon} ${time} ${i.symbol} ${i.side}${pnl}
              </div>`;
            }).join('')}
          </div>
        </details>`;
    }

    el.innerHTML = summaryHtml + lossesHtml + itemsHtml;
  } catch (e) {
    console.warn('[loadRecentAutoOutcomes] 실패:', e && e.message);
  }
}

// 🔄 v163 사장님: 자동 진입 카운터 리셋!
async function resetAutoBBCounter() {
  if (!confirm('🔄 자동 진입 카운터 리셋?\n\n= 지금 이후 진입만 = 카운트!\n= 이전 활성/손절 = 카운트 X!')) return;
  try {
    const r = await api('/strategy-suggestions/auto-bb-reset', { method: 'POST' });
    if (typeof toast === 'function') {
      toast('✅ 리셋 완료! 지금 이후 자동 진입만 = 카운트!', 'success');
    }
    setTimeout(loadAutoBBLimit, 300);
  } catch (e) {
    if (typeof toast === 'function') toast('❌ 리셋 실패: ' + (e.message || e), 'error');
  }
}

// 🌟 v155 사장님 (2026-08-16): 85% 미만 초기화!
async function dismissLowConfidence() {
  if (!confirm('신뢰도 85% 미만 = 모두 삭제(DISMISSED)? 되돌릴 수 없습니다!')) return;
  try {
    const result = await api('/strategy-suggestions/dismiss-low-confidence?threshold=0.85',
                             { method: 'POST' });
    if (typeof toast === 'function') {
      toast(`✅ 초기화 완료! ${result.dismissed || 0}건 dismiss!`, 'success');
    }
    setTimeout(loadStrategySuggestions, 500);
  } catch (e) {
    if (typeof toast === 'function') toast('❌ 실패: ' + (e.message || e), 'error');
  }
}

// 🌟 v136a: 활성 포지션 심볼 캐시!
let _activeSymbolsCache = new Set();

async function loadStrategySuggestions() {
  try {
    // 활성 심볼 로드 (병렬!)
    const [suggestions, strategies] = await Promise.all([
      // 🌟 v172 (2026-08-17 사장님!): min_confidence 0.85 → 0.75!
      // 사장님 지적: "신뢰도 85% 없을 수 없다!"
      // 원인: predictor 실제 conf 범위 = 0.65~0.95 (사장님 시장 = 대부분 0.75~0.85!)
      // = 필터 완화 필요! 자동 진입은 여전히 사장님 수동 승인!
      api('/strategy-suggestions?min_confidence=0.75&exclude_active=true'),
      api('/strategies?limit=200').catch(() => []),
    ]);
    _cachedSuggestions = suggestions || [];
    // 활성 심볼 캐시 갱신!
    const openStatuses = new Set([
      'STAGE_1_OPEN', 'STAGE_2_OPEN', 'STAGE_3_OPEN', 'STAGE_4_OPEN',
      'STAGE_5_OPEN', 'STAGE_6_OPEN', 'STAGE_7_OPEN', 'STAGE_8_OPEN',
      'STAGE_9_OPEN', 'STAGE_10_OPEN',
    ]);
    _activeSymbolsCache = new Set(
      (Array.isArray(strategies) ? strategies : [])
        .filter(s => openStatuses.has(s.status) && Math.abs(Number(s.current_position_qty || 0)) > 0)
        .map(s => `${s.symbol}:${s.side}`)
    );
    renderSuggestions();
  } catch (e) {
    console.warn('[suggestions] load 실패:', e);
  }
}

function _setSugFilter(filter) {
  _sugSideFilter = filter;
  renderSuggestions();
}

function renderSuggestions() {
  try {
    const card = document.getElementById('strategy-suggestions-card');
    const countEl = document.getElementById('suggestions-count');
    const listEl = document.getElementById('suggestions-list');
    if (!card || !countEl || !listEl) return;

    // 🌟 v132 사장님: 항상 카드 표시!
    card.classList.remove('hidden');

    const all = _cachedSuggestions || [];
    const longs = all.filter(s => s.side === 'LONG');
    const shorts = all.filter(s => s.side === 'SHORT');

    // 필터 적용!
    let filtered = all;
    if (_sugSideFilter === 'LONG') filtered = longs;
    else if (_sugSideFilter === 'SHORT') filtered = shorts;

    countEl.textContent = String(all.length);

    // 필터 버튼 HTML!
    const filterBtns = `
      <div class="flex gap-1 mb-2 text-xs">
        <button onclick="_setSugFilter('ALL')"
                class="px-2 py-1 rounded ${_sugSideFilter==='ALL'?'bg-purple-600 text-white font-bold':'bg-slate-700 text-slate-300'}">
          전체 (${all.length})
        </button>
        <button onclick="_setSugFilter('LONG')"
                class="px-2 py-1 rounded ${_sugSideFilter==='LONG'?'bg-green-600 text-white font-bold':'bg-slate-700 text-slate-300'}">
          🐂 LONG (${longs.length})
        </button>
        <button onclick="_setSugFilter('SHORT')"
                class="px-2 py-1 rounded ${_sugSideFilter==='SHORT'?'bg-red-600 text-white font-bold':'bg-slate-700 text-slate-300'}">
          🐻 SHORT (${shorts.length})
        </button>
      </div>
    `;

    if (all.length === 0) {
      listEl.innerHTML = filterBtns +
        '<div class="text-xs text-slate-400 text-center py-2">아직 학습 X! 「🎯 지금 실행」 클릭!</div>';
      return;
    }

    if (filtered.length === 0) {
      listEl.innerHTML = filterBtns +
        `<div class="text-xs text-slate-400 text-center py-2">「${_sugSideFilter}」 = 0건! 다른 필터 선택!</div>`;
      return;
    }

    // 🌟 v136a: 활성 심볼은 뒤로! (구분 명확!)
    const suggestionsSorted = [...filtered].sort((a, b) => {
      const aActive = _activeSymbolsCache.has(`${a.symbol}:${a.side}`);
      const bActive = _activeSymbolsCache.has(`${b.symbol}:${b.side}`);
      if (aActive === bActive) return 0;
      return aActive ? 1 : -1;  // 활성 = 뒤!
    });
    const suggestions = suggestionsSorted;
    countEl.textContent = String(all.length);
    // 아래 렌더링 로직 (v133 사장님 요구: 신뢰도 순 + 순위 + 배지!)
    const cardsHtml = suggestions.map((s, idx) => {
      const side = s.side || 'SHORT';
      const sideColor = side === 'LONG' ? '#22c55e' : '#ef4444';
      const sideIcon = side === 'LONG' ? '🐂' : '🐻';
      const sideLabel = side === 'LONG' ? 'LONG' : 'SHORT';
      const confRaw = s.confidence_score ? Number(s.confidence_score) : 0;
      const confPct = (confRaw * 100).toFixed(0);
      const conf = confRaw ? confPct + '%' : '?';
      // 🌟 v136a: 활성 포지션 여부!
      const isActive = _activeSymbolsCache.has(`${s.symbol}:${side}`);
      const activeBadge = isActive
        ? `<span style="background:#fbbf24;color:#000;padding:1px 6px;border-radius:4px;font-size:10px;font-weight:bold;margin-left:4px" title="이 심볼 = 이미 진입 중! (중복 진입 주의!)">🔒 진입중</span>`
        : '';
      const activeOpacity = isActive ? 'opacity:0.6' : '';

      // 🌟 v133 신: 신뢰도별 배지 + 색상!
      let confBadge = '';
      let confColor = '#fbbf24';  // 기본 노랑
      if (confRaw >= 0.90) {
        confBadge = '🔥 최상';
        confColor = '#ef4444';  // 빨강 = 최상!
      } else if (confRaw >= 0.80) {
        confBadge = '⭐ 상';
        confColor = '#f59e0b';  // 주황 = 상!
      } else if (confRaw >= 0.70) {
        confBadge = '✨ 중';
        confColor = '#fbbf24';  // 노랑 = 중!
      } else {
        confBadge = '💧 하';
        confColor = '#94a3b8';  // 회색 = 하!
      }

      // 순위 (1위, 2위, 3위!)
      const rankIcon = idx === 0 ? '🥇' : idx === 1 ? '🥈' : idx === 2 ? '🥉' : `#${idx + 1}`;

      // 🌟 v133c: suggestion_type label 매핑!
      // 🌟 Fix 69 (2026-08-25): v219 sajangnim_top/bottom + 마틴게일 재진입 접미사 매핑 확장!
      const TYPE_LABELS = {
        // 🌟 v143a: 자동 제안 소스가 4H 볼밴 스캐너로 교체됨 (실측 기대값 기반)
        'bb4h_mid_down': '📉 4H 중단이탈→하단',
        'bb4h_mid_up': '📈 4H 중단돌파→상단',
        'bb4h_lower_break': '📉 4H 하단이탈',
        'bb4h_upper_break': '📈 4H 상단돌파',
        // 🌟 Fix 14 (v219): 사장님 실 성공 로직 = 7중 정점 SHORT / 저점 LONG!
        'sajangnim_top_short': '👑 v219 정점 SHORT',
        'sajangnim_top_short_reentry1': '👑🥈 정점 2차재진입 SHORT',
        'sajangnim_top_short_reentry2': '👑🥉 정점 3차재진입 SHORT',
        'sajangnim_top_short_reentry3': '👑🚨 정점 라스트 SHORT',
        'sajangnim_bottom_long': '🌊 v219 저점 LONG',
        'sajangnim_bottom_long_reentry1': '🌊🥈 저점 2차재진입 LONG',
        'sajangnim_bottom_long_reentry2': '🌊🥉 저점 3차재진입 LONG',
        'sajangnim_bottom_long_reentry3': '🌊🚨 저점 라스트 LONG',
        // 🌟 Fix 4/Fix 7: 성공 피라미딩 + PENDING_HC fast + Unified 15m + OBV
        'auto_bb_break_pyramid1': '🎯 성공재진입 #1',
        'auto_bb_break_pyramid2': '🎯 성공재진입 #2',
        'auto_bb_break_pyramid3': '🎯 성공재진입 #3 MAX',
        'auto_bb_break_lastchance': '🚨 라스트챈스',
        'PENDING_HC_FAST': '⚡ 급속 HC 85%+',
        'UNIFIED_15M': '📊 통합 15m',
        'OBV_HOLD': '📈 OBV 홀드',
        // 아래는 옛 24h 순위 기반 (v143a 이전 생성분 = 24h 내 자동 만료)
        'pump_end': '급등후 반락',
        'pump_continuation': '급등 지속',
        'pump_live': '🚀 실시간 급등!',
        'dump_continuation': '급락 지속',
        'dump_reversal': '급락 반등',
        'dump_live': '📉 실시간 급락!',
      };
      const typeLabel = TYPE_LABELS[s.suggestion_type] || s.suggestion_type;
      // 실시간은 = 더 강조!
      const isLive = s.suggestion_type === 'pump_live' || s.suggestion_type === 'dump_live';
      const liveGlow = isLive ? 'box-shadow:0 0 15px ' + sideColor + ',0 0 5px ' + sideColor + ';animation:pulse 1.5s infinite' : '';

      const createdAgo = _formatTimeAgo(s.created_at);
      const cfg = s.strategy_config || {};
      const cap1 = (cfg.capitals && cfg.capitals[0]) || '?';
      const lev = cfg.leverage || '?';
      const forceSl = cfg.force_sl_roi_override || '?';
      const reason = s.reason || '(이유 없음)';

      return `
        <div style="background:rgba(0,0,0,0.3);border:1px solid ${sideColor};border-radius:6px;padding:8px 10px;box-shadow:0 0 8px ${sideColor}44;${liveGlow};${activeOpacity};cursor:pointer"
             onclick="openSuggestionAnalysis('${s.symbol}', '${side}', ${s.id})"
             title="클릭 = 상세 분석 새 창!">
          <div class="flex items-center justify-between mb-1">
            <span class="text-sm font-bold" style="color:${sideColor}">
              <span style="color:#c4b5fd;font-size:0.85em">${rankIcon}</span>
              ${sideIcon} ${s.symbol} ${sideLabel}${activeBadge}
              <span class="text-xs text-slate-400 ml-1">| ${typeLabel}</span>
            </span>
            <span class="text-xs font-bold" style="color:${confColor}">
              ${confBadge} ${conf}
            </span>
          </div>
          <div class="text-xs text-slate-400 mb-1">
            ⏰ 생성: <span style="color:#c4b5fd">${createdAgo}</span>
            &nbsp;|&nbsp;
            📊 ${cap1} USDT × ${lev}x, 강제 SL -${forceSl}%
          </div>
          <div class="text-xs text-blue-300 mb-2" style="font-style:italic">
            💡 ${reason}
          </div>
          <div class="flex gap-2">
            <button onclick="event.stopPropagation();confirmLiveEntry('${s.symbol}', '${side}', '${encodeURIComponent(JSON.stringify(cfg))}')"
                    class="text-xs font-bold px-3 py-1 rounded"
                    style="background:linear-gradient(135deg,#059669,#22c55e);color:#fff;border:0;cursor:pointer"
                    title="추천 이유 확인 → 세팅 modal!">
              ✏ 세팅 후 진입
            </button>
            <button onclick="event.stopPropagation();openSuggestionAnalysis('${s.symbol}', '${side}', ${s.id})"
                    class="text-xs font-bold px-3 py-1 rounded"
                    style="background:linear-gradient(135deg,#3b82f6,#8b5cf6);color:#fff;border:0;cursor:pointer"
                    title="상세 분석 새 창 열기!">
              📊 상세 분석
            </button>
            <span class="text-xs px-2 py-1 rounded"
                  style="background:rgba(6,182,212,0.20);color:#67e8f9;border:1px solid rgba(6,182,212,0.4);font-weight:bold"
                  title="v224 통합 워커(unified_15m_entry) = 15m 급등/급락 심볼만 매 30초 자동 진입. 이 카드는 조회 전용!">
              ⚠️ v224 통합 워커가 자동 진입! 조회 전용!
            </span>
            <button onclick="event.stopPropagation();dismissSuggestion(${s.id})"
                    class="text-xs px-3 py-1 rounded"
                    style="background:#475569;color:#fff;border:0;cursor:pointer"
                    title="이 제안 삭제!">
              ❌ 삭제
            </button>
          </div>
        </div>
      `;
    }).join('');
    listEl.innerHTML = filterBtns + cardsHtml;
  } catch (e) {
    console.warn('[suggestions] render 실패:', e);
  }
}

function _formatTimeAgo(iso) {
  if (!iso) return '?';
  try {
    const ms = Date.now() - new Date(iso).getTime();
    if (ms < 0) return '방금 전';
    const min = Math.floor(ms / 60000);
    if (min < 1) return '방금 전';
    if (min < 60) return `${min}분 전`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}시간 전`;
    const day = Math.floor(hr / 24);
    return `${day}일 전`;
  } catch { return '?'; }
}

// 🌟 v132 사장님 요구 (2026-08-11):
// "기존 전략과 같이 세팅할수 있어야 하는데 기존 전략방식에 세팅을 할수 있게 해줘"
// = executeSuggestion = 신 전략 모달 열기!
// = 심볼/side/자본/TP/SL 자동 세팅!
// = 사장님이 = 확인 + 세팅 조정 + 진입!
async function executeSuggestion(id, symbol, side, configStr) {
  try {
    // 1. 신 전략 모달 열기 (기존 방식!)
    if (typeof openCreateModal !== 'function') {
      if (typeof toast === 'function') toast('❌ 신 전략 모달 함수 없음', 'error');
      return;
    }
    await openCreateModal();

    // 2. config 파싱 (encodeURIComponent 로 인코딩 되어 있음!)
    let config = {};
    try {
      config = JSON.parse(decodeURIComponent(configStr));
    } catch (_e) {
      console.warn('[suggestion] config 파싱 실패:', _e);
    }

    // 3. 자동 세팅! (300ms 대기 = modal 완전 로드!)
    setTimeout(() => {
      try {
        // 심볼!
        const symbolInput = document.getElementById('cm-symbol');
        if (symbolInput) {
          symbolInput.value = symbol;
          symbolInput.dispatchEvent(new Event('input', {bubbles: true}));
          symbolInput.dispatchEvent(new Event('change', {bubbles: true}));
        }
        // side!
        if (typeof setCmSide === 'function') setCmSide(side);
        // 레버리지!
        if (config.leverage) {
          const lvEl = document.getElementById('cm-leverage');
          if (lvEl) {
            lvEl.value = config.leverage;
            if (typeof cmLeverageManuallyEdited !== 'undefined') {
              cmLeverageManuallyEdited = true;
            }
          }
        }
        // 자본 (1~10단계!)
        const caps = config.capitals || [];
        const trigs = config.trigger_percents || [];
        for (let i = 0; i < 10; i++) {
          const capEl = document.getElementById(`cm-cap-${i+1}`);
          const trgEl = document.getElementById(`cm-trg-${i+1}`);
          if (capEl) capEl.value = (caps[i] !== undefined && caps[i] !== null) ? caps[i] : '';
          if (trgEl && i > 0) {
            trgEl.value = (trigs[i] !== undefined && trigs[i] !== null) ? trigs[i] : '';
          }
        }
        // TP1~10!
        for (let n = 1; n <= 10; n++) {
          const pctEl = document.getElementById(`cm-tp${n}-pct`);
          const qtyEl = document.getElementById(`cm-tp${n}-qty`);
          if (pctEl && config[`tp${n}_percent`] !== undefined) {
            pctEl.value = config[`tp${n}_percent`] || '';
          }
          if (qtyEl && config[`tp${n}_qty_ratio`] !== undefined) {
            qtyEl.value = config[`tp${n}_qty_ratio`] || '';
          }
        }
        // SL!
        if (config.stop_loss_percent_of_capital) {
          const slEl = document.getElementById('cm-sl-pct');
          if (slEl) slEl.value = config.stop_loss_percent_of_capital;
        }
        // 실시간 계산!
        if (typeof onCapitalsChange === 'function') onCapitalsChange();
        if (typeof _refreshLiveCalc === 'function') _refreshLiveCalc();

        if (typeof toast === 'function') {
          toast(`🎯 ${symbol} ${side} 제안 = 모달! 세팅 확인 후 진입!`, 'success');
        }
      } catch (_e) {
        console.warn('[suggestion] auto-fill 실패:', _e);
      }
    }, 300);

    // 4. 제안 삭제 (사장님 선택했으니!) - 진입 후 자동!
    // 진입 완료 = executed status = 다른 방식으로 추적!
    // 지금은 = 자동 삭제 X (사장님이 취소 가능!)
  } catch (e) {
    if (typeof toast === 'function') toast('❌ 실행 실패: ' + (e.message || e), 'error');
  }
}

async function dismissSuggestion(id) {
  if (!confirm('이 제안을 삭제하시겠습니까?')) return;
  try {
    await api('/strategy-suggestions/' + id, { method: 'DELETE' });
    if (typeof toast === 'function') toast('✅ 제안 삭제', 'success');
    loadStrategySuggestions();
  } catch (e) {
    if (typeof toast === 'function') toast('❌ 삭제 실패: ' + (e.message || e), 'error');
  }
}

// 🌟 v132 사장님 요구: 즉시 학습 실행!
async function triggerLearningNow() {
  // 사장님 = 재실행 시 = 오늘 것 삭제하고 새로!
  const force = confirm(
    '지금 즉시 학습 실행!\n\n' +
    '= Binance 급등/급락 top 40 예측!\n' +
    '= 20 LONG + 20 SHORT!\n\n' +
    '👉 [확인] = 오늘 기존 제안 = 자동 삭제 후 재생성!\n' +
    '👉 [취소] = 실행 안 함!'
  );
  if (!force) return;
  try {
    if (typeof toast === 'function') toast('🎯 학습 시작! 30초 대기...', 'info');
    const r = await api('/strategy-suggestions/trigger-now?force=true', { method: 'POST' });
    const created = (r.result || {}).created || 0;
    const preds = (r.result || {}).predictions || 0;
    if (typeof toast === 'function') {
      toast(`✅ 학습 완료! ${preds} 예측, ${created} 신 제안 생성!`, 'success');
    }
    loadStrategySuggestions();  // 카드 즉시 새로고침!
  } catch (e) {
    if (typeof toast === 'function') toast('❌ 학습 실패: ' + (e.message || e), 'error');
  }
}

async function briefingNow() {
  if (!confirm('지금 즉시 브리핑 발송하시겠습니까?\n\n= Telegram으로 요약!')) return;
  try {
    const r = await api('/strategy-suggestions/briefing-now', { method: 'POST' });
    if (typeof toast === 'function') {
      toast(`✅ 브리핑 발송 완료! Telegram 확인!`, 'success');
    }
  } catch (e) {
    if (typeof toast === 'function') toast('❌ 브리핑 실패: ' + (e.message || e), 'error');
  }
}

async function openSuggestionsSettingsModal() {
  try {
    const [settings, profilesData] = await Promise.all([
      api('/strategy-suggestions/settings'),
      api('/suggestion-profiles'),
    ]);
    const profiles = profilesData.profiles || [];
    const currentDefault = profilesData.default || 'safe';
    const cfg = (profiles.find(p => p.name === currentDefault) || profiles[0] || {}).config || {};

    const existing = document.getElementById('suggestions-settings-modal');
    if (existing) existing.remove();

    // 프로필 옵션 HTML
    const profileOpts = profiles.map(p =>
      `<option value="${p.name}" ${p.name === currentDefault ? 'selected' : ''}>${p.label || p.name}</option>`
    ).join('');

    const html = `
      <div id="suggestions-settings-modal" class="fixed inset-0 z-50 flex items-center justify-center"
           style="background:rgba(0,0,0,0.7)"
           onclick="if(event.target===this)closeSuggestionsSettingsModal()">
        <div class="bg-slate-900 rounded-lg p-6 max-w-2xl w-full mx-4"
             style="border:2px solid #a855f7;box-shadow:0 0 20px #a855f766;max-height:90vh;overflow-y:auto">
          <h3 class="text-lg font-bold text-purple-300 mb-3">
            ⚙ 전략 제안 세팅
            <span class="text-xs text-slate-400 font-normal">(자동 전략 제안 + 급등락 BB 이탈 자동 진입 = 공유!)</span>
          </h3>
          <div class="text-xs text-yellow-400 mb-3 p-2 rounded bg-slate-800 border border-yellow-800">
            💡 <b>v164a 사장님:</b> 이 세팅은 = 「🎯 자동 전략 제안」 + 「🤖 BB 이탈 자동 진입」 모두 사용!<br>
            = 자본, 트리거 %, TP, SL, 레버리지 = <b>공유 설정!</b>
          </div>

          <!-- ═══════ 섹션 1: 자동 실행 세팅 ═══════ -->
          <div class="mb-4 p-3 rounded bg-slate-800 border border-slate-700">
            <h4 class="text-sm font-bold text-yellow-300 mb-2">🤖 자동 실행 (기본 OFF!)</h4>
            <div class="space-y-2">
              <label class="flex items-center gap-2 text-sm text-slate-200 cursor-pointer">
                <input type="checkbox" id="sug-auto-enabled"
                       ${settings.auto_execute_enabled?'checked':''}
                       style="width:16px;height:16px;cursor:pointer">
                <span class="font-bold">자동 실행 활성화</span>
              </label>
              <p class="text-xs text-yellow-400 ml-6">⚠️ ON = 승인 없이 자동 진입!</p>

              <div class="grid grid-cols-3 gap-2 text-xs">
                <div>
                  <label class="text-slate-400">🎯 신뢰도:</label>
                  <input type="number" id="sug-confidence"
                         value="${settings.confidence_threshold}"
                         min="0" max="1" step="0.01"
                         class="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-slate-200">
                </div>
                <div>
                  <label class="text-slate-400">📆 일일 한도:</label>
                  <input type="number" id="sug-daily-limit"
                         value="${settings.daily_auto_limit}"
                         min="1" max="10"
                         class="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-slate-200">
                </div>
                <div>
                  <label class="text-slate-400">⏰ 자동 삭제(h):</label>
                  <input type="number" id="sug-auto-dismiss"
                         value="${settings.auto_dismiss_hours}"
                         min="0" max="72"
                         class="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-slate-200">
                </div>
              </div>
            </div>
          </div>

          <!-- ═══════ 섹션 2: 기본 프로필 세팅 (심플!) ═══════ -->
          <div class="mb-4 p-3 rounded bg-slate-800 border border-purple-700">
            <h4 class="text-sm font-bold text-purple-300 mb-2">💰 단계별 진입금액 + 트리거율!</h4>
            <p class="text-xs text-slate-400 mb-2">
              💡 자동 학습 = 이 세팅으로 신 전략 제안!<br>
              💡 나머지 (레버리지/TP/SL) = 「✏ 세팅 후 진입」 = 신 전략 모달에서!
            </p>

            <div class="mb-2">
              <label class="text-xs text-slate-400 block mb-1">📋 현재 default 프로필:</label>
              <select id="sug-profile-select"
                      onchange="_switchProfile(this.value)"
                      class="w-full bg-slate-900 border border-purple-600 rounded px-2 py-1 text-slate-200 text-sm">
                ${profileOpts}
              </select>
            </div>

            <div class="grid grid-cols-4 gap-1 text-xs mt-2">
              <div>
                <label class="text-slate-400 block mb-1">💰 1단계 자본:</label>
                <input type="number" id="prof-cap-1" value="${(cfg.capitals||[])[0]||500}"
                       placeholder="필수!"
                       class="w-full bg-slate-900 border border-slate-600 rounded px-1 py-1 text-slate-200 text-center">
              </div>
              <div>
                <label class="text-slate-400 block mb-1">2단계 (선택):</label>
                <input type="number" id="prof-cap-2" value="${(cfg.capitals||[])[1]||''}"
                       placeholder="비움"
                       class="w-full bg-slate-900 border border-slate-600 rounded px-1 py-1 text-slate-200 text-center">
              </div>
              <div>
                <label class="text-slate-400 block mb-1">3단계 (선택):</label>
                <input type="number" id="prof-cap-3" value="${(cfg.capitals||[])[2]||''}"
                       placeholder="비움"
                       class="w-full bg-slate-900 border border-slate-600 rounded px-1 py-1 text-slate-200 text-center">
              </div>
              <div>
                <label class="text-slate-400 block mb-1">4단계 (선택):</label>
                <input type="number" id="prof-cap-4" value="${(cfg.capitals||[])[3]||''}"
                       placeholder="비움"
                       class="w-full bg-slate-900 border border-slate-600 rounded px-1 py-1 text-slate-200 text-center">
              </div>
            </div>

            <div class="grid grid-cols-4 gap-1 text-xs mt-2">
              <div>
                <label class="text-slate-400 block mb-1">📊 1단계 트리거:</label>
                <input type="text" value="즉시" disabled
                       class="w-full bg-slate-900 border border-slate-700 rounded px-1 py-1 text-slate-500 text-center">
              </div>
              <div>
                <label class="text-slate-400 block mb-1">2단계 %:</label>
                <input type="number" id="prof-trg-2" value="${(cfg.trigger_percents||[])[1]||10}"
                       placeholder="10"
                       class="w-full bg-slate-900 border border-slate-600 rounded px-1 py-1 text-slate-200 text-center">
              </div>
              <div>
                <label class="text-slate-400 block mb-1">3단계 %:</label>
                <input type="number" id="prof-trg-3" value="${(cfg.trigger_percents||[])[2]||20}"
                       placeholder="20"
                       class="w-full bg-slate-900 border border-slate-600 rounded px-1 py-1 text-slate-200 text-center">
              </div>
              <div>
                <label class="text-slate-400 block mb-1">4단계 %:</label>
                <input type="number" id="prof-trg-4" value="${(cfg.trigger_percents||[])[3]||20}"
                       placeholder="20"
                       class="w-full bg-slate-900 border border-slate-600 rounded px-1 py-1 text-slate-200 text-center">
              </div>
            </div>

            <p class="text-xs text-green-300 mt-2">
              💡 <strong>1단계 = 필수!</strong> 2/3/4단계 = 비우면 = 사용 X!<br>
              💡 예: 1단계만 세팅 → 1단계만 진입!
            </p>
          </div>

          <p class="text-xs text-blue-300 mb-3">
            💡 <strong>개별 세팅 우선!</strong> 「✏ 세팅 후 진입」 = 사장님 조정 가능!<br>
            💡 <strong>이 기본값</strong> = 자동 학습 + 신 제안 시 = 시작점!
          </p>

          <div class="flex gap-2 mt-4">
            <button onclick="saveSuggestionsSettings()"
                    class="flex-1 bg-purple-600 hover:bg-purple-500 text-white font-bold py-2 rounded">
              💾 저장
            </button>
            <button onclick="closeSuggestionsSettingsModal()"
                    class="flex-1 bg-slate-700 hover:bg-slate-600 text-slate-300 py-2 rounded">
              ✕ 취소
            </button>
          </div>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);
  } catch (e) {
    if (typeof toast === 'function') toast('❌ 세팅 조회 실패: ' + (e.message || e), 'error');
  }
}

function closeSuggestionsSettingsModal() {
  const el = document.getElementById('suggestions-settings-modal');
  if (el) el.remove();
}

// 🌟 v132 사장님: 프로필 전환 (심플 = 자본 + 트리거만!)
// 빈 단계 = 빈 값 표시!
async function _switchProfile(profileName) {
  try {
    const profilesData = await api('/suggestion-profiles');
    const profiles = profilesData.profiles || [];
    const p = profiles.find(x => x.name === profileName);
    if (!p) return;
    const cfg = p.config || {};
    const set = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.value = (val !== undefined && val !== null && val !== '') ? val : '';
    };
    const caps = cfg.capitals || [];
    const trigs = cfg.trigger_percents || [];
    // 1단계 = 필수 (default 500)!
    set('prof-cap-1', caps[0] || 500);
    // 2~4단계 = 빈 값 지원!
    set('prof-cap-2', caps[1]);
    set('prof-cap-3', caps[2]);
    set('prof-cap-4', caps[3]);
    // 트리거 %
    set('prof-trg-2', trigs[1] || 10);
    set('prof-trg-3', trigs[2] || 20);
    set('prof-trg-4', trigs[3] || 20);
  } catch (_e) {
    console.warn('[profile] 전환 실패:', _e);
  }
}

async function saveSuggestionsSettings() {
  try {
    // 1. 자동 실행 세팅 저장!
    const enabled = document.getElementById('sug-auto-enabled').checked;
    const confidence = document.getElementById('sug-confidence').value;
    const dailyLimit = document.getElementById('sug-daily-limit').value;
    const autoDismiss = document.getElementById('sug-auto-dismiss').value;

    await api('/strategy-suggestions/settings', {
      method: 'PUT',
      body: {
        auto_execute_enabled: enabled,
        confidence_threshold: confidence,
        daily_auto_limit: dailyLimit,
        auto_dismiss_hours: autoDismiss,
      }
    });

    // 2. 🌟 신: 심플 프로필 세팅 저장 (자본 + 트리거만!)
    const profileName = document.getElementById('sug-profile-select').value;
    const num = (id, def) => {
      const el = document.getElementById(id);
      return el ? Number(el.value) || def : def;
    };

    // 기존 프로필 config 로드 → 자본/트리거만 update!
    const profilesData = await api('/suggestion-profiles');
    const profiles = profilesData.profiles || [];
    const idx = profiles.findIndex(p => p.name === profileName);
    if (idx >= 0) {
      const existingConfig = profiles[idx].config || {};

      // 🌟 v132 사장님 (2026-08-12): 빈 단계 = 사용 X!
      // 값이 있고 > 0 인 단계만 포함!
      const numOrNull = (id) => {
        const el = document.getElementById(id);
        if (!el || !el.value) return null;
        const v = Number(el.value);
        return (v > 0) ? v : null;
      };

      const rawCaps = [
        numOrNull('prof-cap-1'),
        numOrNull('prof-cap-2'),
        numOrNull('prof-cap-3'),
        numOrNull('prof-cap-4'),
      ];
      // 값 있는 단계만! (1단계 필수, 없으면 = 500 default)
      const caps = rawCaps.filter(c => c !== null);
      if (caps.length === 0) {
        caps.push(500);  // 1단계 필수 fallback!
      }

      const rawTrigs = [
        null,  // 1단계 = 즉시!
        numOrNull('prof-trg-2') || 10,
        numOrNull('prof-trg-3') || 20,
        numOrNull('prof-trg-4') || 20,
      ];
      // caps 개수만큼만!
      const trigs = rawTrigs.slice(0, caps.length);

      existingConfig.capitals = caps;
      existingConfig.trigger_percents = trigs;
      profiles[idx].config = existingConfig;
    }
    // 저장!
    await api('/suggestion-profiles', {
      method: 'PUT',
      body: {
        profiles: profiles,
        default: profileName,  // 사장님 선택 = default!
      }
    });

    // 🌟 v132 사장님 지적 (2026-08-12): 오늘 PENDING 카드에도 즉시 적용!
    let applyResult = null;
    try {
      applyResult = await api('/suggestion-profiles/apply-to-pending', { method: 'POST' });
    } catch (_e) {
      console.warn('[settings] apply-to-pending 실패:', _e);
    }

    if (typeof toast === 'function') {
      const applyMsg = applyResult && applyResult.updated
        ? ` + 오늘 ${applyResult.updated}건 카드 신 세팅 적용!`
        : '';
      toast(`✅ 세팅 저장! 자동 실행 ${enabled?'ON 🤖':'OFF 🙋'}${applyMsg}`, 'success');
    }
    closeSuggestionsSettingsModal();
    // 카드 새로고침 = 신 세팅 반영!
    if (typeof loadStrategySuggestions === 'function') {
      loadStrategySuggestions();
    }
  } catch (e) {
    if (typeof toast === 'function') toast('❌ 저장 실패: ' + (e.message || e), 'error');
  }
}

// 🌟 v133c (2026-08-13 사장님!): 상세 분석 새 창!
function openSuggestionAnalysis(symbol, side, suggestionId) {
  try {
    const url = `/static/analysis.html?symbol=${encodeURIComponent(symbol)}&side=${encodeURIComponent(side)}&sid=${suggestionId}`;
    window.open(url, '_blank', 'width=550,height=700,scrollbars=yes');
  } catch (e) {
    console.warn('[analysis] 새 창 열기 실패:', e);
    if (typeof toast === 'function') toast('❌ 새 창 열기 실패!', 'error');
  }
}

if (typeof window !== 'undefined') {
  window.loadStrategySuggestions = loadStrategySuggestions;
  window.executeSuggestion = executeSuggestion;
  window.dismissSuggestion = dismissSuggestion;
  window.triggerLearningNow = triggerLearningNow;  // v132 즉시 실행!
  window.dismissLowConfidence = dismissLowConfidence;  // v155 85%↓ 초기화!
  window.saveAutoBBLimit = saveAutoBBLimit;  // v162 자동 BB 진입 개수!
  window.loadAutoBBLimit = loadAutoBBLimit;

// 🎯 사장님 (2026-08-22): OBV 자동 진입 전용 세팅 modal!
async function openOBVSettingsModal() {
  let s;
  try {
    s = await api('/strategy-suggestions/obv-settings');
  } catch (e) {
    if (typeof toast === 'function') toast('OBV 세팅 로드 실패: ' + e.message, 'error');
    return;
  }
  const _inp = (id, val, opts = {}) =>
    `<input type="number" id="${id}" value="${val}" min="${opts.min ?? 0}" max="${opts.max ?? 999999}" step="${opts.step ?? 1}"
      style="width:${opts.width || 70}px;background:#0f172a;border:1px solid #334155;color:#e2e8f0;padding:2px 6px;border-radius:4px" />`;
  const html = `
    <div id="obv-modal-bg" style="position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.75);z-index:9999;display:flex;align-items:center;justify-content:center;overflow-y:auto;padding:20px" onclick="if(event.target.id==='obv-modal-bg')document.getElementById('obv-modal-bg').remove()">
      <div style="background:#1e293b;color:#e2e8f0;padding:20px;border-radius:8px;max-width:560px;width:95%;border:2px solid #7c3aed;max-height:90vh;overflow-y:auto">
        <h3 style="font-size:16px;font-weight:bold;color:#22d3ee;margin-bottom:12px">🎯 OBV 자동 진입 전용 세팅</h3>
        <div style="font-size:11px;color:#94a3b8;margin-bottom:12px;padding:8px;background:rgba(0,0,0,0.3);border-radius:4px;border-left:3px solid #7c3aed">
          <b>사장님 사상:</b> 신뢰도 높은 심볼만 신중! + <b style="color:#22c55e">3단계 오래 버티기!</b><br>
          진입 = <b style="color:#22d3ee">1단계 MARKET</b> → <b style="color:#f59e0b">2단계 (-5%)</b> → <b style="color:#ef4444">3단계 (-10%)</b><br>
          강제 SL 비활성 = 사장님 수동 개입 (증거금/포지션!)
        </div>

        <div style="margin-bottom:14px;padding:10px;background:rgba(124,58,237,0.1);border-radius:6px;border-left:3px solid #a78bfa">
          <div style="font-weight:bold;color:#a78bfa;margin-bottom:8px">📋 활성화 + 안전!</div>
          <label style="display:flex;align-items:center;gap:8px;font-size:12px;margin-bottom:6px">
            <input type="checkbox" id="obv-enabled" ${s.enabled ? 'checked' : ''} />
            <b>ON / OFF</b>
          </label>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:12px">
            <label><b>일 최대 건수</b><br>${_inp('obv-daily-limit', s.daily_limit, {min:0, max:20})} <span style="color:#94a3b8;font-size:10px">건/일</span></label>
            <label><b>최소 신뢰도</b><br>${_inp('obv-min-conf', s.min_confidence, {min:0.5, max:1.0, step:0.01})} <span style="color:#94a3b8;font-size:10px">(0~1)</span></label>
          </div>
        </div>

        <div style="margin-bottom:14px;padding:10px;background:rgba(34,197,94,0.08);border-radius:6px;border-left:3px solid #22c55e">
          <div style="font-weight:bold;color:#22c55e;margin-bottom:8px">💰 자본 + 레버리지</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:12px">
            <label><b>1단계 자본</b><br>${_inp('obv-capital', s.capital_per_stage, {min:10, max:100000})} <span style="color:#94a3b8;font-size:10px">USDT × 3단계!</span></label>
            <label><b>레버리지</b><br>${_inp('obv-leverage', s.leverage, {min:1, max:20})} <span style="color:#94a3b8;font-size:10px">x</span></label>
          </div>
          <div style="font-size:10px;color:#94a3b8;margin-top:6px">= 총 자본: <b id="obv-total-capital" style="color:#22c55e">${s.capital_per_stage * 3}</b> USDT</div>
        </div>

        <div style="margin-bottom:14px;padding:10px;background:rgba(245,158,11,0.08);border-radius:6px;border-left:3px solid #f59e0b">
          <div style="font-weight:bold;color:#f59e0b;margin-bottom:8px">🎯 단계 트리거 (반대방향!)</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:12px">
            <label><b>2단계 트리거</b><br>${_inp('obv-trig2', s.stage2_trigger_pct, {min:-50, max:-0.5, step:0.5})} <span style="color:#94a3b8;font-size:10px">% (반대방향 -5%!)</span></label>
            <label><b>3단계 트리거</b><br>${_inp('obv-trig3', s.stage3_trigger_pct, {min:-80, max:-1, step:0.5})} <span style="color:#94a3b8;font-size:10px">% (반대방향 -10%!)</span></label>
          </div>
        </div>

        <div style="margin-bottom:14px;padding:10px;background:rgba(56,189,248,0.08);border-radius:6px;border-left:3px solid #38bdf8">
          <div style="font-weight:bold;color:#38bdf8;margin-bottom:8px">📈 TP (익절 %)</div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:6px;font-size:12px">
            <label><b>TP1</b><br>${_inp('obv-tp1', s.tp1_percent, {min:0.5, max:100, step:0.5, width:55})}%</label>
            <label><b>TP2</b><br>${_inp('obv-tp2', s.tp2_percent, {min:0.5, max:100, step:0.5, width:55})}%</label>
            <label><b>TP3</b><br>${_inp('obv-tp3', s.tp3_percent, {min:0.5, max:100, step:0.5, width:55})}%</label>
            <label><b>TP4</b><br>${_inp('obv-tp4', s.tp4_percent, {min:0.5, max:100, step:0.5, width:55})}%</label>
          </div>
        </div>

        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button onclick="document.getElementById('obv-modal-bg').remove()"
                  style="padding:6px 14px;background:#475569;color:#fff;border:0;border-radius:4px;cursor:pointer">✕ 취소</button>
          <button onclick="saveOBVSettings()"
                  style="padding:6px 14px;background:linear-gradient(135deg,#0891b2,#7c3aed);color:#fff;border:0;border-radius:4px;cursor:pointer;font-weight:bold">💾 저장</button>
        </div>
      </div>
    </div>`;
  document.body.insertAdjacentHTML('beforeend', html);
  // 자본×3 자동 갱신!
  document.getElementById('obv-capital').addEventListener('input', (e) => {
    document.getElementById('obv-total-capital').textContent = (parseFloat(e.target.value) || 0) * 3;
  });
}

async function saveOBVSettings() {
  const payload = {
    enabled: document.getElementById('obv-enabled').checked ? 1 : 0,
    daily_limit: parseInt(document.getElementById('obv-daily-limit').value) || 3,
    min_confidence: parseFloat(document.getElementById('obv-min-conf').value) || 0.95,
    capital_per_stage: parseInt(document.getElementById('obv-capital').value) || 400,
    leverage: parseInt(document.getElementById('obv-leverage').value) || 2,
    stage2_trigger_pct: parseFloat(document.getElementById('obv-trig2').value) || -5.0,
    stage3_trigger_pct: parseFloat(document.getElementById('obv-trig3').value) || -10.0,
    tp1_percent: parseFloat(document.getElementById('obv-tp1').value) || 10.0,
    tp2_percent: parseFloat(document.getElementById('obv-tp2').value) || 15.0,
    tp3_percent: parseFloat(document.getElementById('obv-tp3').value) || 20.0,
    tp4_percent: parseFloat(document.getElementById('obv-tp4').value) || 25.0,
  };
  try {
    await api('/strategy-suggestions/obv-settings', {
      method: 'PUT', body: payload,
    });
    if (typeof toast === 'function') toast(
      `✅ OBV 세팅 저장! ${payload.enabled ? 'ON' : 'OFF'} · 일 ${payload.daily_limit}건 · 신뢰도 ${(payload.min_confidence*100).toFixed(0)}%+`,
      'success'
    );
    document.getElementById('obv-modal-bg').remove();
    loadOBVStatus();  // 상태 갱신!
  } catch (e) {
    if (typeof toast === 'function') toast('❌ 저장 실패: ' + e.message, 'error');
  }
}

async function loadOBVStatus() {
  try {
    const s = await api('/strategy-suggestions/obv-settings');
    const el = document.getElementById('obv-status');
    if (el) {
      el.textContent = ` (${s.enabled ? 'ON' : 'OFF'}·일${s.daily_limit}·${(s.min_confidence*100).toFixed(0)}%+)`;
    }
  } catch (e) {}
}
window.openOBVSettingsModal = openOBVSettingsModal;
window.saveOBVSettings = saveOBVSettings;
window.loadOBVStatus = loadOBVStatus;
setTimeout(loadOBVStatus, 800);
setInterval(loadOBVStatus, 60000);

// 🎯 v219 (2026-08-22 사장님!): 사장님 정점 SHORT 세팅 모달!
async function openSajangnimSettingsModal() {
  let s = {};
  try { s = await api('/strategy-suggestions/sajangnim-settings'); } catch(e) {}
  const html = `
    <div class="modal-overlay" onclick="closeSajangnimSettingsModal()"
         style="position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.85);z-index:9999;display:flex;align-items:center;justify-content:center;">
      <div onclick="event.stopPropagation()" style="background:#1e293b;padding:20px;border-radius:12px;max-width:480px;width:90%;color:#e2e8f0;border:2px solid #a78bfa;">
        <h3 style="color:#a78bfa;margin:0 0 12px 0;font-size:18px;">🎯 사장님 정점 SHORT 세팅 (v219)</h3>
        <div style="font-size:11px;color:#94a3b8;margin-bottom:14px;">
          "급등하는 심볼 4시간봉 최상단 볼밴 최상단밖 obv 최고점 macd rsi cci 모든 지표가 최고점일때 진입"
        </div>
        <div style="margin-bottom:10px;">
          <label style="display:block;font-size:12px;color:#c4b5fd;margin-bottom:2px;">💰 초기 진입 자본 (1단계 USDT!):</label>
          <input id="sn-default-capital" type="number" step="50" min="50" max="100000" value="${s.default_capital ?? 300}"
                 style="width:100%;background:#334155;color:#e2e8f0;border:1px solid #475569;padding:6px;border-radius:4px;">
          <div style="font-size:10px;color:#64748b;">사장님 default = 300 USDT / 운영하면서 조정!</div>
        </div>
        <div style="margin-bottom:10px;">
          <label style="display:block;font-size:12px;color:#c4b5fd;margin-bottom:2px;">🎯 마틴게일 최대 단계:</label>
          <select id="sn-max-stage" style="width:100%;background:#334155;color:#e2e8f0;border:1px solid #475569;padding:6px;border-radius:4px;">
            <option value="1" ${(s.max_stage ?? 2) === 1 ? 'selected' : ''}>1 = 재진입 X (1단계에서 종료)</option>
            <option value="2" ${(s.max_stage ?? 2) === 2 ? 'selected' : ''}>2 = 1→2단계까지 (사장님 추천!)</option>
            <option value="3" ${(s.max_stage ?? 2) === 3 ? 'selected' : ''}>3 = 1→2→3단계까지 (매우 신중!)</option>
          </select>
          <div style="font-size:10px;color:#64748b;line-height:1.5;margin-top:3px;">
            💡 1=재진입 X / 2=1→2단계까지 (사장님 추천!) / 3=1→2→3단계까지 (매우 신중!)
          </div>
        </div>
        <div style="margin-bottom:12px;padding:10px;background:#1e293b;border-left:3px solid #ec4899;border-radius:4px;">
          <div style="font-size:11px;color:#f472b6;font-weight:bold;margin-bottom:4px;">🎯 사장님 마틴게일 (v219 최종 확정!):</div>
          <div style="font-size:11px;color:#e2e8f0;line-height:1.6;">
            <b>1단계</b> = 초기 (예: <b>${s.default_capital ?? 300} USDT</b>)<br>
            <b>2단계</b> = 이전 × 2 (예: <b>${(s.default_capital ?? 300) * 2} USDT</b>) ← 가급적 여기서 끝!<br>
            <b style="color:#f59e0b;">⚠️ 3단계</b> = 투자금 전체 × 2 (예: <b style="color:#f59e0b;">${(s.default_capital ?? 300) * 6} USDT</b>) = 매우 신중!<br>
            <b style="color:#ef4444;">🚨 4단계+ = 금지! (사장님 상한!)</b>
          </div>
          <div style="font-size:10px;color:#94a3b8;margin-top:6px;">
            💡 전체 자산 무관 = 사장님 판단!<br>
            💡 3단계 = 가급적 피해야 = 강한 확신 시만! 손실 관리 필수!
          </div>
        </div>
        <div style="margin-bottom:14px;padding:8px;background:#1e293b;border-left:3px solid #f59e0b;border-radius:4px;">
          <div style="font-size:11px;color:#fbbf24;font-weight:bold;">📅 일 자동 진입 = 급등락 실시간과 공유!</div>
          <div style="font-size:10px;color:#94a3b8;margin-top:4px;">
            → 위 카드 「BB 이탈 자동 진입」 슬라이더에서 조정!<br>
            → v219 정점 SHORT = 여기에 통합됨! (별도 X!)
          </div>
        </div>
        <div style="display:flex;gap:8px;justify-content:flex-end;">
          <button onclick="closeSajangnimSettingsModal()" style="padding:6px 14px;background:#475569;color:#fff;border:none;border-radius:4px;cursor:pointer;">취소</button>
          <button onclick="saveSajangnimSettings()" style="padding:6px 14px;background:#a78bfa;color:#000;border:none;border-radius:4px;cursor:pointer;font-weight:bold;">✅ 저장</button>
        </div>
      </div>
    </div>`;
  const div = document.createElement('div');
  div.id = 'sajangnim-modal';
  div.innerHTML = html;
  document.body.appendChild(div);
}
function closeSajangnimSettingsModal() {
  const el = document.getElementById('sajangnim-modal');
  if (el) el.remove();
}
async function saveSajangnimSettings() {
  // 🎯 v219+ (2026-08-23): max_stage 신 필드! (1~3 clamp = 백엔드에서 재검증!)
  const maxStageRaw = parseInt(document.getElementById('sn-max-stage')?.value || 2);
  const maxStage = Math.max(1, Math.min(3, isNaN(maxStageRaw) ? 2 : maxStageRaw));
  const payload = {
    default_capital: parseFloat(document.getElementById('sn-default-capital').value || 300),
    max_stage: maxStage,
  };
  // localStorage 백업 = 서버 실패 시에도 UI 유지!
  try { localStorage.setItem('sajangnim_settings_backup', JSON.stringify(payload)); } catch(_) {}
  try {
    const r = await api('/strategy-suggestions/sajangnim-settings', {method: 'PUT', body: JSON.stringify(payload)});
    if (r.ok) {
      if (typeof toast === 'function') toast('✅ 사장님 정점 세팅 저장! (마틴게일 최대 ' + maxStage + '단계)', 'success');
      closeSajangnimSettingsModal();
    } else {
      if (typeof toast === 'function') toast('❌ ' + (r.error || '저장 실패'), 'error');
    }
  } catch (e) {
    if (typeof toast === 'function') toast('❌ 저장 실패: ' + e.message, 'error');
  }
}
// 🎯 v219 UI 개선: 모드 변경 = 자산% 필드 활성/비활성 토글!
function _snToggleModeUI() {
  const mode = document.getElementById('sn-capital-mode').value;
  const box = document.getElementById('sn-pct-box');
  const input = document.getElementById('sn-entry-pct');
  if (box) box.style.opacity = (mode === 'fixed') ? '0.4' : '1';
  if (input) input.disabled = (mode === 'fixed');
}
if (typeof window !== 'undefined') {
  window.openSajangnimSettingsModal = openSajangnimSettingsModal;
  window.closeSajangnimSettingsModal = closeSajangnimSettingsModal;
  window.saveSajangnimSettings = saveSajangnimSettings;
  window._snToggleModeUI = _snToggleModeUI;
}

// 🎯 v219 (2026-08-23): 카드형 세팅 UI (v219-daily-limit / v219-capital / v219-max-stage 필드!)
async function saveV219Settings() {
  const limitEl = document.getElementById('v219-daily-limit');
  const capitalEl = document.getElementById('v219-capital');
  const maxStageEl = document.getElementById('v219-max-stage');
  if (!limitEl || !capitalEl || !maxStageEl) {
    alert('❌ v219 세팅 UI를 찾을 수 없습니다.');
    return;
  }
  const limit = parseInt(limitEl.value);
  const capital = parseFloat(capitalEl.value);
  const maxStageRaw = parseInt(maxStageEl.value);
  const maxStage = Math.max(1, Math.min(3, isNaN(maxStageRaw) ? 2 : maxStageRaw));
  const payload = {
    top_short_daily_limit: isNaN(limit) ? 5 : limit,
    default_capital: isNaN(capital) ? 300 : capital,
    max_stage: maxStage,
  };
  try { localStorage.setItem('v219_settings_backup', JSON.stringify(payload)); } catch(_) {}
  try {
    const r = await api('/strategy-suggestions/sajangnim-settings', {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
    if (r && r.ok === false) {
      alert('❌ 저장 실패: ' + (r.error || 'unknown'));
      return;
    }
    if (typeof toast === 'function') {
      toast('✅ v219 세팅 저장 완료! (마틴게일 최대 ' + maxStage + '단계)', 'success');
    } else {
      alert('✅ v219 세팅 저장 완료!');
    }
    loadV219Settings();  // 재로드
  } catch (e) {
    alert('❌ 저장 실패: ' + (e && e.message ? e.message : e));
  }
}

async function loadV219Settings() {
  const limitEl = document.getElementById('v219-daily-limit');
  const capitalEl = document.getElementById('v219-capital');
  const maxStageEl = document.getElementById('v219-max-stage');
  if (!limitEl && !capitalEl && !maxStageEl) return;  // 카드 미표시 = skip
  try {
    const resp = await api('/strategy-suggestions/sajangnim-settings');
    if (limitEl) limitEl.value = resp.top_short_daily_limit ?? 5;
    if (capitalEl) capitalEl.value = resp.default_capital ?? 300;
    if (maxStageEl) maxStageEl.value = resp.max_stage ?? 2;
  } catch (e) {
    // 서버 실패 = localStorage backup 복원!
    try {
      const backup = localStorage.getItem('v219_settings_backup');
      if (backup) {
        const s = JSON.parse(backup);
        if (limitEl) limitEl.value = s.top_short_daily_limit ?? 5;
        if (capitalEl) capitalEl.value = s.default_capital ?? 300;
        if (maxStageEl) maxStageEl.value = s.max_stage ?? 2;
      }
    } catch(_) {}
  }
}

if (typeof window !== 'undefined') {
  window.saveV219Settings = saveV219Settings;
  // Fix 145: 사다리 입력 시 미리보기/단계수 즉시 반영
  document.addEventListener('input', (ev) => {
    if (!ev.target || ev.target.id !== 'v219-ladder') return;
    const parts = String(ev.target.value || '').split(',').map(x => x.trim()).filter(Boolean);
    const prev = document.getElementById('v219-ladder-preview');
    if (prev) prev.textContent = parts.map((v, i) => (i + 1) + '단계 ' + v).join(' · ') || '-';
    const ms = document.getElementById('v219-max-stage');
    if (ms) ms.value = String(parts.length || 1);
  });
  window.loadV219Settings = loadV219Settings;
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(loadV219Settings, 600);
  });
}
  window.resetAutoBBCounter = resetAutoBBCounter;  // 🔄 v163 리셋!
  document.addEventListener('DOMContentLoaded', () => {
    // 🌟 v182 사장님 「세팅 유지!」: 즉시 backup 복원! (사장님 「끔」 보임 방지!)
    try {
      const backup = localStorage.getItem(_AUTO_BB_LIMIT_LS_KEY);
      const el = document.getElementById('auto-bb-daily-limit');
      if (el && backup !== null && backup !== '') {
        el.value = backup;  // 즉시 복원!
      }
    } catch (_e) {}
    setTimeout(loadAutoBBLimit, 500);  // v182: 1500 → 500 (더 빠르게!)
    setInterval(loadAutoBBLimit, 60000);  // v163 = 매 60초 상태 새로고침!
  });
  window.briefingNow = briefingNow;  // v132 즉시 브리핑!
  window._switchProfile = _switchProfile;  // v132 프로필 전환!
  window._setSugFilter = _setSugFilter;  // v132 롱/숏 필터!
  window.renderSuggestions = renderSuggestions;
  window.openSuggestionsSettingsModal = openSuggestionsSettingsModal;
  window.closeSuggestionsSettingsModal = closeSuggestionsSettingsModal;
  window.saveSuggestionsSettings = saveSuggestionsSettings;
  window.openSuggestionAnalysis = openSuggestionAnalysis;  // 🌟 v133c!
  // 🎯 v218 사장님 (2026-08-22): 자동 제안 outcome 함수 전역 노출!
  window.loadRecentAutoOutcomes = loadRecentAutoOutcomes;
  // 🌟 v224 사장님 (2026-08-23): 15m 통합 워커 실시간 모니터링!
  // "지금까지 모든 자동매매는 오늘 15분 차트 급등과 급락한 심볼만 자동매매를 하는걸로 통합"
  async function loadUnified15mMonitoring() {
    const bodyEl = document.getElementById('unified-15m-body');
    const badgeEl = document.getElementById('unified-15m-badge');
    // Fix 34: v224 OFF 시 자동 접힘 + opacity!
    try {
      const detailsEl = document.getElementById('unified-15m-details');
      const cardEl = document.getElementById('unified-15m-monitoring-card');
      if (detailsEl && cardEl) {
        if (!enabled) {
          detailsEl.removeAttribute('open');
          cardEl.style.opacity = '0.5';
          cardEl.style.background = 'linear-gradient(135deg,rgba(100,116,139,0.15),rgba(71,85,105,0.15))';
        } else {
          detailsEl.setAttribute('open', 'open');
          cardEl.style.opacity = '1';
        }
      }
    } catch(e){}
    const updEl = document.getElementById('unified-15m-updated');
    if (!bodyEl) return;
    try {
      const r = await api('/strategy-suggestions/unified-15m/monitoring');
      if (!r || r.empty) {
        if (badgeEl) badgeEl.textContent = 'v219 ON';
        if (updEl) updEl.textContent = r && r.note ? r.note : '아직 실행 X';
        bodyEl.innerHTML = '<div class="text-xs text-slate-400 text-center py-2">30초 대기 후 첫 스캔 결과 표시!</div>';
        return;
      }
      const enabled = !!r.unified_entry_enabled;
      const surges = Array.isArray(r.surges) ? r.surges : [];
      const skipReasons = r.skip_reasons || {};
      const last = r.last_run_at ? new Date(r.last_run_at) : null;
      const agoSec = last ? Math.max(0, Math.floor((Date.now() - last.getTime())/1000)) : null;
      const agoStr = agoSec == null ? '?' :
                     agoSec < 60 ? `${agoSec}초 전` : `${Math.floor(agoSec/60)}분 전`;
      if (badgeEl) {
        badgeEl.textContent = enabled ? `ON · surge ${surges.length}` : 'OFF';
        badgeEl.style.background = enabled ? '#22d3ee' : '#64748b';
      }
      if (updEl) updEl.textContent = `${agoStr} 갱신 · 오늘 ${r.entered_today||0}/${r.daily_limit||0}건`;

      const summary = `
        <div style="display:flex;gap:6px;flex-wrap:wrap;font-size:11px;margin-bottom:6px">
          <span style="background:#0e7490;color:#fff;padding:2px 8px;border-radius:8px">🔎 스캔 ${r.scanned||0}</span>
          <span style="background:#334155;color:#e2e8f0;padding:2px 8px;border-radius:8px">캔들X ${r.no_candles||0}</span>
          <span style="background:#334155;color:#e2e8f0;padding:2px 8px;border-radius:8px">평온 ${r.no_surge||0}</span>
          <span style="background:#f59e0b;color:#000;padding:2px 8px;border-radius:8px">🎯 급등락 ${r.surges_found||0}</span>
          <span style="background:#10b981;color:#000;padding:2px 8px;border-radius:8px">✅ 진입 ${r.entered||0}</span>
          <span style="background:#ef4444;color:#fff;padding:2px 8px;border-radius:8px">⏭ skip ${r.skipped||0}</span>
        </div>`;

      let surgesHtml = '';
      if (surges.length === 0) {
        surgesHtml = '<div class="text-xs text-slate-400 py-2">지금 15m 급등/급락 없음 (평온!)</div>';
      } else {
        surgesHtml = `
          <div style="max-height:220px;overflow-y:auto;padding-right:4px">
            ${surges.map(s => {
              const isLong = s.side === 'LONG';
              const sideColor = isLong ? '#22c55e' : '#ef4444';
              const icon = isLong ? '🐂' : '🐻';
              const pct = Number(s.matched_pct||0);
              const pctStr = (pct>=0?'+':'') + pct.toFixed(2) + '%';
              const win = s.window || '?';
              const c24 = Number(s.change_24h_pct||0);
              const c24Str = (c24>=0?'+':'') + c24.toFixed(2) + '%';
              return `<div style="display:flex;justify-content:space-between;align-items:center;padding:3px 6px;margin-bottom:2px;background:rgba(15,23,42,0.5);border-left:3px solid ${sideColor};border-radius:3px;font-size:11px">
                <span><b>${icon} ${s.symbol}</b> <span style="color:${sideColor}">${s.side}</span></span>
                <span style="color:${sideColor}">${win} ${pctStr} <span style="color:#94a3b8">· 24h ${c24Str}</span></span>
              </div>`;
            }).join('')}
          </div>`;
      }

      let reasonsHtml = '';
      const rk = Object.keys(skipReasons);
      if (rk.length > 0) {
        reasonsHtml = `
          <details style="margin-top:6px;font-size:11px">
            <summary style="cursor:pointer;color:#94a3b8">🔎 skip 이유 breakdown (${rk.length}종)</summary>
            <div style="padding:4px 8px;color:#cbd5e1">
              ${rk.map(k => `<div>· ${k}: ${skipReasons[k]}건</div>`).join('')}
            </div>
          </details>`;
      }

      const enabledNote = enabled ? '' :
        `<div style="background:#7f1d1d;color:#fecaca;padding:4px 8px;border-radius:4px;margin-bottom:6px;font-size:11px">
          ⚠️ unified_entry_enabled=0 = v219 = 유일한 자동 진입!!
        </div>`;

      bodyEl.innerHTML = enabledNote + summary + surgesHtml + reasonsHtml;
    } catch (e) {
      if (bodyEl) bodyEl.innerHTML = `<div class="text-xs text-red-400">모니터링 로드 실패: ${(e&&e.message)||e}</div>`;
      console.warn('[unified-15m/monitoring] 실패:', e);
    }
  }
  window.loadUnified15mMonitoring = loadUnified15mMonitoring;

  // 🎯 v219: 사장님 정점 SHORT + 활성 SHORT 실시간 모니터링!
  // 📉 (2026-08-24): 저점 LONG 대칭 추가 = 별도 컨테이너에 렌더!
  async function loadV219Monitoring() {
    const bodyEl = document.getElementById('unified-15m-body');
    const longSymEl = document.getElementById('v219-monitoring-symbols-long');
    const longReentryEl = document.getElementById('v219-reentry-watch-long');
    if (!bodyEl) return;
    try {
      const r = await api('/strategy-suggestions/v219-monitoring');

      // ==================== 🎯 SHORT 영역 (기존 유지) ====================
      let html = '';
      // 활성 SHORT 표시
      if (r.active_shorts && r.active_shorts.length) {
        html += `<div style="color:#f1f5f9;font-size:12px;margin-top:8px;"><b>🎯 활성 SHORT ${r.active_shorts.length}건:</b><br>`;
        r.active_shorts.forEach(s => {
          const pnlVal = Number(s.unrealized_pnl) || 0;
          const pnlColor = pnlVal >= 0 ? '#22c55e' : '#ef4444';
          html += `<div style="padding:4px 8px;background:rgba(30,41,59,0.6);margin:2px 0;border-radius:4px;">${s.symbol} stage${s.stage} avg=${s.avg_price} <span style="color:${pnlColor};">${pnlVal.toFixed(2)} USDT</span></div>`;
        });
        html += '</div>';
      }
      // 정점 감지 후보
      if (r.pump_top_alerts && r.pump_top_alerts.length) {
        html += `<div style="color:#f1f5f9;font-size:12px;margin-top:8px;"><b>🚨 정점 감지 후보 ${r.pump_top_alerts.length}건:</b><br>`;
        r.pump_top_alerts.forEach(a => {
          html += `<div style="padding:4px 8px;background:rgba(236,72,153,0.15);margin:2px 0;border-radius:4px;">${a.symbol} ${a.side} conf=${a.confidence} 24h=${a.change_24h}%</div>`;
        });
        html += '</div>';
      }
      // 🔍 SHORT 실시간 감시 심볼 (사장님 요구 2026-08-24 복원: 정의2 삭제 시 유실 방지!)
      if (r.monitoring_symbols && r.monitoring_symbols.length) {
        html += `<div style="color:#f1f5f9;font-size:12px;margin-top:8px;"><b>🔍 v219 감시 심볼 (SHORT 정점) ${r.monitoring_symbols.length}개:</b></div>`;
        r.monitoring_symbols.forEach(m => {
          const color = m.passed_v219 ? '#22c55e' : (m.change_24h >= 10 ? '#f97316' : '#94a3b8');
          const badge = m.passed_v219 ? '✅통과' : '👀감시';
          html += `<div style="padding:3px 8px;background:rgba(30,41,59,0.6);margin:2px 0;border-radius:4px;color:#f1f5f9;font-size:11px;">${m.symbol} 24h=<span style="color:${color};font-weight:bold;">${m.change_24h}%</span> ${badge} vol=${m.volume_24h_m||"?"}M</div>`;
        });
      }
      // 🔄 SHORT 재진입 대기 (24h 내 청산 이력, 사장님 요구 2026-08-24 복원!)
      if (r.reentry_watch && r.reentry_watch.length) {
        html += `<div style="color:#f1f5f9;font-size:12px;margin-top:8px;"><b>🔄 SHORT 재진입 대기 (24h 청산!) ${r.reentry_watch.length}개:</b></div>`;
        r.reentry_watch.forEach(w => {
          const pnl = parseFloat(w.realized_pnl || 0);
          const c = pnl >= 0 ? '#22c55e' : '#ef4444';
          html += `<div style="padding:3px 8px;background:rgba(30,41,59,0.6);margin:2px 0;border-radius:4px;color:#f1f5f9;font-size:11px;">${w.symbol} ${w.status||w.reason||''} <span style="color:${c};">${pnl.toFixed(2)}</span></div>`;
        });
      }
      // 진입 슬롯 (SHORT + LONG 활성 합산 표시)
      const shortCnt = (r.active_shorts && r.active_shorts.length) || 0;
      const longCnt = (r.active_longs && r.active_longs.length) || 0;
      html += `<div style="color:#94a3b8;font-size:11px;margin-top:8px;">오늘 진입: ${r.daily_used}/${r.daily_limit} · 활성 🎯 SHORT ${shortCnt} / 📉 LONG ${longCnt}</div>`;
      if (!html) html = `<div style="color:#94a3b8;">v219 감지 대기 중...</div>`;
      bodyEl.innerHTML = html;

      // ==================== 📉 LONG 영역 (2026-08-24 신규) ====================
      // 활성 LONG + 저점 감지 후보 = monitoring_symbols_long 컨테이너에 렌더
      if (longSymEl) {
        let lh = '';
        if (r.active_longs && r.active_longs.length) {
          lh += `<div style="color:#f1f5f9;font-size:12px;margin-top:8px;"><b>📉 활성 LONG ${r.active_longs.length}건:</b><br>`;
          r.active_longs.forEach(s => {
            const pnlVal = Number(s.unrealized_pnl) || 0;
            const pnlColor = pnlVal >= 0 ? '#22c55e' : '#ef4444';
            lh += `<div style="padding:4px 8px;background:rgba(30,41,59,0.6);margin:2px 0;border-radius:4px;">${s.symbol} stage${s.stage} avg=${s.avg_price} <span style="color:${pnlColor};">${pnlVal.toFixed(2)} USDT</span></div>`;
          });
          lh += '</div>';
        }
        if (r.long_bottom_alerts && r.long_bottom_alerts.length) {
          lh += `<div style="color:#f1f5f9;font-size:12px;margin-top:8px;"><b>🟢 저점 감지 후보 ${r.long_bottom_alerts.length}건:</b><br>`;
          r.long_bottom_alerts.forEach(a => {
            lh += `<div style="padding:4px 8px;background:rgba(34,197,94,0.15);margin:2px 0;border-radius:4px;">${a.symbol} ${a.side} conf=${a.confidence} 24h=${a.change_24h}%</div>`;
          });
          lh += '</div>';
        }
        if (r.monitoring_symbols_long && r.monitoring_symbols_long.length) {
          lh += `<div style="color:#f1f5f9;font-size:12px;margin-top:8px;"><b>📉 v219 감시 심볼 (LONG 저점) ${r.monitoring_symbols_long.length}건:</b><br>`;
          r.monitoring_symbols_long.forEach(s => {
            const sym = (s && s.symbol) ? s.symbol : String(s);
            const extra = (s && s.change_24h !== undefined) ? ` 24h=${s.change_24h}%` : '';
            lh += `<div style="padding:4px 8px;background:rgba(34,197,94,0.10);margin:2px 0;border-radius:4px;">${sym}${extra}</div>`;
          });
          lh += '</div>';
        }
        longSymEl.innerHTML = lh;
      }

      // 재진입 대기 (LONG)
      if (longReentryEl) {
        let rh = '';
        if (r.reentry_watch_long && r.reentry_watch_long.length) {
          rh += `<div style="color:#f1f5f9;font-size:12px;margin-top:8px;"><b>🔄 LONG 재진입 대기 ${r.reentry_watch_long.length}건:</b><br>`;
          r.reentry_watch_long.forEach(w => {
            const sym = (w && w.symbol) ? w.symbol : String(w);
            const stage = (w && w.stage !== undefined) ? ` stage${w.stage}` : '';
            const note = (w && w.note) ? ` — ${w.note}` : '';
            rh += `<div style="padding:4px 8px;background:rgba(34,197,94,0.10);margin:2px 0;border-radius:4px;">${sym}${stage}${note}</div>`;
          });
          rh += '</div>';
        }
        longReentryEl.innerHTML = rh;
      }

      // ==================== Badge 갱신 ====================
      const shortBadge = document.getElementById('unified-15m-badge');
      const longBadge = document.getElementById('unified-15m-badge-long');
      if (shortBadge) {
        const shortPending = (r.pump_top_alerts && r.pump_top_alerts.length) || 0;
        shortBadge.textContent = `🎯 ${shortCnt}/${shortPending}`;
      }
      if (longBadge) {
        const longPending = (r.long_bottom_alerts && r.long_bottom_alerts.length) || 0;
        longBadge.textContent = `📉 ${longCnt}/${longPending}`;
      }
    } catch (e) {
      bodyEl.innerHTML = `<div style="color:#ef4444;">❌ 로드 실패: ${(e && e.message) || e}</div>`;
      if (longSymEl) longSymEl.innerHTML = '';
      if (longReentryEl) longReentryEl.innerHTML = '';
      console.warn('[v219/monitoring] 실패:', e);
    }
  }
  window.loadV219Monitoring = loadV219Monitoring;

  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(loadStrategySuggestions, 1200);
    setInterval(loadStrategySuggestions, 30000);  // 30초 polling
    // 🎯 v218: 자동 제안 outcome 표시! (매 30초 갱신!)
    setTimeout(loadRecentAutoOutcomes, 1500);
    setInterval(loadRecentAutoOutcomes, 30000);
    // 🌟 v224: 15m 통합 워커 실시간 모니터링! (매 30초 갱신!)
    setTimeout(loadUnified15mMonitoring, 1800);
    setInterval(loadUnified15mMonitoring, 30000);
    // 🎯 v219: 사장님 정점 SHORT 모니터링! (매 30초 갱신!)
    setTimeout(loadV219Monitoring, 2100);
    setInterval(loadV219Monitoring, 30000);
  });
}

// Fix 35 (2026-08-23): v219 세팅 폼!
async function saveV219Settings() {
  const limit = parseInt(document.getElementById('v219-daily-limit').value);
  const capital = parseFloat(document.getElementById('v219-capital').value);
  // 🎯 Fix 145: 최대 단계는 사다리 칸 수에서 파생 (별도 입력 = 모순 원인)
  const _ladderRaw = (document.getElementById('v219-ladder') || {}).value || '';
  const _rungs = String(_ladderRaw).split(',').map(x => x.trim()).filter(Boolean).length;
  const maxStage = _rungs > 0 ? _rungs : parseInt((document.getElementById('v219-max-stage') || {}).value || '3');
  const msgEl = document.getElementById('v219-settings-msg');
  // 🎯 Fix 144 (2026-08-26 사장님): 자본 사다리도 함께 저장
  const ladderEl = document.getElementById('v219-ladder');
  const ladder = ladderEl ? String(ladderEl.value || '').trim() : '';
  const payload = { top_short_daily_limit: limit, default_capital: capital, max_stage: maxStage };
  if (ladder) payload.capital_ladder = ladder;
  // 🎯 Fix 176 (2026-08-27 사장님): 피라미딩 1회 금액 (사다리와 독립된 고정값)
  const pyrEl = document.getElementById('v219-pyramid-capital');
  const pyr = pyrEl ? parseFloat(pyrEl.value) : NaN;
  if (!isNaN(pyr) && pyr > 0) payload.pyramid_capital = pyr;
  try {
    await api('/strategy-suggestions/sajangnim-settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    if (msgEl) msgEl.innerHTML = '<span style="color:#22c55e;font-weight:bold;">✅ 저장 완료! 값=' + payload.top_short_daily_limit + ' (2초 후 재로드!)</span>';
    setTimeout(() => {
      loadV219Settings();
      // 값 세팅 후 = 확실히 UI 반영!
      setTimeout(() => {
        const limitEl = document.getElementById('v219-daily-limit');
        if (limitEl) limitEl.value = String(payload.top_short_daily_limit);
        console.log('✅ 강제 세팅:', payload.top_short_daily_limit);
      }, 1000);
    }, 500);
  } catch(e) {
    if (msgEl) msgEl.innerHTML = '<span style="color:#ef4444;">❌ 실패: ' + e.message + '</span>';
  }
}
async function loadV219Settings(retry = 0) {
  const limitEl = document.getElementById('v219-daily-limit');
  const capitalEl = document.getElementById('v219-capital');
  const maxStageEl = document.getElementById('v219-max-stage');
  // Fix 38: 요소 없으면 = 재시도! (카드가 늦게 로드!)
  if (!limitEl && !capitalEl && !maxStageEl && !document.getElementById('v219-ladder')) {
    if (retry < 20) setTimeout(() => loadV219Settings(retry + 1), 500);
    return;
  }
  try {
    const r = await api('/strategy-suggestions/sajangnim-settings');
    if (limitEl) limitEl.value = r.top_short_daily_limit ?? 5;
    if (capitalEl) capitalEl.value = r.default_capital ?? 10;
    if (maxStageEl) maxStageEl.value = r.max_stage ?? 3;
    // 🎯 Fix 176: 피라미딩 1회 금액 (서버가 돌려주는 「실제 적용값」 — 헌법 85)
    const pyrEl2 = document.getElementById('v219-pyramid-capital');
    if (pyrEl2 && r.pyramid_capital != null) pyrEl2.value = r.pyramid_capital;
    // 🎯 Fix 144: 사다리 값 + 미리보기 (실제 적용값을 화면에서 확인 가능하게)
    const ladderEl2 = document.getElementById('v219-ladder');
    if (ladderEl2 && r.capital_ladder) ladderEl2.value = r.capital_ladder;
    // 🚨 Fix 154: 배지(helpers.js)가 쓸 수 있게 전역에 실제 사다리를 공유
    if (r.capital_ladder && typeof window !== 'undefined') {
      const arr = String(r.capital_ladder).split(',')
        .map(x => parseFloat(x.trim())).filter(v => !isNaN(v) && v > 0);
      if (arr.length) window.__SAJANGNIM_LADDER = arr;
    }
    const prev = document.getElementById('v219-ladder-preview');
    if (prev && r.capital_ladder) {
      const parts = String(r.capital_ladder).split(',').map(x => x.trim()).filter(Boolean);
      prev.textContent = parts.map((v, i) => (i + 1) + '단계 ' + v).join(' · ');
    }
  } catch(e) {}
}
if (typeof window !== 'undefined') {
  window.saveV219Settings = saveV219Settings;
  window.loadV219Settings = loadV219Settings;
  document.addEventListener('DOMContentLoaded', () => setTimeout(loadV219Settings, 600));
}

// Fix 63 (2026-08-24): silent bug 제거 = loadV219Monitoring 중복 정의 삭제!
// 정의2가 정의1 결과 매번 덮어써서 실시간 감시/재진입 대기 심볼 UI 사라짐!
// 헌법 63 (함수 재정의 금지) 준수!
//
// 배경 (Fix 36/37 (2026-08-23) → 정의 통합 (2026-08-24 사장님 지적!)):
//   loadV219Monitoring 함수가 파일 내 2번 정의되어 = silent bug!
//   정의2가 정의1보다 600ms 먼저 실행되나 정의1이 매 사이클 마다 bodyEl 덮어씀!
//   → 정의2가 렌더하던 monitoring_symbols (SHORT 실시간 감시) / reentry_watch (SHORT 재진입 대기) = 화면 소실!
//   → 사장님 스크린샷 = 「정점 감지 후보 2건」 만 표시!
//   fix = 정의1(위쪽 IIFE 내부)에 monitoring_symbols + reentry_watch 렌더 추가 + 정의2 완전 삭제!
//   v211 잔재 사고 재발 방지!
