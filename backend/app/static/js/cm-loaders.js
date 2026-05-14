/**
 * Create-Modal — accounts/templates/symbols 목록 loader (Phase 3 단계 3c, 2026-05-14).
 *
 * 모달 진입 시 호출되는 데이터 fetch + 라디오/datalist 렌더 함수들.
 *
 * 함수:
 *   - loadCmAccounts()           : /exchange-accounts → 라디오 목록
 *   - loadCmTemplates()          : /admin/strategy-templates (active 만) → 라디오 목록
 *   - loadCmSymbols()            : /symbols + /symbols/whitelist-info → datalist + 화이트리스트 캐시
 *   - _renderWhitelistHint()      : 모달 상단 화이트리스트 안내
 *   - _validateCurrentSymbol()    : 현재 심볼 입력 화이트리스트 즉시 검증 (시각 표시)
 *
 * 외부 의존성 (script-scope 공유):
 *   - cmState (mutable global)
 *   - updateCmSubmit / setCmSide / loadCmMarketInfo
 *   - api / toast (api.js)
 *   - escapeHtml / fmtNum (helpers.js)
 *
 * State (이 모듈 소유):
 *   - _cmWhitelistInfo : { enabled, allowed: Set<string> }
 */

async function loadCmAccounts() {
  try {
    const data = await api('/exchange-accounts');
    const el = document.getElementById('cm-accounts');
    if (!data.length) {
      el.innerHTML = '<p class="text-red-400 text-sm">⚠️ 등록된 거래소 계정이 없습니다. 먼저 등록하세요.</p>';
      return;
    }
    el.innerHTML = data.map((a, idx) => `
      <label class="flex items-center gap-2 p-2 rounded cursor-pointer hover:bg-slate-700">
        <input type="radio" name="cm-account" value="${a.id}" ${idx===0?'checked':''} onchange="cmState.accountId=${a.id}; updateCmSubmit()" />
        <span class="font-mono">#${a.id}</span>
        <span>${a.exchange_name}/${a.market_type}</span>
        ${a.is_testnet ? '<span class="badge badge-yellow">testnet</span>' : '<span class="badge badge-red">mainnet</span>'}
        ${a.hedge_mode_enabled ? '<span class="badge badge-blue">hedge</span>' : ''}
      </label>
    `).join('');
    cmState.accountId = data[0].id;
    updateCmSubmit();
  } catch (e) { toast('계정 조회 실패: '+e.message, 'error'); }
}

async function loadCmTemplates() {
  try {
    const data = await api('/admin/strategy-templates');
    const el = document.getElementById('cm-templates');
    const active = data.filter(t => t.is_active);
    if (!active.length) {
      el.innerHTML = '<p class="text-red-400 text-sm">⚠️ 활성 템플릿이 없습니다.</p>';
      return;
    }
    el.innerHTML = active.map(t => {
      const sc = t.stages_config || {};
      const stages = (sc.capitals || []).join(' / ');
      // 2026-05-12 fix (사용자 보고 「성공인데 전략 없음」): template radio 선택 시
      // cmState.side 도 template 의 side 로 자동 sync — 이전엔 templateId 만 set 되고
      // side 는 default 'SHORT' 그대로라, LONG 템플릿 선택 시 side 불일치로 실패 가능.
      return `<label class="flex items-center gap-2 p-2 rounded cursor-pointer hover:bg-slate-700">
        <input type="radio" name="cm-template" value="${t.id}" onchange="cmState.templateId=${t.id}; setCmSide('${t.side}'); updateCmSubmit()" />
        <span class="font-mono text-blue-300">#${t.id}</span>
        <span class="font-semibold">${escapeHtml(t.name)}</span>
        <span class="badge ${t.side==='SHORT'?'badge-red':'badge-green'}">${t.side}</span>
        <span class="text-xs text-slate-400">${t.leverage}x · ${fmtNum(t.total_capital)} USDT · ${stages}</span>
      </label>`;
    }).join('');
  } catch (e) { toast('템플릿 조회 실패: '+e.message, 'error'); }
}

// 2026-05-07: 화이트리스트 캐시 — 심볼 입력 시 즉시 검증.
let _cmWhitelistInfo = { enabled: false, allowed: new Set() };

async function loadCmSymbols() {
  // 화이트리스트 정보 먼저 로드 (비차단)
  api('/symbols/whitelist-info').then(info => {
    _cmWhitelistInfo = {
      enabled: !!info.enabled,
      allowed: new Set((info.allowed_symbols || []).map(s => s.toUpperCase())),
    };
    _renderWhitelistHint();
    _validateCurrentSymbol();
  }).catch(() => { /* 비활성 시 무시 */ });

  try {
    // limit 200 → 1000 으로 증가. testnet 에 586+ TRADING 심볼이 있어 200 제한 시
    // 알파벳 순으로 SOL/XRP/DOGE 등 인기 코인이 자동완성에서 누락되는 문제 해결.
    const data = await api('/symbols?only_trading=true&limit=1000');
    const list = document.getElementById('cm-symbol-list');
    // 2026-05-07: datalist option 의 label 에 화이트리스트 상태 표시
    // (브라우저별 렌더링 차이 있지만 Chrome/Firefox/Edge 에서 자동완성 시 표시됨).
    list.innerHTML = data.map(s => {
      const sym = s.symbol;
      const isAllowed = !_cmWhitelistInfo.enabled || _cmWhitelistInfo.allowed.has(sym.toUpperCase());
      const label = _cmWhitelistInfo.enabled
        ? (isAllowed ? `${sym} ✓ 허용` : `${sym} 🚫 화이트리스트 외`)
        : sym;
      return `<option value="${sym}" label="${label}"></option>`;
    }).join('');
  } catch { /* symbols 없으면 무시 — 사용자 직접 입력 가능 */ }
  // 심볼 입력 변경 시 시세 자동 로드 + 화이트리스트 검증 (debounce)
  const symEl = document.getElementById('cm-symbol');
  if (!symEl.dataset.bound) {
    let timer = null;
    const trigger = () => {
      _validateCurrentSymbol();
      clearTimeout(timer);
      timer = setTimeout(() => loadCmMarketInfo(), 400);
    };
    symEl.addEventListener('input', trigger);
    symEl.addEventListener('change', trigger);
    symEl.dataset.bound = '1';
  }
  // 거래소 계정 변경 시 testnet 여부 변경 → 시세 다시
  loadCmMarketInfo();
}

// 2026-05-07: 모달 상단의 화이트리스트 안내 표시.
function _renderWhitelistHint() {
  const el = document.getElementById('cm-symbol-whitelist-hint');
  if (!el) return;
  if (!_cmWhitelistInfo.enabled) {
    el.classList.add('hidden');
    return;
  }
  const list = [..._cmWhitelistInfo.allowed].join(', ');
  el.innerHTML = `🔒 <span class="text-yellow-400">화이트리스트 운영</span> — 허용: <span class="font-mono text-green-300">${list}</span>`;
  el.classList.remove('hidden');
}

// 2026-05-07: 현재 입력된 심볼이 화이트리스트 안인지 즉시 시각 표시.
// 거부 심볼이면 빨간색 + 입력 박스 ring red. 「전략 시작」 버튼 누르기 전에 사용자가 알 수 있게.
function _validateCurrentSymbol() {
  const inp = document.getElementById('cm-symbol');
  const status = document.getElementById('cm-symbol-status');
  if (!inp || !status) return;
  const sym = (inp.value || '').toUpperCase().trim();
  if (!sym || !_cmWhitelistInfo.enabled) {
    status.classList.add('hidden');
    inp.classList.remove('ring-2', 'ring-red-400', 'ring-green-400');
    return;
  }
  const isAllowed = _cmWhitelistInfo.allowed.has(sym);
  if (isAllowed) {
    status.innerHTML = `<span class="text-green-400">✓ ${sym} 진입 허용</span>`;
    inp.classList.remove('ring-2', 'ring-red-400');
    inp.classList.add('ring-2', 'ring-green-400');
  } else {
    status.innerHTML = `<span class="text-red-400">🚫 ${sym} 화이트리스트 외 — 진입 거부됨</span>`;
    inp.classList.remove('ring-2', 'ring-green-400');
    inp.classList.add('ring-2', 'ring-red-400');
  }
  status.classList.remove('hidden');
}
