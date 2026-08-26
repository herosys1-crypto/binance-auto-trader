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

// ==================== 신 「차트 OBV 자동」 전략 모달 (v130!) ====================
// 🌟 2026-08-06 사장님 요구: 신 시스템 = 2개 페이지 (구/OBV)
// spec: docs/CHART_REENTRY_STRATEGY_SPEC.md
// - 1단계 = 사장님 시작가 진입 (구 시스템 동일!)
// - 2~N단계 = 4H OBV 첫 하락 봉 + 15m/1h 확인 + 10% 가격 = 자동 재진입!
// - N+ = 사장님 수동 관리 (구 시스템 동일!)
// - TP/SL = 구 시스템 그대로!
//
// 구현: 기존 openCreateModal() 재사용 + trigger_mode='OBV_REVERSE' flag!
async function openCreateChartObvModal() {
  // 기존 모달 오픈
  await openCreateModal();
  // 🚨 v130 CRITICAL fix (2026-08-06): OBV 모드 = 「직접 입력」 강제!
  //   옛 silent bug: template 모드 = 옛 template 재사용 = trigger_mode=PRICE_DOWN_PCT!
  //   = 사장님 OBV 원했는데 = 「➕ 기존」 저장!
  //   fix: mode='direct' 강제 + template 선택 무효!
  cmState._triggerMode = 'OBV_REVERSE';
  cmState.mode = 'direct';  // 강제!
  cmState.templateId = null;  // template 선택 무효화!
  // UI = direct 라디오 강제 선택 (있으면)
  const directRadio = document.querySelector('input[name="cm-mode"][value="direct"]');
  if (directRadio) directRadio.checked = true;
  // template 선택 UI = 숨김 or 비활성 (있으면)
  const tplSelectEl = document.getElementById('cm-template-select');
  if (tplSelectEl) tplSelectEl.disabled = true;
  // 모달 타이틀 변경 = 사장님 명확!
  const titleEl = document.getElementById('cm-title');
  if (titleEl) {
    titleEl.textContent = '📊 새 전략 (OBV 자동 재진입!) — 직접 입력 필수!';
    titleEl.style.color = '#a78bfa';  // 보라 = 신 모드 시각!
  }
  // 배너 = OBV 설명 + direct 강제 안내!
  const bannerEl = document.getElementById('cm-edit-banner-detail');
  if (bannerEl) {
    // 🎯 Fix 173 (2026-08-27 사장님): 배너가 옛 로직을 설명하고 있었다.
    //   옛 문구 "4H OBV 첫 하락 + 15m/1h 확인 + 10% 가격 이동" =
    //   check_obv_reverse_signal 의 3중 AND. SHORT 전용이라 LONG 은 사실상 발동 안 함.
    //   신: 자동 진입 워커와 **같은 게이트**를 쓴다 (stage_entry_signal).
    bannerEl.innerHTML =
      '<b style="color:#a78bfa">📊 새 「OBV 자동 재진입」 모드 — 운영 진입 로직 적용!</b><br>' +
      '<b style="color:#fbbf24">⚠️ 직접 입력 필수!</b> (저장된 template 사용 X = 신 template 자동 생성!)<br>' +
      '• 1단계 = 사장님 시작가 진입 (기존과 동일!)<br>' +
      '• <b style="color:#34d399">2~N단계 = 트리거 % 를 안 씁니다.</b> ' +
      '지금 자동매매가 신규 진입을 판단할 때 쓰는 그 게이트를 그대로 통과해야 진입합니다:<br>' +
      '&nbsp;&nbsp;① OBV 게이트 (4H 세력 방향) ② 양방향 실패 차단 ' +
      '③ 급등/급락 regime (숏) ④ <b>15분 정점·저점 확인</b><br>' +
      '&nbsp;&nbsp;<span style="color:#94a3b8">④ = 「한번 올랐다 내려오길 2~3번 반복 + ' +
      'RSI/MACD/CCI 중 2개 이상 꺾임」 (사장님 사상)</span><br>' +
      '• <b style="color:#34d399">단계별 금액 = 입력하신 금액 그대로</b> 들어갑니다 ' +
      '(발주 시점 가격으로 수량만 재계산).<br>' +
      '• 진입을 안 하면 <b>왜 안 했는지</b> 사유가 기록됩니다 (전략 카드 / 진단 화면).<br>' +
      '• 손절/TP = 기존 로직 그대로! (사장님 옵션 우선!) • N+ 단계 = 수동 관리!';
    bannerEl.style.borderLeft = '3px solid #a78bfa';
    bannerEl.style.paddingLeft = '8px';
  }
  const bannerParent = document.getElementById('cm-edit-banner');
  if (bannerParent) bannerParent.classList.remove('hidden');

  // 🌟 v130 (2026-08-08): 신 OBV 자동 세팅!
  //   - 레버리지 = 2x (사장님 재확정 = 모두 2x!)
  //   - TP1/2/3/4 qty = 10/15/20/25 (사장님 진짜 요구!)
  setTimeout(() => {
    // 🌟 2026-08-11 v132 사장님 재재확정: 5x → 2x (신 OBV 모달!)
    // 히스토리: 2026-08-08 (2x) → 2026-08-09 (5x) → 2026-08-11 (2x!)
    const lvInp = document.getElementById('cm-leverage');
    if (lvInp && !lvInp.value) lvInp.value = 2;
    // TP qty 자동 세팅 (사장님 원하면 = 수정 가능!)
    const _tpQtyDefaults = {'cm-tp1-qty': 10, 'cm-tp2-qty': 15, 'cm-tp3-qty': 20, 'cm-tp4-qty': 25};
    for (const [id, val] of Object.entries(_tpQtyDefaults)) {
      const el = document.getElementById(id);
      if (el && !el.value) el.value = val;
    }
    // 🎯 Fix 173: OBV 모드 = 트리거 % 미사용 → 입력칸 비활성 + 이유 표시.
    //   사장님이 임의로 정해야 했던 값이 바로 「신뢰가 없다」던 그 값이다.
    //   ⚠️ 값을 **지우지는 않는다** — 미리보기 계산이 0% 로 degenerate 한 단계가를
    //      만들지 않도록 그대로 두고 비활성화만 한다 (사용되지 않는 값).
    const _trgTip = 'OBV 모드에서는 이 % 를 쓰지 않습니다 — 운영 진입 로직(15분 정점확인 등)이 판단합니다.';
    const _disableTrg = (el) => {
      if (!el) return;
      el.disabled = true;
      el.title = _trgTip;
      el.style.opacity = '0.4';
      el.style.cursor = 'not-allowed';
    };
    for (let i = 2; i <= 10; i++) _disableTrg(document.getElementById('cm-trg-' + i));
    _disableTrg(document.getElementById('cm-last-stage-trigger-pct'));
    // 자본 칸 옆에 한 줄 안내 (그리드 위)
    try {
      const grid = document.getElementById('cm-capitals-grid');
      if (grid && !document.getElementById('cm-obv-trg-note')) {
        const note = document.createElement('div');
        note.id = 'cm-obv-trg-note';
        note.style.cssText = 'margin:6px 0;padding:6px 8px;border-left:3px solid #34d399;'
          + 'background:rgba(52,211,153,0.08);color:#a7f3d0;font-size:12px;line-height:1.5';
        note.innerHTML = '🎯 <b>트리거 % 는 비활성입니다.</b> 다음 단계 진입은 '
          + '<b>지금 운영 중인 진입 로직</b>이 판단합니다 (15분 정점·저점 확인 + OBV 게이트).<br>'
          + '단계별 <b>금액만</b> 입력하시면 됩니다 — 그 금액 그대로 진입합니다.';
        grid.parentNode.insertBefore(note, grid);
      }
    } catch (_e) { /* 안내 실패는 기능에 영향 없음 */ }
  }, 200);
}

// ==================== 신규 전략 모달 (구 시스템) ====================
let cmState = {
  accountId: null,
  side: 'SHORT',
  templateId: null,
  mode: 'direct',  // 'direct' | 'template'
  capitals: ['', '', '', '', '', '', '', '', '', ''],  // 1~10단계
  preview: null,
};

async function openCreateModal(editStrategyId) {
  // 🎯 Fix 173 (2026-08-27): OBV 모달이 비활성화한 트리거 칸을 **반드시 되돌린다**.
  //   두 모달이 같은 DOM 을 공유하므로, 초기화하지 않으면
  //   「OBV 모달 열었다가 → 기존 방식 열기」 시 트리거 칸이 비활성인 채로 남아
  //   사장님이 값을 못 넣는다 (헌법 110 = 화면과 실제가 어긋나는 함정).
  try {
    const _enableTrg = (el) => {
      if (!el) return;
      el.disabled = false;
      el.title = '';
      el.style.opacity = '';
      el.style.cursor = '';
    };
    for (let i = 2; i <= 10; i++) _enableTrg(document.getElementById('cm-trg-' + i));
    _enableTrg(document.getElementById('cm-last-stage-trigger-pct'));
    const _oldNote = document.getElementById('cm-obv-trg-note');
    if (_oldNote) _oldNote.remove();
  } catch (_e) { /* 초기화 실패해도 모달 자체는 열려야 한다 */ }
  // 🌟 v130 (2026-08-06): _triggerMode 초기화 = default 'PRICE_DOWN_PCT' (구 시스템!)
  //   openCreateChartObvModal()가 = 이후에 = 'OBV_REVERSE'로 덮어씀!
  cmState._triggerMode = 'PRICE_DOWN_PCT';
  const _modalEl = document.getElementById('create-modal');
  _modalEl.classList.remove('hidden');
  /* 🚨 v92: 「⬆ 심볼로」 fixed 버튼 = 모달 열림 시 = 표시! */
  try {
    const _scrollBtn = document.getElementById('cm-scroll-to-symbol-btn');
    if (_scrollBtn) _scrollBtn.style.display = 'block';
  } catch (_e) {}
  document.getElementById('cm-preview').classList.add('hidden');
  document.getElementById('cm-submit').disabled = true;
  // 🚨 2026-06-22 사장님 critical v6: scroll guard 강력 모니터링!
  // 사장님 보고: v1~v5 모두 부족 = 「바로 아래로 내려감」!
  // 진짜 원인: 모달 open 후 = await 비동기 (loadCmAccounts, loadPrevBlueprint, _refreshLiveCalc)
  //            = 새 layout = scrollTop 변경 = 옛 requestAnimationFrame 보다 늦음!
  // fix v6: 모달 open 후 = 2초 동안 = scrollTop = 0 강제 모니터링!
  //         + 매 scroll 이벤트 = 0 으로 복원!
  const _inner = _modalEl.querySelector(':scope > div');
  let _scrollGuardActive = true;
  let _scrollGuardTimer = null;
  const _scrollGuardHandler = (e) => {
    if (_scrollGuardActive) {
      if (_inner && _inner.scrollTop !== 0) _inner.scrollTop = 0;
      if (_modalEl.scrollTop !== 0) _modalEl.scrollTop = 0;
    }
  };
  // 옛 listener 제거 (= 누적 방지!)
  if (_modalEl._scrollGuardHandler) {
    _modalEl.removeEventListener('scroll', _modalEl._scrollGuardHandler);
    if (_inner) _inner.removeEventListener('scroll', _modalEl._scrollGuardHandler);
  }
  _modalEl._scrollGuardHandler = _scrollGuardHandler;
  _modalEl.addEventListener('scroll', _scrollGuardHandler, { passive: true });
  if (_inner) _inner.addEventListener('scroll', _scrollGuardHandler, { passive: true });
  // 2초 후 = 사장님 자유 스크롤!
  if (_modalEl._scrollGuardTimer) clearTimeout(_modalEl._scrollGuardTimer);
  _modalEl._scrollGuardTimer = setTimeout(() => {
    _scrollGuardActive = false;
  }, 2000);
  // 즉시 + requestAnimationFrame x 3 = scrollTop 0 (= 첫 frame 부터!)
  if (_inner) _inner.scrollTop = 0;
  _modalEl.scrollTop = 0;
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (_inner) _inner.scrollTop = 0;
        _modalEl.scrollTop = 0;
        window.scrollTo({top: 0, left: 0, behavior: 'instant'});
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
  if (_lvInit) _lvInit.value = 2;  // 🌟 v132 (2026-08-11): 2x default (다음 setCmSide 가 다시 적용)
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
          // 🌟 v131 사장님 지적 (2026-08-09): 레버리지 = 신 default 강제!
          // 사장님 스크린샷: 이전 전략 5x = 자동 로드! = 신 default 2x 무시!
          // fix: 이전 전략 로드 후 = 레버리지만 = 신 default (2x!) override!
          //      (심볼별 조정 = 사장님 직접 입력!)
          try {
            const _lvEl = document.getElementById('cm-leverage');
            if (_lvEl && typeof _defaultLeverageForSide === 'function') {
              const _defLev = _defaultLeverageForSide(cmState ? cmState.side : 'SHORT');
              _lvEl.value = _defLev;
              cmLeverageManuallyEdited = false;  // = 자동 갱신 가능!
            }
          } catch (_le) {
            console.warn('[new-strategy] 레버리지 신 default 세팅 실패:', _le);
          }
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
    // 🚨 2026-07-01 사장님 critical fix (label vs 실제 값 silent bug!):
    // 옛 silent bug: label = t.name (= 사장님 옛 별명, 실제 값과 불일치!)
    // = 사장님 = "10 300_45" 별명 → 실제 값 = [400, 800] = 헷갈림!
    // fix: label = 실제 capitals + triggers 자동 생성 (= 정확!)
    //      + template name = title tooltip 에 보존!
    container.innerHTML = userTpls.map(t => {
      const sideColor = t.side === 'SHORT' ? 'text-red-400' : 'text-green-400';
      const sideIcon = t.side === 'SHORT' ? '📉' : '📈';
      // 실제 값 기반 label 생성:
      const caps = (t.stages_config?.capitals || []).filter(c => c && Number(c) > 0);
      const trigs = t.stages_config?.trigger_percents || [];
      // "cap1 cap2_trig2 cap3_trig3" 형식 (= 사장님 옛 표기법!)
      const label = caps.map((c, i) => {
        const trg = trigs[i];
        return (trg && Number(trg) > 0) ? `${c}_${trg}` : String(c);
      }).join(' ').substring(0, 22);
      const stagesCount = caps.length || 0;
      return `<button onclick="if(typeof startStrategyFromTemplate==='function') startStrategyFromTemplate(${t.id})"
        class="px-2 py-1 bg-slate-800 hover:bg-slate-700 border border-slate-600 rounded text-xs"
        style="min-width:0"
        title="📋 별명: ${t.name} | 실제: ${caps.join(', ')} USDT (트리거: ${trigs.filter(x=>x).join(', ') || 'default'}) | ${t.side} ${t.leverage}x, ${stagesCount}단계 — 클릭 = 신 strategy!">
        <span class="${sideColor}">${sideIcon}</span>
        <span class="font-semibold text-blue-300">${label}</span>
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
