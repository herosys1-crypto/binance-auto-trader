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
    // 5) 시작가 — 2026-06-03 사장님 사상 변경:
    // 이전: 수정 모드면 옛 bp.start_price 채움 → 사장님이 옛 가격 기준 미리보기 보고
    //       「🔄 종료 후 새로 시작」 시 옛 LIMIT 가격으로 진입 위험.
    // 변경: 수정 모드든 일반 불러오기든 시작가는 항상 빈값 → loadCmMarketInfo 가
    //       자동으로 현재가 채움 → 트리거가 + 평단 + 청산가 모두 현재가 기준 재계산.
    // 🌟 2026-06-09 v16 사장님 critical fix (SLXUSDT 가 63100 BTC 가격 표시 버그):
    // _cmCurrentPrice 옛 cache (= 마지막 조회한 BTC 등 다른 심볼 가격) 강제 초기화
    // → loadCmMarketInfo 완료 후 = 신 symbol 의 실제 현재가만 사용
    document.getElementById('cm-start-price').value = '';
    if (typeof _cmCurrentPrice !== 'undefined') {
      _cmCurrentPrice = null;  // ⭐ critical: 옛 BTC/다른 심볼 캐시 무효화
    }
    // 시세 자리도 임시 "-" 표시 (= loadCmMarketInfo 완료까지)
    const _mktEl = document.getElementById('cm-mkt-price');
    if (_mktEl) _mktEl.textContent = '-';
    onCapitalsChange();
    if (!silent) {
      const editNote = cmState.editingStrategyId
        ? ` (수정 모드 — 시작가는 현재가로 자동 갱신됨, 옛 시작가 ${bp.start_price || '?'} 참고용)`
        : '';
      toast(`전략 #${bp.source_strategy_id} 설정을 불러왔습니다. 종목/시작가 확인 후 진행${editNote}`, 'success');
    }
    // 시세 다시 로드 → 자동으로 현재가가 cm-start-price 에 채워짐 → _refreshLiveCalc 트리거
    await loadCmMarketInfo();
    // 🌟 2026-06-10 v29 사장님 신 critical 사상 (= STGUSDT 사례!):
    // 사장님 명시: "현재가를 실행하면 정상적으로 나오는데 이럴경우 수정을 클릭하면
    //              각각 심볼의 현재가를 불러오면 되는것 같은데"
    // = 사장님 의도 = 「불러오기」 클릭 시 = 무조건 현재가로 = 자동 덮어쓰기!
    // = silent bug 원천 차단!
    //
    // 옛 v21 (= toast 알림 만):
    //   loadCmMarketInfo() → cm-market-info L60 = 빈값일 때만 자동 → 옛 값 보존 = silent bug!
    //
    // 신 v29 (= 사장님 사상 강제 적용):
    //   loadCmMarketInfo() 완료 후 = 무조건 fillStartPrice('current') 호출
    //   = 옛 strategy 의 옛 시작가 = 무조건 신 현재가로 덮어쓰기!
    try {
      if (typeof fillStartPrice === 'function' && _cmCurrentPrice && !isNaN(_cmCurrentPrice)) {
        fillStartPrice('current');  // 🌟 사장님 사상: 무조건 현재가 강제!
        toast('✅ 시작가 = 현재가 자동 적용 (사장님 사상 v29)', 'success');
      } else {
        // 현재가 조회 실패 = 사장님 즉시 알림 + 빨간 테두리
        const startPriceEl = document.getElementById('cm-start-price');
        toast('⚠️ 현재가 조회 실패! 「현재가」 버튼 수동 클릭', 'warning');
        if (startPriceEl) {
          startPriceEl.style.border = '2px solid #f00';
          startPriceEl.style.backgroundColor = '#fee';
          setTimeout(() => {
            startPriceEl.style.border = '';
            startPriceEl.style.backgroundColor = '';
          }, 8000);
        }
      }
    } catch (e) {
      console.warn('[v29] 시작가 자동 적용 실패:', e);
    }
  } catch (e) { toast('불러오기 실패: '+e.message, 'error'); }
}
