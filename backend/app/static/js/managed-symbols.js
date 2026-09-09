/**
 * 🧭 심볼 관리 재진입 UI (Fix 365, 2026-09-09)
 *
 * 사장님: "첫 진입에 실패하면 청산하고 재진입 모니터링으로 특별 관리해서 우선 포지션 진입할 심볼로
 *         관리를 하고 재진입 모니터링 후 다시 10usdt로 진입해서 성공하면 포지션추가로 … 10번까지 반복"
 *
 * 이 파일은 판정을 하지 않는다 — 명부(app/models/managed_symbol.py)를 보여주고, 사장님이
 * 심볼을 추가/초기화/해제하는 버튼만 다룬다. 실제 감시·진입은 managed_symbol_worker.py.
 *
 * API: GET/POST /managed-symbols, POST /managed-symbols/{id}/reset, DELETE /managed-symbols/{id}
 *
 * DOM:
 *   #managed-symbols-card             = 카드 (숨김/표시)
 *   #managed-symbols-count            = 개수 배지
 *   #managed-symbols-cycle            = 워커 마지막 사이클 한 줄 요약
 *   #managed-symbols-settings         = 설정 한 줄(모드/진입on-off/상한/일일한도)
 *   #managed-symbols-hide-released    = 「관리 종료 숨김」 체크박스 (기본 켬)
 *   #managed-symbols-add-input        = 심볼 입력칸
 *   #managed-symbols-list             = 명부 행 목록
 */

function _msAgoLabel(iso) {
  if (!iso) return '?';
  try {
    const ms = Date.now() - new Date(iso).getTime();
    if (ms < 0) return '방금 전';
    const min = Math.floor(ms / 60000);
    if (min < 1) return '방금 전';
    if (min < 60) return `${min}분 전`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}시간 전`;
    return `${Math.floor(hr / 24)}일 전`;
  } catch { return '?'; }
}

function _msTimeLabel(iso) {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  } catch { return '-'; }
}

function _msTruncate(s, n) {
  s = String(s || '');
  return s.length > n ? s.slice(0, n) + '…' : s;
}

function _msEscape(s) {
  const d = document.createElement('div');
  d.textContent = String(s == null ? '' : s);
  return d.innerHTML;
}

function _msStatusChip(status) {
  const map = {
    WATCHING: { bg: '#0e7490', fg: '#fff', label: '👁 감시중' },
    EXHAUSTED: { bg: '#b45309', fg: '#fff', label: '⛔ 소진' },
    RELEASED: { bg: '#475569', fg: '#e2e8f0', label: '✕ 해제' },
  };
  const m = map[status] || { bg: '#334155', fg: '#e2e8f0', label: status || '?' };
  return `<span class="text-xs" style="background:${m.bg};color:${m.fg};padding:1px 6px;border-radius:8px">${m.label}</span>`;
}

function _msCycleSummary(c) {
  if (!c) return '워커 기록 없음';
  if (c.off) return `설정 OFF (${_msTimeLabel(c.at)})`;
  const skipped = c.skipped && typeof c.skipped === 'object'
    ? Object.entries(c.skipped).map(([k, v]) => `${k}:${v}`).join(' ')
    : '';
  const err = c.error ? ` ⚠ ${_msEscape(c.error)}` : '';
  return `${_msTimeLabel(c.at)} (${_msAgoLabel(c.at)}) · 감시 ${c.watching ?? 0} · 판정 ${c.checked ?? 0} · `
       + `진입 ${c.entered ?? 0} · 해제 ${c.released ?? 0}${skipped ? ' · 보류[' + skipped + ']' : ''}${err}`;
}

function _msSettingsSummary(s) {
  if (!s) return '';
  const mode = s.obv_loss_ladder_mode === 'ladder' ? '사다리(ladder)' : '프로브(probe)';
  const entryOn = s.managed_symbol_entry_enabled ? 'ON' : 'OFF';
  const enabledOn = s.managed_symbol_enabled ? 'ON' : 'OFF';
  return `모드 ${mode} · 감시 ${enabledOn} · 진입 ${entryOn} · 연속실패상한 ${s.managed_symbol_max_attempts ?? '?'} · `
       + `일일한도 ${s.managed_symbol_daily_entry_limit ?? '?'}`;
}

function _msRow(item) {
  const status = item.status || 'WATCHING';
  const attempts = item.attempts ?? 0;
  const maxAttempts = item.max_attempts ?? 10;
  const successes = item.successes ?? 0;
  const totalEntries = item.total_entries ?? 0;
  const lastSide = item.last_side || null;
  const lastPnl = item.last_pnl;
  const pnlColor = (lastPnl == null) ? '#94a3b8' : (Number(lastPnl) >= 0 ? '#22c55e' : '#ef4444');
  const pnlLabel = (lastPnl == null) ? '-' : (Number(lastPnl) >= 0 ? '+' : '') + Number(lastPnl).toFixed(2);
  const reasons = item.last_reasons || {};
  const activeSides = item.active_sides || [];

  const activeChip = activeSides.length
    ? `<span class="text-xs" style="background:#7c3aed;color:#fff;padding:1px 6px;border-radius:8px">보유 ${activeSides.join('/')}</span>`
    : '';

  const longLine = reasons.LONG
    ? `<div class="text-xs" style="color:#86efac" title="${_msEscape(reasons.LONG)}">LONG: ${_msEscape(_msTruncate(reasons.LONG, 90))}</div>` : '';
  const shortLine = reasons.SHORT
    ? `<div class="text-xs" style="color:#fca5a5" title="${_msEscape(reasons.SHORT)}">SHORT: ${_msEscape(_msTruncate(reasons.SHORT, 90))}</div>` : '';
  const stateLine = reasons.state
    ? `<div class="text-xs text-slate-300" title="${_msEscape(reasons.state)}">${_msEscape(_msTruncate(reasons.state, 90))}</div>` : '';
  const errLine = reasons.error
    ? `<div class="text-xs" style="color:#f87171">⚠ ${_msEscape(_msTruncate(reasons.error, 90))}</div>` : '';

  const checkLabel = item.last_check_at
    ? `${_msTimeLabel(item.last_check_at)} (${_msAgoLabel(item.last_check_at)})` : '아직 판정 전';

  return `
    <div class="rounded" style="background:rgba(0,0,0,0.25);border:1px solid rgba(6,182,212,0.25);padding:6px 8px">
      <div class="flex items-center justify-between flex-wrap gap-1">
        <div class="flex items-center gap-1 flex-wrap">
          <span class="font-bold text-sm" style="color:#67e8f9">${_msEscape(item.symbol)}</span>
          ${_msStatusChip(status)}
          ${activeChip}
          <span class="text-xs text-slate-400">실패 ${attempts}/${maxAttempts}</span>
          <span class="text-xs text-slate-400">성공 ${successes}</span>
          <span class="text-xs text-slate-400">재진입 ${totalEntries}</span>
          ${lastSide ? `<span class="text-xs" style="color:${pnlColor}">${_msEscape(lastSide)} ${pnlLabel}</span>` : ''}
        </div>
        <div class="flex items-center gap-1">
          <button onclick="resetManagedSymbol(${item.id})" class="text-xs bg-slate-700 hover:bg-slate-600 text-white px-2 py-0.5 rounded"
                  title="시도 0으로 되돌리고 다시 감시">↺ 초기화</button>
          <button onclick="releaseManagedSymbol(${item.id}, '${_msEscape(item.symbol)}')" class="text-xs bg-red-800 hover:bg-red-700 text-white px-2 py-0.5 rounded"
                  title="명부에서 내림 (행은 남고 RELEASED 로 표시)">✕ 해제</button>
        </div>
      </div>
      ${longLine}${shortLine}${stateLine}${errLine}
      <div class="text-xs text-slate-500 mt-1">마지막 판정: ${checkLabel}</div>
    </div>
  `;
}

async function loadManagedSymbols() {
  try {
    const hideChk = document.getElementById('managed-symbols-hide-released');
    const includeReleased = (hideChk && !hideChk.checked) ? 1 : 0;
    const data = await api(`/managed-symbols?include_released=${includeReleased}`);
    const card = document.getElementById('managed-symbols-card');
    const countEl = document.getElementById('managed-symbols-count');
    const cycleEl = document.getElementById('managed-symbols-cycle');
    const settingsEl = document.getElementById('managed-symbols-settings');
    const listEl = document.getElementById('managed-symbols-list');
    if (!card || !countEl || !listEl) return;

    const items = (data && data.items) || [];
    const lastCycle = data ? data.last_cycle : null;

    if (items.length === 0 && !lastCycle) {
      card.classList.add('hidden');
      return;
    }
    card.classList.remove('hidden');

    countEl.textContent = String(items.length);
    if (cycleEl) cycleEl.textContent = _msCycleSummary(lastCycle);
    if (settingsEl) settingsEl.textContent = _msSettingsSummary(data ? data.settings : null);
    listEl.innerHTML = items.length
      ? items.map(_msRow).join('')
      : `<div class="text-xs text-slate-500">관리 중인 심볼이 없습니다.</div>`;
  } catch (e) {
    console.warn('[managed_symbols] load 실패:', e);
  }
}

async function addManagedSymbol() {
  const input = document.getElementById('managed-symbols-add-input');
  if (!input) return;
  const symbol = (input.value || '').trim().toUpperCase();
  if (!symbol) {
    if (typeof toast === 'function') toast('❌ 심볼을 입력해 주세요', 'error');
    return;
  }
  try {
    await api('/managed-symbols', { method: 'POST', body: { symbol } });
    input.value = '';
    if (typeof toast === 'function') toast(`✅ ${symbol} 관리 명부에 등록`, 'success');
    loadManagedSymbols();
  } catch (e) {
    if (typeof toast === 'function') toast('❌ 등록 실패: ' + (e.message || e), 'error');
  }
}

async function resetManagedSymbol(id) {
  try {
    await api(`/managed-symbols/${id}/reset`, { method: 'POST' });
    if (typeof toast === 'function') toast('✅ 초기화 완료', 'success');
    loadManagedSymbols();
  } catch (e) {
    if (typeof toast === 'function') toast('❌ 초기화 실패: ' + (e.message || e), 'error');
  }
}

async function releaseManagedSymbol(id, symbol) {
  if (!confirm(`${symbol || '이 심볼'}을(를) 관리 명부에서 해제할까요?\n(포지션이 있으면 별도로 종료해야 합니다)`)) return;
  try {
    await api(`/managed-symbols/${id}`, { method: 'DELETE' });
    if (typeof toast === 'function') toast('✅ 해제 완료', 'success');
    loadManagedSymbols();
  } catch (e) {
    if (typeof toast === 'function') toast('❌ 해제 실패: ' + (e.message || e), 'error');
  }
}

if (typeof window !== 'undefined') {
  window.loadManagedSymbols = loadManagedSymbols;
  window.addManagedSymbol = addManagedSymbol;
  window.resetManagedSymbol = resetManagedSymbol;
  window.releaseManagedSymbol = releaseManagedSymbol;
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(loadManagedSymbols, 1000);
    setInterval(loadManagedSymbols, 30000);  // 30초 polling
  });
}
