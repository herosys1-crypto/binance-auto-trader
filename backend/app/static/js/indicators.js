/**
 * Pure 보조지표 계산 + isolated 청산가 (Phase 3 단계 3l, 2026-05-14).
 *
 * 모두 pure math 함수 — 외부 의존성 없음. 차트 렌더 시 호출.
 *
 * 함수:
 *   - _sma(arr, period)                  : Simple Moving Average
 *   - _ema(arr, period)                  : Exponential Moving Average
 *   - _bollingerBands(closes, period, mult) : Bollinger Bands (middle/upper/lower)
 *   - _rsi(closes, period)               : Relative Strength Index
 *   - _macd(closes, fast, slow, signal)  : MACD (line/signal/histogram)
 *   - _obv(closes, volumes)              : On-Balance Volume
 *   - _computeIsolatedLiqPrice(strategy) : Isolated margin 청산가 (UX #26)
 */

// ===== 보조지표 계산 함수 =====
function _sma(arr, period) {
  const out = new Array(arr.length).fill(null);
  let sum = 0;
  for (let i = 0; i < arr.length; i++) {
    sum += arr[i];
    if (i >= period) sum -= arr[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}
function _ema(arr, period) {
  const out = new Array(arr.length).fill(null);
  const k = 2 / (period + 1);
  let prev = null;
  for (let i = 0; i < arr.length; i++) {
    if (i < period - 1) continue;
    if (prev === null) {
      let s = 0;
      for (let j = 0; j < period; j++) s += arr[j];
      prev = s / period;
    } else {
      prev = (arr[i] - prev) * k + prev;
    }
    out[i] = prev;
  }
  return out;
}
function _bollingerBands(closes, period = 20, mult = 2) {
  const middle = _sma(closes, period);
  const upper = new Array(closes.length).fill(null);
  const lower = new Array(closes.length).fill(null);
  for (let i = 0; i < closes.length; i++) {
    if (middle[i] === null) continue;
    let v = 0;
    for (let j = i - period + 1; j <= i; j++) v += Math.pow(closes[j] - middle[i], 2);
    const sd = Math.sqrt(v / period);
    upper[i] = middle[i] + mult * sd;
    lower[i] = middle[i] - mult * sd;
  }
  return { middle, upper, lower };
}
function _rsi(closes, period = 14) {
  const out = new Array(closes.length).fill(null);
  if (closes.length <= period) return out;
  let gain = 0, loss = 0;
  for (let i = 1; i <= period; i++) {
    const ch = closes[i] - closes[i - 1];
    if (ch > 0) gain += ch; else loss -= ch;
  }
  let avgG = gain / period, avgL = loss / period;
  out[period] = avgL === 0 ? 100 : 100 - (100 / (1 + avgG / avgL));
  for (let i = period + 1; i < closes.length; i++) {
    const ch = closes[i] - closes[i - 1];
    avgG = (avgG * (period - 1) + Math.max(0, ch)) / period;
    avgL = (avgL * (period - 1) + Math.max(0, -ch)) / period;
    out[i] = avgL === 0 ? 100 : 100 - (100 / (1 + avgG / avgL));
  }
  return out;
}
function _macd(closes, fast = 12, slow = 26, signal = 9) {
  const ef = _ema(closes, fast);
  const es = _ema(closes, slow);
  const line = closes.map((_, i) => (ef[i] === null || es[i] === null) ? null : ef[i] - es[i]);
  // signal = EMA of line. line 의 null 부분은 건너뛰고 첫 비-null 부터 EMA 계산.
  const validIdx = line.findIndex(v => v !== null);
  const validLine = validIdx >= 0 ? line.slice(validIdx).map(v => v === null ? 0 : v) : [];
  const sigCalc = _ema(validLine, signal);
  const sig = new Array(closes.length).fill(null);
  for (let i = 0; i < sigCalc.length; i++) {
    if (sigCalc[i] !== null) sig[validIdx + i] = sigCalc[i];
  }
  const hist = line.map((l, i) => (l === null || sig[i] === null) ? null : l - sig[i]);
  return { line, signal: sig, histogram: hist };
}
function _obv(closes, volumes) {
  const out = [0];
  for (let i = 1; i < closes.length; i++) {
    if (closes[i] > closes[i - 1]) out.push(out[i - 1] + volumes[i]);
    else if (closes[i] < closes[i - 1]) out.push(out[i - 1] - volumes[i]);
    else out.push(out[i - 1]);
  }
  return out;
}

// ===== UX #26: 체결분 기준 isolated 청산가 계산 =====
// 거래소 cross-margin liquidation_price 는 잔고 전체 기준이라 매우 멀게 나옴.
// 사용자가 원하는 건 "이 포지션만의 마진이 떨어지면 어디서 청산되는가" — isolated 방식.
// 공식:
//   SHORT: liq = avg_entry × (1 + 1/leverage - MMR)
//   LONG : liq = avg_entry × (1 - 1/leverage + MMR)
// MMR ≈ 0.005 (Tier 1 유지증거금율)
function _computeIsolatedLiqPrice(strategy) {
  if (!strategy) return null;
  const avg = Number(strategy.avg_entry_price || 0);
  const lev = Number(strategy.leverage || 0);
  if (avg <= 0 || lev <= 0) return null;
  const MMR = 0.005;
  if (strategy.side === 'SHORT') {
    return avg * (1 + 1 / lev - MMR);
  } else {
    return avg * (1 - 1 / lev + MMR);
  }
}
