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
        if (liqEl) { liqEl.textContent = '-'; liqEl.className = 'col-span-1 text-xs text-orange-300 text-right'; }
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
        // 첫 채워진 단계 = 새 1단계 (IMMEDIATE) — 압축 후 idx 무관 시작가 사용
        entryPrice = startPrice;
        pendingTriggerPct = 0;  // 첫 단계 누적 무시
      } else if (cmState.editingStrategyId && _editCurrentStage > 0 && i === _editCurrentStage + 1) {
        // 🌟 사장님 「수정 모드」: 첫 미진입 단계 = 시작가 기준 (= 현재가 × (1 + trigger%))
        // 진입 단계 (1~current_stage) 의 옛 진입가 = 무시 + 신 미진입 단계 = 현재가 새로 시작
        let trgPct = tNum;
        if (i === lastStageNo && trgPct === 0) trgPct = DEFAULT_LAST_TRIGGER_PCT;
        const effectiveTrgPct = trgPct + pendingTriggerPct;
        pendingTriggerPct = 0;
        if (side === 'SHORT') {
          entryPrice = startPrice * (1 + effectiveTrgPct / 100);
        } else {
          entryPrice = startPrice * (1 - effectiveTrgPct / 100);
        }
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
