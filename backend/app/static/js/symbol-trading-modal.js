/**
 * Symbol Trading Modal — 사장님 = 「📊」 클릭 = 차트 + Order Book + 수동 거래 통합 (#22!)
 *
 * 사장님 = 1 클릭 = 모든 정보 + 자율 운영!
 * = critical = lightweight-charts CDN + WebSocket depth + 수동 거래 검증!
 *
 * Phase 2/3: 차트 + Order Book
 * Phase 4: 수동 거래 = backend endpoint 필요 (= 별도 PR!)
 */
(function() {
    'use strict';

    const LWC_CDN = 'https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js';
    let lwcLoaded = false;
    let currentSymbol = null;
    let currentInterval = '1h';
    let chart = null;
    let candleSeries = null;
    let depthWs = null;
    let intervalRefresh = null;

    /** lightweight-charts CDN 로드 (= 1회!) */
    function loadLWC() {
        return new Promise((resolve, reject) => {
            if (lwcLoaded || window.LightweightCharts) {
                lwcLoaded = true;
                resolve();
                return;
            }
            const script = document.createElement('script');
            script.src = LWC_CDN;
            script.onload = () => { lwcLoaded = true; resolve(); };
            script.onerror = () => reject(new Error('lightweight-charts CDN load failed'));
            document.head.appendChild(script);
        });
    }

    /** 모달 HTML 생성 (= 3 컬럼!) */
    function buildModalHtml(symbol) {
        return `
        <div id="symbol-trading-modal-overlay" class="modal-overlay" style="z-index:9000;">
          <div class="modal-content" style="max-width:1280px;width:96vw;max-height:92vh;overflow:auto;background:#1a1d24;color:#e0e0e0;border-radius:8px;">
            <div style="padding:14px 18px;border-bottom:1px solid #2a2f3a;display:flex;justify-content:space-between;align-items:center;">
              <h2 style="margin:0;font-size:18px;">📊 <span id="stm-symbol-title">${symbol}</span> = 차트 + Order Book + 수동 거래</h2>
              <button id="stm-close-btn" style="background:#3a3f4a;color:#fff;border:0;border-radius:4px;padding:6px 12px;cursor:pointer;">✕</button>
            </div>
            <div style="display:grid;grid-template-columns:1fr 320px 280px;gap:12px;padding:14px;min-height:500px;">
              <!-- 좌: 차트 -->
              <div>
                <div style="margin-bottom:8px;display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
                  <span style="font-size:12px;color:#888;">인터벌:</span>
                  ${['1m','5m','15m','1h','4h','1d'].map(iv => `
                    <button class="stm-iv-btn" data-iv="${iv}" style="background:${iv==='1h'?'#2e7d32':'#3a3f4a'};color:#fff;border:0;border-radius:3px;padding:3px 8px;font-size:11px;cursor:pointer;">${iv}</button>
                  `).join('')}
                  <span id="stm-price-now" style="margin-left:12px;font-weight:bold;color:#4dabf7;font-size:14px;">--</span>
                </div>
                <div id="stm-chart" style="width:100%;height:460px;background:#0d1117;border:1px solid #2a2f3a;border-radius:4px;"></div>
                <div id="stm-chart-status" style="font-size:11px;color:#888;margin-top:4px;">로딩 중...</div>
              </div>
              <!-- 중: Order Book -->
              <div>
                <div style="font-size:13px;color:#888;margin-bottom:6px;">📖 Order Book (실시간)</div>
                <div id="stm-orderbook" style="background:#0d1117;border:1px solid #2a2f3a;border-radius:4px;padding:8px;height:480px;overflow:hidden;font-family:'Courier New',monospace;font-size:11px;">
                  <div style="text-align:center;color:#888;padding:20px;">로딩 중...</div>
                </div>
              </div>
              <!-- 우: 수동 거래 UI (= Phase 4 = 안전 우선!) -->
              <div>
                <div style="font-size:13px;color:#888;margin-bottom:6px;">💼 수동 거래</div>
                <div style="background:#2a1f1f;border:1px solid #5a3a3a;border-radius:4px;padding:10px;color:#ffa500;font-size:11px;line-height:1.5;">
                  ⚠️ <b>수동 거래 = Phase 4</b><br>
                  사장님 critical 자본 보호 = 다층 검증 + 확인 모달 = 별도 PR!<br><br>
                  현재 = 차트 + Order Book = <b>조회 전용</b>!<br>
                  사장님 = 화면 확인 후 = Binance 앱 거래!
                </div>
                <div style="margin-top:12px;font-size:12px;color:#888;">
                  ✅ 차트 마커: Entry/SL/TP1/TP2 (= 활성 strategy!)<br>
                  ✅ 인터벌 변경: 1m~1d<br>
                  ✅ Order Book: depth20@100ms!
                </div>
              </div>
            </div>
          </div>
        </div>
        `;
    }

    /** 차트 초기화! */
    async function initChart() {
        await loadLWC();
        const container = document.getElementById('stm-chart');
        if (!container || !window.LightweightCharts) return;
        chart = LightweightCharts.createChart(container, {
            width: container.clientWidth,
            height: 460,
            layout: { background: { color: '#0d1117' }, textColor: '#aaa' },
            grid: { vertLines: { color: '#1a1d24' }, horzLines: { color: '#1a1d24' } },
            timeScale: { borderColor: '#2a2f3a', timeVisible: true, secondsVisible: false },
            rightPriceScale: { borderColor: '#2a2f3a' },
        });
        candleSeries = chart.addCandlestickSeries({
            upColor: '#26a69a',
            downColor: '#ef5350',
            borderUpColor: '#26a69a',
            borderDownColor: '#ef5350',
            wickUpColor: '#26a69a',
            wickDownColor: '#ef5350',
        });
        await refreshKlines();
    }

    /** klines fetch + 차트 업데이트! */
    async function refreshKlines() {
        if (!currentSymbol || !candleSeries) return;
        const status = document.getElementById('stm-chart-status');
        try {
            const r = await fetch(`/api/v1/market/klines?symbol=${currentSymbol}&interval=${currentInterval}&limit=300`);
            if (!r.ok) throw new Error('klines fetch fail');
            const data = await r.json();
            const candles = data.map(k => ({
                time: Math.floor(k[0] / 1000),
                open: parseFloat(k[1]),
                high: parseFloat(k[2]),
                low: parseFloat(k[3]),
                close: parseFloat(k[4]),
            }));
            candleSeries.setData(candles);
            if (candles.length > 0) {
                const last = candles[candles.length - 1].close;
                const priceEl = document.getElementById('stm-price-now');
                if (priceEl) priceEl.textContent = `현재: ${last}`;
            }
            if (status) status.textContent = `✅ ${candles.length} 캔들 (${currentInterval})`;
        } catch (e) {
            if (status) status.textContent = `❌ ${e.message}`;
        }
    }

    /** Order Book WebSocket! */
    function initOrderBook() {
        if (!currentSymbol) return;
        if (depthWs) {
            try { depthWs.close(); } catch (_) {}
            depthWs = null;
        }
        const symbolLower = currentSymbol.toLowerCase();
        try {
            depthWs = new WebSocket(`wss://fstream.binance.com/ws/${symbolLower}@depth20@100ms`);
            depthWs.onmessage = (e) => {
                try {
                    const data = JSON.parse(e.data);
                    renderOrderBook(data);
                } catch (_) {}
            };
            depthWs.onerror = () => {
                const el = document.getElementById('stm-orderbook');
                if (el) el.innerHTML = '<div style="color:#ef5350;padding:20px;text-align:center;">WebSocket 실패!</div>';
            };
        } catch (e) {
            // fallback = REST!
            fallbackDepthRest();
        }
    }

    /** Order Book render! */
    function renderOrderBook(data) {
        const el = document.getElementById('stm-orderbook');
        if (!el) return;
        const bids = (data.b || data.bids || []).slice(0, 15);
        const asks = (data.a || data.asks || []).slice(0, 15).reverse();
        const maxQty = Math.max(
            ...bids.map(b => parseFloat(b[1])),
            ...asks.map(a => parseFloat(a[1])),
            1
        );
        const askHtml = asks.map(a => {
            const price = a[0]; const qty = parseFloat(a[1]);
            const pct = Math.min(100, (qty / maxQty) * 100);
            return `<div style="display:grid;grid-template-columns:1fr 1fr;padding:1px 4px;background:linear-gradient(to left, rgba(239,83,80,0.2) ${pct}%, transparent ${pct}%);"><span style="color:#ef5350;">${price}</span><span style="color:#aaa;text-align:right;">${qty}</span></div>`;
        }).join('');
        const bidHtml = bids.map(b => {
            const price = b[0]; const qty = parseFloat(b[1]);
            const pct = Math.min(100, (qty / maxQty) * 100);
            return `<div style="display:grid;grid-template-columns:1fr 1fr;padding:1px 4px;background:linear-gradient(to left, rgba(38,166,154,0.2) ${pct}%, transparent ${pct}%);"><span style="color:#26a69a;">${price}</span><span style="color:#aaa;text-align:right;">${qty}</span></div>`;
        }).join('');
        const midPrice = asks.length > 0 ? asks[asks.length - 1][0] : (bids[0] ? bids[0][0] : '--');
        el.innerHTML = `
            <div style="margin-bottom:4px;font-weight:bold;color:#888;display:grid;grid-template-columns:1fr 1fr;padding:0 4px;">
                <span>가격</span><span style="text-align:right;">수량</span>
            </div>
            ${askHtml}
            <div style="text-align:center;padding:4px;background:#1a1d24;color:#4dabf7;font-weight:bold;margin:2px 0;">⭐ ${midPrice}</div>
            ${bidHtml}
        `;
    }

    /** WebSocket 실패 시 REST fallback! */
    async function fallbackDepthRest() {
        try {
            const r = await fetch(`/api/v1/market/depth?symbol=${currentSymbol}&limit=20`);
            if (!r.ok) throw new Error('depth REST fail');
            const data = await r.json();
            renderOrderBook(data);
        } catch (e) {
            const el = document.getElementById('stm-orderbook');
            if (el) el.innerHTML = `<div style="color:#ef5350;padding:20px;text-align:center;">depth 로드 실패: ${e.message}</div>`;
        }
    }

    /** 인터벌 변경! */
    function bindIntervalButtons() {
        document.querySelectorAll('.stm-iv-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.stm-iv-btn').forEach(b => b.style.background = '#3a3f4a');
                btn.style.background = '#2e7d32';
                currentInterval = btn.dataset.iv;
                refreshKlines();
            });
        });
    }

    /** 모달 닫기 + 정리! */
    function closeModal() {
        if (depthWs) { try { depthWs.close(); } catch (_) {} depthWs = null; }
        if (intervalRefresh) { clearInterval(intervalRefresh); intervalRefresh = null; }
        if (chart) { try { chart.remove(); } catch (_) {} chart = null; candleSeries = null; }
        const overlay = document.getElementById('symbol-trading-modal-overlay');
        if (overlay) overlay.remove();
        currentSymbol = null;
    }

    /** 사장님 = 「📊」 클릭 = 모달 열기! */
    window.openSymbolTradingModal = async function(symbol) {
        if (!symbol) return;
        closeModal();  // 옛 모달 정리!
        currentSymbol = symbol.toUpperCase();
        currentInterval = '1h';
        document.body.insertAdjacentHTML('beforeend', buildModalHtml(currentSymbol));
        const closeBtn = document.getElementById('stm-close-btn');
        if (closeBtn) closeBtn.addEventListener('click', closeModal);
        const overlay = document.getElementById('symbol-trading-modal-overlay');
        if (overlay) overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closeModal();
        });
        bindIntervalButtons();
        await initChart();
        initOrderBook();
        // 매 30초 = klines refresh!
        intervalRefresh = setInterval(refreshKlines, 30000);
    };

    // ESC 키 = 닫기!
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && currentSymbol) closeModal();
    });
})();
