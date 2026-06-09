/**
 * Dashboard refresh group — Phase 3 단계 3j (2026-05-14).
 *
 * 메인 대시보드의 모든 panel 갱신 함수 통합. refreshAll 이 5초마다 호출.
 *
 * 함수:
 *   - refreshAll()                : 모든 panel + 잔액 + 시스템 status banner + WL 캐시 갱신
 *   - loadGlobalWhitelistInfo()   : 화이트리스트 캐시 (심볼 옆 ⚠️ 외 배지용)
 *   - renderWhitelistBadge(sym)   : 미등재 심볼 빨간 배지 HTML
 *   - _localizeActivity(text)     : 영문 RiskEvent → 한글 매핑 (legacy DB 호환)
 *   - refreshActivity()           : 활동 피드 (orders + risk_events + notifications)
 *   - refreshSysHealth()          : 8개 시스템 컴포넌트 status (DB/Redis/Scheduler 등)
 *   - refreshStats()              : 운영 통계 카드 (winrate / TP 카운트 / 크라이시스 등)
 *   - refreshHealth()             : /health endpoint (시스템 라이브니스)
 *   - loadBalance()               : 거래소 잔액 카드
 *
 * 외부 의존성 (script-scope 공유):
 *   - api / toast (api.js)
 *   - escapeHtml / fmtNum / setMetric (helpers.js)
 *   - selectStrategy / refreshTemplates / refreshStrategies / refreshExchangeAccounts (index.html)
 *   - loadSystemStatus (system-banner.js)
 *
 * State (이 모듈 소유):
 *   - _globalWhitelistInfo : { allowed: Set<string>, envConfigured: boolean }
 */

async function refreshAll() {
  await Promise.all([
    refreshHealth(),
    refreshTemplates(),
    refreshStrategies(),
    refreshExchangeAccounts(),
    refreshStats(),
    refreshActivity(),
    refreshSysHealth(),
    loadBalance(),  // 거래소 잔액 카드 (2026-05-03 추가)
    loadSystemStatus(),  // ⚠️ Zombie Guardian 배너 (2026-05-03 추가)
    loadGlobalWhitelistInfo(),  // 🔒 화이트리스트 캐시 (2026-05-08 — 심볼 옆 WL 배지)
  ]);
  document.getElementById('last-updated').textContent = '마지막 갱신: ' + new Date().toLocaleTimeString('ko-KR');
}

// 2026-05-08 (v3): 화이트리스트 미등재 심볼만 위험 표시 — 단순화.
// 이전 버전(녹색/회색 등재 + 빨강 미등재 + 토글 색상 가변)이 너무 복잡하다는
// 사용자 피드백 반영. 사용자가 보고 싶은 단 한 가지 정보 = "이 심볼이 위험한가?".
// - env 화이트리스트 미설정 → 표시 없음 (의미 없음)
// - 등재 심볼 → 표시 없음 (정상 — 표시 안 해도 알 수 있음)
// - 미등재 심볼 → 「⚠️ 외」 빨간 배지 (토글 무관 — 위험 알림 목적)
let _globalWhitelistInfo = { allowed: new Set(), envConfigured: false };

async function loadGlobalWhitelistInfo() {
  try {
    const info = await api('/symbols/whitelist-info');
    _globalWhitelistInfo = {
      allowed: new Set((info.allowed_symbols || []).map(s => s.toUpperCase())),
      envConfigured: !!info.env_configured,
    };
  } catch { /* 비활성 시 무시 */ }
}

function renderWhitelistBadge(symbol) {
  if (!_globalWhitelistInfo.envConfigured) return '';
  const sym = (symbol || '').toUpperCase();
  if (_globalWhitelistInfo.allowed.has(sym)) return '';
  return ' <span class="badge badge-red" style="font-size:9px;padding:1px 4px" title="화이트리스트 외 — 위험 심볼">⚠️ 외</span>';
}

// loadSystemStatus + clearKillSwitch 는 /static/js/system-banner.js 로 분리 (Phase 3 추가).

// 영문 RiskEvent / 활동 메시지를 한글로 매핑 (옛 DB 데이터 호환, 2026-05-03)
function _localizeActivity(text) {
  if (!text) return text;
  const dict = [
    [/Unmatched stream event/gi, '📡 매칭 안 된 거래소 이벤트'],
    [/No local order matched the incoming stream payload/gi, '시스템에 없는 주문에 대한 stream 이벤트 (외부 거래)'],
    [/Local\/exchange position quantity mismatch/gi, '⚠️ 포지션 수량 불일치 (DB ↔ 거래소)'],
    [/STOPPING zombie auto-promoted to STOPPED/gi, '✅ 좀비 STOPPING 자동 정리'],
    [/Auto-stopped DB-only orphan strategy/gi, '🧹 외부 청산된 전략 자동 정리'],
    [/No matching position found on exchange/gi, '⚠️ 거래소에 매칭 포지션 없음'],
    [/Stop loss triggered/gi, '🛑 손절 발동'],
    [/Binance listenKey expired/gi, '🚨 Binance listenKey 만료'],
    [/Reconciled stuck PENDING -> OPEN/gi, '✅ PENDING → OPEN 자가 회복'],
    [/Emergency close place_market_order failed/gi, '❌ 강제 청산 시장가 주문 실패'],
    [/Emergency close 시장가 주문 발송 실패/gi, '❌ 강제 청산 시장가 주문 실패'],
    [/exchange position closed externally, marking STOPPED/gi, '거래소 외부 청산 → STOPPED 마킹'],
    [/exchange position 0, promoting STOPPING → STOPPED/gi, '거래소 포지션 0 → STOPPING → STOPPED'],
    [/User data stream expired; new orders must be blocked until stream restarts/gi, '거래소 user data stream 끊김 — 재연결까지 새 주문 차단'],
    [/local=([\-\d.]+), exchange=([\-\d.]+)/gi, '시스템 기록 $1 vs 거래소 실 포지션 $2'],
    [/symbol=(\w+), side=(\w+)/gi, '$1 $2'],
  ];
  let out = text;
  for (const [pat, rep] of dict) out = out.replace(pat, rep);
  return out;
}

async function refreshActivity() {
  try {
    // 2026-05-12 (사용자 요청): 20건 hardcode → 사용자 선택 (20/50/100/200/500).
    const limitSel = document.getElementById('activity-limit-select');
    const limit = limitSel ? Number(limitSel.value || 50) : 50;
    const data = await api(`/admin/recent-activity?limit=${limit}`);
    const el = document.getElementById('activity-feed');
    document.getElementById('activity-updated').textContent = '갱신 ' + new Date().toLocaleTimeString('ko-KR');

    // 2026-06-03 신규: 계정별 필터 — window._strategiesById (strategies-list.js 가 채움) 활용.
    // strategy_id → exchange_account_id 매핑 후 client-side 필터.
    const accSel = document.getElementById('activity-account-filter');
    const strategiesIdx = window._strategiesById || {};
    // 활성 계정 목록 추출 (data 의 strategy_id → exchange_account_id)
    const uniqAccIds = new Set();
    data.forEach(t => {
      if (t.strategy_id && strategiesIdx[t.strategy_id]) {
        const accId = strategiesIdx[t.strategy_id].exchange_account_id;
        if (accId) uniqAccIds.add(accId);
      }
    });
    // dropdown 동적 채움
    if (accSel) {
      const curVal = accSel.value || 'all';
      const sortedIds = [...uniqAccIds].sort((a, b) => a - b);
      accSel.innerHTML = `<option value="all">전체</option>` +
        sortedIds.map(id => `<option value="${id}">계정 #${id}</option>`).join('');
      // 선택값 복원 (없어진 옵션이면 'all' 로)
      accSel.value = curVal === 'all' || sortedIds.includes(Number(curVal)) ? curVal : 'all';
    }
    // 필터 적용
    const accFilter = accSel ? accSel.value : 'all';
    let filtered = data;
    if (accFilter !== 'all') {
      filtered = data.filter(t => {
        if (!t.strategy_id) return false;  // strategy 없는 알림은 계정 필터 시 제외
        const s = strategiesIdx[t.strategy_id];
        return s && String(s.exchange_account_id) === String(accFilter);
      });
    }

    const lbl = document.getElementById('activity-count-label');
    if (lbl) {
      const filterNote = accFilter !== 'all' ? ` 계정 #${accFilter}` : '';
      lbl.textContent = `(${filtered.length}/${data.length}건${filterNote}${data.length >= limit ? ' — ↑ 표시 변경' : ''})`;
    }
    if (!filtered.length) {
      el.innerHTML = `<p class="text-slate-500 text-sm text-center py-4">필터 결과 없음 (전체 ${data.length}건 중 0건)</p>`;
      return;
    }
    const kindColor = { ORDER: 'text-blue-300', RISK: 'text-red-300', NOTIFY: 'text-slate-400' };
    el.innerHTML = filtered.map(t => {
      const ts = new Date(t.ts);
      const tsStr = ts.toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
      const kindCls = kindColor[t.kind] || 'text-slate-300';
      const stratLink = t.strategy_id
        ? `<button onclick="event.stopPropagation(); selectStrategy(${t.strategy_id})" class="text-blue-400 hover:underline">#${t.strategy_id}</button>`
        : '<span class="text-slate-500">-</span>';
      return `<div class="flex gap-3 py-1.5 border-b border-slate-700 last:border-0 text-xs">
        <div class="text-slate-500 font-mono whitespace-nowrap" style="min-width:120px">${tsStr}</div>
        <div class="text-lg leading-tight">${t.icon}</div>
        <div class="whitespace-nowrap" style="min-width:100px">${stratLink} <span class="text-slate-400">${escapeHtml(t.symbol || '')}</span></div>
        <div class="flex-1">
          <div class="${kindCls} font-semibold">${escapeHtml(_localizeActivity(t.title))}</div>
          <div class="text-slate-400 text-xs mt-0.5">${escapeHtml(_localizeActivity((t.detail || '')).slice(0, 200))}</div>
        </div>
      </div>`;
    }).join('');
  } catch (err) { /* 실패는 무시 */ }
}

async function refreshSysHealth() {
  try {
    const data = await api('/admin/system-health');
    const overallEl = document.getElementById('syshealth-overall');
    const overallMap = {
      ok: { ko: '🟢 모두 정상', cls: 'text-green-400' },
      warn: { ko: '🟡 일부 주의', cls: 'text-yellow-400' },
      down: { ko: '🔴 장애 발생', cls: 'text-red-400' },
    };
    const ov = overallMap[data.overall] || overallMap.ok;
    overallEl.textContent = ov.ko;
    overallEl.className = 'text-xs font-semibold ' + ov.cls;

    const grid = document.getElementById('syshealth-grid');
    const statusToDot = (s) => {
      if (s === 'ok') return '<span class="sys-dot sys-dot-green"></span>';
      if (s === 'warn') return '<span class="sys-dot sys-dot-yellow"></span>';
      return '<span class="sys-dot sys-dot-red"></span>';
    };
    grid.innerHTML = Object.entries(data.components).map(([key, c]) => {
      return `<div class="flex items-start gap-2 p-2 rounded bg-slate-900 border border-slate-700">
        <div class="pt-1">${statusToDot(c.status)}</div>
        <div class="flex-1 min-w-0">
          <div class="text-sm font-semibold text-slate-200">${escapeHtml(c.label)}</div>
          <div class="text-xs text-slate-400 truncate" title="${escapeHtml(c.detail)}">${escapeHtml(c.detail)}</div>
        </div>
      </div>`;
    }).join('');
  } catch (err) { /* 무시 */ }
}

async function refreshStats() {
  try {
    const s = await api('/admin/stats');
    document.getElementById('stats-total').textContent = s.total;
    document.getElementById('stats-completed').textContent = s.completed;
    document.getElementById('stats-sl').textContent = s.stop_loss;
    const manualEl = document.getElementById('stats-manual');
    if (manualEl) manualEl.textContent = (s.manual_stop != null) ? s.manual_stop : '-';
    // 2026-05-06: 승률 = strategy 단위 (수익/손실 strategy 수 기준).
    document.getElementById('stats-winrate').textContent = s.win_rate_pct + '%';
    const winDetailEl = document.getElementById('stats-winrate-detail');
    if (winDetailEl) {
      const profit = Number(s.profit_strategy_count || 0);
      const loss = Number(s.loss_strategy_count || 0);
      winDetailEl.textContent = `수익 ${profit} / 손실 ${loss}`;
      winDetailEl.title = `realized_pnl > 0 인 strategy ${profit}개, realized_pnl < 0 인 strategy ${loss}개. ` +
        `알림 기반 승률 (이전): ${s.win_rate_alert_based_pct}%`;
    }
    const realizedNum = Number(s.realized_pnl_total || 0);
    const realizedEl = document.getElementById('stats-realized');
    realizedEl.textContent = (realizedNum >= 0 ? '+' : '') + fmtNum(realizedNum) + ' USDT';
    realizedEl.className = 'text-xl font-bold ' + (realizedNum > 0 ? 'pos' : realizedNum < 0 ? 'neg' : '');
    const crisisEl = document.getElementById('stats-crisis');
    crisisEl.textContent = s.crisis_total + (s.crisis_active > 0 ? ` (현재 ${s.crisis_active})` : '');
    crisisEl.className = 'text-xl font-bold ' + (s.crisis_active > 0 ? 'text-red-400' : 'text-yellow-400');
    // TP 단계별 카운트 (notification 기준) — 2026-05-12: TP1~10 + TRAILING
    const tpb = s.tp_breakdown || {};
    for (let n = 1; n <= 10; n++) {
      const el = document.getElementById(`stats-tp${n}`);
      if (el) el.textContent = tpb[`TP${n}`] || 0;
    }
    const trEl = document.getElementById('stats-trailing');
    if (trEl) trEl.textContent = tpb['TRAILING_TP'] || 0;
  } catch (err) { /* 통계 조회 실패는 무시 — 다른 패널은 정상 동작 */ }
}

async function refreshHealth() {
  try {
    const res = await fetch(window.location.origin + '/health');
    const data = await res.json();
    const ok = data.status === 'ok';
    setMetric('system', ok ? '🟢 정상' : '🔴 오류',  ok ? 'API + DB 연결됨' : '연결 실패', ok ? 'green' : 'red');
  } catch {
    setMetric('system', '🔴 오류', 'API 응답 없음', 'red');
  }
}

// 🌟 2026-06-09 v3 사장님 전문가 디자인 — 거래소 잔액 카드 신 DOM 채우기
// 진행바 색상 분기: < 50% green / 50-79 yellow / 80-94 orange / ≥95 red+pulse
// 3-grid mini: 🔒 실 / 📦 예약 / 💵 여유 (= 카드 안 한눈 파악)
// 신 전략 가용: 음수 = 빨강 (= 신 전략 차단 위험)
function _updateBalanceCardV3({used, limit, pct, real, reserved, free, newStratAvail}) {
  // 🌟 v11 fix: 신 DOM 있으면 = 신 DOM 만 채움 (legacy 는 hidden 유지!)
  //              신 DOM 없으면 = legacy 채움 (fallback)
  // = 사장님 「중복 표시 + layout 깨짐」 silent bug 차단
  // 안전 값 (= NaN 방지)
  used = Number(used || 0); limit = Number(limit || 0); pct = Number(pct || 0);
  real = Number(real || 0); reserved = Number(reserved || 0); free = Number(free || 0);
  newStratAvail = Number(newStratAvail || 0);

  // === 신 DOM 우선 채움 (= v3 HTML 정상 표시) ===
  try {
    const bar = document.getElementById('balance-progress-bar');
    const realEl = document.getElementById('balance-mini-real');
    if (bar && realEl) {
      // 신 DOM 모두 있음 = 신 DOM 만 채움 + legacy 는 hidden 유지 (= 중복 표시 방지!)
      const legacyDetail = document.getElementById('metric-balance-detail');
      if (legacyDetail) {
        legacyDetail.classList.add('hidden');  // 강제 hidden = 카드 layout 깨짐 방지
      }
      // 아래 신 DOM 채움 계속
    } else {
      // === fallback: 신 DOM 없음 (= 옛 HTML 캐시) → legacy detail 에 채움 ===
      const legacyDetail = document.getElementById('metric-balance-detail');
      if (legacyDetail) {
        legacyDetail.classList.remove('hidden');
        legacyDetail.style.display = '';
        const pctColor = pct >= 95 ? '#f87171' : pct >= 80 ? '#fb923c' : pct >= 50 ? '#facc15' : '#34d399';
        const stratColor = newStratAvail <= 0 ? '#fca5a5' : '#86efac';
        legacyDetail.innerHTML =
          `🔒 실 <b>${fmt(real)}</b> · 📦 예약 <b>${fmt(reserved)}</b> · 💵 여유 <b>${fmt(free)}</b><br>` +
          `⚡ <b>${fmt(used)}</b> / ${fmt(limit)} <b style="color:${pctColor}">${pct.toFixed(1)}%</b>` +
          ` · 🆕 신 전략 <b style="color:${stratColor}">${newStratAvail <= 0 ? '🚫 차단' : '+' + fmt(newStratAvail)}</b>`;
      }
      return;  // legacy 만 채움 = 종료
    }
  } catch (e) {
    console.error('[balance v11 dom check]', e);
  }

  // === 신 DOM 채움 (= mini-grid + 진행바 + 신 전략) ===
  try {
    const bar = document.getElementById('balance-progress-bar');
    if (!bar) return;  // 안전망 (= 위에서 이미 체크)
    const pctEl = document.getElementById('balance-progress-pct');
    const usedEl = document.getElementById('balance-progress-used');
    const limitEl = document.getElementById('balance-progress-limit');
    const realEl = document.getElementById('balance-mini-real');
    const reservedEl = document.getElementById('balance-mini-reserved');
    const freeEl = document.getElementById('balance-mini-free');
    const newStratEl = document.getElementById('balance-new-strategy');

    // 진행바 너비 (= 0~100 clamp)
    const w = Math.max(0, Math.min(100, pct));
    bar.style.width = w + '%';
    const colorClass = pct >= 95 ? 'warn-red' : (pct >= 80 ? 'warn-orange' : (pct >= 50 ? 'warn-yellow' : ''));
    bar.classList.remove('warn-yellow','warn-orange','warn-red');
    if (colorClass) bar.classList.add(colorClass);
    if (pctEl) {
      pctEl.classList.remove('warn-yellow','warn-orange','warn-red');
      if (colorClass) pctEl.classList.add(colorClass);
      pctEl.textContent = pct.toFixed(1) + '%';
    }
    if (usedEl) usedEl.textContent = fmt(used);
    if (limitEl) limitEl.textContent = fmt(limit);
    if (realEl) realEl.textContent = fmt(real);
    if (reservedEl) reservedEl.textContent = fmt(reserved);
    if (freeEl) freeEl.textContent = fmt(free);
    if (newStratEl) {
      if (newStratAvail <= 0) {
        newStratEl.textContent = `🚫 신 전략 차단 (한도 초과 ${fmt(Math.abs(newStratAvail))})`;
        newStratEl.classList.add('warn-red');
      } else {
        newStratEl.textContent = `🆕 신 전략 가용 +${fmt(newStratAvail)}`;
        newStratEl.classList.remove('warn-red');
      }
    }
  } catch (e) {
    console.error('[balance v3 new DOM fill]', e);
  }
}

// 거래소 잔액 카드 — 2026-06-03 다중 계정 합산 (모든 active 계정 병렬 호출).
// 이전: 첫 active 계정만 → 사장님 다중 Sub-Account 운영 시 부정확
// 신규: 모든 active 계정 합산 + tooltip 으로 개별 (사장님 통합 모니터링)
async function loadBalance() {
  try {
    const accounts = await api('/exchange-accounts').catch(() => []);
    const activeAccounts = (accounts || []).filter(a => a.is_active);
    if (!activeAccounts.length) {
      setMetric('balance', '-', '거래소 계정 없음', 'gray');
      return;
    }
    // 모든 active 계정 병렬 호출 (backend Redis 15s 캐시 — 부담 작음, PR #46)
    const balances = await Promise.all(activeAccounts.map(a =>
      api(`/exchange-accounts/${a.id}/balance`).catch(() => null)
    ));
    const valid = balances.filter(b => b !== null);
    if (!valid.length) {
      setMetric('balance', '-', '잔액 조회 실패 (모든 계정)', 'red');
      return;
    }
    // 합산
    let walletSum = 0, reservedSum = 0, ourAvailSum = 0, stratSum = 0;
    let maintMarginSum = 0, marginBalSum = 0;
    let actualMarginSum = 0;  // 2026-06-05: 실제 lock 마진 합 (total_position_initial_margin)
    // 🌟 2026-06-09 사장님 신 130% 정책 필드
    let wallet130Sum = 0, newStratAvailSum = 0;
    let hasTestnet = false;
    for (const b of valid) {
      walletSum += Number(b.total_wallet_balance || 0);
      reservedSum += Number(b.reserved_for_strategies || 0);
      ourAvailSum += Number(b.our_available_balance || 0);
      stratSum += Number(b.active_strategy_count || 0);
      maintMarginSum += Number(b.total_maint_margin || 0);
      marginBalSum += Number(b.total_margin_balance || 0);
      actualMarginSum += Number(b.total_position_initial_margin || 0);
      wallet130Sum += Number(b.wallet_limit_130 || 0);
      newStratAvailSum += Number(b.new_strategy_available || 0);
      if (b.is_testnet) hasTestnet = true;
    }
    // 합산 마진 비율 = total maint / total margin balance
    const aggRatio = marginBalSum > 0 ? (maintMarginSum / marginBalSum * 100) : 0;
    // 2026-06-05 사장님 요구 정확 반영 (3 구간 분해):
    //   ① 실 사용 마진 (Binance lock 중)  = actualMarginSum  ← 단위: 마진
    //   ② 보수 예약 (자본 단위 합)         = reservedSum     ← 단위: 자본 (사장님 사상 PR #30/#44)
    //   ③ 운용 가용 (신규 가능)            = ourAvailSum     ← 지갑 - 예약 (2026-06-06: 「자유」 → 「운용 가용」 명확화)
    // 예약 ≥ 실 사용 (자본 단위 보수 가드 = 마진 단위보다 큼 = 안전 마진 사장님 사상)
    // 사장님 직관: 큰 글씨 = 지갑 (내 돈 전체). 작은 글씨 = 3 구간 분해.
    const reservedRatio = walletSum > 0 ? (reservedSum / walletSum * 100) : 0;
    let sig;
    if (ourAvailSum < 0) sig = 'red';
    else if (reservedRatio < 80) sig = 'green';     // 80% 미만 예약 = 여유 있음
    else if (reservedRatio < 95) sig = 'yellow';    // 80~95% = 주의
    else sig = 'red';                                // 95%+ = 신규 strategy 거의 불가
    const fmt = (n) => Number(n).toLocaleString('en-US', {maximumFractionDigits: 2});
    // 2026-06-06 사장님 직관 정확화 (재정의):
    //   사장님 명시: "예약 3,140은 대부분 포지션에 진입했고 예약에 남아 있는 잔액만 표현해야"
    //
    // 옛 「예약」 = 전체 계획 자본 (= 사장님 자본 합 = 실 + 미진입 단계) ← 사장님 직관 무시 (중복 카운트)
    // 신 「포지션 예약됨」 = 계획 자본 - 실 사용 = 앞으로 lock 될 예정만 ← 사장님 직관 정확!
    //
    // = 상호 배타적 3 구간 (실 + 예약남은 + 운용가용 = 거래소 잔액)
    //
    // 합산 검증 (사장님 EPICUSDT 사례):
    //   🔒 실 1,395  +  📦 포지션 예약됨 1,745  +  💵 운용 가용 -32  =  3,108 ✅
    //   = 거래소 잔액 일치! 한눈에 명확.
    //
    // 운용 가용 계산 = 변경 없음 (지갑 - 전체 계획 자본). 표시 「예약」 만 = 남은 = 직관.
    const reservedRemainingSum = Math.max(0, reservedSum - actualMarginSum);  // 음수 방지

    // tooltip 으로 계정별 detail (4 구간 표시)
    const perAccountLines = valid.map((b, idx) => {
      const acc = activeAccounts[idx];
      const wlt = Number(b.total_wallet_balance || 0);
      const rsv = Number(b.reserved_for_strategies || 0);
      const act = Number(b.total_position_initial_margin || 0);
      const avl = Number(b.our_available_balance || 0);
      const cnt = Number(b.active_strategy_count || 0);
      const rsvRemaining = Math.max(0, rsv - act);  // 계정별 남은 예약
      return `#${acc.id}: 지갑 ${fmt(wlt)} | 🔒 실 ${fmt(act)} | 📦 포지션 예약됨 ${fmt(rsvRemaining)} | 💵 운용 가용 ${fmt(avl)} (${cnt}건)`;
    }).join('\n');
    // 신규 표시 형식 (사장님 2026-06-06 요구 — 직관 정확):
    //   큰 글씨   = 지갑 총액 (사장님 직관 = "내 돈 전체")
    //   작은 글씨 = 🔒 실 N | 📦 포지션 예약됨 M | 💵 운용 가용 X (전략 K건, 예약률 P%)
    //     🔒 실        = 현재 Binance lock 마진 (이미 사용 — 진입한 단계까지)
    //     📦 포지션 예약됨 = 사장님 계획 자본 중 = 앞으로 lock 될 예정 (= 미진입 단계 예약)
    //     💵 운용 가용 = 지갑 - 전체 계획 자본 = 신규 strategy 가능 한도 (음수 = 예약 초과)
    //   = 상호 배타적, 합 = 거래소 잔액 (사장님 한눈에)
    // 🌟 2026-06-09 사장님 신 정책 표시 (= 130% 한도 + 신 전략 가용):
    // 사장님 명시: "실 사용 + 예약 합 + 130% 한도 + 신 전략 가용 = 한눈 파악"
    // 예: 실 3500 + 예약 1500 = 사용 5000, 한도 7702 (= wallet 5925 × 1.30), 신 전략 가용 +2702
    const usedTotal = actualMarginSum + reservedRemainingSum;  // 실 + 예약 = 사용 중
    const realFreedom = walletSum - actualMarginSum;  // 실 자본 여유 (= wallet - 진입 마진)
    const newStrategyRatio = wallet130Sum > 0 ? (usedTotal / wallet130Sum * 100) : 0;
    let newSig;
    if (newStratAvailSum <= 0) newSig = 'red';
    else if (newStrategyRatio < 80) newSig = 'green';
    else if (newStrategyRatio < 95) newSig = 'yellow';
    else newSig = 'red';
    // 🌟 2026-06-09 모바일 v2: 모바일 = 줄바꿈 정리 + 핵심만, 데스크탑 = 풀 detail
    const isMobile = window.innerWidth <= 768;
    const detailMain = isMobile
      ? // 모바일 = 3줄 깔끔 (각 줄 한 가지 정보)
        `🔒 실 ${fmt(actualMarginSum)}  📦 예약 ${fmt(reservedRemainingSum)}\n` +
        `💵 여유 ${fmt(realFreedom)}  ⚡ 130% ${fmt(wallet130Sum)}\n` +
        `🆕 신 전략 +${fmt(newStratAvailSum)} (${newStrategyRatio.toFixed(0)}%)` +
        `${hasTestnet ? ' · testnet' : ''}`
      : // 데스크탑 = 기존 풀 detail (사장님 한눈 파악)
        `🔒 실 ${fmt(actualMarginSum)} + 📦 예약 ${fmt(reservedRemainingSum)} = 사용 ${fmt(usedTotal)} | ` +
        `💵 실 여유 ${fmt(realFreedom)}\n` +
        `⚡ 130% 한도 ${fmt(wallet130Sum)} | 신 전략 가용 +${fmt(newStratAvailSum)} (${newStrategyRatio.toFixed(1)}%)` +
        `${hasTestnet ? ' · testnet 포함' : ''}`;
    const accountInfo = valid.length > 1 ? ` · ${valid.length}계정 합산` : '';
    setMetric(
      'balance',
      `${fmt(walletSum)} USDT`,                       // 큰 글씨 = 지갑 총액 (사장님 직관)
      detailMain + accountInfo,                       // 작은 글씨 = 사용 + 130% 한도 (legacy hidden)
      newSig,
    );
    // 🌟 2026-06-09 v3 신 카드 = 진행바 + 3-grid mini + 신 전략 가용 (전문가 디자인)
    _updateBalanceCardV3({
      used: usedTotal,
      limit: wallet130Sum,
      pct: newStrategyRatio,
      real: actualMarginSum,
      reserved: reservedRemainingSum,
      free: realFreedom,
      newStratAvail: newStratAvailSum,
    });
    // tooltip — 마진율 + 계정별 detail + 단위 차이 + 「예약」 의미 설명
    const balCard = document.getElementById('card-balance') || document.querySelector('[data-metric="balance"]');
    if (balCard) {
      const ratioInfo = `마진율: ${aggRatio.toFixed(2)}% (유지 ${fmt(maintMarginSum)} / 마진 잔고 ${fmt(marginBalSum)})`;
      const reservedHelp = `📊 잔액 구간 의미 (2026-06-06 사장님 직관 정확화):\n\n` +
        `🔒 「실」 (이미 lock) = ${fmt(actualMarginSum)} USDT\n` +
        `   = Binance 가 현재 lock 한 마진 (진입한 단계까지 실제 사용)\n\n` +
        `📦 「포지션 예약됨」 (앞으로 lock) = ${fmt(reservedRemainingSum)} USDT\n` +
        `   = 사장님 계획 자본 ${fmt(reservedSum)} - 실 사용 ${fmt(actualMarginSum)}\n` +
        `   = 미진입 단계까지 lock 될 예정 자본 (= 자동 단계 진입 시 사용)\n\n` +
        `💵 「운용 가용」 (자유 잔액) = ${fmt(ourAvailSum)} USDT\n` +
        `   = 거래소 잔액 - 계획 자본 = 신규 strategy 생성 가능 한도\n` +
        `   = 음수 시: 계획 자본 초과 → 신규 strategy 생성 차단 (안전망)\n\n` +
        `✅ 합산 검증: 🔒 ${fmt(actualMarginSum)} + 📦 ${fmt(reservedRemainingSum)} + 💵 ${fmt(ourAvailSum)} = ${fmt(walletSum)} 💼\n` +
        `   = 거래소 잔액 일치 (사장님 한눈에 OK)`;
      balCard.title = valid.length > 1
        ? `📊 ${valid.length}개 active 계정 합산\n\n${perAccountLines}\n\n${ratioInfo}\n\n${reservedHelp}`
        : `${ratioInfo}\n\n${reservedHelp}`;
    }
  } catch (e) {
    setMetric('balance', '-', '잔액 조회 실패', 'red');
  }
}
