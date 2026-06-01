/**
 * Create-Modal — cmState + open / edit / restart entrypoints (Phase 3 단계 3i, 2026-05-14).
 *
 * create-modal 의 root state 와 진입점 함수들. 다른 cm-*.js 모듈이 cmState 를 모두 참조.
 *
 * State (script-scope global):
 *   - cmState : create-modal 의 모든 mutable state
 *     { accountId, side, templateId, mode ('direct'|'template'|'prev'),
 *       capitals[10], preview, editingStrategyId,
 *       _balanceInsufficient, _liquidationRisk, _duplicateActive,
 *       _directInputs, _directTpsl }
 *
 * 함수:
 *   - openCreateModal(editStrategyId) : 모달 표시 + 모든 form 초기화 + 데이터 로드
 *   - editStrategy(id)                : confirm + openCreateModal(id)
 *   - restartStrategy(id)              : 종료 strategy 재진입 (확인 메시지만 다름)
 *
 * 외부 의존성 (script-scope 공유 — 모두 다른 cm-*.js 또는 index.html 정의):
 *   - buildCapitalsGrid (cm-capitals-grid.js)
 *   - cmLeverageManuallyEdited / setCmSide / setCmMode (cm-state-helpers.js)
 *   - loadCmAccounts / loadCmTemplates / loadCmSymbols (cm-loaders.js)
 *   - loadPrevBlueprint (cm-prev-blueprint.js)
 *
 * Phase 3 create-modal 분리 완료 (3a~3i).
 */

// ==================== 신규 전략 모달 ====================
let cmState = {
  accountId: null,
  side: 'SHORT',
  templateId: null,
  mode: 'direct',  // 'direct' | 'template'
  capitals: ['', '', '', '', '', '', '', '', '', ''],  // 1~10단계
  preview: null,
};

async function openCreateModal(editStrategyId) {
  document.getElementById('create-modal').classList.remove('hidden');
  document.getElementById('cm-preview').classList.add('hidden');
  document.getElementById('cm-submit').disabled = true;
  cmState = { accountId: null, side: 'SHORT', templateId: null, mode: 'direct',
              capitals: ['', '', '', '', '', '', '', '', '', ''], preview: null,
              editingStrategyId: editStrategyId || null };
  buildCapitalsGrid();  // 트리거 % 는 기본값 (2~4=10, 5~9=20) pre-fill 된 상태로 생성됨
  // capital 만 초기화 (트리거 기본값은 유지)
  for (let i = 1; i <= 10; i++) {
    const cap = document.getElementById('cm-cap-' + i); if (cap) cap.value = '';
  }
  // 기본 TP/SL — 2026-05-06 (사용자 요청): 10단계 익절 점진적 분할 (5% 간격)
  // TP1 +10% / 25%   TP2 +15% / 25%   TP3 +20% / 25%   TP4 +25% / 25%   TP5 +30% / 25%
  // TP6 +35% / 25%   TP7 +40% / 25%   TP8 +45% / 25%   TP9 +50% / 25%   TP10 +55% / 100%
  // 각 ratio 는 「잔량의 N%」 (orchestrator close_ratio 의미). TP10 = 마지막 활성, 잔량 100%.
  // 손절 -50% (총 자본 대비) + 트레일링: 피크 ≥ +5% 후 -5% 회귀 시 잔량 100%.
  const _tpDefaults = {
    1: ['10', '25'], 2: ['15', '25'], 3: ['20', '25'], 4: ['25', '25'], 5: ['30', '25'],
    6: ['35', '25'], 7: ['40', '25'], 8: ['45', '25'], 9: ['50', '25'], 10: ['55', '100'],
  };
  for (const [n, [pct, qty]] of Object.entries(_tpDefaults)) {
    const pctEl = document.getElementById(`cm-tp${n}-pct`);
    const qtyEl = document.getElementById(`cm-tp${n}-qty`);
    if (pctEl) pctEl.value = pct;
    if (qtyEl) qtyEl.value = qty;
  }
  document.getElementById('cm-sl-pct').value = '80';
  document.getElementById('cm-start-price').value = '';
  // UX #18: 레버리지 입력 + 수동수정 플래그 초기화 (모달 열 때마다)
  cmLeverageManuallyEdited = false;
  const _lvInit = document.getElementById('cm-leverage');
  if (_lvInit) _lvInit.value = 2;  // SHORT 기본값 (다음 setCmSide 가 다시 적용)
  await Promise.all([loadCmAccounts(), loadCmTemplates(), loadCmSymbols()]);
  setCmSide('SHORT');
  setCmMode('direct');
  // 수정 모드면 배너 표시 + blueprint 자동 로드
  const banner = document.getElementById('cm-edit-banner');
  const title = document.getElementById('cm-title');
  const submit = document.getElementById('cm-submit');
  const inplaceBtn = document.getElementById('cm-submit-inplace');
  if (editStrategyId) {
    banner.classList.remove('hidden');
    document.getElementById('cm-edit-banner-detail').textContent =
      `「↻ 설정만 수정」 — 포지션/단계 유지, TP/SL만 즉시 갱신 (거래소 호출 없음).` +
      `\n「🔄 종료 후 새로 시작」 — 미체결 주문 취소 + 1단계부터 새 전략 시작.`;
    title.textContent = `✏️ 전략 #${editStrategyId} 수정`;
    submit.textContent = '🔄 종료 후 새로 시작';
    if (inplaceBtn) inplaceBtn.classList.remove('hidden');  // in-place 버튼 노출
    await loadPrevBlueprint(editStrategyId, /*silent=*/true);
  } else {
    banner.classList.add('hidden');
    title.textContent = '➕ 새 전략 시작';
    submit.textContent = '🚀 전략 시작';
    if (inplaceBtn) inplaceBtn.classList.add('hidden');  // 신규 모드엔 숨김
  }
  // Phase D (2026-06-01 사장님 사상): 실시간 가용 자본 표시 시작.
  _startWalletInfoLoop();
}

async function editStrategy(id) {
  if (!confirm(`전략 #${id} 의 설정을 수정하시겠어요?\n\n- 기존 전략의 미체결 주문은 모두 취소됩니다.\n- 이미 체결된 포지션은 그대로 유지됩니다.\n- 새 설정으로 새 전략이 시작됩니다.`)) return;
  await openCreateModal(id);
}

// 2026-05-04 v2 (재진입 UX): 종료된 전략 행에서 「🔄 다시 시작」 클릭 시 호출.
// 이전엔 「🟢 새 전략 시작」 모달 → "이전 전략 불러오기" 탭 → 선택 — 3 단계.
// editStrategy 와 다른 점: 정리할 게 없으므로 "기존 전략 종료" 안내 빠짐.
async function restartStrategy(id) {
  if (!confirm(`전략 #${id} 의 설정으로 새 전략을 시작합니다.\n\n- 이 종료된 전략은 그대로 보존됩니다 (감사 로그).\n- 같은 심볼/방향/단계 설정으로 새 strategy 가 생성됩니다.\n- 모달에서 시작가/자본 등을 조정한 후 시작 가능합니다.`)) return;
  await openCreateModal(id);
}

// ==================== Phase D (2026-06-01 사장님 핵심 사상) ====================
// 신규 전략 모달의 실시간 가용 자본 표시.
// 1.5초마다 fetch /exchange-accounts/{id}/balance + 사용자 입력 자본 합 비교.
// 입력 자본 > 가용 시 빨간 경고 (Phase A 백엔드 가드가 어차피 차단할 거니까 미리 안내).
// 모달이 열려있을 때만 의미 — accountId null 이면 fetch skip.
async function _updateWalletInfoDisplay() {
  const el = document.getElementById('cm-wallet-info');
  if (!el) return;  // 모달 닫혀있음
  if (!cmState.accountId) {
    el.innerHTML = '💰 계정 선택 후 가용 자본 표시됩니다.';
    return;
  }
  try {
    const data = await api(`/exchange-accounts/${cmState.accountId}/balance`);
    const wallet = Number(data.total_wallet_balance || 0);
    const reserved = Number(data.reserved_for_strategies || 0);
    const ourAvail = Number(data.our_available_balance || 0);
    const stratCount = Number(data.active_strategy_count || 0);

    // 사용자 입력 자본 합산 (1~10단계)
    let inputTotal = 0;
    for (let i = 1; i <= 10; i++) {
      const inp = document.getElementById('cm-cap-' + i);
      if (inp && inp.value) inputTotal += Number(inp.value) || 0;
    }

    const fmt = (n) => Number(n).toLocaleString('en-US', {maximumFractionDigits: 2});
    let html = `💰 가용 자본: <b>${fmt(ourAvail)} USDT</b> &nbsp;(wallet ${fmt(wallet)} − 예약 ${fmt(reserved)} [${stratCount}건])`;
    let isInsufficient = false;
    if (inputTotal > 0) {
      const after = ourAvail - inputTotal;
      const sign = after >= 0 ? '+' : '';
      const color = after >= 0 ? 'text-emerald-400' : 'text-red-400';
      html += `<br>📊 신규 입력 ${fmt(inputTotal)} USDT → 진입 후 잔여 <span class="${color}"><b>${sign}${fmt(after)} USDT</b></span>`;
      if (after < 0) {
        html += ` <b class="text-red-400">⚠️ Phase A 가드 차단 (잔액 기반 운영)</b>`;
        isInsufficient = true;
      }
    }
    el.innerHTML = html;
    el.className = `text-xs p-2 rounded mt-2 ${isInsufficient ? 'bg-red-900/30 border border-red-500 text-red-200' : 'bg-slate-800 border border-slate-700 text-slate-300'}`;
  } catch (e) {
    // API 실패 — 표시 유지 (사용자 영향 X)
  }
}

let _walletInfoTimer = null;
function _startWalletInfoLoop() {
  if (_walletInfoTimer) return;  // 중복 방지
  _updateWalletInfoDisplay();
  _walletInfoTimer = setInterval(_updateWalletInfoDisplay, 1500);
}
// 모달 닫을 때 stop 은 안 함 — fetch 가 accountId null 시 skip 이라 무해. (간단함 우선)
