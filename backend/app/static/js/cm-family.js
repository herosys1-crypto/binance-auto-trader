/**
 * Create-Modal — 「기존 방식」 vs 「OBV 자동」 가족 판정 + 전용 UI 처리 (Fix 369, 2026-09-13).
 *
 * 사장님: "새 전략기존방식 과 새전략 obv 자동 둘을 완전 다르게 둘로 분리해서 개발을해줘
 *         두개가 계속 겹치는것 같아"
 *
 * 배경 (S3 감사, 2026-09-13): 두 모달이 같은 DOM/state(cmState) 를 공유해서
 *   - OBV 모달에서 「📋 템플릿 선택」/「📂 이전 전략 불러오기」 탭으로 가격 템플릿을 고르면
 *     토스트는 "OBV" 라고 말하고 실제로는 기존 방식 인스턴스가 만들어졌다.
 *   - 수정/재시작이 원본 전략의 가족을 못 찾으면 조용히 기존 방식으로 떨어졌다.
 *   - 새 모달의 자동 채움이 가족을 가리지 않고 「가장 최근 전략」을 그대로 썼다.
 *
 * 이 모듈은 그 판정을 **한 곳**에서 한다 — 백엔드 app.services.strategy_family.family_of
 * 와 이름을 맞췄다 (legacy_manual / obv_auto / 그 외).
 *
 * 함수 (순수 — DOM/전역 미접근, node 로도 실행 가능):
 *   - _resolveFamilyLoose(s)                                    : 즉시 분류 (자동 채움 후보 거르기용, 모호하면 null)
 *   - familyFromStrategy(orig)                                  : 수정/재시작 — trigger_mode 로 확정 (null = 중단)
 *   - computeModalFamily({editStrategyId, resolvedFamily,
 *                          pendingObvForThisOpen})               : 이번 openCreateModal() 호출이 어느 가족인지 결정
 *
 * 함수 (DOM 조작):
 *   - _applyObvModalVisuals()      : OBV 모달 공통 시각 처리 (탭 비활성 + 트리거 칸 비활성 + 안내)
 *   - _resetObvModalVisuals()      : 위 처리를 원상복구 (모달을 다시 열 때마다 호출)
 *
 * 외부 의존성: 없음 (cmState 참조만, cm-open-modal.js 보다 먼저 로드돼야 함
 * cmState 자체는 함수 호출 시점에만 읽으므로 로드 순서는 무관 — 다만 이 파일은 다른
 * cm-*.js 가 참조하므로 그것들보다 먼저 있어야 한다).
 *
 * 🚨 반박 검증 (2026-09-13, S3 리뷰) 이 잡은 사고 두 건 — 지금 이 파일의 설계는 그 교훈이다:
 *   BLOCKING — cmState._pendingObv 는 openCreateChartObvModal() 이 「이번 한 번의 open」을 위해
 *     세팅하는 **일회용** 신호다. 예전 코드는 이걸 `!!(cmState && cmState._pendingObv) || (...)` 로
 *     OR 해서 새 cmState 에 다시 실어 날랐다 — editStrategyId 가 있는 호출(수정/재시작)이
 *     그 값을 읽어버려서, "OBV 전략을 수정하고 닫은 뒤 「➕ 기존 방식」 새 전략" 이 여전히
 *     OBV_REVERSE 로 만들어졌다. → computeModalFamily 는 editStrategyId 가 있으면 이번 호출에서
 *     확정한 resolvedFamily **만** 보고, pendingObv 는 editStrategyId 가 없을 때만 본다.
 *   HIGH — 표식 없는 전략을 만나면 확인창(confirm)으로 물었는데 **OK 가 OBV** 였다. 습관적으로 OK 를
 *     누르는 사장님에게 반대로(대부분은 기존 방식인) 전략을 OBV 로 재생성시키는 함정이었다.
 *     → 대화상자를 완전히 없애고, 항상 있는 trigger_mode 하나로만 결정한다(옛 Fix 367d 방식).
 */

// 확인창 없이 즉시 분류 — 자동 채움("가장 최근 전략") 후보를 가족별로 거를 때 사용.
// 모호하면(표식 없음/다른 가족) null 반환 — 호출자는 후보에서 제외한다 (섞임 방지 우선).
function _resolveFamilyLoose(s) {
  if (!s) return null;
  // 서버가 이제 family 를 계산해서 내려준다 (Fix 369 — app.services.strategy_family.family_of).
  if (s.family === 'obv_auto' || s.family === 'legacy_manual') return s.family;
  const profile = s.entry_profile || null;
  const trig = String(s.trigger_mode || '').toUpperCase();
  if (profile === 'obv_auto' || trig === 'OBV_REVERSE') return 'obv_auto';
  if (profile === 'legacy_manual') return 'legacy_manual';
  return null;  // 미표식(Fix 367 이전) / 관리 재진입 / auto_bb / 사다리 등 — 후보 제외
}

// 수정(✏️)/재시작(🔄) 전용 — 원본 전략의 가족을 trigger_mode 로 확정한다.
// 🚨 리뷰 HIGH #2: 확인창(confirm) 대화상자를 쓰지 않는다 — "OK = OBV" 습관 클릭이 대부분(기존 방식)인
//   전략을 OBV 로 재생성시켰다. trigger_mode 는 서버 기본값(PRICE_DOWN_PCT)이 있어 사실상 항상
//   존재하므로, family_of() 판정(split/ladder/single/other 등)과 무관하게 옛 Fix 367d 그대로
//   "OBV_REVERSE 면 OBV, 그 외 값이 있으면 기존 방식" 으로 결정한다 — 침묵 폴백이 아니라 실제
//   데이터로 결정하는 것이라 안전하다. trigger_mode 자체가 없거나(응답 손상) 호출자가 이미
//   API 조회에 실패했을 때만 null(중단) — 확인창으로 사장님께 되묻지 않는다.
// 반환: 'obv_auto' | 'legacy_manual' | null(중단 — 호출자가 에러 토스트 후 중단해야 함)
function familyFromStrategy(orig) {
  if (!orig) return null;
  const trig = String(orig.trigger_mode || '').toUpperCase();
  if (trig === 'OBV_REVERSE') return 'obv_auto';
  if (trig) return 'legacy_manual';
  return null;
}

// 🚨 리뷰 BLOCKING #1: 이번 openCreateModal() 호출이 어느 가족인지 — **이번 호출의 입력만** 본다.
//   editStrategyId 가 있으면(수정/재시작) resolvedFamily(=familyFromStrategy 결과) 만 쓰고
//   과거 cmState 플래그는 절대 섞지 않는다. editStrategyId 가 없으면(신규) pendingObvForThisOpen
//   (= openCreateChartObvModal 이 이번 호출 직전에 세팅한 값)만 본다.
function computeModalFamily({ editStrategyId, resolvedFamily, pendingObvForThisOpen }) {
  if (editStrategyId) {
    return resolvedFamily === 'obv_auto' ? 'obv_auto' : 'legacy_manual';
  }
  return pendingObvForThisOpen ? 'obv_auto' : 'legacy_manual';
}

// OBV 모달 공통 시각 처리 — openCreateChartObvModal() 과 「수정 = OBV 가족」 경로가 함께 쓴다.
// 타이틀/배너 텍스트는 호출자가 각자 맥락에 맞게 설정한다 (이 함수는 안 건드림).
function _applyObvModalVisuals() {
  // 🎯 Fix 369 감사 #1: 「📋 템플릿 선택」/「📂 이전 전략 불러오기」 탭 모두 가족 필터가
  //   따로 없어 다른 가족을 골라도 그대로 진행됐다. OBV 모달은 「직접 입력」만 지원해서
  //   이 사고 경로 자체를 없앤다 (설계 선택 — 두 탭을 가족별로 필터링하는 대신 숨긴다).
  const _disableModeTab = (id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.disabled = true;
    el.title = 'OBV 자동 모달은 직접 입력만 지원합니다 (가족이 섞이는 사고 방지, Fix 369).';
    el.style.opacity = '0.4';
    el.style.cursor = 'not-allowed';
  };
  _disableModeTab('cm-mode-template');
  _disableModeTab('cm-mode-prev');

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
}

// 모달을 다시 열 때마다 호출 — 옛 OBV 시각 처리를 되돌린다 (Fix 173 의 취지 그대로,
// 「📋 템플릿 선택」/「📂 이전 전략 불러오기」 탭 비활성까지 포함하도록 확장).
function _resetObvModalVisuals() {
  const _enableModeTab = (id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.disabled = false;
    el.title = '';
    el.style.opacity = '';
    el.style.cursor = '';
  };
  _enableModeTab('cm-mode-template');
  _enableModeTab('cm-mode-prev');

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
}
