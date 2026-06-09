/**
 * Create-Modal — submitCreate (전략 시작 액션) (Phase 3 단계 3f, 2026-05-14).
 *
 * 「🚀 전략 시작」 버튼 클릭 시 호출. 단일/수정/다중 모드 모두 처리.
 *
 * 흐름:
 *   1. 다중 심볼 모드 → submitCreateMulti() 위임 (multi-symbol.js)
 *   2. 단일 모드:
 *      a. 수정 모드면 기존 strategy /stop (cancel_only)
 *      b. direct 모드면 _quick_ 자동 template 생성
 *      c. POST /strategies + POST /strategies/{id}/start
 *      d. 모달 닫기 + 목록 갱신
 *
 * 외부 의존성 (script-scope 공유):
 *   - cmState (mutable)
 *   - submitCreateMulti (multi-symbol.js)
 *   - _collectDirectInputs / _collectTpSl / _defaultLeverageForSide (cm-collectors.js)
 *   - closeCreateModal (index.html)
 *   - refreshStrategies / refreshTemplates (index.html)
 *   - api / toast (api.js)
 *   - fmtNum (helpers.js)
 *   - DOM: #cm-symbol, #cm-start-price, #cm-leverage, #cm-submit, #cm-multi-symbol-toggle
 */

async function submitCreate() {
  // 2026-05-12 v2 (사용자 UX 개선): 다중 심볼 모드면 batch 처리로 우회.
  // 단일 모드는 기존 로직 그대로.
  const isMulti = document.getElementById('cm-multi-symbol-toggle')?.checked;
  const editingId = cmState.editingStrategyId;
  if (isMulti && !editingId) {
    return submitCreateMulti();  // 신규 batch 함수 호출
  }
  const symbol = document.getElementById('cm-symbol').value.toUpperCase().trim();
  const startPrice = document.getElementById('cm-start-price').value;

  // 🌟 2026-06-10 v21 사장님 critical (= VELVETUSDT 시작가 silent bug 영구 차단):
  // 사장님 사례: 시작가 0.078745 (옛 strategy 데이터) vs 현재가 0.39131 = 5배 차이!
  // = 옛 시작가 silent bug = 사장님 자본 위험!
  // = 시작가 vs 현재가 차이 > 50% = confirm 강제 (= 사장님 명시 의도 확인)
  try {
    const currentPriceEl = document.getElementById('cm-mkt-price');
    const currentPriceText = currentPriceEl ? currentPriceEl.textContent : '';
    const currentPrice = parseFloat(currentPriceText.replace(/[^0-9.]/g, ''));
    const startPriceNum = parseFloat(startPrice);
    if (currentPrice > 0 && startPriceNum > 0) {
      const ratio = Math.max(currentPrice, startPriceNum) / Math.min(currentPrice, startPriceNum);
      // 🌟 2026-06-10 v22 사장님 critical = BTWUSDT 75만 배 차이 사례!
      // 차이 > 10배 = 무조건 강제 차단 (= confirm 무시 = 사장님 자본 보호 우선)
      if (ratio > 10) {
        alert(
          `🚨🚨🚨 시작가 자동 차단! (silent bug 100%!)\n\n` +
          `📌 시작가 (입력): ${startPriceNum}\n` +
          `📌 현재가 (Binance): ${currentPrice}\n` +
          `📌 차이: ${ratio.toFixed(0)}배!\n\n` +
          `🚨 시작가 vs 현재가 = 10배 이상 차이 = 100% silent bug!\n` +
          `= 사장님 자본 보호 = 무조건 차단!\n\n` +
          `💡 해결:\n` +
          `  • 시작가 옆 「💲 현재가」 버튼 클릭\n` +
          `  • 또는 = 직접 ${currentPrice} 입력`
        );
        document.getElementById('cm-submit').disabled = false;
        document.getElementById('cm-submit').textContent = editingId ? '🔄 종료 후 새로 시작' : '🚀 전략 시작';
        return;  // 강제 차단! (= confirm 무시)
      }
      if (ratio > 1.5) {
        const pctDiff = ((ratio - 1) * 100).toFixed(1);
        const sideLabel = cmState.side === 'SHORT' ? '📉 SHORT' : '📈 LONG';
        const directionHint = cmState.side === 'SHORT'
          ? (startPriceNum < currentPrice ? '⚠️ SHORT + 시작가 < 현재가 = 즉시 손실 진입!' : '⚠️ SHORT + 시작가 >> 현재가 = LIMIT 미체결!')
          : (startPriceNum > currentPrice ? '⚠️ LONG + 시작가 > 현재가 = 즉시 손실 진입!' : '⚠️ LONG + 시작가 << 현재가 = LIMIT 미체결!');
        const proceed = confirm(
          `🚨 시작가 vs 현재가 큰 차이 감지! (silent bug 가능성!)\n\n` +
          `📌 심볼: ${symbol} ${sideLabel}\n` +
          `📌 시작가 (입력): ${startPriceNum}\n` +
          `📌 현재가 (Binance): ${currentPrice}\n` +
          `📌 차이: ${pctDiff}% (= ${ratio.toFixed(2)}배 차이!)\n\n` +
          `${directionHint}\n\n` +
          `🚨 위험:\n` +
          `  • 옛 strategy 시작가 silent 재사용 가능성\n` +
          `  • 트리거 절대 도달 X = 자동 진입 X\n` +
          `  • LIMIT 주문 미체결 위험\n` +
          `  • 사장님 자본 위험!\n\n` +
          `💡 사장님 선택:\n` +
          `  • 「취소」 (추천!) = 시작가 수정 + 「현재가」 버튼 클릭\n` +
          `  • 「확인」 = 의도적 진행 (= 사장님 의도 = 옛 가격 사용)`
        );
        if (!proceed) {
          document.getElementById('cm-submit').disabled = false;
          document.getElementById('cm-submit').textContent = editingId ? '🔄 종료 후 새로 시작' : '🚀 전략 시작';
          return;
        }
      }
    }
  } catch (e) {
    console.warn('[v21] 시작가 검증 실패 (= 진행):', e);
  }

  const confirmMsg = editingId
    ? `🔄 전략 #${editingId} 수정\n\n1. 기존 미체결 주문 자동 취소\n2. 새 설정으로 ${symbol} ${cmState.side==='SHORT'?'📉 숏':'📈 롱'} 전략 시작\n\n시작가: ${fmtNum(startPrice)}\n총 자본: ${fmtNum(cmState.preview.stages.reduce((s,x)=>s+Number(x.planned_capital||0),0))} USDT\n\n진행할까요?`
    : `${symbol} ${cmState.side==='SHORT'?'📉 숏':'📈 롱'} 전략을 시작합니다.\n\n시작가: ${fmtNum(startPrice)}\n총 자본: ${fmtNum(cmState.preview.stages.reduce((s,x)=>s+Number(x.planned_capital||0),0))} USDT\n\n진행할까요? (testnet 거래소면 실거래 발생)`;
  if (!confirm(confirmMsg)) return;
  try {
    document.getElementById('cm-submit').disabled = true;
    document.getElementById('cm-submit').textContent = editingId ? '⏳ 종료 + 재시작 중...' : '⏳ 생성 중...';

    // 수정 모드 — 기존 전략 먼저 cancel_only 로 정지
    if (editingId) {
      try {
        await api(`/strategies/${editingId}/stop`, {
          method: 'POST',
          body: { mode: 'cancel_only', reason: '수정 모드 — 새 설정으로 재시작' },
        });
        toast(`전략 #${editingId} 미체결 주문 취소 완료`, 'success');
      } catch (e) {
        // 이미 종료됐거나 주문 없으면 무시하고 계속
        console.warn('Cancel old strategy:', e.message);
      }
    }

    // 직접 입력 모드 — 이 시점에만 템플릿 1번 생성
    let templateId = cmState.templateId;
    // UX #18: 레버리지는 입력 필드에서 가져옴. 비었으면 사이드 기본값.
    const lvInpEl = document.getElementById('cm-leverage');
    const leverageFromInput = lvInpEl && lvInpEl.value ? Number(lvInpEl.value) : _defaultLeverageForSide(cmState.side);
    if (cmState.mode === 'direct') {
      const ts = new Date().toISOString().replace(/[^0-9]/g, '').slice(0, 14);
      const leverage = leverageFromInput;
      const inp = cmState._directInputs || _collectDirectInputs();
      const tpsl = cmState._directTpsl || _collectTpSl();
      // 2026-05-06 사용자 보고 fix: 이전엔 TP1~5 만 전송 → 신규 strategy 의 template 에
      // TP6~10 NULL 저장됨. _collectTpSl 는 TP1~10 수집하지만 여기서 안 보내서 누락.
      // dict comprehension 으로 TP1~10 모두 동적 전송 (TP4~10 NULL 이면 그대로 NULL).
      const _tpFields = {};
      for (let n = 1; n <= 10; n++) {
        _tpFields[`tp${n}_percent`] = tpsl[`tp${n}_percent`];
        _tpFields[`tp${n}_qty_ratio`] = tpsl[`tp${n}_qty_ratio`];
      }
      const tplCreated = await api('/admin/strategy-templates', {
        method: 'POST',
        body: {
          name: `_quick_${ts}`,
          strategy_type: cmState.side === 'SHORT' ? 'DYNAMIC_SHORT' : 'DYNAMIC_LONG',
          side: cmState.side,
          leverage,
          capitals: inp.capitals,
          trigger_percents: inp.trigger_percents,
          additional_margins: inp.additional_margins,
          last_stage_trigger_percent: inp.last_stage_trigger_percent,
          ..._tpFields,  // TP1~10 모두 (TP4~10 NULL 가능)
          stop_loss_percent_of_capital: tpsl.stop_loss_percent_of_capital,
          crisis_max_loss_threshold: tpsl.crisis_max_loss_threshold,
          reentry_policy: 'manual_ready',
        },
      });
      templateId = tplCreated.id;
    }

    const created = await api('/strategies', {
      method: 'POST',
      body: {
        exchange_account_id: cmState.accountId,
        strategy_template_id: templateId,
        symbol, side: cmState.side, start_price: startPrice,
        // UX #18: 레버리지 override (템플릿 기본값을 덮어씀)
        leverage_override: leverageFromInput,
      },
    });
    toast('✅ 전략 #' + created.id + ' 생성됨. 1단계 주문 발송 중...', 'success');
    try {
      await api('/strategies/' + created.id + '/start', { method: 'POST' });
      toast('🚀 전략 #' + created.id + ' 시작 완료. 1단계 주문 발송됨.', 'success');
    } catch (startErr) {
      // 🌟 2026-06-09 사장님 -4412 친절화: Binance 에러 코드별 명확 안내
      const errMsg = String(startErr.message || startErr);
      let friendlyMsg = '';
      if (errMsg.includes('-4412')) {
        friendlyMsg = `🌍 Binance 지역 제한 (= 사장님 행동 X 가능)\n\n` +
          `심볼: ${symbol} | ${cmState.side}\n\n` +
          `이유 (3가지 중 1):\n` +
          `  ① 이 심볼이 사장님 지역에서 거래 차단\n` +
          `  ② VPS IP (159.65.137.250) 가 제한 지역 인식\n` +
          `  ③ API 키 futures 권한 갱신 필요\n\n` +
          `해결책:\n` +
          `  ✅ 다른 메인 심볼 시도 (BTCUSDT, ETHUSDT, SOLUSDT)\n` +
          `  ✅ Binance 웹사이트에서 = 이 심볼 거래 가능 확인\n` +
          `  ✅ 전략 #${created.id} 는 보관 처리 권장 (=⛔ 진입 실패)`;
      } else if (errMsg.includes('-2010') || errMsg.includes('-2019')) {
        friendlyMsg = `💰 잔액/마진 부족\n전략 #${created.id} = 진입 실패. 잔액 확인 후 재시도.`;
      } else if (errMsg.includes('-4061')) {
        friendlyMsg = `🔄 Position mode 불일치 (Hedge vs One-way)\n전략 #${created.id} = 진입 실패. 계정 설정 확인.`;
      } else {
        friendlyMsg = `전략 #${created.id} 생성됐지만 시작 실패\n에러: ${errMsg}\n수동으로 다시 시도하거나 보관 처리하세요.`;
      }
      toast(friendlyMsg, 'warning');
      console.error('[strategy start failed]', startErr);
    }
    closeCreateModal();
    refreshStrategies();
    refreshTemplates();
    // 🌟 2026-06-09 사장님 요청: 전략 생성 시 = 즉시 잔액 갱신 (5초 polling 기다리지 X)
    if (typeof loadBalance === 'function') loadBalance();
  } catch (e) {
    toast('전략 생성 실패: '+e.message, 'error');
    document.getElementById('cm-submit').disabled = false;
    document.getElementById('cm-submit').textContent = '🚀 전략 시작';
  }
}
