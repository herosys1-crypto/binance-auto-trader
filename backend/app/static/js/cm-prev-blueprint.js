/**
 * Create-Modal — 「📂 이전 전략 불러오기」 (Phase 3 단계 3b, 2026-05-14).
 *
 * 이전 strategy 의 blueprint 를 가져와 form 에 자동 채움.
 *
 * 함수:
 *   - loadCmPrevStrategies()
 *     /strategies 호출 → 라디오 목록 렌더 (선택 시 loadPrevBlueprint 호출).
 *
 *   - loadPrevBlueprint(strategyId, silent)
 *     /strategies/{id}/blueprint 호출 → 모든 form 필드 자동 채움
 *     (계정, 심볼, 방향, capitals, trigger_percents, additional_margins, TP/SL).
 *
 * 외부 의존성 (script-scope 공유):
 *   - cmState (mutable state)
 *   - setCmSide / setCmMode / onCapitalsChange / loadCmMarketInfo
 *   - api / toast / STATUS_MAP / renderWhitelistBadge
 *   - DOM: #cm-prev-list, #cm-symbol, #cm-cap-{1..10}, #cm-trg-{2..10},
 *     #cm-add-margin-{1..10}, #cm-tp{1..10}-{pct,qty}, #cm-sl-pct, #cm-start-price
 */

async function loadCmPrevStrategies() {
  try {
    const data = await api('/strategies');
    const list = document.getElementById('cm-prev-list');
    if (!data.length) {
      list.innerHTML = '<p class="text-slate-500 text-sm">이전 전략이 없습니다.</p>';
      return;
    }
    list.innerHTML = data.map(s => {
      const sideKo = s.side === 'SHORT' ? '📉 숏' : '📈 롱';
      const status = (s.status || '').toUpperCase();
      const statusKo = (STATUS_MAP[status] || {ko: status}).ko;
      return `<label class="flex items-center gap-2 p-2 rounded cursor-pointer hover:bg-slate-700">
        <input type="radio" name="cm-prev" value="${s.id}" onchange="loadPrevBlueprint(${s.id})" />
        <span class="font-mono text-blue-300">#${s.id}</span>
        <span class="font-semibold">${s.symbol}${renderWhitelistBadge(s.symbol)}</span>
        <span class="badge ${s.side==='SHORT'?'badge-red':'badge-green'}">${sideKo}</span>
        <span class="badge badge-gray">${statusKo}</span>
        <span class="text-xs text-slate-400 ml-auto">레버리지 ${s.leverage}x</span>
      </label>`;
    }).join('');
  } catch (e) { toast('이전 전략 조회 실패: '+e.message, 'error'); }
}

async function loadPrevBlueprint(strategyId, silent) {
  try {
    const bp = await api(`/strategies/${strategyId}/blueprint`);
    // 1) 거래소 계정 자동 선택 (있으면)
    const accountRadio = document.querySelector(`input[name="cm-account"][value="${bp.exchange_account_id}"]`);
    if (accountRadio) { accountRadio.checked = true; cmState.accountId = bp.exchange_account_id; }
    // 2) 심볼 + 방향
    document.getElementById('cm-symbol').value = bp.symbol;
    setCmSide(bp.side);  // 부수효과: leverage 가 사이드별 default 로 reset 됨 → 아래에서 덮어씀
    // 2-a) 2026-05-15 사용자 보고: 이전 전략의 leverage 가 안 따라옴 (롱이면 항상 1 로 떨어짐).
    // setCmSide 가 default 로 reset 한 직후 bp.leverage 로 덮어쓰고 manualEdited 마킹.
    if (bp.leverage !== undefined && bp.leverage !== null && Number(bp.leverage) > 0) {
      const lvInp = document.getElementById('cm-leverage');
      if (lvInp) lvInp.value = bp.leverage;
      cmLeverageManuallyEdited = true;  // 이후 사이드 토글 시 자동 reset 안 되게
    }
    // 3) 직접 입력 모드로 전환 + capitals/trigger_percents/additional_margins 채우기
    setCmMode('direct');
    const addMargins = bp.additional_margins || [];
    // 2026-05-12 fix (사용자 보고): 「이전 전략 불러오기」 시 마지막 단계 trigger% 가 항상 빈칸.
    // 원인: stages_config 에서 마지막 단계 trigger 는 last_stage_trigger_percent 컬럼에
    // 별도 저장되고, trigger_percents 배열의 마지막 idx 는 None 인 경우가 많음
    // (legacy LIQUIDATION_BUFFER 모드 호환). loadPrevBlueprint 가 그 fallback 을 안 함.
    // → 마지막 사용 단계 식별 후, 그 단계 trigger 가 비었으면 last_stage_trigger_percent 로 대체.
    let lastUsedStage = 0;
    for (let k = 0; k < (bp.capitals || []).length; k++) {
      const c = (bp.capitals || [])[k];
      if (c !== null && c !== undefined && c !== '' && Number(c) > 0) lastUsedStage = k + 1;
    }
    for (let i = 1; i <= 10; i++) {
      const cap = (bp.capitals || [])[i-1];
      let trg = (bp.trigger_percents || [])[i-1];
      const addM = addMargins[i-1];
      document.getElementById('cm-cap-' + i).value = cap !== undefined && cap !== null ? cap : '';
      if (i > 1) {
        // 마지막 사용 단계인데 trigger 비었으면 last_stage_trigger_percent fallback.
        if ((trg === null || trg === undefined || trg === '') && i === lastUsedStage
            && bp.last_stage_trigger_percent !== null && bp.last_stage_trigger_percent !== undefined && bp.last_stage_trigger_percent !== '') {
          trg = bp.last_stage_trigger_percent;
        }
        document.getElementById('cm-trg-' + i).value = trg !== undefined && trg !== null ? trg : '';
      }
      // 2026-05-11: 단계별 추가 증거금 자동 채움 (이전 전략의 설정 그대로)
      const addEl = document.getElementById('cm-add-margin-' + i);
      if (addEl) {
        addEl.value = (addM !== undefined && addM !== null && Number(addM) > 0) ? addM : '';
      }
    }
    // 4) TP/SL 채우기 (TP4/5 nullable)
    // 2026-05-06: TP1~10 동적 (10단계 익절 확장)
    for (let n = 1; n <= 10; n++) {
      const pctEl = document.getElementById(`cm-tp${n}-pct`);
      const qtyEl = document.getElementById(`cm-tp${n}-qty`);
      if (pctEl) pctEl.value = bp[`tp${n}_percent`] || '';
      if (qtyEl) qtyEl.value = bp[`tp${n}_qty_ratio`] || '';
    }
    document.getElementById('cm-sl-pct').value = bp.stop_loss_percent_of_capital;
    // 2026-05-14: 크라이시스 dropdown 제거됨 (사용자 결정 「손절만 사용」).
    // 새 strategy 는 자동으로 -100 (비활성) 적용 — _collectTpSl 참조.
    // 5) 시작가 — 수정 모드면 원래 시작가 유지, 일반 불러오기는 비움
    if (cmState.editingStrategyId && bp.start_price) {
      document.getElementById('cm-start-price').value = bp.start_price;
    } else {
      document.getElementById('cm-start-price').value = '';
    }
    onCapitalsChange();
    if (!silent) {
      toast(`전략 #${bp.source_strategy_id} 설정을 불러왔습니다. 종목/시작가만 변경하세요`, 'success');
    }
    // 시세 다시 로드
    loadCmMarketInfo();
  } catch (e) { toast('불러오기 실패: '+e.message, 'error'); }
}
