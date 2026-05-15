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
    const lbl = document.getElementById('activity-count-label');
    if (lbl) lbl.textContent = `(최신순 ${data.length}건${data.length >= limit ? ' — 더 보려면 ↑ 표시 변경' : ''})`;
    if (!data.length) {
      el.innerHTML = '<p class="text-slate-500 text-sm text-center py-4">활동 이력 없음</p>';
      return;
    }
    const kindColor = { ORDER: 'text-blue-300', RISK: 'text-red-300', NOTIFY: 'text-slate-400' };
    el.innerHTML = data.map(t => {
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

// 거래소 잔액 카드 — 첫 active 거래소 계정 기준 (다중 계정이면 별도 처리 필요)
async function loadBalance() {
  try {
    const accounts = await api('/exchange-accounts').catch(() => []);
    if (!accounts || !accounts.length) {
      setMetric('balance', '-', '거래소 계정 없음', 'gray');
      return;
    }
    const active = accounts.find(a => a.is_active) || accounts[0];
    const data = await api(`/exchange-accounts/${active.id}/balance`);
    const wallet = Number(data.total_wallet_balance || 0);
    const available = Number(data.available_balance || 0);
    const ratio = Number(data.margin_ratio_pct || 0);
    // 마진 비율 기반 신호: < 50% green, 50~80% yellow, > 80% red
    const sig = ratio < 50 ? 'green' : ratio < 80 ? 'yellow' : 'red';
    setMetric(
      'balance',
      `${available.toLocaleString('en-US', {maximumFractionDigits: 2})} USDT`,
      `wallet ${wallet.toLocaleString('en-US', {maximumFractionDigits: 2})} / ${ratio.toFixed(2)}%${data.is_testnet ? ' (testnet)' : ''}`,
      sig,
    );
  } catch (e) {
    setMetric('balance', '-', '잔액 조회 실패', 'red');
  }
}
