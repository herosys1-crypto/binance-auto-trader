/**
 * 거래소 계정 관리 모달 (Phase 3 단계 3o, 2026-05-15).
 *
 * - openAccountsModal / closeAccountsModal : 모달 열기/닫기
 * - renderAccountsModalBody                : 화이트리스트 토글 + 계정 테이블 렌더
 * - toggleWhitelist(enabled)               : 심볼 화이트리스트 DB 영속 토글 (즉시 반영)
 * - updateAccountLimit(accountId)          : 일일 손실 한도 인라인 수정 (prompt 기반)
 * - openCredentialsForm(accountId, isT)    : API 키 회전 + testnet ↔ mainnet 전환
 *
 * 외부 의존 (script-scope 공유):
 *   - api, toast (전역 헬퍼)
 *   - _cmWhitelistInfo, _renderWhitelistHint, _validateCurrentSymbol (cm-* 모듈)
 *   - _globalWhitelistInfo (전역 캐시)
 *   - refreshStrategies (strategies-list.js)
 */

// 2026-05-04 (P): 거래소 계정 관리 모달 — daily_loss_limit_usdt 인라인 수정.
async function openAccountsModal() {
  document.getElementById('accounts-modal').classList.remove('hidden');
  await renderAccountsModalBody();
}

function closeAccountsModal() {
  document.getElementById('accounts-modal').classList.add('hidden');
}

// 2026-06-03 신규: 모달 안에서 신규 계정 등록 폼 직접 — Swagger UI 대체.
// 사장님 다중 계정 (Sub-Account 최대 10개) 운영 + 등록 편의.
function openAddAccountForm() {
  const html = `
    <div id="add-account-form" class="mb-4 p-3 rounded border-2 border-blue-500 bg-slate-800/60">
      <h3 class="text-sm font-bold mb-2 text-blue-300">➕ 신규 거래소 계정 등록</h3>
      <p class="text-xs text-slate-400 mb-3">
        📌 사전 작업 (사장님 Binance):
        ① Sub-Account 생성 → ② API Management 에서 키 발급
        (Read + Enable Futures, IP whitelist <code class="text-yellow-300">159.65.137.250</code>)
      </p>
      <div class="grid grid-cols-1 gap-2">
        <input type="text" id="new-acc-api-key" placeholder="API Key (앞뒤 공백 X)"
          class="px-2 py-1 bg-slate-900 border border-slate-600 rounded text-white text-sm font-mono" />
        <input type="password" id="new-acc-api-secret" placeholder="API Secret"
          class="px-2 py-1 bg-slate-900 border border-slate-600 rounded text-white text-sm font-mono" />
        <div class="flex items-center gap-3">
          <label class="text-xs cursor-pointer flex items-center gap-1">
            <input type="checkbox" id="new-acc-testnet" />
            <span>testnet (보통 OFF)</span>
          </label>
          <label class="text-xs cursor-pointer flex items-center gap-1">
            <input type="checkbox" id="new-acc-hedge" checked />
            <span>Hedge mode (PR #50: 자동 검증)</span>
          </label>
          <label class="text-xs flex items-center gap-1">
            <span>일일 한도(USDT):</span>
            <input type="number" id="new-acc-daily-limit" placeholder="비움=폴백"
              class="w-20 px-1 py-0.5 bg-slate-900 border border-slate-600 rounded text-white text-xs" />
          </label>
        </div>
        <div class="flex gap-2 mt-2">
          <button onclick="submitNewAccount()" class="btn-success btn text-xs">
            ✅ 등록 (자동 검증)
          </button>
          <button onclick="cancelNewAccount()" class="btn-ghost btn text-xs">
            취소
          </button>
        </div>
        <p class="text-xs text-blue-300 mt-1">
          💡 등록 시 자동 검증 (PR #50): API key 유효성 + IP whitelist + Futures 권한 + Hedge mode 일치.
          실패 시 친절 에러로 원인 안내.
        </p>
      </div>
    </div>
  `;
  const body = document.getElementById('accounts-modal-body');
  if (body) body.insertAdjacentHTML('afterbegin', html);
}

function cancelNewAccount() {
  const form = document.getElementById('add-account-form');
  if (form) form.remove();
}

async function submitNewAccount() {
  const apiKey = document.getElementById('new-acc-api-key').value.trim();
  const apiSecret = document.getElementById('new-acc-api-secret').value.trim();
  const isTestnet = document.getElementById('new-acc-testnet').checked;
  const hedgeMode = document.getElementById('new-acc-hedge').checked;
  const dailyLimitRaw = document.getElementById('new-acc-daily-limit').value.trim();
  const dailyLimit = dailyLimitRaw ? Number(dailyLimitRaw) : null;
  if (!apiKey || apiKey.length < 10) { toast('⚠️ API Key 입력 (최소 10자)', 'error'); return; }
  if (!apiSecret || apiSecret.length < 10) { toast('⚠️ API Secret 입력 (최소 10자)', 'error'); return; }
  const body = {
    exchange_name: 'binance',
    market_type: 'usds_m_futures',
    api_key: apiKey,
    api_secret: apiSecret,
    is_testnet: isTestnet,
    hedge_mode_enabled: hedgeMode,
  };
  if (dailyLimit !== null && dailyLimit >= 0) body.daily_loss_limit_usdt = dailyLimit;
  try {
    const res = await api('/exchange-accounts', { method: 'POST', body });
    toast(`✅ 계정 #${res.id} 등록 완료 (자동 검증 + Hedge mode 동기화). 워커들이 15분 이내 자동 감지.`, 'success');
    cancelNewAccount();
    await renderAccountsModalBody();  // 목록 refresh
  } catch (e) {
    toast('등록 실패: ' + e.message, 'error');
  }
}

async function renderAccountsModalBody() {
  const body = document.getElementById('accounts-modal-body');
  // 2026-05-07 사용자 요청: 화이트리스트 운영 토글 (DB 영속, 즉시 적용)
  let whitelistHtml = '';
  try {
    const wl = await api('/admin/settings/whitelist');
    const allowedList = (wl.allowed_symbols || []).join(', ') || '(env 미설정)';
    const checked = wl.enabled ? 'checked' : '';
    const note = wl.env_configured
      ? `허용: <span class="font-mono text-green-300">${allowedList}</span>`
      : `<span class="text-yellow-400">⚠️ env 의 ALLOWED_SYMBOLS_CSV 가 비어있어 토글 켜도 무의미. .env 에 심볼 채운 후 컨테이너 재기동 필요.</span>`;
    whitelistHtml = `
      <div class="mb-4 p-3 rounded border border-slate-700 bg-slate-800/40">
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" id="wl-toggle" ${checked} onchange="toggleWhitelist(this.checked)"
                 class="w-4 h-4 cursor-pointer" />
          <span class="text-sm font-semibold">🔒 심볼 화이트리스트 적용</span>
          <span class="text-xs text-slate-400">— 체크 시 허용 심볼 외 진입 거부</span>
        </label>
        <div class="text-xs mt-1 ml-6">${note}</div>
      </div>`;
  } catch (e) {
    whitelistHtml = `<div class="mb-4 text-xs text-red-400">화이트리스트 상태 조회 실패: ${e.message}</div>`;
  }

  // 2026-06-24 사장님: 손실 한도 강제 청산 (FORCE_SL) — ROI 한도 도달 시 전량 청산 + 종료.
  // 전역 (롱/숏 독립). 롱 기본 ON -10% / 숏 기본 OFF. 기존 SL(-80~90%)과 별개 추가 안전망.
  try {
    const fsl = await api('/admin/settings/force-sl');
    const allowed = fsl.allowed_roi || [5, 10, 15, 20];
    const roiOpts = (cur) => allowed.map(v =>
      `<option value="${v}" ${Number(cur) === Number(v) ? 'selected' : ''}>-${v}%</option>`).join('');
    const sideRow = (side, cfg, emoji, label) => `
      <div class="flex items-center gap-2 mb-1">
        <input type="checkbox" id="fsl-${side}-enabled" ${cfg.enabled ? 'checked' : ''}
               onchange="saveForceSl('${side.toUpperCase()}')" class="w-4 h-4 cursor-pointer" />
        <span class="text-xs w-10">${emoji} ${label}</span>
        <select id="fsl-${side}-roi" onchange="saveForceSl('${side.toUpperCase()}')"
                class="text-xs bg-slate-900 border border-slate-600 rounded px-1 py-0.5">
          ${roiOpts(cfg.roi)}
        </select>
        <span class="text-xs text-slate-400">손실 ROI 도달 시 청산</span>
      </div>`;
    whitelistHtml += `
      <div class="mb-4 p-3 rounded border border-slate-700 bg-slate-800/40">
        <div class="text-sm font-semibold mb-2">🛑 손실 한도 강제 청산
          <span class="text-xs text-slate-400">— ROI 한도 도달 시 전량 자동 청산 + 전략 종료 (재진입 X)</span>
        </div>
        ${sideRow('long', fsl.long, '📈', '롱')}
        ${sideRow('short', fsl.short, '📉', '숏')}
        <div class="text-xs mt-1 text-slate-500">💡 기존 SL(-80~90%)과 별개 추가 안전망 · 아무 단계에서나 발동 · 가격 정보 없으면 청산 안 함.</div>
      </div>`;
  } catch (e) {
    whitelistHtml += `<div class="mb-4 text-xs text-red-400">강제 청산 설정 조회 실패: ${e.message}</div>`;
  }

  try {
    const accounts = await api('/exchange-accounts');
    if (!accounts.length) {
      body.innerHTML = whitelistHtml + `
        <div class="text-center py-8">
          <div class="text-yellow-300 mb-2">⚠️ 등록된 거래소 계정이 없습니다.</div>
          <div class="text-slate-400 text-xs mb-3">
            아래 「➕ 계정 추가」 버튼으로 등록하세요.
          </div>
          <button onclick="openAddAccountForm()" class="btn-success btn text-sm">
            ➕ 계정 추가
          </button>
        </div>`;
      return;
    }
    // 2026-06-03 신규: 각 계정의 balance + 활성 strategy 수 병렬 조회 (사장님 통합 모니터링).
    const balances = await Promise.all(accounts.map(a =>
      api(`/exchange-accounts/${a.id}/balance`).catch(() => null)
    ));
    const rows = accounts.map((a, idx) => {
      const limit = a.daily_loss_limit_usdt;
      const limitText = limit === null || limit === undefined
        ? `<span class="text-slate-400" title="settings.daily_loss_limit_usdt 폴백">global 폴백</span>`
        : Number(limit) === 0
          ? `<span class="text-red-400" title="0 = 한도 비활성">비활성</span>`
          : `<span class="text-green-400">${limit} USDT</span>`;
      const envBadge = a.is_testnet
        ? '<span class="badge badge-yellow">testnet</span>'
        : '<span class="badge badge-red">mainnet</span>';
      const activeBadge = a.is_active
        ? '<span class="badge badge-green">active</span>'
        : '<span class="badge badge-gray">inactive</span>';
      // 2026-06-03 신규: balance 정보 표시 (사장님 통합 모니터링)
      const bal = balances[idx];
      let balText, upnlText, stratText, ratioText;
      if (bal) {
        const wallet = Number(bal.total_wallet_balance || 0);
        const ourAvail = Number(bal.our_available_balance || 0);
        const reserved = Number(bal.reserved_for_strategies || 0);
        const upnl = Number(bal.total_unrealized_pnl || 0);
        const stratCount = Number(bal.active_strategy_count || 0);
        const ratio = Number(bal.margin_ratio_pct || 0);
        const availCls = ourAvail < 0 ? 'text-red-400 font-bold' : 'text-green-300';
        balText = `<span class="${availCls}" title="가용 잔액 = wallet - reserved (5단계 풀 예약 기준)">${ourAvail.toFixed(2)}</span> <span class="text-slate-500">/ ${wallet.toFixed(2)}</span>`;
        const upnlCls = upnl > 0 ? 'text-green-400' : upnl < 0 ? 'text-red-400' : 'text-slate-400';
        upnlText = `<span class="${upnlCls}">${upnl >= 0 ? '+' : ''}${upnl.toFixed(2)}</span>`;
        stratText = `<span class="text-blue-300">${stratCount}건</span> <span class="text-slate-500">(예약 ${reserved.toFixed(0)})</span>`;
        const ratioCls = ratio >= 80 ? 'text-red-400 font-bold' : ratio >= 50 ? 'text-yellow-300' : 'text-slate-400';
        ratioText = `<span class="${ratioCls}">${ratio.toFixed(1)}%</span>`;
      } else {
        balText = '<span class="text-slate-500">조회 실패</span>';
        upnlText = '<span class="text-slate-500">-</span>';
        stratText = '<span class="text-slate-500">-</span>';
        ratioText = '<span class="text-slate-500">-</span>';
      }
      return `
        <tr>
          <td class="text-xs">#${a.id}</td>
          <td class="text-xs">${a.exchange_name}</td>
          <td>${envBadge}</td>
          <td>${activeBadge}</td>
          <td class="text-xs font-mono" title="가용 / wallet (USDT)">${balText}</td>
          <td class="text-xs font-mono">${upnlText}</td>
          <td class="text-xs">${stratText}</td>
          <td class="text-xs">${ratioText}</td>
          <td class="text-xs">${limitText}</td>
          <td class="space-x-1">
            <button class="btn-ghost btn text-xs" style="padding:4px 8px"
                    onclick="updateAccountLimit(${a.id})">✏️ 한도</button>
            <button class="btn-warning btn text-xs" style="padding:4px 8px"
                    onclick="openCredentialsForm(${a.id}, ${a.is_testnet})"
                    title="API 키 회전 + testnet ↔ mainnet 전환">🔑 키 변경</button>
          </td>
        </tr>`;
    }).join('');
    body.innerHTML = whitelistHtml + `
      <div class="mb-2 flex justify-between items-center">
        <span class="text-sm text-slate-300">등록된 계정 ${accounts.length}개 (최대 권장: <strong class="text-yellow-300">10개</strong> — 2vCPU/8GB 안전 한도)</span>
        <button onclick="openAddAccountForm()" class="btn-success btn text-xs">
          ➕ 계정 추가
        </button>
      </div>
      <table class="min-w-full">
        <thead>
          <tr class="text-slate-400 text-xs">
            <th class="text-left p-2">#</th>
            <th class="text-left p-2">거래소</th>
            <th class="text-left p-2">환경</th>
            <th class="text-left p-2">상태</th>
            <th class="text-left p-2" title="가용 잔액 / 전체 wallet (USDT)">잔액 (가용/wallet)</th>
            <th class="text-left p-2" title="미실현 손익 (USDT)">uPnL</th>
            <th class="text-left p-2" title="활성 strategy 수 + 5단계 풀 예약 자본">활성 / 예약</th>
            <th class="text-left p-2" title="마진 비율 (>=80% 청산 위험)">마진 %</th>
            <th class="text-left p-2">일일 손실 한도</th>
            <th class="text-left p-2">액션</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
      <p class="text-xs text-slate-500 mt-2">💡 잔액 조회 = 30초 캐시 (Binance accountInfo). 모달 열 때마다 갱신.</p>`;
  } catch (err) {
    body.innerHTML = whitelistHtml + `<div class="text-red-400 text-sm">계정 조회 실패: ${err.message}</div>`;
  }
}

// 2026-05-07: 화이트리스트 토글 (DB 영속, 즉시 적용)
async function toggleWhitelist(enabled) {
  try {
    const resp = await api('/admin/settings/whitelist', {
      method: 'PATCH',
      body: { enabled: !!enabled },
    });
    const status = resp.enabled ? '✅ 적용' : '⛔ 미적용';
    toast(`화이트리스트 ${status} (즉시 반영)`, 'success');
    // 새 전략 모달의 hint 갱신
    if (typeof _cmWhitelistInfo !== 'undefined') {
      _cmWhitelistInfo = {
        enabled: resp.enabled,
        allowed: new Set((resp.allowed_symbols || []).map(s => s.toUpperCase())),
      };
      if (typeof _renderWhitelistHint === 'function') _renderWhitelistHint();
      if (typeof _validateCurrentSymbol === 'function') _validateCurrentSymbol();
    }
    // 2026-05-08 v3: 전역 캐시 갱신 — 미등재만 위험 표시 정책이라 enforced 불필요
    _globalWhitelistInfo = {
      allowed: new Set((resp.allowed_symbols || []).map(s => s.toUpperCase())),
      envConfigured: resp.allowed_symbols && resp.allowed_symbols.length > 0,
    };
    refreshStrategies();  // 전략 테이블 재렌더 → 새 배지 표시
  } catch (e) {
    toast(`토글 실패: ${e.message}`, 'error');
    // 체크박스 상태 되돌리기 — 다시 렌더
    await renderAccountsModalBody();
  }
}

// 2026-06-24: 손실 한도 강제 청산 설정 저장 (DB 영속, 즉시 적용). side = 'LONG' | 'SHORT'.
async function saveForceSl(side) {
  const key = side.toLowerCase();
  const enabledEl = document.getElementById(`fsl-${key}-enabled`);
  const roiEl = document.getElementById(`fsl-${key}-roi`);
  if (!enabledEl || !roiEl) return;
  const enabled = !!enabledEl.checked;
  const roi = Number(roiEl.value);
  try {
    await api('/admin/settings/force-sl', {
      method: 'PATCH',
      body: { side, enabled, roi },
    });
    const label = side === 'LONG' ? '📈 롱' : '📉 숏';
    toast(`${label} 강제 청산 ${enabled ? `✅ ON (-${roi}%)` : '⛔ OFF'} (즉시 반영)`, 'success');
  } catch (e) {
    toast(`강제 청산 설정 실패: ${e.message}`, 'error');
    await renderAccountsModalBody();  // 상태 되돌리기
  }
}

async function updateAccountLimit(accountId) {
  const input = prompt(
    `💼 계정 #${accountId} 일일 손실 한도 수정\n\n` +
    `USDT 금액 입력:\n` +
    `  • 양수 (예: 100) → 이 계정 전용 한도 (global 무시)\n` +
    `  • 0 → 비활성 (한도 없음, 위험)\n` +
    `  • 비워두면 global 폴백 (.env DAILY_LOSS_LIMIT_USDT 사용)`,
    ""
  );
  if (input === null) return;  // 취소
  let amount;
  if (input.trim() === "") {
    amount = null;  // global 폴백
  } else {
    amount = parseFloat(input);
    if (isNaN(amount) || amount < 0) {
      toast(`잘못된 값: ${input}. 양수 또는 빈값 (global 폴백) 입력하세요.`, 'error');
      return;
    }
  }
  try {
    await api(`/exchange-accounts/${accountId}/daily-loss-limit`, {
      method: 'PATCH',
      body: { daily_loss_limit_usdt: amount },
    });
    toast(`✅ 계정 #${accountId} 한도 갱신 완료`, 'success');
    await renderAccountsModalBody();  // 모달 다시 렌더
  } catch (err) {
    toast(`한도 갱신 실패: ${err.message}`, 'error');
  }
}

// 2026-05-07: API 키 회전 + testnet ↔ mainnet 전환 (사용자 요청).
// 흐름: 새 키/secret + 옵션으로 환경 전환 → 백엔드가 Binance 호출로 검증 → 저장.
// 환경 전환 시 활성 strategy 가 있으면 백엔드가 거부 (포지션 mismatch 방지).
async function openCredentialsForm(accountId, currentIsTestnet) {
  const apiKey = prompt(
    `🔑 계정 #${accountId} 키 변경 (1/3)\n\n` +
    `새 API key 입력 (10~200자).\n` +
    `취소하면 변경 안 됨.`,
    ""
  );
  if (!apiKey || apiKey.trim() === "") return;

  const apiSecret = prompt(
    `🔑 계정 #${accountId} 키 변경 (2/3)\n\n` +
    `새 API secret 입력 (10~200자).`,
    ""
  );
  if (!apiSecret || apiSecret.trim() === "") return;

  const envChoice = prompt(
    `🔑 계정 #${accountId} 키 변경 (3/3) — 환경\n\n` +
    `현재: ${currentIsTestnet ? 'testnet' : 'mainnet'}\n\n` +
    `다음 중 입력:\n` +
    `  • testnet → testnet 으로 (현재 mainnet 이면 전환)\n` +
    `  • mainnet → mainnet 으로 (현재 testnet 이면 전환)\n` +
    `  • 비워두면 환경 유지 (키만 회전)\n\n` +
    `※ 환경 전환은 활성 strategy 가 0건일 때만 가능.`,
    ""
  );
  if (envChoice === null) return;
  const trimmed = envChoice.trim().toLowerCase();
  let isTestnet = null;  // null = 유지
  if (trimmed === "testnet") isTestnet = true;
  else if (trimmed === "mainnet") isTestnet = false;
  else if (trimmed !== "") {
    toast(`잘못된 환경 값: ${envChoice}. testnet / mainnet / 빈값 중 입력.`, 'error');
    return;
  }

  // 최종 확인 — 환경 전환 시 강한 경고
  const willChangeEnv = isTestnet !== null && isTestnet !== currentIsTestnet;
  const confirmMsg = willChangeEnv
    ? `⚠️ 환경 전환: ${currentIsTestnet ? 'testnet' : 'mainnet'} → ${isTestnet ? 'testnet' : 'mainnet'}\n\n` +
      `백엔드가 활성 strategy 0건 확인 + 새 키로 Binance 인증 검증 후 저장합니다.\n\n진행?`
    : `🔑 키 회전 (환경 ${currentIsTestnet ? 'testnet' : 'mainnet'} 유지)\n\n진행?`;
  if (!confirm(confirmMsg)) return;

  try {
    await api(`/exchange-accounts/${accountId}/credentials`, {
      method: 'PATCH',
      body: {
        api_key: apiKey,
        api_secret: apiSecret,
        is_testnet: isTestnet,
      },
    });
    toast(`✅ 계정 #${accountId} 키 ${willChangeEnv ? '변경 + 환경 전환' : '회전'} 완료. 텔레그램 audit 발송됨.`, 'success');
    await renderAccountsModalBody();
  } catch (err) {
    toast(`키 변경 실패: ${err.message}`, 'error');
  }
}
