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

// 🌟 v131 (사장님 A 안전): 알람 클릭 = 신/구 선택 팝업!
async function createStrategyFromAlert(safeKey, symbol, side, exchangeAccountId) {
  // 이미 열려있으면 = 닫기
  const existing = document.getElementById('reentry-choose-modal');
  if (existing) existing.remove();

  const sideIcon = side === 'LONG' ? '🐂' : '🐻';
  const sideColor = side === 'LONG' ? '#22c55e' : '#ef4444';

  const html = `
    <div id="reentry-choose-modal" class="fixed inset-0 z-50 flex items-center justify-center"
         style="background:rgba(0,0,0,0.7)"
         onclick="if(event.target===this)document.getElementById('reentry-choose-modal').remove()">
      <div class="bg-slate-900 rounded-lg p-6 max-w-md w-full mx-4"
           style="border:2px solid ${sideColor};box-shadow:0 0 20px ${sideColor}66">
        <h3 class="text-lg font-bold mb-2" style="color:${sideColor}">
          ${sideIcon} ${symbol} ${side} 재진입!
        </h3>
        <p class="text-xs text-slate-400 mb-4">
          💡 신/구 방식 선택하세요!
        </p>

        <div class="space-y-3">
          <button onclick="_reentryPick('${safeKey}', '${symbol}', '${side}', ${exchangeAccountId}, 'obv')"
                  class="w-full text-left bg-gradient-to-r from-purple-700 to-blue-700
                         hover:from-purple-600 hover:to-blue-600
                         text-white p-4 rounded-lg transition">
            <div class="font-bold text-base mb-1">📊 신 OBV 자동 재진입</div>
            <div class="text-xs opacity-90">
              1단계 = MARKET 진입! 2단계+ = 4H OBV 신호 대기!<br>
              (= 손절되도 자동 재진입 감지!)
            </div>
          </button>

          <button onclick="_reentryPick('${safeKey}', '${symbol}', '${side}', ${exchangeAccountId}, 'classic')"
                  class="w-full text-left bg-slate-700 hover:bg-slate-600
                         text-white p-4 rounded-lg transition">
            <div class="font-bold text-base mb-1">➕ 기존 방식 (가격 도달)</div>
            <div class="text-xs opacity-90">
              가격 도달 시 = 단계별 자동 진입! (옛 방식!)<br>
              (= 사장님 옛 습관 그대로!)
            </div>
          </button>
        </div>

        <button onclick="document.getElementById('reentry-choose-modal').remove()"
                class="w-full mt-4 bg-slate-800 hover:bg-slate-700 text-slate-400 py-2 rounded text-sm">
          ✕ 취소
        </button>
      </div>
    </div>
  `;
  document.body.insertAdjacentHTML('beforeend', html);
}

// 신/구 선택 후 실제 모달 열기
async function _reentryPick(safeKey, symbol, side, exchangeAccountId, mode) {
  try {
    // 선택 팝업 닫기
    const chooseModal = document.getElementById('reentry-choose-modal');
    if (chooseModal) chooseModal.remove();

    // 신 모드 = openCreateChartObvModal / 구 모드 = openCreateModal
    const openFn = (mode === 'obv')
      ? window.openCreateChartObvModal
      : window.openCreateModal;

    if (typeof openFn !== 'function') {
      if (typeof toast === 'function') {
        toast(`❌ ${mode === 'obv' ? '신 OBV' : '구'} 모달 함수 없음`, 'error');
      }
      return;
    }
    await openFn();

    // 심볼 + side + 계정 자동 설정
    setTimeout(() => {
      const symbolInput = document.getElementById('cm-symbol');
      if (symbolInput) {
        symbolInput.value = symbol;
        symbolInput.dispatchEvent(new Event('input', {bubbles: true}));
        symbolInput.dispatchEvent(new Event('change', {bubbles: true}));
      }
      if (typeof cmState !== 'undefined') {
        cmState.side = side;
        const sideRadio = document.querySelector(`input[name="cm-side"][value="${side}"]`);
        if (sideRadio) sideRadio.checked = true;
        if (exchangeAccountId) {
          cmState.accountId = Number(exchangeAccountId);
          const acctSelect = document.getElementById('cm-account');
          if (acctSelect) acctSelect.value = String(exchangeAccountId);
        }
      }
      if (typeof toast === 'function') {
        const modeLabel = mode === 'obv' ? '📊 신 OBV' : '➕ 기존 방식';
        toast(`🎯 ${symbol} ${side} = ${modeLabel} 모달! 자본 세팅 후 진입!`, 'success');
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

// 🚨 v131 사장님 결정 (A 안전!): 자동 실행 세팅 = 「⏳ 준비중」!
// = 안전장치 6개 미완성 = 잘못 켜면 자본 손실 위험!
// = 다음 세션 안전장치 완성 후 = 정식 활성화!
async function openReentrySettingsModal() {
  // 기존 modal 제거 후 삽입
  const existing = document.getElementById('reentry-settings-modal');
  if (existing) existing.remove();

  const html = `
    <div id="reentry-settings-modal" class="fixed inset-0 z-50 flex items-center justify-center"
         style="background:rgba(0,0,0,0.7)"
         onclick="if(event.target===this)closeReentrySettingsModal()">
      <div class="bg-slate-900 rounded-lg p-6 max-w-md w-full mx-4"
           style="border:2px solid #f59e0b;box-shadow:0 0 20px #f59e0b66">
        <h3 class="text-lg font-bold text-yellow-300 mb-3">
          ⏳ 자동 실행 = 준비중!
        </h3>
        <p class="text-sm text-slate-200 mb-4">
          사장님 안전 결정 (2026-08-09):<br>
          <strong class="text-yellow-400">자동 실행 = 안전장치 미완성!</strong>
        </p>
        <div class="bg-slate-800 rounded p-3 mb-4 text-xs text-slate-300 space-y-1">
          <div class="font-bold text-yellow-300 mb-1">🚨 완성 필요 안전장치 (4개):</div>
          <div>1. 4H 봉 완성 후에만 판정!</div>
          <div>2. 중복 진입 방지 (같은 심볼)!</div>
          <div>3. 심볼 blacklist (연속 손실!)</div>
          <div>4. RSI 극값 필터 (&lt; 30 / &gt; 70)!</div>
        </div>
        <p class="text-xs text-blue-300 mb-2">
          💡 <strong>자본 한도는 필요 X!</strong><br>
          이유 = 신 전략 만들 때 사장님이 단계별 자본 세팅!<br>
          (1단계 500 / 2단계 500 / 3단계 1000 = 사장님 결정!)
        </p>
        <p class="text-xs text-green-300 mb-4">
          ✅ <strong>지금 = 수동 승인만!</strong><br>
          알람 클릭 → 신/구 방식 선택 → 사장님 승인 = 안전!
        </p>
        <button onclick="closeReentrySettingsModal()"
                class="w-full bg-slate-700 hover:bg-slate-600 text-slate-200 py-2 rounded">
          알겠습니다!
        </button>
      </div>
    </div>
  `;
  document.body.insertAdjacentHTML('beforeend', html);
}

function closeReentrySettingsModal() {
  const el = document.getElementById('reentry-settings-modal');
  if (el) el.remove();
}

// 🚨 saveReentrySettings 제거 = v131 사장님 A 안전!
// = 자동 실행 = 다음 세션 안전장치 완성 후 재활성!

// 5초마다 알람 갱신 (dashboard-refresh polling에 통합)
if (typeof window !== 'undefined') {
  window.loadReentryAlerts = loadReentryAlerts;
  window.deleteReentryAlert = deleteReentryAlert;
  window.createStrategyFromAlert = createStrategyFromAlert;
  window._reentryPick = _reentryPick;  // v131 신/구 선택!
  window.openReentrySettingsModal = openReentrySettingsModal;
  window.closeReentrySettingsModal = closeReentrySettingsModal;
  // 초기 로드
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(loadReentryAlerts, 1000);
    setInterval(loadReentryAlerts, 15000);  // 15초 polling
  });
}
