/**
 * 전략 상세 차트 + 보조지표 패널 (Phase 3 단계 3n, 2026-05-15).
 *
 * Lightweight Charts 기반 메인 캔들 차트 + RSI/MACD/OBV 서브 패널 + 가로선
 * (시작가/단계가/평단/청산예정/현재가) + 청산가 포함 토글 + 타임프레임 전환.
 *
 * 외부 의존 (script-scope 공유):
 *   - api, fmtNum, toast (전역 헬퍼)
 *   - _bollingerBands, _rsi, _macd, _obv, _computeIsolatedLiqPrice (indicators.js)
 *   - LightweightCharts (CDN)
 *
 * 내보내는 전역 (다른 모듈/HTML 핸들러에서 참조):
 *   - _detailChartState           : 차트 상태 (strategy/stagePlans/chart/series 등)
 *   - refreshDetailChart()        : 수동 새로고침 버튼
 *   - toggleLiqIncluded()         : 청산가 포함 보기 토글
 *   - _updateLiqToggleBtnLabel()  : 토글 버튼 레이블 갱신
 *   - setDetailChartInterval()    : 1h/4h/1d 전환 버튼
 *   - _renderDetailChart()        : 메인 차트 렌더 (selectStrategy 에서 호출)
 *   - _renderIndicatorChart()     : 단일 라인 보조지표 (RSI/OBV)
 *   - _attachSubChartSync()       : 메인 ↔ 서브 차트 logical range 동기화
 *   - _renderMacdChart()          : MACD line + signal + histogram
 */

// UX #20-23 (2026-04-29): TradingView Lightweight Charts + 보조지표.
// 단계별 진입가 + 평단 + 청산예정가 + BB/RSI/MACD/OBV. 줌/팬/크로스헤어 지원.
// 기본 인터벌은 1d (사용자 요청).
let _detailChartState = {
  strategy: null, stagePlans: null, interval: '1d',
  chart: null, candleSeries: null, bbSeries: { upper: null, middle: null, lower: null },
  rsiChart: null, macdChart: null, obvChart: null,
  // UX #25: 기본 ON — 청산라인이 항상 차트에 보이도록 (Y축 자동 확장).
  // 청산가가 멀면 캔들이 압축돼 보이는 단점이 있어 toggle 로 끌 수 있게 함.
  liqIncluded: true,
};

// 차트 수동 새로고침 — 최신 strategy 데이터 (avg_entry 포함) 다시 가져와서 재렌더
async function refreshDetailChart() {
  if (!_detailChartState.strategy) return toast('전략이 선택되지 않았습니다', 'warning');
  const id = _detailChartState.strategy.id;
  try {
    const [stagePlans, strategy] = await Promise.all([
      api('/strategies/' + id + '/stage-plans').catch(() => []),
      api('/strategies/' + id).catch(() => null),
    ]);
    if (strategy) {
      await _renderDetailChart(strategy, stagePlans);
      const liq = _computeIsolatedLiqPrice(strategy);
      toast(`차트 갱신 완료 — 평단 ${fmtNum(strategy.avg_entry_price || 0)}, 청산예정 ${liq ? fmtNum(liq) : '-'}`, 'success');
    } else {
      toast('전략 정보 갱신 실패', 'error');
    }
  } catch (e) {
    toast('차트 갱신 실패: ' + e.message, 'error');
  }
}

// ===== 청산가 포함 보기 토글 =====
// Lightweight Charts 는 가격축 직접 setRange 가 없으므로,
// 청산가에 보이지 않는 phantom 라인 시리즈를 추가해 자동 스케일이 청산가까지 확장되도록 유도.
function toggleLiqIncluded() {
  _detailChartState.liqIncluded = !_detailChartState.liqIncluded;
  const ch = _detailChartState.chart;
  if (!ch) return;
  if (_detailChartState.liqIncluded) {
    // UX #26: isolated 청산가 우선 사용 (체결분 기준)
    const liq = _computeIsolatedLiqPrice(_detailChartState.strategy)
      || (_detailChartState.strategy && _detailChartState.strategy.liquidation_price
        ? Number(_detailChartState.strategy.liquidation_price) : null);
    if (!liq) {
      _detailChartState.liqIncluded = false;
      return toast('청산가 정보 없음', 'warning');
    }
    if (!_detailChartState._liqPhantomSeries && _detailChartState._lastCandles && _detailChartState._lastCandles.length > 0) {
      const phantom = ch.addLineSeries({
        color: 'rgba(0,0,0,0)',  // 투명
        priceScaleId: 'left',
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      const t1 = _detailChartState._lastCandles[0].time;
      const t2 = _detailChartState._lastCandles[_detailChartState._lastCandles.length - 1].time;
      phantom.setData([{ time: t1, value: liq }, { time: t2, value: liq }]);
      _detailChartState._liqPhantomSeries = phantom;
    }
    toast('청산가 포함 모드 — 청산가까지 Y축 확장됨', 'success');
    // 포함되었으니 OOR 인디케이터 숨김
    const ind = document.getElementById('liq-oor-indicator');
    if (ind) ind.classList.add('hidden');
    _updateLiqToggleBtnLabel();
  } else {
    if (_detailChartState._liqPhantomSeries) {
      try { ch.removeSeries(_detailChartState._liqPhantomSeries); } catch (e) {}
      _detailChartState._liqPhantomSeries = null;
    }
    toast('자동 스케일 복귀 — 캔들 영역 확대됨', 'success');
    _updateLiqToggleBtnLabel();
    // 자동 모드 복귀 시 다시 OOR 체크하려면 차트 재렌더 (간단히)
    if (_detailChartState.strategy) {
      _renderDetailChart(_detailChartState.strategy, _detailChartState.stagePlans).catch(e => console.warn(e));
    }
  }
}

function _updateLiqToggleBtnLabel() {
  const btn = document.getElementById('liq-toggle-btn');
  if (!btn) return;
  if (_detailChartState.liqIncluded) {
    btn.textContent = '📐 청산가 포함됨 (끄기)';
    btn.className = 'btn-primary btn text-xs ml-2';
  } else {
    btn.textContent = '📐 청산가 포함 보기 (켜기)';
    btn.className = 'btn-ghost btn text-xs ml-2';
  }
  btn.style.padding = '2px 8px';
  btn.style.fontSize = '11px';
}

function setDetailChartInterval(interval) {
  _detailChartState.interval = interval;
  document.querySelectorAll('#detail-chart-tf-buttons button').forEach(btn => {
    const isActive = btn.dataset.tf === interval;
    btn.className = isActive ? 'btn-primary btn text-xs' : 'btn-ghost btn text-xs';
    btn.style.padding = '2px 8px';
    btn.style.fontSize = '11px';
  });
  if (_detailChartState.strategy) {
    _renderDetailChart(_detailChartState.strategy, _detailChartState.stagePlans).catch(e => console.warn(e));
  }
}

async function _renderDetailChart(strategy, stagePlans) {
  // 상태 저장 (타임프레임 전환 시 재사용)
  _detailChartState.strategy = strategy;
  _detailChartState.stagePlans = stagePlans;
  const interval = _detailChartState.interval || '1d';
  // 버튼 활성 표시 동기화 (첫 진입 시)
  document.querySelectorAll('#detail-chart-tf-buttons button').forEach(btn => {
    const isActive = btn.dataset.tf === interval;
    btn.className = isActive
      ? 'btn-primary btn text-xs'
      : 'btn-ghost btn text-xs';
    btn.style.padding = '2px 8px';
    btn.style.fontSize = '11px';
  });

  // 타임프레임별 캔들 수
  const limitFor = { '1h': 200, '4h': 200, '1d': 180 }[interval] || 200;

  const symbol = strategy.symbol;
  const klResp = await fetch(
    `${window.location.origin}/api/v1/market/klines?symbol=${encodeURIComponent(symbol)}&interval=${interval}&limit=${limitFor}`
  ).then(r => r.json()).catch(() => null);
  const container = document.getElementById('detail-chart-container');
  const infoEl = document.getElementById('detail-chart-info');
  const loadingEl = document.getElementById('detail-chart-loading');
  if (loadingEl) loadingEl.style.display = 'none';

  if (!Array.isArray(klResp) || klResp.length < 2) {
    infoEl.textContent = `${symbol} — 차트 데이터 없음`;
    container.innerHTML = '<div class="text-slate-500 text-sm" style="position:absolute; top:50%; left:50%; transform:translate(-50%,-50%)">차트 데이터를 가져올 수 없습니다</div>';
    return;
  }

  if (typeof LightweightCharts === 'undefined') {
    infoEl.textContent = '차트 라이브러리 로딩 실패';
    container.innerHTML = '<div class="text-slate-500 text-sm" style="position:absolute; top:50%; left:50%; transform:translate(-50%,-50%)">Lightweight Charts 라이브러리를 불러오지 못했습니다 (인터넷 연결 확인)</div>';
    return;
  }

  // OHLC 데이터 변환 (Binance kline → Lightweight Charts 형식)
  const candleData = klResp.map(c => ({
    time: Math.floor(c[0] / 1000),
    open: Number(c[1]),
    high: Number(c[2]),
    low: Number(c[3]),
    close: Number(c[4]),
  }));
  const closes = candleData.map(c => c.close);
  const last = closes[closes.length - 1];

  const avgEntry = strategy.avg_entry_price ? Number(strategy.avg_entry_price) : null;
  const startPx = strategy.start_price ? Number(strategy.start_price) : null;
  // UX #26: 체결분 기준 isolated 청산가 사용 (cross-margin DB값보다 직관적)
  const isolatedLiq = _computeIsolatedLiqPrice(strategy);
  const exchangeLiq = strategy.liquidation_price ? Number(strategy.liquidation_price) : null;
  // 1순위: isolated 계산값 (체결분 기준), fallback: 거래소 값 (체결 전)
  const liqPx = isolatedLiq !== null ? isolatedLiq : exchangeLiq;

  // 기존 차트 dispose
  if (_detailChartState.chart) {
    try { _detailChartState.chart.remove(); } catch (e) { /* ignore */ }
    _detailChartState.chart = null;
    _detailChartState.candleSeries = null;
  }
  // 컨테이너 비우기 (혹시 남은 DOM) — 단, 로딩 + OOR 인디케이터는 보존
  Array.from(container.children).forEach(ch => {
    if (ch.id !== 'detail-chart-loading' && ch.id !== 'liq-oor-indicator') ch.remove();
  });

  const chart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: container.clientHeight || 280,
    layout: {
      background: { type: 'solid', color: '#0f172a' },
      textColor: '#cbd5e1',
      fontFamily: 'Pretendard, Segoe UI, sans-serif',
      fontSize: 11,
    },
    grid: {
      vertLines: { color: 'rgba(148,163,184,0.08)' },
      horzLines: { color: 'rgba(148,163,184,0.08)' },
    },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    timeScale: {
      borderColor: '#334155',
      timeVisible: interval !== '1d',
      secondsVisible: false,
      // UX (2026-05-04): 우측 여백 — 차트가 우측 모서리에 붙어있지 않게.
      rightOffset: 12,
      // barSpacing 은 fitContent 가 자동 계산 — 폭/캔들 수에 맞게 적응.
      // 고정값 (예 5) 으로 박으면 컨테이너 폭에 따라 좌측이 비고 우측 몰림 발생.
      fixLeftEdge: false,
      fixRightEdge: false,
    },
    // UX #27: 가격축을 좌측으로 이동
    leftPriceScale: {
      visible: true,
      borderColor: '#334155',
      scaleMargins: { top: 0.1, bottom: 0.1 },
    },
    rightPriceScale: { visible: false },
  });

  const candleSeries = chart.addCandlestickSeries({
    upColor: '#10b981',
    downColor: '#ef4444',
    borderUpColor: '#10b981',
    borderDownColor: '#ef4444',
    wickUpColor: '#10b981',
    wickDownColor: '#ef4444',
    priceScaleId: 'left',  // UX #27
    // 자동 last-close 가격 라벨/라인 비활성화 (1d 에서 어제 종가가 평단 옆에 따로 떠서 혼동 유발)
    // 대신 아래에서 명시적으로 "현재가" 라벨 라인을 그려 모든 timeframe 에서 일관된 표시.
    priceLineVisible: false,
    lastValueVisible: false,
    priceFormat: {
      type: 'price',
      precision: 8,
      minMove: 0.00000001,
    },
  });
  candleSeries.setData(candleData);
  _detailChartState.chart = chart;
  _detailChartState.candleSeries = candleSeries;
  _detailChartState._lastCandles = candleData;
  // 데이터 bound 에 자동 정렬 — 옛 visible range stuck 방지 (1h↔4h↔1d 전환 시).
  // 그 후 rightOffset (12 캔들) 만큼 자동 우측 여백.
  try { chart.timeScale().fitContent(); } catch (e) {}

  // ===== UX #23: 볼린저 밴드 (BB 20,2) 오버레이 — 좌측 가격축 =====
  const bb = _bollingerBands(closes, 20, 2);
  const bbToData = (vals) => candleData.map((c, i) => vals[i] === null ? null : { time: c.time, value: vals[i] }).filter(v => v !== null);
  const bbCommon = { priceScaleId: 'left', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false };
  const bbUpperSeries = chart.addLineSeries({ ...bbCommon, color: 'rgba(167,139,250,0.7)' });
  const bbMiddleSeries = chart.addLineSeries({ ...bbCommon, color: 'rgba(167,139,250,0.5)', lineStyle: 2 });
  const bbLowerSeries = chart.addLineSeries({ ...bbCommon, color: 'rgba(167,139,250,0.7)' });
  bbUpperSeries.setData(bbToData(bb.upper));
  bbMiddleSeries.setData(bbToData(bb.middle));
  bbLowerSeries.setData(bbToData(bb.lower));
  _detailChartState.bbSeries = { upper: bbUpperSeries, middle: bbMiddleSeries, lower: bbLowerSeries };

  // ===== UX #23: RSI 패널 =====
  _renderIndicatorChart('ind-rsi-container', 'rsiChart', candleData, _rsi(closes, 14), {
    color: '#fbbf24', name: 'RSI(14)', infoEl: 'ind-rsi-info',
    horizontalLines: [{ price: 70, color: 'rgba(239,68,68,0.4)', title: '70 과매수' }, { price: 30, color: 'rgba(16,185,129,0.4)', title: '30 과매도' }, { price: 50, color: 'rgba(148,163,184,0.3)', title: '' }],
    minMove: 0.01, precision: 2,
  });

  // ===== UX #23: MACD 패널 (line + signal + histogram) =====
  const macdRes = _macd(closes, 12, 26, 9);
  _renderMacdChart('ind-macd-container', candleData, macdRes, 'ind-macd-info');

  // ===== UX #23: OBV 패널 =====
  const volumes = klResp.map(c => Number(c[5]));
  const obvVals = _obv(closes, volumes);
  _renderIndicatorChart('ind-obv-container', 'obvChart', candleData, obvVals, {
    color: '#60a5fa', name: 'OBV', infoEl: 'ind-obv-info',
    minMove: 1, precision: 0,
  });

  // 가격 라인 추가 헬퍼
  const addLine = (price, color, lineStyle, title, lineWidth = 1) => {
    if (price == null || isNaN(price) || price <= 0) return;
    candleSeries.createPriceLine({
      price,
      color,
      lineWidth,
      lineStyle,  // 0=Solid, 1=Dotted, 2=Dashed, 3=LargeDashed
      axisLabelVisible: true,
      title,
    });
  };

  // 1) 시작가 — 회색 점선
  if (startPx && (!avgEntry || Math.abs(startPx - (avgEntry || 0)) > Math.abs(last) * 0.0005)) {
    addLine(startPx, '#94a3b8', 1, '시작가');
  }

  // 2) 단계별 가로선 — 체결 = 초록 실선 / 예정 = 노랑 점선
  (stagePlans || []).forEach(s => {
    if (!s.trigger_price) return;
    const price = Number(s.trigger_price);
    const filled = s.is_triggered;
    addLine(
      price,
      filled ? '#10b981' : '#fbbf24',
      filled ? 0 : 2,
      filled ? `${s.stage_no}단계 ✓` : `${s.stage_no}단계 ○`,
      filled ? 1 : 1,
    );
  });

  // 3) 평단가 — 파란 굵은 실선
  if (avgEntry) {
    addLine(avgEntry, '#3b82f6', 0, '평단', 2);
  }

  // 4) 청산예정가 — 빨간 굵은 점선 (체결분 기준 isolated 계산). UX #28: 굵기 강화 4px (최대)
  if (liqPx) {
    addLine(liqPx, '#ef4444', 2, '청산예정', 4);
  }

  // 5) 현재가(마크) — 시안 실선. 모든 timeframe 에서 일관된 표시.
  // 우선순위:
  //   (a) ticker24h 의 lastPrice  ← 가장 정확 (실시간)
  //   (b) avg_entry + uPnL / qty 역산 (포지션 있을 때)
  //   (c) candle close (마지막 fallback)
  // 1d 차트는 Binance 가 어제 종가를 last 로 반환해 timeframe 마다 다른 문제 → ticker24h 로 해결.
  let currentMark = null;
  try {
    const isTestnet = (strategy.is_testnet === true) || (strategy.exchange_account_is_testnet === true);
    const tickResp = await fetch(
      `${window.location.origin}/api/v1/market/ticker24h?symbol=${encodeURIComponent(symbol)}&testnet=${isTestnet}`
    ).then(r => r.json()).catch(() => null);
    if (tickResp && (tickResp.lastPrice || tickResp.last_price)) {
      currentMark = Number(tickResp.lastPrice || tickResp.last_price);
    }
  } catch (e) { /* fallback 아래 */ }
  if (!currentMark) {
    const sAvg = Number(strategy.avg_entry_price || 0);
    const sQty = Math.abs(Number(strategy.current_position_qty || 0));
    const sPnl = strategy.unrealized_pnl != null ? Number(strategy.unrealized_pnl) : null;
    if (sAvg > 0 && sQty > 0 && sPnl !== null && !isNaN(sPnl)) {
      currentMark = strategy.side === 'LONG' ? (sAvg + sPnl / sQty) : (sAvg - sPnl / sQty);
    }
  }
  const markPriceForLine = currentMark || last;
  if (markPriceForLine && markPriceForLine > 0) {
    addLine(markPriceForLine, '#06b6d4', 1, '현재가');
  }

  // UX #24: 청산가 범위 밖일 때 HTML 오버레이 인디케이터 표시
  // 차트의 자동 Y축 범위는 캔들 데이터 기반이라 청산가가 밖에 있으면 라벨이 잘림.
  // 이때만 우상/우하 모서리에 빨간 배지로 화살표 + 가격 표시.
  const liqIndEl = document.getElementById('liq-oor-indicator');
  if (liqIndEl) {
    if (liqPx && _detailChartState._lastCandles && _detailChartState._lastCandles.length > 0) {
      const lows = _detailChartState._lastCandles.map(c => c.low);
      const highs = _detailChartState._lastCandles.map(c => c.high);
      const dataMin = Math.min(...lows);
      const dataMax = Math.max(...highs);
      // 캔들 범위 + 단계 가격 + 평단/시작가 모두 고려한 효과적 범위
      const allInChart = [dataMin, dataMax, ...(stagePlans || []).filter(s => s.trigger_price).map(s => Number(s.trigger_price))];
      if (avgEntry) allInChart.push(avgEntry);
      if (startPx) allInChart.push(startPx);
      const effMin = Math.min(...allInChart);
      const effMax = Math.max(...allInChart);
      const isOOR = liqPx > effMax || liqPx < effMin;
      if (isOOR && !_detailChartState.liqIncluded) {
        const arrow = liqPx > effMax ? '↑' : '↓';
        // 청산가가 위에 있으면 차트 상단, 아래면 시간축 위쪽에 배치
        liqIndEl.innerHTML = `${arrow} 청산 ${fmtNum(liqPx)}`;
        liqIndEl.title = '클릭 시 차트 Y축이 청산가까지 자동 확장됩니다';
        if (liqPx > effMax) {
          liqIndEl.style.top = '8px';
          liqIndEl.style.bottom = 'auto';
        } else {
          liqIndEl.style.top = 'auto';
          liqIndEl.style.bottom = '38px';
        }
        // UX #27: 가격축이 좌측으로 이동했으니 인디케이터는 우측 모서리에 (라벨과 안 겹침)
        liqIndEl.style.right = '12px';
        liqIndEl.style.left = 'auto';
        liqIndEl.classList.remove('hidden');
      } else {
        liqIndEl.classList.add('hidden');
      }
    } else {
      liqIndEl.classList.add('hidden');
    }
  }

  // UX #25: liqIncluded 모드 기본 ON — 청산라인이 항상 차트에 보이도록 phantom 시리즈 추가
  if (_detailChartState.liqIncluded && liqPx && candleData.length > 0) {
    const phantom = chart.addLineSeries({
      color: 'rgba(0,0,0,0)',  // 투명
      priceScaleId: 'left',
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    phantom.setData([
      { time: candleData[0].time, value: liqPx },
      { time: candleData[candleData.length - 1].time, value: liqPx },
    ]);
    _detailChartState._liqPhantomSeries = phantom;
  }

  // 시간축 fit (전체 캔들 보이게)
  chart.timeScale().fitContent();

  // 윈도우 리사이즈 시 차트도 따라가게
  if (!_detailChartState._resizeListenerAdded) {
    window.addEventListener('resize', () => {
      if (_detailChartState.chart && container.clientWidth) {
        _detailChartState.chart.applyOptions({ width: container.clientWidth });
      }
    });
    _detailChartState._resizeListenerAdded = true;
  }

  const sideLabel = strategy.side === 'SHORT' ? '📉 숏' : '📈 롱';
  // UX #26: isolated 청산가 우선 표시 + 거래소 cross 청산가도 비교용으로 작게 표시
  let liqHint = '';
  if (isolatedLiq) {
    liqHint = ` · 청산예정 ${fmtNum(isolatedLiq)} (체결분 기준)`;
    if (exchangeLiq && Math.abs(exchangeLiq - isolatedLiq) / isolatedLiq > 0.1) {
      liqHint += ` · 거래소 ${fmtNum(exchangeLiq)}`;
    }
  } else if (exchangeLiq) {
    liqHint = ` · 거래소 청산 ${fmtNum(exchangeLiq)}`;
  }
  infoEl.textContent = `${symbol} · ${sideLabel} · ${strategy.leverage}x · 단계 ${strategy.current_stage}/${(stagePlans || []).length} · ${candleData.length}개 ${interval} 캔들${liqHint}`;
}

// 단일 라인 보조지표 (RSI, OBV) 렌더링 헬퍼
function _renderIndicatorChart(containerId, stateKey, candleData, values, opts) {
  const container = document.getElementById(containerId);
  if (!container) return;
  // 기존 차트 dispose
  if (_detailChartState[stateKey]) {
    try { _detailChartState[stateKey].remove(); } catch (e) {}
    _detailChartState[stateKey] = null;
  }
  Array.from(container.children).forEach(c => c.remove());
  if (typeof LightweightCharts === 'undefined') return;
  const chart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: container.clientHeight || 120,
    layout: { background: { type: 'solid', color: '#0f172a' }, textColor: '#94a3b8', fontSize: 10 },
    grid: { vertLines: { color: 'rgba(148,163,184,0.05)' }, horzLines: { color: 'rgba(148,163,184,0.05)' } },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    // 메인 차트와 동일 timeScale 옵션 (rightOffset 등) — 시각 정렬 일관.
    // visible:false 이지만 내부 timeScale 은 살아있어 동기화에 사용.
    timeScale: { borderColor: '#334155', timeVisible: false, visible: false, rightOffset: 12 },
    leftPriceScale: { visible: true, borderColor: '#334155', scaleMargins: { top: 0.1, bottom: 0.1 } },
    rightPriceScale: { visible: false },
  });
  const series = chart.addLineSeries({
    color: opts.color,
    lineWidth: 1.5,
    priceScaleId: 'left',
    priceFormat: { type: 'price', precision: opts.precision, minMove: opts.minMove },
  });
  // RSI/OBV: warmup null 채워서 sub-chart 의 candleData 와 길이/타임스탬프 정확 일치 보장.
  // 이래야 logical range (인덱스 기반) 동기화 시 메인 차트와 정확히 정렬됨.
  // null 은 setData 가 자동 무시 (선이 갭으로 표시).
  const data = candleData.map((c, i) => values[i] == null
    ? { time: c.time }                       // whitespace point — x 자리는 차지하되 y 안 그림
    : { time: c.time, value: values[i] }
  );
  series.setData(data);
  (opts.horizontalLines || []).forEach(hl => {
    series.createPriceLine({ price: hl.price, color: hl.color, lineWidth: 1, lineStyle: 2, axisLabelVisible: !!hl.title, title: hl.title });
  });
  _detailChartState[stateKey] = chart;
  if (opts.infoEl) {
    const last = values[values.length - 1];
    document.getElementById(opts.infoEl).textContent = last != null ? `${opts.name} = ${last.toFixed(opts.precision)}` : `${opts.name} = -`;
  }
  _attachSubChartSync(chart);
}

// 메인 차트 ↔ 보조차트 동기화 (logical range 기반 — 인덱스로 정렬).
// 이전엔 time range 사용했는데, RSI/MACD warmup null 이 있으면 sub-chart 의
// 내부 시간 범위가 메인과 달라져 동기화 어긋남. 이제 모든 sub-chart 가 메인과
// 동일한 candleData 길이로 setData 하므로 logical range 정확.
function _attachSubChartSync(subChart) {
  const main = _detailChartState.chart;
  if (!main || !subChart) return;
  // 초기 range 메인에서 가져와 적용
  try {
    const init = main.timeScale().getVisibleLogicalRange();
    if (init) subChart.timeScale().setVisibleLogicalRange(init);
  } catch (e) {}
  // main → this sub
  main.timeScale().subscribeVisibleLogicalRangeChange((r) => {
    if (_detailChartState._isSyncing || !r) return;
    _detailChartState._isSyncing = true;
    try { subChart.timeScale().setVisibleLogicalRange(r); } finally { _detailChartState._isSyncing = false; }
  });
  // this sub → main (양방향)
  subChart.timeScale().subscribeVisibleLogicalRangeChange((r) => {
    if (_detailChartState._isSyncing || !r) return;
    _detailChartState._isSyncing = true;
    try { main.timeScale().setVisibleLogicalRange(r); } finally { _detailChartState._isSyncing = false; }
  });
}

// MACD 전용 (line + signal + histogram)
function _renderMacdChart(containerId, candleData, macdRes, infoElId) {
  const container = document.getElementById(containerId);
  if (!container) return;
  if (_detailChartState.macdChart) {
    try { _detailChartState.macdChart.remove(); } catch (e) {}
    _detailChartState.macdChart = null;
  }
  Array.from(container.children).forEach(c => c.remove());
  if (typeof LightweightCharts === 'undefined') return;
  const chart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: container.clientHeight || 140,
    layout: { background: { type: 'solid', color: '#0f172a' }, textColor: '#94a3b8', fontSize: 10 },
    grid: { vertLines: { color: 'rgba(148,163,184,0.05)' }, horzLines: { color: 'rgba(148,163,184,0.05)' } },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    // 메인 차트와 동일 timeScale 옵션 — sub-chart 동기화 일관성.
    timeScale: { borderColor: '#334155', timeVisible: false, visible: false, rightOffset: 12 },
    leftPriceScale: { visible: true, borderColor: '#334155', scaleMargins: { top: 0.1, bottom: 0.1 } },
    rightPriceScale: { visible: false },
  });
  // Histogram (양/음 색 다르게). null 자리는 whitespace point 로 채워 길이 일치.
  const histSeries = chart.addHistogramSeries({ priceScaleId: 'left', priceFormat: { type: 'price', precision: 6, minMove: 0.000001 }, color: '#10b981' });
  const histData = candleData.map((c, i) => macdRes.histogram[i] == null
    ? { time: c.time }
    : { time: c.time, value: macdRes.histogram[i],
        color: macdRes.histogram[i] >= 0 ? 'rgba(16,185,129,0.6)' : 'rgba(239,68,68,0.6)' }
  );
  histSeries.setData(histData);
  // MACD line
  const lineSeries = chart.addLineSeries({ color: '#60a5fa', lineWidth: 1.5, priceScaleId: 'left', priceFormat: { type: 'price', precision: 6, minMove: 0.000001 } });
  lineSeries.setData(candleData.map((c, i) => macdRes.line[i] == null
    ? { time: c.time } : { time: c.time, value: macdRes.line[i] }
  ));
  // Signal line
  const sigSeries = chart.addLineSeries({ color: '#f97316', lineWidth: 1.5, priceScaleId: 'left', priceFormat: { type: 'price', precision: 6, minMove: 0.000001 } });
  sigSeries.setData(candleData.map((c, i) => macdRes.signal[i] == null
    ? { time: c.time } : { time: c.time, value: macdRes.signal[i] }
  ));
  // 0 기준선
  lineSeries.createPriceLine({ price: 0, color: 'rgba(148,163,184,0.3)', lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: '' });
  _detailChartState.macdChart = chart;
  // 정보 라벨
  if (infoElId) {
    const lastL = macdRes.line[macdRes.line.length - 1];
    const lastS = macdRes.signal[macdRes.signal.length - 1];
    const lastH = macdRes.histogram[macdRes.histogram.length - 1];
    document.getElementById(infoElId).textContent = (lastL !== null && lastS !== null)
      ? `MACD ${lastL.toFixed(6)} / Signal ${lastS.toFixed(6)} / Hist ${lastH !== null ? lastH.toFixed(6) : '-'}`
      : 'MACD 데이터 부족';
  }
  // 메인 ↔ MACD 동기화 — RSI/OBV 와 동일 헬퍼 사용 (logical range 기반)
  _attachSubChartSync(chart);
}
