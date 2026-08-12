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

async function loadStrategySuggestions() {
  try {
    const suggestions = await api('/strategy-suggestions', 'GET');
    const card = document.getElementById('strategy-suggestions-card');
    const countEl = document.getElementById('suggestions-count');
    const listEl = document.getElementById('suggestions-list');
    if (!card || !countEl || !listEl) return;

    if (!suggestions || suggestions.length === 0) {
      card.classList.add('hidden');
      countEl.textContent = '0';
      listEl.innerHTML = '';
      return;
    }

    card.classList.remove('hidden');
    countEl.textContent = String(suggestions.length);
    listEl.innerHTML = suggestions.map(s => {
      const side = s.side || 'SHORT';
      const sideColor = side === 'LONG' ? '#22c55e' : '#ef4444';
      const sideIcon = side === 'LONG' ? '🐂' : '🐻';
      const sideLabel = side === 'LONG' ? 'LONG' : 'SHORT';
      const conf = s.confidence_score
        ? (Number(s.confidence_score) * 100).toFixed(0) + '%'
        : '?';
      const createdAgo = _formatTimeAgo(s.created_at);
      const cfg = s.strategy_config || {};
      const cap1 = (cfg.capitals && cfg.capitals[0]) || '?';
      const lev = cfg.leverage || '?';
      const forceSl = cfg.force_sl_roi_override || '?';
      const reason = s.reason || '(이유 없음)';

      return `
        <div style="background:rgba(0,0,0,0.3);border:1px solid ${sideColor};border-radius:6px;padding:8px 10px;box-shadow:0 0 8px ${sideColor}44">
          <div class="flex items-center justify-between mb-1">
            <span class="text-sm font-bold" style="color:${sideColor}">
              ${sideIcon} ${s.symbol} ${sideLabel}
              <span class="text-xs text-slate-400 ml-2">| ${s.suggestion_type}</span>
            </span>
            <span class="text-xs font-bold" style="color:#fbbf24">
              🎯 신뢰도 ${conf}
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
            <button onclick="executeSuggestion(${s.id})"
                    class="text-xs font-bold px-3 py-1 rounded"
                    style="background:linear-gradient(135deg,#059669,#22c55e);color:#fff;border:0;cursor:pointer"
                    title="지금 실행 (수동 - 사장님!)">
              ▶ 지금 실행
            </button>
            <button onclick="openSuggestionsSettingsModal()"
                    class="text-xs px-3 py-1 rounded"
                    style="background:#7c3aed;color:#fff;border:0;cursor:pointer"
                    title="자동 실행 옵션 세팅!">
              ⚙ 자동
            </button>
            <button onclick="dismissSuggestion(${s.id})"
                    class="text-xs px-3 py-1 rounded"
                    style="background:#475569;color:#fff;border:0;cursor:pointer"
                    title="이 제안 삭제!">
              ❌ 삭제
            </button>
          </div>
        </div>
      `;
    }).join('');
  } catch (e) {
    console.warn('[suggestions] load 실패:', e);
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

async function executeSuggestion(id) {
  if (!confirm('이 전략 제안을 실행하시겠습니까?\n\n= 신 전략 즉시 생성됩니다!')) return;
  try {
    const r = await api('/strategy-suggestions/' + id + '/execute', 'POST');
    if (typeof toast === 'function') {
      toast(`✅ ${r.symbol} ${r.side} 실행!` + (r.note ? ` (${r.note})` : ''), 'success');
    }
    loadStrategySuggestions();
  } catch (e) {
    if (typeof toast === 'function') toast('❌ 실행 실패: ' + (e.message || e), 'error');
  }
}

async function dismissSuggestion(id) {
  if (!confirm('이 제안을 삭제하시겠습니까?')) return;
  try {
    await api('/strategy-suggestions/' + id, 'DELETE');
    if (typeof toast === 'function') toast('✅ 제안 삭제', 'success');
    loadStrategySuggestions();
  } catch (e) {
    if (typeof toast === 'function') toast('❌ 삭제 실패: ' + (e.message || e), 'error');
  }
}

async function openSuggestionsSettingsModal() {
  try {
    const settings = await api('/strategy-suggestions/settings', 'GET');

    const existing = document.getElementById('suggestions-settings-modal');
    if (existing) existing.remove();

    const html = `
      <div id="suggestions-settings-modal" class="fixed inset-0 z-50 flex items-center justify-center"
           style="background:rgba(0,0,0,0.7)"
           onclick="if(event.target===this)closeSuggestionsSettingsModal()">
        <div class="bg-slate-900 rounded-lg p-6 max-w-md w-full mx-4"
             style="border:2px solid #a855f7;box-shadow:0 0 20px #a855f766">
          <h3 class="text-lg font-bold text-purple-300 mb-3">
            ⚙ 전략 제안 자동 실행 세팅
          </h3>
          <p class="text-xs text-slate-400 mb-3">
            💡 <strong>기본 = OFF (수동!)</strong><br>
            사장님 = 자동 실행 = 위험 감수!
          </p>

          <div class="space-y-3">
            <label class="flex items-center gap-2 text-sm text-slate-200 cursor-pointer">
              <input type="checkbox" id="sug-auto-enabled"
                     ${settings.auto_execute_enabled?'checked':''}
                     style="width:18px;height:18px;cursor:pointer">
              <span class="font-bold">🤖 자동 실행 활성화</span>
            </label>
            <p class="text-xs text-yellow-400 -mt-2 ml-6">⚠️ ON = 사장님 승인 없이 = 자동 진입!</p>

            <div>
              <label class="text-sm text-slate-300 block mb-1">🎯 자동 실행 최소 신뢰도:</label>
              <input type="number" id="sug-confidence"
                     value="${settings.confidence_threshold}"
                     min="0" max="1" step="0.01"
                     class="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-slate-200 text-sm">
              <p class="text-xs text-slate-500 mt-1">0.85 이상 권장!</p>
            </div>

            <div>
              <label class="text-sm text-slate-300 block mb-1">📆 일일 자동 실행 한도:</label>
              <input type="number" id="sug-daily-limit"
                     value="${settings.daily_auto_limit}"
                     min="1" max="10" step="1"
                     class="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-slate-200 text-sm">
            </div>

            <div>
              <label class="text-sm text-slate-300 block mb-1">⏰ 미실행 자동 삭제 (시간):</label>
              <input type="number" id="sug-auto-dismiss"
                     value="${settings.auto_dismiss_hours}"
                     min="0" max="72" step="1"
                     class="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-slate-200 text-sm">
              <p class="text-xs text-slate-500 mt-1">0 = 자동 삭제 안 함!</p>
            </div>
          </div>

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

async function saveSuggestionsSettings() {
  try {
    const enabled = document.getElementById('sug-auto-enabled').checked;
    const confidence = document.getElementById('sug-confidence').value;
    const dailyLimit = document.getElementById('sug-daily-limit').value;
    const autoDismiss = document.getElementById('sug-auto-dismiss').value;

    await api('/strategy-suggestions/settings', 'PUT', {
      auto_execute_enabled: enabled,
      confidence_threshold: confidence,
      daily_auto_limit: dailyLimit,
      auto_dismiss_hours: autoDismiss,
    });

    if (typeof toast === 'function') {
      toast(`✅ 세팅 저장! 자동 실행 ${enabled?'ON 🤖':'OFF 🙋'}`, 'success');
    }
    closeSuggestionsSettingsModal();
  } catch (e) {
    if (typeof toast === 'function') toast('❌ 저장 실패: ' + (e.message || e), 'error');
  }
}

if (typeof window !== 'undefined') {
  window.loadStrategySuggestions = loadStrategySuggestions;
  window.executeSuggestion = executeSuggestion;
  window.dismissSuggestion = dismissSuggestion;
  window.openSuggestionsSettingsModal = openSuggestionsSettingsModal;
  window.closeSuggestionsSettingsModal = closeSuggestionsSettingsModal;
  window.saveSuggestionsSettings = saveSuggestionsSettings;
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(loadStrategySuggestions, 1200);
    setInterval(loadStrategySuggestions, 30000);  // 30초 polling
  });
}
