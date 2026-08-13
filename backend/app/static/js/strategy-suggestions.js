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

async function loadStrategySuggestions() {
  try {
    const suggestions = await api('/strategy-suggestions');
    _cachedSuggestions = suggestions || [];
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

    const suggestions = filtered;
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
      const TYPE_LABELS = {
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
        <div style="background:rgba(0,0,0,0.3);border:1px solid ${sideColor};border-radius:6px;padding:8px 10px;box-shadow:0 0 8px ${sideColor}44;${liveGlow};cursor:pointer"
             onclick="openSuggestionAnalysis('${s.symbol}', '${side}', ${s.id})"
             title="클릭 = 상세 분석 새 창!">
          <div class="flex items-center justify-between mb-1">
            <span class="text-sm font-bold" style="color:${sideColor}">
              <span style="color:#c4b5fd;font-size:0.85em">${rankIcon}</span>
              ${sideIcon} ${s.symbol} ${sideLabel}
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
            <button onclick="event.stopPropagation();openSuggestionsSettingsModal()"
                    class="text-xs px-3 py-1 rounded"
                    style="background:#7c3aed;color:#fff;border:0;cursor:pointer"
                    title="자동 실행 옵션 세팅!">
              ⚙ 자동
            </button>
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
          </h3>

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
  window.briefingNow = briefingNow;  // v132 즉시 브리핑!
  window._switchProfile = _switchProfile;  // v132 프로필 전환!
  window._setSugFilter = _setSugFilter;  // v132 롱/숏 필터!
  window.renderSuggestions = renderSuggestions;
  window.openSuggestionsSettingsModal = openSuggestionsSettingsModal;
  window.closeSuggestionsSettingsModal = closeSuggestionsSettingsModal;
  window.saveSuggestionsSettings = saveSuggestionsSettings;
  window.openSuggestionAnalysis = openSuggestionAnalysis;  // 🌟 v133c!
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(loadStrategySuggestions, 1200);
    setInterval(loadStrategySuggestions, 30000);  // 30초 polling
  });
}
