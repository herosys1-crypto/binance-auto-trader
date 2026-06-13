/**
 * Create-Modal — 단계별 capital grid + 실시간 계산 (Phase 3 단계 3e, 2026-05-14).
 *
 * 단계별 input 변경 시 실시간 단계 진입가 / 평균진입 / 청산가 / 누적 손실 % / USDT 계산.
 *
 * 함수:
 *   - _defaultTriggerPct(stageNo)  : 1=빈, 2~4=10%, 5+=20%
 *   - buildCapitalsGrid()           : 10단계 grid HTML 생성 (모달 진입 시)
 *   - _refreshLiveCalc()             : 입력 변경 시 모든 단계 재계산 + UI 갱신
 *   - onCapitalsChange()             : 합계 재계산 + summary 표시 + preview 무효화
 *
 * 외부 의존성 (script-scope 공유):
 *   - cmState (mutable)
 *   - _decimalsForPrice (cm-market-info.js)
 *   - _estimateLiquidationPrice (index.html — 호출 시점에 정의됨)
 *   - fmtNum (helpers.js)
 *   - updateCmSubmit (index.html)
 *   - DOM: #cm-capitals-grid, #cm-cap-{1..10}, #cm-trg-{1..10}, #cm-add-margin-{1..10},
 *     #cm-stage-{entry,avg,liq,loss,lossusd}-{1..10}, #cm-start-price, #cm-leverage,
 *     #cm-capitals-summary, #cm-preview
 */

function _defaultTriggerPct(stageNo) {
  // 🌟 2026-06-09 사장님 신 default: 2단계만 10%, 3~10단계 모두 20%
  // 사장님 명시: "2단계만 트리거 10으로 하고 나머진 20%로 해줘"
  if (stageNo === 1) return '';
  if (stageNo === 2) return '10';
  return '20';
}

function buildCapitalsGrid() {
  const grid = document.getElementById('cm-capitals-grid');
  // 헤더 + 10행 — 단계 / 자본 / 트리거% / 단계 진입가 / 누적 평균진입 / 청산가 / 누적 손실%
  // (실시간 계산 — 입력 즉시 갱신)
  // 2026-06-08 사장님 요구: 「자본」 input = 만 단위 (5자) 까지 잘 보이게 가로 확장.
  // 옛 col-span-1 (12분의 1 ≈ 8.3%) = 100 단위 (3자) 만 보이고 잘림.
  // 신 col-span-2 = 12분의 2 ≈ 16.7% = 만 단위 ~ 십만 단위 (5~6자) 충분.
  // 「평균진입」 col-span 2 → 1 로 축소 (계산값 = 보통 7자 = col-span 1 = 약 60px = 충분).
  // 합계 12 유지: 단계(1) + 자본(2) + 트리%(1) + 증거금(1) + 진입가(2) + 평균(1) + 청산(1) + 손실율(1) + 손실$(2) = 12 ✅
  let html = `<div class="grid grid-cols-12 gap-1 text-xs text-slate-500 px-1 pb-1 border-b border-slate-700 mb-1">
    <div class="col-span-1">단계</div>
    <div class="col-span-2">💵 자본</div>
    <div class="col-span-1">📊 트리%</div>
    <div class="col-span-1 text-yellow-400" title="단계 진입 직후 추가로 투입할 isolated 증거금 (USDT). 비우거나 0 = 추가 안 함. 청산가를 멀리 밀어 안전 마진 확보 (사용자 요청, 2026-05-11)">💰 증거금</div>
    <div class="col-span-2 text-right text-purple-400" title="이 단계의 LIMIT 진입 가격 (이전 단계 × (1±trigger%))">단계 진입가</div>
    <div class="col-span-1 text-right text-cyan-400" title="이 단계까지 누적 가중평균 진입가">평균진입</div>
    <div class="col-span-1 text-right text-orange-400" title="누적 평균 기준 예상 청산가 (Isolated 보수적)">청산가</div>
    <div class="col-span-1 text-right text-red-400" title="이 단계 = 진입 전 (위) + 진입 후 (아래) 누적 ROI %">손실율<br><span class="text-[9px] text-slate-500">전/후</span></div>
    <div class="col-span-2 text-right text-red-300" title="이 단계 진입 시점의 누적 손실 USDT">손실$</div>
  </div>`;
  for (let i = 1; i <= 10; i++) {
    let triggerPlaceholder, triggerDisabled, triggerTitle, triggerValue;
    if (i === 1) {
      triggerPlaceholder = '시작가에 즉시 진입';
      triggerDisabled = 'disabled';
      triggerTitle = '1단계는 운영자가 입력한 시작가에 즉시 LIMIT 주문 발송';
      triggerValue = '';
    } else {
      // 사용자 기획 변경 (2026-04-30): 10단계도 직접 입력 가능 (PRICE_UP_PCT/DOWN_PCT).
      // 이전엔 LIQUIDATION_BUFFER 로 disabled 였음.
      triggerPlaceholder = '';
      triggerDisabled = '';
      triggerTitle = `직전 단계 대비 +${_defaultTriggerPct(i)}% (▲▼ 1씩 조정)`;
      triggerValue = _defaultTriggerPct(i);  // 기본값 미리 채움 → ▲▼ 즉시 동작
    }
    const capPlaceholder = i === 1 ? '예: 100' : '비움';
    // 2026-06-08 사장님 요구: 자본 col-span 1→2 (만 단위 보이게) + 평균 2→1 (합 12 유지)
    html += `<div class="grid grid-cols-12 gap-1 items-center">
      <div class="col-span-1 text-xs text-slate-300 font-semibold">${i}단계</div>
      <div class="col-span-2">
        <input type="number" min="0" step="any" id="cm-cap-${i}" placeholder="${capPlaceholder}"
          oninput="onCapitalsChange(); _refreshLiveCalc()"
          title="단계별 투입 자본 (USDT). 1단계 필수, 2단계 이후 비우면 그 단계 사용 안 함. 만 단위까지 입력 가능."
          class="w-full px-1 py-1 bg-slate-900 border border-slate-700 rounded text-white text-sm" />
      </div>
      <div class="col-span-1">
        <input type="number" min="0" step="1" id="cm-trg-${i}" placeholder="${triggerPlaceholder}" value="${triggerValue}" ${triggerDisabled}
          title="${triggerTitle}"
          oninput="onCapitalsChange(); _refreshLiveCalc()"
          class="w-full px-1 py-1 bg-slate-900 border border-slate-700 rounded text-white text-sm ${triggerDisabled?'opacity-50 cursor-not-allowed':''}" />
      </div>
      <div class="col-span-1">
        <input type="number" min="0" step="any" id="cm-add-margin-${i}" placeholder="0"
          title="단계 ${i} 진입 직후 추가로 투입할 isolated 증거금 (USDT). 비우면 추가 안 함."
          oninput="onCapitalsChange(); _refreshLiveCalc()"
          class="w-full px-1 py-1 bg-slate-900 border border-yellow-800 rounded text-yellow-300 text-sm" />
      </div>
      <div class="col-span-2 text-xs text-purple-300 text-right" id="cm-stage-entry-${i}" title="이 단계의 LIMIT 진입가">-</div>
      <div class="col-span-1 text-xs text-cyan-300 text-right" id="cm-stage-avg-${i}" title="이 단계까지 누적 평균 진입가">-</div>
      <div class="col-span-1 text-xs text-orange-300 text-right" id="cm-stage-liq-${i}" title="평균 기준 예상 청산가">-</div>
      <div class="col-span-1 text-xs text-red-400 text-right" id="cm-stage-loss-${i}" title="이 단계 진입 시점의 누적 ROI %">-</div>
      <div class="col-span-2 text-xs text-red-300 text-right" id="cm-stage-lossusd-${i}" title="이 단계 진입 시점의 누적 손실 USDT (단조 증가)">-</div>
    </div>`;
  }
  grid.innerHTML = html;
}

// 단계별 input 변경 시 실시간 단계 진입가 + 평균진입가 + 청산가 + 손실율 계산
// (미리보기 클릭 전에도 즉시 표시)
function _refreshLiveCalc() {
  try {
    const startPriceStr = document.getElementById('cm-start-price').value;
    const startPrice = Number(startPriceStr);
    const clearAll = () => {
      for (let i = 1; i <= 10; i++) {
        ['cm-stage-entry-', 'cm-stage-avg-', 'cm-stage-liq-', 'cm-stage-loss-', 'cm-stage-lossusd-'].forEach(prefix => {
          const el = document.getElementById(prefix + i);
          if (el) el.textContent = '-';
        });
      }
    };
    if (!startPrice || startPrice <= 0) { clearAll(); return; }
    const lvInpEl = document.getElementById('cm-leverage');
    const lev = lvInpEl && lvInpEl.value ? Number(lvInpEl.value) : 2;
    const side = (cmState.side || 'SHORT').toUpperCase();
    // 마지막 단계 = 첫 빈 capital 직전. 백엔드와 일치 (capitals 컷오프).
    let lastStageNo = 0;
    for (let k = 1; k <= 10; k++) {
      const v = (document.getElementById('cm-cap-' + k) || {}).value;
      if (v === '' || v === null || v === undefined || Number(v) === 0) break;
      lastStageNo = k;
    }
    const DEFAULT_LAST_TRIGGER_PCT = 20;  // backend 와 동일 (DEFAULT_LAST_*_TRIGGER_PCT)
    let prevPrice = startPrice;
    let cumQty = 0, cumNotional = 0, cumMargin = 0;
    let prevLiq = null;
    // 🌟 2026-06-13 사장님 critical: 단계별 청산 분석 데이터 (= 신 박스용!)
    const stageAnalysis = [];
    // 2026-06-03 사장님 사상: 빈 단계 자동 압축 + trigger 누적 (_collectDirectInputs 와 일치).
    // 빈 자본 단계 = '-' 표시 + 그 단계 trigger 는 다음 채워진 단계에 누적.
    let pendingTriggerPct = 0;
    let compressedStageNo = 0;  // 새 단계 번호 (압축 후)
    const compressionMap = {};  // 원 단계 → 새 단계 (사장님 시각화 도움)
    for (let i = 1; i <= 10; i++) {
      const capEl = document.getElementById('cm-cap-' + i);
      const trgEl = document.getElementById('cm-trg-' + i);
      const entryEl = document.getElementById('cm-stage-entry-' + i);
      const avgEl = document.getElementById('cm-stage-avg-' + i);
      const liqEl = document.getElementById('cm-stage-liq-' + i);
      const lossEl = document.getElementById('cm-stage-loss-' + i);
      const lossUsdEl = document.getElementById('cm-stage-lossusd-' + i);
      if (!capEl || !avgEl) continue;
      const cap = Number(capEl.value);
      const tNum = Number(trgEl ? trgEl.value : 0) || 0;
      // 빈 자본 단계 — '-' 표시 + trigger 누적 (다음 채워진 단계에 합산)
      if (!cap || cap <= 0) {
        if (i > 1 && tNum > 0) pendingTriggerPct += tNum;
        if (entryEl) { entryEl.textContent = '-'; entryEl.className = 'col-span-2 text-xs text-purple-300 text-right'; }
        if (avgEl) { avgEl.textContent = '-'; avgEl.className = 'col-span-1 text-xs text-cyan-300 text-right'; }
        if (liqEl) { liqEl.textContent = '-'; liqEl.innerHTML = '-'; liqEl.className = 'col-span-1 text-xs text-orange-300 text-right'; }
        if (lossEl) {
          const note = tNum > 0
            ? `<span class="text-yellow-300" title="자본 없음 — 다음 채워진 단계에 trigger +${tNum}% 누적">↳ +${tNum}% 누적</span>`
            : '-';
          lossEl.innerHTML = note;
          lossEl.className = 'col-span-1 text-xs text-right';
        }
        if (lossUsdEl) { lossUsdEl.textContent = '-'; lossUsdEl.className = 'col-span-2 text-xs text-red-300 text-right'; }
        // border 제거 (이전 cycle 잔재)
        capEl.classList.remove('border-red-500');
        capEl.style.borderWidth = '';
        continue;
      }
      // 채워진 단계 — 압축 후 새 단계 번호
      compressedStageNo += 1;
      compressionMap[i] = compressedStageNo;
      // border 제거 (이전 cycle 잔재)
      capEl.classList.remove('border-red-500');
      capEl.style.borderWidth = '';
      // 🌟 2026-06-08 사장님 「수정 모드」 사상 (Phase 3):
      // 신 strategy: 모든 단계 = 시작가 부터 누적 (옛 로직 그대로)
      // 수정 모드: 진입 단계 (1~current_stage) = 옛 진입가 시각 (= 사장님 보호)
      //           첫 미진입 단계 = **시작가 (= 현재가) × (1 + trigger%)** ⭐
      //           이후 미진입 단계 = 첫 미진입 단계 기준 누적
      let _editCurrentStage = 0;
      if (cmState.editingStrategyId) {
        const _srcStrategy = (window._strategiesById || {})[cmState.editingStrategyId];
        _editCurrentStage = Number(_srcStrategy?.current_stage || 0);
      }
      // 1) 이 단계 진입가 (raw, leverage 무관) — 사장님 사상: 빈 단계 trigger 누적
      let entryPrice;
      if (compressedStageNo === 1) {
        // 🌟 2026-06-11 v40 사장님 critical 사상 (= BEATUSDT 수정 사례!):
        // 사장님 명시: "현재가를 실행하지 않는한 처음에 세팅할때 잡혀있는 단가로 세팅
        //              두번째는 현재가 기준으로 새롭게 세팅으로 하면 2단계부터 진행할수 있는 세팅"
        // = 수정 모드 + 시작가 변경 (= 사장님 「현재가」 클릭) 시:
        //   1단계 = 옛 평단 (= 사장님 진입 보존!)
        //   2단계+ = 신 시작가 기준 재계산
        if (cmState.editingStrategyId && cmState.editingStrategyBp) {
          const oldAvg = Number(cmState.editingStrategyBp.avg_entry_price || 0);
          const oldStart = Number(cmState.editingStrategyBp.start_price || 0);
          const startChanged = oldStart > 0 && startPrice > 0 && Math.abs(startPrice - oldStart) / oldStart > 0.001;
          if (oldAvg > 0 && startChanged) {
            entryPrice = oldAvg;  // 1단계 = 옛 평단 보존!
            // 2단계+ = startPrice 기준 (= prevPrice 별도 처리!)
          } else {
            entryPrice = startPrice;  // 시작가 변경 X = 옛 값
          }
        } else {
          entryPrice = startPrice;  // 신 strategy = 시작가 그대로
        }
        pendingTriggerPct = 0;  // 첫 단계 누적 무시
      // 🚨 2026-06-11 v43 사장님 critical fix: 옛 v100 분기 폐기!
      // 옛 silent bug: 첫 미진입 단계 = startPrice × (1 + trigger%)
      // = 사장님 사진 6단계 = 9.52 (= 사장님 누적 사상 위배!)
      //
      // 신 v43 사상 (= v40 완성):
      // 모든 단계 (1단계 제외) = 이전 단계 진입가 기준 누적!
      // = 옛 v100 분기 제거 → 정상 누적 logic 사용
      } else {
        // 사용자 #5-07 fix: 마지막 단계 trigger 비어있으면 backend 기본 20%
        let trgPct = tNum;
        if (i === lastStageNo && trgPct === 0) trgPct = DEFAULT_LAST_TRIGGER_PCT;
        // 빈 단계 누적 trigger 합산 (사장님 사상)
        const effectiveTrgPct = trgPct + pendingTriggerPct;
        pendingTriggerPct = 0;  // 사용 후 리셋
        if (side === 'SHORT') {
          entryPrice = prevPrice * (1 + effectiveTrgPct / 100);
        } else {
          entryPrice = prevPrice * (1 - effectiveTrgPct / 100);
        }
      }

      // ★ 직전 ROI 계산 — 이 단계 진입 *직전* (이전 단계까지 누적, 가격은 entryPrice)
      // 의미: 가격이 이 단계 trigger 도달했지만 아직 자본 추가 안 한 시점
      let preRoi = null;
      let preUsd = null;
      if (i > 1 && cumQty > 0 && cumMargin > 0) {
        const preAvg = cumNotional / cumQty;  // 이전 단계까지 평균 (현재 cumQty/cumNotional)
        if (side === 'SHORT') {
          preUsd = cumQty * (preAvg - entryPrice);
        } else {
          preUsd = cumQty * (entryPrice - preAvg);
        }
        preRoi = preUsd / cumMargin * 100;
      }

      // 2) 누적 — qty (capital × lev / price), notional (qty × price), margin (cap)
      const qty = (cap * lev) / entryPrice;
      cumQty += qty;
      cumNotional += qty * entryPrice;
      cumMargin += cap;
      const avg = cumNotional / cumQty;
      // 3) 청산가 (누적 평균 기준)
      const liq = _estimateLiquidationPrice(side, avg, lev);
      // 🌟 2026-06-13 사장님 critical: 증거금 추가 후 청산가 효과!
      // 증거금 = 추가 margin (위치 유지, qty 변경 X)
      // 청산가 변화 = margin 늘어남 = 가격 변동 견디는 한도 증가!
      const addMarginEl = document.getElementById('cm-add-margin-' + i);
      const addMargin = Number(addMarginEl ? addMarginEl.value : 0) || 0;
      let liqWithMargin = liq;
      if (addMargin > 0 && cumQty > 0) {
        // 신 청산가 = avg ± (cumMargin + addMargin) / cumQty (= margin per qty)
        // SHORT: 가격 상승 시 손실, 청산가 = avg + (margin / qty)
        // LONG: 청산가 = avg - (margin / qty)
        const marginPerQty = (cumMargin + addMargin) / cumQty;
        if (side === 'SHORT') {
          liqWithMargin = avg + marginPerQty;
        } else {
          liqWithMargin = Math.max(0, avg - marginPerQty);
        }
      }
      // 4) 이 단계 진입 시점 손실율 (누적 ROI, margin 대비, leverage 적용)
      //    SHORT: ROI = (avg - entry) / avg × leverage × 100  (entry > avg 면 손실 음수)
      //    LONG:  ROI = (entry - avg) / avg × leverage × 100
      let roi;
      if (side === 'SHORT') {
        roi = (avg - entryPrice) / avg * lev * 100;
      } else {
        roi = (entryPrice - avg) / avg * lev * 100;
      }
      // 청산 위험 색상 (이 단계 진입가가 이전 단계의 청산가 위 → SHORT 도달 불가)
      let liqColor = 'text-orange-300';
      if (prevLiq !== null && i > 1) {
        if (side === 'SHORT' && entryPrice >= prevLiq) liqColor = 'text-red-400 font-bold';
        if (side === 'LONG' && entryPrice <= prevLiq) liqColor = 'text-red-400 font-bold';
      }
      const decimals = _decimalsForPrice(avg);
      if (entryEl) entryEl.textContent = entryPrice.toFixed(decimals);
      if (avgEl) avgEl.textContent = avg.toFixed(decimals);
      if (liqEl) {
        // 🌟 2026-06-13 사장님 critical fix v2: 청산가 = 강력 방어 + 절대 빈칸 X!
        try {
          if (addMargin > 0 && Number.isFinite(liqWithMargin)) {
            liqEl.innerHTML = `<div class="leading-none">${liqWithMargin.toFixed(decimals)}</div>` +
                              `<div class="leading-none text-[9px] text-yellow-300" title="옛 청산가: ${Number.isFinite(liq) ? liq.toFixed(decimals) : '?'}">+${addMargin}$</div>`;
          } else if (Number.isFinite(liq)) {
            liqEl.textContent = liq.toFixed(decimals);
          } else {
            // 디버그: liq 가 NaN/undefined = 절대 안 일어나야!
            liqEl.textContent = '⚠️NaN';
            console.warn('[liq] 단계 ' + i + ' = liq NaN!', { side, avg, lev, liq, liqWithMargin });
          }
          liqEl.className = 'col-span-1 text-xs text-right ' + liqColor;
        } catch (_liqErr) {
          liqEl.textContent = '⚠️Err';
          console.error('[liq] 단계 ' + i + ' 표시 실패!', _liqErr);
        }
      }
      if (lossEl) {
        // 🌟 2026-06-13 사장님 critical: 진입 전 + 진입 후 ROI = 줄바꿈 = 모두 명확 표시!
        // 옛: "X% → Y%" 한 줄 = "→" 뒤 잘림 silent bug!
        // 신: 두 줄 = 진입전 (큰) / 진입후 (작은) 모두 명확!
        const postTxt = (roi >= 0 ? '+' : '') + roi.toFixed(2) + '%';
        const postColor = roi < -85 ? 'text-red-500 font-bold' : (roi < -50 ? 'text-red-400 font-semibold' : (roi < 0 ? 'text-red-300' : 'text-emerald-300'));
        let html;
        let dangerWarn = '';
        if (preRoi !== null) {
          const preTxt = (preRoi >= 0 ? '+' : '') + preRoi.toFixed(2) + '%';
          let preColor;
          if (preRoi < -85) {
            preColor = 'text-red-500 font-bold';
            dangerWarn = '⚠️';
          } else if (preRoi < -50) {
            preColor = 'text-red-400 font-semibold';
          } else {
            preColor = 'text-red-300';
          }
          // 🌟 신: 줄바꿈 = 진입 전 (위) + 진입 후 (아래, 작게)
          html = `<div class="${preColor} leading-none" title="진입 직전 누적 ROI">${preTxt}${dangerWarn}</div>` +
                 `<div class="${postColor} leading-none text-[10px] mt-0.5" title="진입 직후 누적 ROI (= 평단 변경 후)">→ ${postTxt}</div>`;
        } else {
          // 1단계 = 진입 전 없음 = 단일 표시
          html = `<div class="${postColor}" title="1단계 진입 후 ROI">${postTxt}</div>`;
        }
        lossEl.innerHTML = html;
        lossEl.className = 'col-span-1 text-xs text-right';
      }
      // USDT 누적 손실 — 단조 증가, 직관적 절대 위험도
      // SHORT 손실 USDT = cumQty × (avg - entry)  (음수면 손실)
      if (lossUsdEl) {
        let pnlUsd;
        if (side === 'SHORT') {
          pnlUsd = cumQty * (avg - entryPrice);
        } else {
          pnlUsd = cumQty * (entryPrice - avg);
        }
        const usdText = (pnlUsd >= 0 ? '+' : '') + pnlUsd.toLocaleString('en-US', { maximumFractionDigits: 2 }) + ' $';
        const usdColor = pnlUsd < 0 ? 'text-red-300' : 'text-emerald-300';
        lossUsdEl.textContent = usdText;
        lossUsdEl.className = 'col-span-2 text-xs text-right ' + usdColor;
      }
      // 🌟 2026-06-13 사장님 critical: 단계별 청산 분석 데이터 모음!
      // 사장님 자율 청산 회피 전략 = "최대한 청산가 전 다음 단계 진입!"
      stageAnalysis.push({
        stageNo: compressedStageNo,
        origStageNo: i,
        entryPrice: entryPrice,
        avg: avg,
        liq: liq,
        liqWithMargin: liqWithMargin,
        addMargin: addMargin,
        cap: cap,
        cumMargin: cumMargin,
        preRoi: preRoi,
        postRoi: roi,
        prevLiq: prevLiq,
        // 도달 가능성: 이 단계 trigger 가 이전 단계 청산가 (증거금 포함!) 보다 안전한지!
        reachable: prevLiq === null ? true : (side === 'SHORT' ? entryPrice < prevLiq : entryPrice > prevLiq),
        // 안전 마진 % (현재 청산가까지 가격이 얼마나 멀리?)
        safetyMarginPct: side === 'SHORT'
          ? ((liqWithMargin - entryPrice) / entryPrice * 100)
          : ((entryPrice - liqWithMargin) / entryPrice * 100),
      });

      // 🌟 v40 사장님 사상: 1단계 = 옛 평단 보존 시 = 2단계 기준 = startPrice (= entryPrice 아님!)
      // = 사장님 사상: '2단계부터 진행할 수 있는 세팅' = 신 시작가 기준!
      if (compressedStageNo === 1 && cmState.editingStrategyId && cmState.editingStrategyBp) {
        const oldAvg = Number(cmState.editingStrategyBp.avg_entry_price || 0);
        const oldStart = Number(cmState.editingStrategyBp.start_price || 0);
        const startChanged = oldStart > 0 && startPrice > 0 && Math.abs(startPrice - oldStart) / oldStart > 0.001;
        if (oldAvg > 0 && startChanged) {
          prevPrice = startPrice;  // 2단계 = startPrice × (1 + trigger%) = 신 시작!
        } else {
          prevPrice = entryPrice;  // 옛 동작
        }
      } else {
        prevPrice = entryPrice;
      }
      // 🌟 2026-06-13 사장님 critical: 다음 단계 도달 가능성 검증 = 증거금 추가 후 청산가 기준!
      prevLiq = liqWithMargin;
    }

    // 🌟 2026-06-13 사장님 critical: 신 「단계별 청산 분석 박스」 표시!
    _renderStageAnalysisBox(stageAnalysis, side, lev);
    // 2026-06-03 사장님 사상: 빈 단계 자동 압축 + trigger 누적 안내 (silent drop 경고 제거)
    let infoBox = document.getElementById('cm-capitals-compression-info');
    const compressedCount = Object.keys(compressionMap).length;
    const originalMax = Math.max(0, ...Object.keys(compressionMap).map(Number));
    const hasCompression = originalMax > compressedCount && compressedCount > 0;
    if (hasCompression) {
      if (!infoBox) {
        infoBox = document.createElement('div');
        infoBox.id = 'cm-capitals-compression-info';
        infoBox.className = 'mt-2 p-2 rounded bg-blue-900/30 border border-blue-500';
        const grid = document.getElementById('cm-capitals-grid');
        if (grid && grid.parentNode) {
          grid.parentNode.insertBefore(infoBox, grid.nextSibling);
        }
      }
      // 압축 매핑 표시 (예: "4→3, 5→4")
      const mappingTxt = Object.entries(compressionMap)
        .filter(([orig, comp]) => Number(orig) !== comp)
        .map(([orig, comp]) => `${orig}→${comp}`)
        .join(', ');
      infoBox.innerHTML =
        `<p class="text-sm text-blue-300 font-semibold">✅ 빈 단계 자동 압축 (사장님 사상 2026-06-03)</p>` +
        `<p class="text-xs text-slate-200 mt-1">빈 자본 단계는 자동 skip → 채워진 ${compressedCount}개 단계만 사용. 단계 번호 재배치: <strong>${mappingTxt}</strong></p>` +
        `<p class="text-xs text-yellow-300 mt-1">💡 빈 단계의 trigger % 가 있으면 다음 채워진 단계의 trigger 에 자동 누적 (예: 3 비움 +10% → 4단계 (새 3단계) +10% → 합산 +20%)</p>`;
      infoBox.style.display = 'block';
    } else if (infoBox) {
      infoBox.style.display = 'none';
    }
  } catch (e) {
    // 🚨 2026-06-13 사장님 critical: silent fail 차단 = 사장님 = F12 console 즉시 확인!
    console.error('[_refreshLiveCalc] 사장님 silent bug 감지!', e);
  }
}

// 🌟 2026-06-13 사장님 critical: 신 「단계별 청산 분석 박스」
// 사장님 자율 청산 회피 전략 = "1단계 진입 후 청산가 직전까지 다음 단계 진입!" 100% 시각화!
function _renderStageAnalysisBox(stages, side, lev) {
  let box = document.getElementById('cm-stage-analysis-box');
  const gridEl = document.getElementById('cm-capitals-grid');
  if (!stages || stages.length === 0) {
    if (box) box.style.display = 'none';
    return;
  }
  if (!box) {
    box = document.createElement('div');
    box.id = 'cm-stage-analysis-box';
    box.className = 'mt-3 p-3 rounded bg-slate-900/60 border border-cyan-700';
    if (gridEl && gridEl.parentNode) {
      gridEl.parentNode.insertBefore(box, gridEl.nextSibling);
    }
  }
  box.style.display = 'block';

  const decimals = stages[0] ? _decimalsForPrice(stages[0].avg || 1) : 4;
  let unreachableCount = 0;
  let rowsHtml = '';
  stages.forEach((s, idx) => {
    const isFirst = idx === 0;
    const reachableIcon = isFirst ? '✅' : (s.reachable ? '✅' : '❌');
    const reachableTxt = isFirst ? '즉시 진입' : (s.reachable ? '도달 가능' : '도달 불가!');
    const reachableColor = isFirst ? 'text-emerald-300' : (s.reachable ? 'text-emerald-300' : 'text-red-400 font-bold');
    if (!isFirst && !s.reachable) unreachableCount++;

    const marginEffectTxt = s.addMargin > 0
      ? `<span class="text-yellow-300">💰 증거금 +${s.addMargin}: 청산가 ${s.liq.toFixed(decimals)} → ${s.liqWithMargin.toFixed(decimals)}</span>`
      : `<span class="text-slate-500">증거금 X</span>`;

    const safetyColor = s.safetyMarginPct > 30 ? 'text-emerald-300' : (s.safetyMarginPct > 10 ? 'text-yellow-300' : 'text-red-400');
    const preRoiTxt = s.preRoi !== null ? `${s.preRoi >= 0 ? '+' : ''}${s.preRoi.toFixed(2)}%` : '-';
    const postRoiTxt = `${s.postRoi >= 0 ? '+' : ''}${s.postRoi.toFixed(2)}%`;

    rowsHtml += `
      <div class="border-t border-slate-700 py-1.5 text-xs">
        <div class="flex justify-between items-center mb-0.5">
          <span class="font-semibold text-cyan-300">📍 ${s.stageNo}단계 ${reachableIcon} <span class="${reachableColor}">${reachableTxt}</span></span>
          <span class="text-slate-400">진입가 <b class="text-purple-300">${s.entryPrice.toFixed(decimals)}</b></span>
        </div>
        <div class="grid grid-cols-2 gap-1 text-[11px]">
          <div>📊 진입 전 ROI: <b class="text-red-300">${preRoiTxt}</b></div>
          <div>📈 진입 후 ROI: <b class="text-red-300">${postRoiTxt}</b></div>
          <div>📐 평단: <b class="text-cyan-300">${s.avg.toFixed(decimals)}</b></div>
          <div>🛑 청산가: <b class="text-orange-300">${s.liqWithMargin.toFixed(decimals)}</b></div>
          <div class="col-span-2">${marginEffectTxt}</div>
          <div class="col-span-2">🛡 안전 마진: <b class="${safetyColor}">${s.safetyMarginPct >= 0 ? '+' : ''}${s.safetyMarginPct.toFixed(2)}%</b> <span class="text-slate-500">(= 청산가까지 가격 거리)</span></div>
        </div>
      </div>
    `;
  });

  let warningHtml = '';
  if (unreachableCount > 0) {
    warningHtml = `
      <div class="mt-2 p-2 rounded bg-red-900/40 border border-red-500">
        <p class="text-sm font-bold text-red-400">⚠️ ${unreachableCount}개 단계 도달 불가 = 청산 위험!</p>
        <p class="text-xs text-red-300 mt-1">트리거가 이전 단계 청산가보다 멀어서 = 가격 도달 전 강제 청산!</p>
        <p class="text-xs text-yellow-300 mt-1">💡 권장 (= 사장님 자율 결정!):
          (1) 증거금 추가 = 청산가 멀어짐 + 안전 마진 ↑
          (2) 트리거 % 줄이기 = 진입가 더 가까이
          (3) 후반 단계 자본 줄이기 = 평단 영향 ↓
          (4) 레버리지 줄이기 (예: 1x) = 청산가 멀리
        </p>
      </div>
    `;
  } else {
    warningHtml = `
      <div class="mt-2 p-2 rounded bg-emerald-900/30 border border-emerald-600">
        <p class="text-xs text-emerald-300">✅ <b>모든 단계 도달 가능!</b> = 사장님 자율 청산 회피 전략 정확! 🛡</p>
      </div>
    `;
  }

  box.innerHTML = `
    <div class="flex items-center justify-between mb-2">
      <h4 class="text-sm font-bold text-cyan-300">🛡 단계별 청산 분석 (= 사장님 자율 전략!)</h4>
      <span class="text-[10px] text-slate-500">SHORT/LONG × ${lev}x 레버리지</span>
    </div>
    <p class="text-[11px] text-slate-400 mb-1">사장님 사상: "1단계 진입 후 → 청산가 직전 → 다음 단계 진입 → 청산가 멀어짐 → 반복!" 손실 -100% 까지 자율 운영!</p>
    ${rowsHtml}
    ${warningHtml}
  `;
}

function onCapitalsChange() {
  let total = 0;
  let count = 0;
  for (let i = 1; i <= 10; i++) {
    const v = document.getElementById('cm-cap-' + i).value;
    cmState.capitals[i-1] = v;
    if (v && Number(v) > 0) { total += Number(v); count++; }
  }
  document.getElementById('cm-capitals-summary').innerHTML =
    `합계: <strong>${fmtNum(total)} USDT</strong> (${count}단계 사용)`;
  cmState.preview = null;
  document.getElementById('cm-preview').classList.add('hidden');
  updateCmSubmit();
}
