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
      `「↻ 설정만 수정」 — 포지션/단계 유지, TP/SL만 즉시 갱신 (거래소 호출 없음). 시작가 무시.\n` +
      `「🔄 종료 후 새로 시작」 — 미체결 주문 취소 + 1단계부터 새 전략 시작.\n` +
      `🆕 2026-06-03: 시작가 자동으로 현재가 적용 (옛 가격 미사용) → 트리거가 + 평단 + 청산가 모두 현재가 기준 재계산.`;
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
  // 2026-06-03 (사장님 사상 정확 적용): SL = 투자금 대비 손실 % (레버리지 무관)
  _attachSlLossPreview();
  // 🌟 2026-06-09 사장님 신 기능: 최근 전략 5개 빠른 선택 자동 로드
  if (typeof loadRecentStrategiesQuick === 'function') {
    loadRecentStrategiesQuick();
  }
}

// 🌟 2026-06-09 사장님 신 기능: 최근 전략 5개 빠른 선택 (1 클릭 자동 로드)
async function loadRecentStrategiesQuick() {
  const container = document.getElementById('cm-recent-strategies-list');
  if (!container) return;
  try {
    const all = await api('/strategies?include_archived=false');
    if (!all || all.length === 0) {
      container.innerHTML = '<span class="text-slate-500">최근 전략 없음</span>';
      return;
    }
    // 최근 5개 (= ID 내림차순)
    const recent = all.sort((a, b) => b.id - a.id).slice(0, 5);
    container.innerHTML = recent.map(s => {
      const sideColor = s.side === 'SHORT' ? 'text-red-400' : 'text-green-400';
      const sideIcon = s.side === 'SHORT' ? '📉' : '📈';
      return `<button onclick="loadPrevBlueprint(${s.id})"
        class="px-2 py-1 bg-slate-800 hover:bg-slate-700 border border-slate-600 rounded text-xs"
        title="#${s.id} ${s.symbol} ${s.side} ${s.leverage}x — 클릭 = 자동 로드">
        <span class="${sideColor}">${sideIcon}</span>
        <span class="font-mono text-blue-300">#${s.id}</span>
        <span class="font-semibold">${s.symbol}</span>
        <span class="text-slate-400">${s.leverage}x</span>
      </button>`;
    }).join('');
  } catch (e) {
    container.innerHTML = `<span class="text-red-400">조회 실패: ${e.message || e}</span>`;
  }
}

// SL preview — 자본 + sl% 입력 시 즉시 USDT 손실 계산 표시 (레버리지 무관).
// 2026-06-03 사장님 명확한 사상:
//   "투자금에 -80%일때 실행되어야해 레버리지 와 상관없이
//    증거금과 포지션추가를 했을때 전체금액에 손실이 -80% 일때 발동.
//    리스크가 투자금액의 80%가 없어지는거야"
function _attachSlLossPreview() {
  const slInp = document.getElementById('cm-sl-pct');
  const lvInp = document.getElementById('cm-leverage');  // 표시용 — 계산엔 사용 X
  if (!slInp) return;
  const recompute = () => {
    const previewEl = document.getElementById('cm-sl-loss-preview');
    if (!previewEl) return;
    const sl = Number(slInp.value || 0);
    const lev = Number(lvInp ? lvInp.value || 1 : 1) || 1;
    // 모든 capital 입력 합
    let totalCap = 0;
    for (let i = 1; i <= 10; i++) {
      const c = document.getElementById('cm-cap-' + i);
      if (c && c.value) totalCap += Number(c.value || 0);
    }
    if (sl <= 0 || totalCap <= 0) {
      previewEl.textContent = '';
      return;
    }
    // 사장님 사상 (레버리지 무관): 투자금 × sl_pct / 100 = 손실 한도
    const usdtLoss = totalCap * sl / 100;
    previewEl.textContent =
      `💰 예상 손실: 투자금 ${totalCap.toFixed(2)} × ${sl}% = ` +
      `약 ${usdtLoss.toFixed(2)} USDT 도달 시 전량 청산 ` +
      `(레버리지 ${lev}x 무관 — 자본 기준)`;
  };
  // 입력 변경 시마다 recompute (한 번만 등록)
  if (!slInp.dataset.previewBound) {
    slInp.addEventListener('input', recompute);
    slInp.dataset.previewBound = '1';
  }
  if (!lvInp.dataset.previewBound) {
    lvInp.addEventListener('input', recompute);
    lvInp.dataset.previewBound = '1';
  }
  // capital 입력들도 binding
  for (let i = 1; i <= 10; i++) {
    const c = document.getElementById('cm-cap-' + i);
    if (c && !c.dataset.slPreviewBound) {
      c.addEventListener('input', recompute);
      c.dataset.slPreviewBound = '1';
    }
  }
  recompute();
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
