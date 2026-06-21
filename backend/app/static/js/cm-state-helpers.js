/**
 * Create-Modal — state toggle helpers (Phase 3 단계 3g, 2026-05-14).
 *
 * 모달 내부 state (mode/side/leverage) 토글 + 패널 표시 + close 액션.
 *
 * 함수:
 *   - setCmMode(mode)        : direct/template/prev 패널 전환 + 버튼 스타일
 *   - setCmSide(side)        : SHORT/LONG 토글 + leverage default reset
 *   - resetCmLeverage()      : leverage 입력을 사이드별 default 로 리셋
 *   - closeCreateModal()     : 모달 숨김 + 다중 심볼 chip 초기화
 *
 * State (이 모듈 소유):
 *   - cmLeverageManuallyEdited : 사용자가 leverage 직접 수정했는지 (true 면 사이드 변경 시 자동 갱신 안 함)
 *
 * 외부 의존성 (script-scope 공유):
 *   - cmState (mutable)
 *   - updateCmSubmit / loadCmPrevStrategies / toggleMultiSymbolMode / _cmMultiSymbols
 *   - _defaultLeverageForSide (cm-collectors.js)
 *   - DOM: #create-modal, #cm-preview, #cm-mode-{direct,template,prev},
 *     #cm-{direct,template,prev}-panel, #cm-side-{short,long}, #cm-leverage,
 *     #cm-multi-symbol-toggle, #cm-multi-add-input
 */

function setCmMode(mode) {
  cmState.mode = mode;
  cmState.preview = null;
  document.getElementById('cm-preview').classList.add('hidden');
  // 버튼 스타일
  const modes = ['direct', 'template', 'prev'];
  modes.forEach(m => {
    const btn = document.getElementById('cm-mode-' + m);
    btn.className = 'btn flex-1' + (m === mode ? ' btn-primary' : ' btn-ghost');
    btn.style.fontSize = '12px';
    btn.style.padding = '6px 10px';
  });
  // 패널 표시
  document.getElementById('cm-direct-panel').classList.toggle('hidden', mode !== 'direct');
  document.getElementById('cm-template-panel').classList.toggle('hidden', mode !== 'template');
  document.getElementById('cm-prev-panel').classList.toggle('hidden', mode !== 'prev');
  if (mode === 'prev') loadCmPrevStrategies();
  updateCmSubmit();
}

function closeCreateModal() {
  const _modalEl = document.getElementById('create-modal');
  _modalEl.classList.add('hidden');
  // 🚨 2026-06-22 사장님 critical v3: 시간 의존 silent bug 영구 fix!
  // 사장님 보고: "처음에는 OK = 시간 지나면 = 모달 위로 스크롤 안 됨!"
  // 원인: 옛 scrollTop 누적 + body overflow 누적 = 신 모달 open 시 = 옛 위치 유지!
  // fix: close 시 = scrollTop 초기화 + body overflow 복원!
  try {
    const _inner = _modalEl.querySelector(':scope > div');
    if (_inner) _inner.scrollTop = 0;
    _modalEl.scrollTop = 0;
  } catch (_e) {}
  // body overflow = 정상 복원!
  if (document.body.style.overflow === 'hidden') {
    document.body.style.overflow = '';
  }
  if (document.documentElement.style.overflow === 'hidden') {
    document.documentElement.style.overflow = '';
  }
  // 2026-05-12: 다중 심볼 토글 + chips 초기화 (다음 진입 시 단일 모드로 시작)
  const multiToggle = document.getElementById('cm-multi-symbol-toggle');
  if (multiToggle && multiToggle.checked) {
    multiToggle.checked = false;
    toggleMultiSymbolMode();
  }
  _cmMultiSymbols = [];
  const addInput = document.getElementById('cm-multi-add-input');
  if (addInput) addInput.value = '';
}

// UX #18: 사용자가 직접 레버리지를 수정했는지 추적. true 면 사이드 변경 시 자동 갱신 안 함.
let cmLeverageManuallyEdited = false;

function resetCmLeverage() {
  const lev = _defaultLeverageForSide(cmState.side);
  document.getElementById('cm-leverage').value = lev;
  cmLeverageManuallyEdited = false;
  cmState.preview = null;
  document.getElementById('cm-preview').classList.add('hidden');
  updateCmSubmit();
}

function setCmSide(side) {
  cmState.side = side;
  document.getElementById('cm-side-short').className = 'btn flex-1' + (side==='SHORT' ? '' : ' btn-ghost');
  document.getElementById('cm-side-short').style.background = side==='SHORT' ? '#ef4444' : 'transparent';
  document.getElementById('cm-side-short').style.color = side==='SHORT' ? '#fff' : '#cbd5e1';
  document.getElementById('cm-side-long').className = 'btn flex-1' + (side==='LONG' ? '' : ' btn-ghost');
  document.getElementById('cm-side-long').style.background = side==='LONG' ? '#10b981' : 'transparent';
  document.getElementById('cm-side-long').style.color = side==='LONG' ? '#fff' : '#cbd5e1';
  // Bug fix (2026-04-30): 사이드 변경 시 무조건 default leverage 로 reset.
  // 이전 버전은 manualEdited=true 면 갱신 안 해서 SHORT 의 2 가 LONG 으로 유지되는 버그.
  const lev = _defaultLeverageForSide(side);
  const lvInp = document.getElementById('cm-leverage');
  if (lvInp) lvInp.value = lev;
  cmLeverageManuallyEdited = false;  // 사이드 바꿨으니 다시 자동 갱신 가능 상태로
  // 방향 변경 시 미리보기 무효화
  cmState.preview = null;
  document.getElementById('cm-preview').classList.add('hidden');
  updateCmSubmit();
}
