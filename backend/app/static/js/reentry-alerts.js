/**
 * 재진입 알람 UI (v130!)
 *
 * 사장님 요구 2026-08-06:
 *   - 강제 종료 후 = OBV+RSI+10% 신호 감지 = 알람!
 *   - 알람 지우기 / 선택 시 신 전략 즉시 생성!
 *
 * API:
 *   GET /api/v1/reentry-alerts = 활성 알람 리스트
 *   DELETE /api/v1/reentry-alerts/{key} = 삭제
 *
 * DOM:
 *   #reentry-alerts-card = 카드 (숨김/표시)
 *   #reentry-alerts-count = 개수 배지
 *   #reentry-alerts-list = 알람 리스트 (각 알람 = 버튼!)
 */

async function loadReentryAlerts() {
  try {
    const alerts = await api('/api/v1/reentry-alerts', 'GET');
    const card = document.getElementById('reentry-alerts-card');
    const countEl = document.getElementById('reentry-alerts-count');
    const listEl = document.getElementById('reentry-alerts-list');
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
      const side = a.side || 'SHORT';
      const sideColor = side === 'LONG' ? '#22c55e' : '#ef4444';
      const sideIcon = side === 'LONG' ? '🐂' : '🐻';
      const detail = a.detail || {};
      const movePct = detail.move_pct || '?';
      const currPrice = detail.current_price || '?';
      const rsi = detail.rsi_last || '?';
      const acctId = a.exchange_account_id || '?';
      // key 이스케이프
      const safeKey = encodeURIComponent(a._key || '');
      const symbol = (a.symbol || '').toUpperCase();
      return `
        <div class="flex items-center gap-1"
             style="background:rgba(0,0,0,0.3);border:1px solid ${sideColor};border-radius:6px;padding:4px 8px;box-shadow:0 0 8px ${sideColor}44">
          <button onclick="createStrategyFromAlert('${safeKey}', '${symbol}', '${side}', ${acctId})"
                  class="text-xs font-bold"
                  style="background:${sideColor};color:#fff;padding:3px 8px;border-radius:4px;border:0;cursor:pointer"
                  title="이 알람으로 = 신 전략 즉시 생성!">
            ${sideIcon} ${symbol} ${side}
          </button>
          <span class="text-xs" style="color:#c4b5fd" title="이전 손절가 대비 이동">
            ${movePct}% | 현재 ${currPrice}
          </span>
          <span class="text-xs text-slate-400">RSI ${rsi}</span>
          <button onclick="deleteReentryAlert('${safeKey}')"
                  class="text-xs"
                  style="background:transparent;color:#9ca3af;border:0;cursor:pointer;padding:0 4px"
                  title="알람 무시 (삭제)">✕</button>
        </div>
      `;
    }).join('');
  } catch (e) {
    console.warn('[reentry_alerts] load 실패:', e);
  }
}

async function deleteReentryAlert(safeKey) {
  try {
    const key = decodeURIComponent(safeKey);
    await api('/api/v1/reentry-alerts/' + encodeURIComponent(key), 'DELETE');
    if (typeof toast === 'function') toast('✅ 알람 삭제', 'success');
    loadReentryAlerts();  // 즉시 재로드
  } catch (e) {
    if (typeof toast === 'function') toast('❌ 삭제 실패: ' + (e.message || e), 'error');
  }
}

// 알람 클릭 → 신 전략 생성 (심볼 자동 설정!)
async function createStrategyFromAlert(safeKey, symbol, side, exchangeAccountId) {
  try {
    // 옵션 A: 신 OBV 전략 모달 열기 (자동 재진입 = 사장님 사상 정확!)
    // 옵션 B: 기존 방식 모달
    // = 옵션 A default (신 OBV 모드!)
    if (typeof openCreateChartObvModal !== 'function') {
      if (typeof toast === 'function') toast('❌ 신 전략 모달 함수 없음', 'error');
      return;
    }
    await openCreateChartObvModal();

    // 심볼 자동 설정
    setTimeout(() => {
      const symbolInput = document.getElementById('cm-symbol');
      if (symbolInput) {
        symbolInput.value = symbol;
        symbolInput.dispatchEvent(new Event('input', {bubbles: true}));
        symbolInput.dispatchEvent(new Event('change', {bubbles: true}));
      }
      // side 설정 (cmState 있으면)
      if (typeof cmState !== 'undefined') {
        cmState.side = side;
        // 라디오 버튼 활성화 (있으면)
        const sideRadio = document.querySelector(`input[name="cm-side"][value="${side}"]`);
        if (sideRadio) sideRadio.checked = true;
        // 계정 자동 설정
        if (exchangeAccountId) {
          cmState.accountId = Number(exchangeAccountId);
          const acctSelect = document.getElementById('cm-account');
          if (acctSelect) acctSelect.value = String(exchangeAccountId);
        }
      }
      if (typeof toast === 'function') {
        toast(`🎯 ${symbol} ${side} 알람 = 신 전략 모달! 자본 세팅 후 진입!`, 'success');
      }
    }, 300);

    // 알람 자동 삭제 (선택했으니 = 무효화)
    setTimeout(() => {
      deleteReentryAlert(safeKey).catch(() => {});
    }, 1000);
  } catch (e) {
    if (typeof toast === 'function') toast('❌ 생성 실패: ' + (e.message || e), 'error');
  }
}

// 5초마다 알람 갱신 (dashboard-refresh polling에 통합)
if (typeof window !== 'undefined') {
  window.loadReentryAlerts = loadReentryAlerts;
  window.deleteReentryAlert = deleteReentryAlert;
  window.createStrategyFromAlert = createStrategyFromAlert;
  // 초기 로드
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(loadReentryAlerts, 1000);
    setInterval(loadReentryAlerts, 15000);  // 15초 polling
  });
}
