/**
 * Create-Modal — Market info (시세 + 차트 + 시작가 자동 채움) (Phase 3 단계 3d, 2026-05-14).
 *
 * 심볼 입력 시 거래소 ticker24h + 1h kline 24개 fetch → UI 업데이트 + mini chart.
 * 시작가 「현재가/+5%/-5%」 버튼 → tick_size 기반 정밀도 보정.
 *
 * 함수:
 *   - loadCmMarketInfo()                : ticker + kline fetch + UI 업데이트
 *   - _drawCmChart(closes)              : SVG 24h × 1h mini chart
 *   - _decimalsForPrice(val)            : 가격 magnitude 별 동적 소수점
 *   - _tickSizeDecimals(tick)           : scientific notation 회피한 tick decimals
 *   - fillStartPrice(mode)              : 「현재가/+5%/-5%」 버튼 동작
 *
 * 외부 의존성 (script-scope 공유):
 *   - api / fetch / toast (api.js)
 *   - fmtNum (helpers.js)
 *   - _refreshLiveCalc (정의된 경우 — 시작가 변경 후 미리보기 재계산)
 *   - DOM: #cm-symbol, #cm-mkt-{price,change,high,low,vol}, #cm-chart, #cm-start-price,
 *     input[name="cm-account"]:checked
 *
 * State (이 모듈 소유):
 *   - _cmCurrentPrice : 현재가 (시작가 자동 채움 + 미리보기 사용)
 *   - _cmTickSize     : 심볼 tick_size 캐시 (시작가 정밀도)
 */

let _cmCurrentPrice = null;
let _cmTickSize = null;  // Bug #13 fix: 심볼별 tick_size 캐시 (시작가 정밀도용)

async function loadCmMarketInfo() {
  const symbol = document.getElementById('cm-symbol').value.toUpperCase().trim();
  if (!symbol) return;
  // 선택된 거래소 계정의 testnet 여부
  const checked = document.querySelector('input[name="cm-account"]:checked');
  const isTestnet = checked ? !!checked.closest('label').querySelector('.badge-yellow') : true;
  // 심볼 정보 (tick_size) 도 함께 가져옴 — 시작가 +/- N% 버튼이 정확한 정밀도로 반올림되도록.
  api(`/symbols/${symbol}`).then(s => {
    if (s && s.tick_size) _cmTickSize = Number(s.tick_size);
  }).catch(() => { _cmTickSize = null; });
  try {
    const [tk, kl] = await Promise.all([
      fetch(`${window.location.origin}/api/v1/market/ticker24h?symbol=${symbol}&testnet=${isTestnet}`).then(r => r.json()),
      fetch(`${window.location.origin}/api/v1/market/klines?symbol=${symbol}&interval=1h&limit=24&testnet=${isTestnet}`).then(r => r.json()),
    ]);
    if (tk && tk.lastPrice) {
      _cmCurrentPrice = Number(tk.lastPrice);
      const changePct = Number(tk.priceChangePercent || 0);
      const changeColor = changePct >= 0 ? 'text-green-400' : 'text-red-400';
      const arrow = changePct >= 0 ? '▲' : '▼';
      document.getElementById('cm-mkt-price').textContent = fmtNum(_cmCurrentPrice);
      const changeEl = document.getElementById('cm-mkt-change');
      changeEl.textContent = `${arrow} ${Math.abs(changePct).toFixed(2)}%`;
      changeEl.className = 'font-semibold ' + changeColor;
      document.getElementById('cm-mkt-high').textContent = fmtNum(tk.highPrice);
      document.getElementById('cm-mkt-low').textContent = fmtNum(tk.lowPrice);
      document.getElementById('cm-mkt-vol').textContent = fmtNum(Number(tk.quoteVolume || 0)) + ' USDT';
      // 2026-05-04 (사용자 요청): 시세 로드 직후 시작가 input 이 비어있거나 0 이면
      // 자동으로 현재가 채움. 사용자가 이미 입력한 양수 값은 보존 (덮어쓰지 않음).
      // 이전: 매번 「현재가」 버튼 클릭 필요 → 사용자 미리보기 422 (start_price=0).
      const startInp = document.getElementById('cm-start-price');
      if (startInp && (!startInp.value || Number(startInp.value) <= 0)) {
        fillStartPrice('current');
      }
    } else {
      document.getElementById('cm-mkt-price').textContent = '-';
    }
    if (Array.isArray(kl) && kl.length > 0) {
      _drawCmChart(kl.map(c => Number(c[4])));  // close prices
    }
  } catch (e) {
    document.getElementById('cm-mkt-price').textContent = '시세 조회 실패';
    console.warn('Market info error', e);
  }
}

function _drawCmChart(closes) {
  if (!closes || closes.length < 2) return;
  const svg = document.getElementById('cm-chart');
  const W = 400, H = 80, P = 4;
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = (max - min) || 1;
  const stepX = (W - P*2) / (closes.length - 1);
  const points = closes.map((c, i) => {
    const x = P + i * stepX;
    const y = P + (H - P*2) * (1 - (c - min) / range);
    return [x, y];
  });
  const path = points.map((p, i) => (i === 0 ? 'M' : 'L') + p[0].toFixed(2) + ',' + p[1].toFixed(2)).join(' ');
  const last = closes[closes.length - 1];
  const first = closes[0];
  const isUp = last >= first;
  const color = isUp ? '#10b981' : '#ef4444';
  const fillColor = isUp ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.15)';
  // 면적 채우기 영역
  const area = `${path} L${points[points.length-1][0].toFixed(2)},${H - P} L${points[0][0].toFixed(2)},${H - P} Z`;
  svg.innerHTML = `
    <path d="${area}" fill="${fillColor}" />
    <path d="${path}" fill="none" stroke="${color}" stroke-width="1.5" />
    <circle cx="${points[points.length-1][0].toFixed(2)}" cy="${points[points.length-1][1].toFixed(2)}" r="3" fill="${color}" />
    <text x="${W-P}" y="14" text-anchor="end" class="text-xs" fill="#64748b" font-size="10">24h × 1h</text>
  `;
}

// 가격 magnitude 에 따른 동적 소수점 정밀도 (작은 알트 0 표시 방지)
function _decimalsForPrice(val) {
  const v = Math.abs(Number(val) || 0);
  if (v >= 1000) return 2;
  if (v >= 100) return 3;
  if (v >= 1) return 4;
  if (v >= 0.01) return 5;
  if (v >= 0.0001) return 6;
  if (v >= 0.000001) return 7;
  return 8;
}

// 2026-05-06 fix (사용자 보고): tick_size 가 scientific notation 으로 표현되는 매우 작은
// 가격 (예: 0.00000001 → "1e-8") 을 처리. 이전 코드는 indexOf('.') 만 보고 -1 이면
// decimals=0 → toFixed(0) → "0" 으로 채워졌음 (입력 빈칸처럼 보임). 사용자 사례:
// 0.00006304 가격 + tick 0.00000001 = "0" 채워짐.
function _tickSizeDecimals(tick) {
  if (!tick || tick <= 0) return 0;
  if (tick >= 1) return 0;
  // 작은 수: -log10 의 ceil 이 정수면 그대로, 아니면 round
  // 0.00000001 → 8, 0.01 → 2, 0.00001 → 5
  const d = Math.round(-Math.log10(tick));
  return Math.max(0, Math.min(d, 18));  // 18: floating-point 표현 한계
}

function fillStartPrice(mode) {
  if (_cmCurrentPrice === null || isNaN(_cmCurrentPrice)) {
    return toast('현재가 조회가 안 됩니다. 직접 입력하세요', 'warning');
  }
  let val = _cmCurrentPrice;
  if (mode !== 'current') {
    const pct = Number(mode);  // '+5' → 5, '-3' → -3
    val = _cmCurrentPrice * (1 + pct / 100);
  }
  // Bug #13 fix + 2026-05-03 강화 + 2026-05-06 scientific notation fix.
  let formatted;
  let stepAttr = 'any';  // any: 브라우저 step 검증 우회 (작은 가격 호환)
  if (_cmTickSize && _cmTickSize > 0) {
    const stepped = Math.floor(val / _cmTickSize) * _cmTickSize;
    if (stepped > 0) {
      // tick decimals 계산 — String(0.00000001) 가 "1e-8" 되는 케이스 회피.
      const decimals = _tickSizeDecimals(_cmTickSize);
      formatted = stepped.toFixed(decimals);
      // step 속성도 같은 decimals 로 명시 (scientific notation 회피)
      stepAttr = decimals > 0 ? Number(_cmTickSize).toFixed(decimals) : String(_cmTickSize);
    } else {
      // tick_size 가 가격보다 커서 floor=0 — magnitude 기반으로 fallback
      const decimals = _decimalsForPrice(val);
      formatted = val.toFixed(decimals);
    }
  } else {
    // tick_size 없을 때는 가격 magnitude 기반 동적 정밀도
    const decimals = _decimalsForPrice(val);
    formatted = val.toFixed(decimals);
  }
  const inp = document.getElementById('cm-start-price');
  inp.step = stepAttr;
  inp.value = formatted;
  // 🌟 2026-06-11 v39 사장님 critical 사상 (= BEATUSDT 사례!):
  // 사장님 명시: "두번째는 현재가 기준으로 새롭게 세팅으로 하면
  //              2단계부터 진행할 수 있는 세팅이 되어야해"
  // = 「수정 모드」 + 「현재가」 클릭 시:
  //   1단계 = 사장님 옛 평단 (= 옛 진입 보존!)
  //   2단계 부터 = 현재가 기준 재계산
  try {
    if (cmState && cmState.editingStrategyId && cmState.editingStrategyBp) {
      const oldAvg = Number(cmState.editingStrategyBp.avg_entry_price || cmState.editingStrategyBp.start_price || 0);
      if (oldAvg > 0) {
        // 신 hidden 필드 또는 = stage_no=1 의 진입가 표시 = 옛 평단 (= 보존!)
        // 사장님 자율: 1단계 자본 변경 = 옛 진입 보존, 2단계+ 자본 = 신 진입
        toast(`✅ 신 시작가 = ${formatted}\\n🛡 1단계 = 옛 평단 ${oldAvg} 보존 (= 사장님 사상 v39)\\n📌 2단계+ = 현재가 기준 재계산!`, 'success');
      }
    }
  } catch (e) {
    console.warn('[v39] 수정모드 현재가 보존 logic 실패:', e);
  }
  // 입력값이 바뀌었으니 미리보기 청산 위험 재계산용 trigger
  if (typeof _refreshLiveCalc === 'function') _refreshLiveCalc();
  // 🚨 2026-06-22 사장님 critical v5: focus() = 자동 scrollIntoView silent bug!
  // 사장님 보고: '바로 아래로 내려가는 문제' = focus() = 「시작가」 = 모달 하단 = 자동 스크롤!
  // fix: preventScroll: true = focus + 스크롤 X = 사장님 = 위에서 시작!
  try {
    document.getElementById('cm-start-price').focus({ preventScroll: true });
  } catch (_e) {
    // 옛 브라우저 = preventScroll 미지원 시 = focus 자체 skip!
    console.warn('[focus] preventScroll 미지원 = focus 호출 skip (= 자동 스크롤 silent bug 차단!)');
  }
}
