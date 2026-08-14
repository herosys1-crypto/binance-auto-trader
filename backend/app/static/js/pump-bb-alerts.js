/**
 * 급등+BB중단 알람 UI (v131 사장님 2026-08-09!)
 *
 * 사장님 요구:
 *   - 바이낸스 선물 급등 top 50!
 *   - 4H 최고점 = BB중단 (20MA!) ±5% 근접!
 *   ⚠️ v147b: 실측상 BB중단은 **지지선이 아님** (4H 도달 후 68.3%가 뚫고 마감).
 *      알람의 caution 문구를 그대로 노출합니다 = 관찰용 신호!
 *   - 알람 카드 표시!
 *
 * API:
 *   GET /api/v1/pump-bb-alerts       = 활성 알람 리스트
 *   DELETE /api/v1/pump-bb-alerts/{id} = 삭제
 *
 * DOM:
 *   #pump-bb-alerts-card = 카드
 *   #pump-bb-count       = 개수 배지
 *   #pump-bb-list        = 알람 리스트
 */

async function loadPumpBbAlerts() {
  try {
    const alerts = await api('/pump-bb-alerts');
    const card = document.getElementById('pump-bb-alerts-card');
    const countEl = document.getElementById('pump-bb-count');
    const listEl = document.getElementById('pump-bb-list');
    if (!card || !countEl || !listEl) return;

    if (!alerts || alerts.length === 0) {
      card.classList.add('hidden');
      countEl.textContent = '0';
      listEl.innerHTML = '';
      return;
    }

    card.classList.remove('hidden');
    countEl.textContent = String(alerts.length);
    listEl.innerHTML = alerts.map(a => {
      const symbol = (a.symbol || '').toUpperCase();
      const detail = a.detail || {};
      const diff = detail.diff_pct || '?';
      const bbMid = detail.bb_middle || '?';
      const peak = detail.peak || '?';
      const currPrice = detail.current_price || '?';
      const dropPct = detail.drop_from_peak_pct || '?';
      const safeKey = encodeURIComponent(a._key || '');
      return `
        <div class="flex items-center gap-1"
             style="background:rgba(0,0,0,0.35);border:1px solid #f59e0b;border-radius:6px;padding:4px 8px;box-shadow:0 0 8px rgba(245,158,11,0.4)">
          <button onclick="createStrategyFromPumpBb('${safeKey}', '${symbol}')"
                  class="text-xs font-bold"
                  style="background:linear-gradient(135deg,#f59e0b,#ef4444);color:#fff;padding:3px 8px;border-radius:4px;border:0;cursor:pointer"
                  title="이 심볼로 = 신 전략 즉시 생성!">
            🚨 ${symbol}
          </button>
          <span class="text-xs text-slate-300" title="최고점 vs BB중단 차이">
            차이 ${diff}%
          </span>
          <span class="text-xs text-slate-400" title="피크 대비 현재가 하락률">
            ↓${dropPct}%
          </span>
          <span class="text-xs text-slate-500" title="현재가 / BB중단">
            현재 ${currPrice} / 20MA ${bbMid}
          </span>
          <button onclick="deletePumpBbAlert('${safeKey}')"
                  class="text-xs"
                  style="background:transparent;color:#9ca3af;border:0;cursor:pointer;padding:0 4px"
                  title="알람 무시 (삭제)">✕</button>
        </div>
      `;
    }).join('');
  } catch (e) {
    console.warn('[pump_bb_alerts] load 실패:', e);
  }
}

async function deletePumpBbAlert(safeKey) {
  try {
    const key = decodeURIComponent(safeKey);
    await api('/pump-bb-alerts/' + encodeURIComponent(key), { method: 'DELETE' });
    if (typeof toast === 'function') toast('✅ 알람 삭제', 'success');
    loadPumpBbAlerts();
  } catch (e) {
    if (typeof toast === 'function') toast('❌ 삭제 실패: ' + (e.message || e), 'error');
  }
}

// 알람 클릭 → 신 전략 생성 (심볼 자동!)
async function createStrategyFromPumpBb(safeKey, symbol) {
  try {
    if (typeof openCreateModal !== 'function') {
      if (typeof toast === 'function') toast('❌ 신 전략 모달 함수 없음', 'error');
      return;
    }
    await openCreateModal();

    // 심볼 자동 설정
    setTimeout(() => {
      const symbolInput = document.getElementById('cm-symbol');
      if (symbolInput) {
        symbolInput.value = symbol;
        symbolInput.dispatchEvent(new Event('input', {bubbles: true}));
        symbolInput.dispatchEvent(new Event('change', {bubbles: true}));
      }
      if (typeof toast === 'function') {
        toast(`🎯 ${symbol} = 신 전략 모달! 자본/방향 세팅 후 진입!`, 'success');
      }
    }, 300);

    // 알람 자동 삭제 (선택했으니!)
    setTimeout(() => {
      deletePumpBbAlert(safeKey).catch(() => {});
    }, 1000);
  } catch (e) {
    if (typeof toast === 'function') toast('❌ 생성 실패: ' + (e.message || e), 'error');
  }
}

if (typeof window !== 'undefined') {
  window.loadPumpBbAlerts = loadPumpBbAlerts;
  window.deletePumpBbAlert = deletePumpBbAlert;
  window.createStrategyFromPumpBb = createStrategyFromPumpBb;
  // 초기 로드
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(loadPumpBbAlerts, 1200);
    setInterval(loadPumpBbAlerts, 30000);  // 30초 polling
  });
}
