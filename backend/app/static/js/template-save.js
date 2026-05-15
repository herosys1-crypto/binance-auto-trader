/**
 * 「💾 템플릿으로 저장」 + batch 진입 — Phase 3 추가 분리 (2026-05-14).
 *
 * 사용자 요청 (2026-05-12): _quick_* 자동 생성 대신 사용자 정의 이름으로 템플릿
 * 영구 저장 → 다중 심볼 batch 생성.
 *
 * 함수:
 *   - saveAsTemplate()
 *     3 모드 모두 지원 — 직접 입력 / 템플릿 선택 (복제) / 이전 전략 (자동 직접 모드 전환).
 *
 *   - openCreateModalForBatch(templateId)
 *     「📋 전략 템플릿」 panel 의 「🚀 다중」 버튼 → 모달 열기 + pre-set
 *     (템플릿 모드 + 라디오 선택 + 다중 심볼 토글 ON).
 *
 *   - _parseBatchSymbols(raw)
 *     콤마/공백/줄바꿈/세미콜론 구분 → 대문자 normalize → dedup.
 *
 * 외부 의존성 (script-scope 공유):
 *   - cmState, _collectDirectInputs, _collectTpSl, _defaultLeverageForSide,
 *     openCreateModal, setCmMode, toggleMultiSymbolMode, refreshTemplates
 *   - api, toast (api.js)
 */

async function saveAsTemplate() {
  // 2026-05-12 v2 (사용자 요청): 3 모드 모두 지원.
  //   📝 직접 입력 → 현재 form 입력값 저장
  //   📋 템플릿 선택 → 선택한 템플릿 config 복제 → 새 이름으로 저장 (rename 효과)
  //   📂 이전 전략 불러오기 → 직접 입력 모드로 자동 전환되므로 직접 입력과 동일
  let body;
  let sourceDesc;
  if (cmState.mode === 'direct') {
    const lvInpEl = document.getElementById('cm-leverage');
    const leverage = lvInpEl && lvInpEl.value ? Number(lvInpEl.value) : _defaultLeverageForSide(cmState.side);
    const inp = _collectDirectInputs();
    const tpsl = _collectTpSl();
    const _tpFields = {};
    for (let n = 1; n <= 10; n++) {
      _tpFields[`tp${n}_percent`] = tpsl[`tp${n}_percent`];
      _tpFields[`tp${n}_qty_ratio`] = tpsl[`tp${n}_qty_ratio`];
    }
    body = {
      strategy_type: cmState.side === 'SHORT' ? 'DYNAMIC_SHORT' : 'DYNAMIC_LONG',
      side: cmState.side,
      leverage,
      capitals: inp.capitals,
      trigger_percents: inp.trigger_percents,
      additional_margins: inp.additional_margins,
      last_stage_trigger_percent: inp.last_stage_trigger_percent,
      ..._tpFields,
      stop_loss_percent_of_capital: tpsl.stop_loss_percent_of_capital,
      reentry_policy: 'manual_ready',
    };
    sourceDesc = '현재 직접 입력값';
  } else if (cmState.mode === 'template') {
    if (!cmState.templateId) {
      toast('⚠️ 「📋 템플릿 선택」 모드에서 라디오로 템플릿을 먼저 선택하세요', 'warning');
      return;
    }
    // 선택한 템플릿 config 복제
    let srcTpl;
    try {
      const tplList = await api('/admin/strategy-templates');
      srcTpl = tplList.find(t => t.id === cmState.templateId);
    } catch (e) {
      toast('⚠️ 템플릿 목록 조회 실패: ' + e.message, 'error');
      return;
    }
    if (!srcTpl) {
      toast('⚠️ 선택된 템플릿을 찾을 수 없음', 'error');
      return;
    }
    const sc = srcTpl.stages_config || {};
    const _tpFields = {};
    for (let n = 1; n <= 10; n++) {
      _tpFields[`tp${n}_percent`] = srcTpl[`tp${n}_percent`];
      _tpFields[`tp${n}_qty_ratio`] = srcTpl[`tp${n}_qty_ratio`];
    }
    body = {
      strategy_type: srcTpl.strategy_type || (srcTpl.side === 'SHORT' ? 'DYNAMIC_SHORT' : 'DYNAMIC_LONG'),
      side: srcTpl.side,
      leverage: srcTpl.leverage,
      capitals: sc.capitals || [],
      trigger_percents: sc.trigger_percents || [],
      additional_margins: sc.additional_margins || [],
      last_stage_trigger_percent: sc.last_stage_trigger_percent,
      ..._tpFields,
      stop_loss_percent_of_capital: srcTpl.stop_loss_percent_of_capital,
      crisis_max_loss_threshold: srcTpl.crisis_max_loss_threshold,
      reentry_policy: srcTpl.reentry_policy || 'manual_ready',
    };
    sourceDesc = `선택한 템플릿 「${srcTpl.name}」 (#${srcTpl.id}) 의 설정 복제`;
  } else {
    toast('⚠️ 알 수 없는 모드: ' + cmState.mode, 'error');
    return;
  }
  // 사용자 정의 이름 입력 — 의미 있는 이름 권장.
  const name = prompt(
    `💾 템플릿 이름 입력\n\n` +
    `소스: ${sourceDesc}\n\n` +
    `권장: 전략 성향이 드러나는 이름\n` +
    `  예시: "공격적 단타 SHORT 5x", "보수적 분할매수 LONG 2x", "메모리코인 7단계", "BTC 안정형"\n\n` +
    `⚠️ "_quick_" 로 시작하는 이름은 자동 생성용이라 사용 불가.\n`
  );
  if (!name || !name.trim()) return;
  const trimmedName = name.trim();
  if (trimmedName.startsWith('_quick_')) {
    toast('⚠️ "_quick_" prefix 는 자동 생성용 — 다른 이름 사용', 'error');
    return;
  }
  body.name = trimmedName;
  try {
    const tplCreated = await api('/admin/strategy-templates', { method: 'POST', body });
    toast(`💾 템플릿 「${trimmedName}」 (#${tplCreated.id}) 저장 완료. 「📋 전략 템플릿」 에서 확인.`, 'success');
    refreshTemplates();
  } catch (e) {
    toast('💾 템플릿 저장 실패: ' + e.message, 'error');
  }
}

// 「📋 전략 템플릿」 panel 의 「🚀 다중」 버튼 → 「+ 새 전략」 모달 열기 + pre-set
//   - 「📋 템플릿 선택」 모드 + 클릭한 template 라디오 활성
//   - 「📦 다중 심볼 모드」 토글 ON
//   - 사용자는 심볼 textarea + 시작 버튼만 누르면 됨
async function openCreateModalForBatch(templateId) {
  await openCreateModal();
  // 템플릿 모드로 전환 + 라디오 선택
  setCmMode('template');
  await new Promise(r => setTimeout(r, 100));  // 라디오 렌더링 대기
  const radio = document.querySelector(`input[name="cm-template"][value="${templateId}"]`);
  if (radio) {
    radio.checked = true;
    radio.dispatchEvent(new Event('change'));
  }
  // 다중 심볼 토글 ON
  const toggle = document.getElementById('cm-multi-symbol-toggle');
  if (toggle && !toggle.checked) {
    toggle.checked = true;
    toggleMultiSymbolMode();
  }
  // 심볼 textarea 포커스 (사용자가 바로 입력)
  setTimeout(() => document.getElementById('cm-symbols-multi')?.focus(), 200);
}

function _parseBatchSymbols(raw) {
  // 콤마/공백/줄바꿈/세미콜론 구분 → 대문자 normalize → dedup → 빈값 제거
  return Array.from(new Set(
    String(raw || '').toUpperCase().split(/[\s,;]+/).filter(s => s.length >= 3)
  ));
}
