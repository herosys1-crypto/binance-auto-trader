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
  // 1단계는 IMMEDIATE, 2/3/4단계=10, 5단계 이후=20
  if (stageNo === 1) return '';
  if (stageNo <= 4) return '10';
  return '20';
}

function buildCapitalsGrid() {
  const grid = document.getElementById('cm-capitals-grid');
  // 헤더 + 10행 — 단계 / 자본 / 트리거% / 단계 진입가 / 누적 평균진입 / 청산가 / 누적 손실%
  // (실시간 계산 — 입력 즉시 갱신)
  let html = `<div class="grid grid-cols-12 gap-1 text-xs text-slate-500 px-1 pb-1 border-b border-slate-700 mb-1">
    <div class="col-span-1">단계</div>
    <div class="col-span-1">💵 자본</div>
    <div class="col-span-1">📊 트리%</div>
    <div class="col-span-1 text-yellow-400" title="단계 진입 직후 추가로 투입할 isolated 증거금 (USDT). 비우거나 0 = 추가 안 함. 청산가를 멀리 밀어 안전 마진 확보 (사용자 요청, 2026-05-11)">💰 증거금</div>
    <div class="col-span-2 text-right text-purple-400" title="이 단계의 LIMIT 진입 가격 (이전 단계 × (1±trigger%))">단계 진입가</div>
    <div class="col-span-2 text-right text-cyan-400" title="이 단계까지 누적 가중평균 진입가">평균진입</div>
    <div class="col-span-1 text-right text-orange-400" title="누적 평균 기준 예상 청산가 (Isolated 보수적)">청산가</div>
    <div class="col-span-1 text-right text-red-400" title="이 단계 진입 직전→직후 누적 ROI %">손실율</div>
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
    html += `<div class="grid grid-cols-12 gap-1 items-center">
      <div class="col-span-1 text-xs text-slate-300 font-semibold">${i}단계</div>
      <div class="col-span-1">
        <input type="number" min="0" step="any" id="cm-cap-${i}" placeholder="${capPlaceholder}"
          oninput="onCapitalsChange(); _refreshLiveCalc()"
          title="단계별 투입 자본 (USDT). 1단계 필수, 2단계 이후 비우면 그 단계 사용 안 함."
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
      <div class="col-span-2 text-xs text-cyan-300 text-right" id="cm-stage-avg-${i}" title="이 단계까지 누적 평균 진입가">-</div>
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
    // 2026-06-03 (사장님 안전 sigil): 중간 단계 빈값 시 backend 가 break + 이후 무시.
    // 사장님이 cap-3 비우고 cap-4 입력하면 미리보기는 표시되지만 실제 저장 X (silent drop).
    // → 빈값 발견 후 채워진 단계는 '⚠ 무시됨' 빨강 강조 + 사장님 인지.
    let firstEmptyStage = 0;  // 0 = 빈값 없음. > 0 = 그 단계 (포함) 부터 backend break.
    const ignoredStages = [];  // 빈값 이후 채워진 단계 — submit 시 무시됨
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
      // CASE A: 빈값 발견 후 채워진 단계 → silent drop 경고
      if (firstEmptyStage > 0 && cap > 0) {
        ignoredStages.push(i);
        if (entryEl) { entryEl.textContent = '⚠ 무시'; entryEl.className = 'col-span-2 text-xs text-right text-red-500 font-bold'; }
        if (avgEl) { avgEl.textContent = '⚠'; avgEl.className = 'col-span-2 text-xs text-right text-red-500 font-bold'; }
        if (liqEl) { liqEl.textContent = '⚠'; liqEl.className = 'col-span-1 text-xs text-right text-red-500 font-bold'; }
        if (lossEl) { lossEl.innerHTML = `<span class="text-red-500 font-bold" title="단계 ${firstEmptyStage} 비움 → 이 단계 submit 시 무시됨">⚠ ${firstEmptyStage} 비움</span>`; lossEl.className = 'col-span-1 text-xs text-right'; }
        if (lossUsdEl) { lossUsdEl.textContent = '⚠'; lossUsdEl.className = 'col-span-2 text-xs text-right text-red-500 font-bold'; }
        // capEl 자체에도 빨강 border 표시
        capEl.classList.add('border-red-500');
        capEl.style.borderWidth = '2px';
        continue;
      }
      // CASE B: 빈값 (이게 첫 빈값이면 firstEmptyStage 기록)
      if (!cap || cap <= 0) {
        if (firstEmptyStage === 0) firstEmptyStage = i;
        if (entryEl) { entryEl.textContent = '-'; entryEl.className = 'col-span-2 text-xs text-purple-300 text-right'; }
        if (avgEl) { avgEl.textContent = '-'; avgEl.className = 'col-span-2 text-xs text-cyan-300 text-right'; }
        if (liqEl) { liqEl.textContent = '-'; liqEl.className = 'col-span-1 text-xs text-orange-300 text-right'; }
        if (lossEl) { lossEl.textContent = '-'; lossEl.className = 'col-span-1 text-xs text-red-400 text-right'; }
        if (lossUsdEl) { lossUsdEl.textContent = '-'; lossUsdEl.className = 'col-span-2 text-xs text-red-300 text-right'; }
        continue;
      }
      // CASE C: 정상 계산 — capEl 의 빨강 border 제거 (이전 cycle 잔재)
      capEl.classList.remove('border-red-500');
      capEl.style.borderWidth = '';
      // 1) 이 단계 진입가 (raw, leverage 무관)
      let entryPrice;
      if (i === 1) {
        entryPrice = startPrice;
      } else {
        // 사용자 #5-07 보고 fix: 마지막 단계 trigger 가 비어있으면 backend 기본 20% 적용
        // (이전엔 0% 로 처리돼 prevPrice 와 같은 값 → "표기가 없는" 듯한 인상).
        let trgPct = Number(trgEl ? trgEl.value : 0) || 0;
        if (i === lastStageNo && trgPct === 0) trgPct = DEFAULT_LAST_TRIGGER_PCT;
        if (side === 'SHORT') {
          entryPrice = prevPrice * (1 + trgPct / 100);
        } else {
          entryPrice = prevPrice * (1 - trgPct / 100);
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
        liqEl.textContent = liq.toFixed(decimals);
        liqEl.className = 'col-span-2 text-xs text-right ' + liqColor;
      }
      if (lossEl) {
        // 직전 → 직후 ROI 표시 (1단계는 직전 없음)
        const postTxt = (roi >= 0 ? '+' : '') + roi.toFixed(2) + '%';
        const postColor = roi < -50 ? 'text-red-400 font-semibold' : (roi < 0 ? 'text-red-300' : 'text-emerald-300');
        let html;
        let dangerWarn = '';
        if (preRoi !== null) {
          const preTxt = (preRoi >= 0 ? '+' : '') + preRoi.toFixed(2) + '%';
          // 직전 ROI < -85% 면 청산 임박 ⚠️
          let preColor;
          if (preRoi < -85) {
            preColor = 'text-red-500 font-bold';
            dangerWarn = '⚠️';
          } else if (preRoi < -50) {
            preColor = 'text-red-400 font-semibold';
          } else {
            preColor = 'text-red-300';
          }
          html = `<span class="${preColor}">${preTxt}</span><span class="text-slate-500"> → </span><span class="${postColor}">${postTxt}</span>${dangerWarn}`;
        } else {
          html = `<span class="${postColor}">${postTxt}</span>`;
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
      prevPrice = entryPrice;
      prevLiq = liq;
    }
    // 2026-06-03: 무시되는 단계 있으면 capitals 그리드 상단에 큰 경고 박스 표시
    let warnBox = document.getElementById('cm-capitals-silent-drop-warn');
    if (ignoredStages.length > 0) {
      if (!warnBox) {
        warnBox = document.createElement('div');
        warnBox.id = 'cm-capitals-silent-drop-warn';
        warnBox.className = 'mt-2 p-2 rounded bg-red-900/30 border-2 border-red-500';
        const grid = document.getElementById('cm-capitals-grid');
        if (grid && grid.parentNode) {
          grid.parentNode.insertBefore(warnBox, grid.nextSibling);
        }
      }
      warnBox.innerHTML =
        `<p class="text-sm text-red-300 font-bold">⚠️ 중간 단계 빈값 → submit 시 ${ignoredStages.length}개 단계 무시됨!</p>` +
        `<p class="text-xs text-slate-200 mt-1">${firstEmptyStage}단계 비움 → 이후 ${ignoredStages.join(', ')}단계 자본은 backend 가 저장하지 않습니다 (silent drop).</p>` +
        `<p class="text-xs text-yellow-300 mt-1">해결: ${firstEmptyStage}단계 자본 입력 또는 ${ignoredStages.join(', ')}단계 자본 삭제 (마지막 단계부터 비우기 권장).</p>`;
      warnBox.style.display = 'block';
    } else if (warnBox) {
      warnBox.style.display = 'none';
    }
  } catch (e) {
    // silent — 입력 중 일시적 NaN 등 무시
  }
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
