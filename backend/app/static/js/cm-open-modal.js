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
  const _modalEl = document.getElementById('create-modal');
  _modalEl.classList.remove('hidden');
  document.getElementById('cm-preview').classList.add('hidden');
  document.getElementById('cm-submit').disabled = true;
  // 🚨 2026-06-22 사장님 critical v3: 시간 의존 silent bug 영구 fix!
  // 사장님 보고: "처음에는 괜찮은데 시간이 지나면 = silent bug!"
  // 원인 v3: 옛 setTimeout 50ms = 옛 scrollTop 누적 + render 안 끝남 + body overflow 누적!
  // fix v3: requestAnimationFrame x 3 (= 정확 render 후!) + body overflow 복원 + window.scrollTo!
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (_modalEl) {
          const _inner = _modalEl.querySelector(':scope > div');
          if (_inner) {
            _inner.scrollTop = 0;
            _inner.scrollTo({top: 0, left: 0, behavior: 'instant'});
          }
          _modalEl.scrollTop = 0;
          _modalEl.scrollTo({top: 0, left: 0, behavior: 'instant'});
        }
        // body 도 = 위에서!
        window.scrollTo({top: 0, left: 0, behavior: 'instant'});
        // body overflow = 정상 복원 (= 옛 hidden 누적 차단!)
        if (document.body.style.overflow === 'hidden') {
          document.body.style.overflow = '';
        }
      });
    });
  });
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
      `🛡 「↻ 설정만 수정 (시작가 유지)」 — 옛 시작가 + 옛 진입 단계 유지! 신 capital/trigger/TP/SL 만 즉시 갱신. 「💲 현재가」 클릭 무시! (= 진행 중 strategy 수정 용도!)\n` +
      `🌟 「🔄 종료 후 새로 시작 (신 시작가)」 — 옛 strategy 종료 + 미체결 취소 + 1단계부터 신 시작! 「💲 현재가」 클릭 시 = 신 시작가 적용! 1단계 = 옛 평단 보존 (v40 사상!)\n` +
      `💡 사장님 critical: 「💲 현재가」 클릭 = 「🔄 종료 후 새로 시작」 클릭 시만 적용!`;
    title.textContent = `✏️ 전략 #${editStrategyId} 수정`;
    submit.textContent = '🔄 종료 후 새로 시작 (신 시작가)';
    if (inplaceBtn) inplaceBtn.classList.remove('hidden');  // in-place 버튼 노출
    await loadPrevBlueprint(editStrategyId, /*silent=*/true);
  } else {
    banner.classList.add('hidden');
    title.textContent = '➕ 새 전략 시작';
    submit.textContent = '🚀 전략 시작';
    if (inplaceBtn) inplaceBtn.classList.add('hidden');  // 신규 모드엔 숨김
    // 🌟 2026-06-19 사장님 critical v2: loadPrevBlueprint 활용 (= 옛 stages_config 정확!)
    // 옛 silent bug: template_capitals 필드 X = 자동 채움 작동 X!
    // 신 fix: loadPrevBlueprint(id, silent=true) = stages_config + tp/sl 모두 채움!
    //         + 그 후 = symbol + start_price = 비우기 (사장님 깨끗 입력!)
    try {
      const _prev = await api('/strategies?include_archived=false');
      if (_prev && _prev.length > 0) {
        const _last = _prev.sort((a, b) => b.id - a.id)[0];
        // loadPrevBlueprint = stages_config + capitals + triggers + tp/sl + leverage + side 모두 자동!
        if (typeof loadPrevBlueprint === 'function' && _last.id) {
          await loadPrevBlueprint(_last.id, /*silent=*/true);
          // 🛡 그 후 = 사장님 critical: 심볼 + 시작가 = 빈칸! (사장님 신 strategy = 깨끗 시작!)
          const _symEl = document.getElementById('cm-symbol');
          if (_symEl) _symEl.value = '';
          const _startEl = document.getElementById('cm-start-price');
          if (_startEl) _startEl.value = '';
          // cmState 도 리셋 (= 신 strategy 모드!)
          if (cmState) {
            cmState.editingStrategyId = null;
            cmState.editingStrategyBp = null;
            cmState.mode = 'direct';
          }
        } else {
          // fallback: 심볼만 비우기
          const _symEl = document.getElementById('cm-symbol');
          if (_symEl) _symEl.value = '';
        }
      } else {
        // 옛 strategy 없음 = 그냥 심볼만 비움
        const _symEl = document.getElementById('cm-symbol');
        if (_symEl) _symEl.value = '';
      }
    } catch (_e) {
      console.warn('[new-strategy] 이전 설정 자동 채움 실패 (= 사장님 빈 모달로 시작):', _e);
      // 실패 시도 = 심볼 비움!
      const _symEl = document.getElementById('cm-symbol');
      if (_symEl) _symEl.value = '';
    }
  }
  // 2026-06-03 (사장님 사상 정확 적용): SL = 투자금 대비 손실 % (레버리지 무관)
  _attachSlLossPreview();
  // 🌟 2026-06-09 사장님 신 기능: 최근 전략 5개 빠른 선택 자동 로드
  if (typeof loadRecentStrategiesQuick === 'function') {
    loadRecentStrategiesQuick();
  }
}

// 🌟 2026-06-19 사장님 요청: 저장된 전략 (= 사용자 정의 template) 6개 (= 2줄!)
// 사장님 명시: "최근 전략이 아니라 저장된 전략을 3개씩 2줄로 6개"
// = 사용자 정의 template (_quick_ 외) 최근 6개 + 1 클릭 신 strategy!
async function loadRecentStrategiesQuick() {
  const container = document.getElementById('cm-recent-strategies-list');
  if (!container) return;
  try {
    // 사용자 정의 template (= 활성 + _quick_ 외) 조회!
    const all = await api('/admin/strategy-templates');
    if (!all || all.length === 0) {
      container.innerHTML = '<span class="text-slate-500">저장된 전략 없음 (= 「📋 템플릿으로 저장」 으로 추가!)</span>';
      return;
    }
    // _quick_* 제외 + 활성 + 최근 6개
    const userTpls = all
      .filter(t => t.is_active && !String(t.name || '').startsWith('_quick_'))
      .sort((a, b) => b.id - a.id)
      .slice(0, 6);
    if (userTpls.length === 0) {
      container.innerHTML = '<span class="text-slate-500">저장된 전략 없음 (= 「📋 템플릿으로 저장」 으로 추가!)</span>';
      return;
    }
    // grid-cols-3 = 자동 2줄!
    container.className = 'grid grid-cols-3 gap-1';
    container.innerHTML = userTpls.map(t => {
      const sideColor = t.side === 'SHORT' ? 'text-red-400' : 'text-green-400';
      const sideIcon = t.side === 'SHORT' ? '📉' : '📈';
      const name = (t.name || '').substring(0, 18);
      const stagesCount = (t.stages_config?.capitals || []).filter(c => c && Number(c) > 0).length || 0;
      return `<button onclick="if(typeof startStrategyFromTemplate==='function') startStrategyFromTemplate(${t.id})"
        class="px-2 py-1 bg-slate-800 hover:bg-slate-700 border border-slate-600 rounded text-xs"
        style="min-width:0"
        title="📋 ${t.name} (${t.side} ${t.leverage}x, ${stagesCount}단계) — 클릭 = 1 클릭 신 전략 시작!">
        <span class="${sideColor}">${sideIcon}</span>
        <span class="font-semibold text-blue-300">${name}</span>
        <span class="text-slate-400">${t.leverage}x</span>
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
