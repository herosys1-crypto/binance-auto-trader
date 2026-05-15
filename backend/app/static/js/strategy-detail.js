/**
 * 전략 상세 패널 로더 + 정지 액션 (Phase 3 단계 3m, 2026-05-15).
 *
 * selectStrategy(id) — 전략 클릭 시 timeline + stagePlans + orders + strategy 를 한 번에
 *   가져와 detail 섹션에 렌더. 차트 렌더는 별도 chart-detail.js 의 _renderDetailChart 호출.
 * stopStrategy(id)   — 미체결 주문만 취소 (포지션 유지). 실패 시 force-stop 폴백 옵션 제공.
 *
 * 외부 의존 (script-scope 공유):
 *   - api, escapeHtml, fmtNum, fmtQty, fmtPnL, toast (전역 헬퍼)
 *   - ORDER_STATUS_MAP, PURPOSE_MAP (constants.js)
 *   - _renderDetailChart, refreshStrategies (다른 모듈)
 */

async function selectStrategy(id) {
  document.getElementById('detail-section').classList.remove('hidden');
  // UX #25: 데이터 로드 전에 즉시 detail section 으로 스크롤 (block: start = 차트가 화면 상단에)
  document.getElementById('detail-section').scrollIntoView({ behavior: 'smooth', block: 'start' });
  try {
    const [timeline, stagePlans, orders, strategy] = await Promise.all([
      api('/strategies/' + id + '/timeline?limit=100').catch(() => []),
      api('/strategies/' + id + '/stage-plans').catch(() => []),
      api('/orders/by-strategy/' + id).catch(() => []),
      api('/strategies/' + id).catch(() => null),
    ]);

    // UX #20: 차트 + 가로선 렌더링 (실패해도 다른 섹션은 정상 표시)
    if (strategy) {
      _renderDetailChart(strategy, stagePlans).catch(e => console.warn('chart render fail', e));
    }

    // 2026-05-12 (사용자 요청): 「선택 전략」 카드 헤더에 심볼 + 방향 + 전략 ID 표시.
    // 이전엔 「선택 전략 — 단계별 계획」 처럼 어떤 전략인지 알 수 없었음.
    const sideLabel = strategy?.side === 'SHORT' ? '📉 SHORT' : (strategy?.side === 'LONG' ? '📈 LONG' : '');
    const headerLabel = strategy
      ? `— #${id} ${escapeHtml(strategy.symbol || '?')} ${sideLabel}`
      : `— #${id}`;
    const stEl = document.getElementById('detail-stage-symbol');
    const ordEl = document.getElementById('detail-orders-symbol');
    if (stEl) stEl.innerHTML = headerLabel;
    if (ordEl) ordEl.innerHTML = headerLabel;

    // 활동 타임라인 렌더링
    const tlEl = document.getElementById('timeline-container');
    if (!timeline.length) {
      tlEl.innerHTML = '<p class="text-slate-500 text-sm text-center py-4">활동 이력 없음</p>';
    } else {
      const kindColor = { ORDER: 'text-blue-300', RISK: 'text-red-300', NOTIFY: 'text-slate-400' };
      tlEl.innerHTML = timeline.map(t => {
        const ts = new Date(t.ts);
        const tsStr = ts.toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const kindCls = kindColor[t.kind] || 'text-slate-300';
        return `<div class="flex gap-3 py-1.5 border-b border-slate-700 last:border-0 text-xs">
          <div class="text-slate-500 font-mono whitespace-nowrap" style="min-width:120px">${tsStr}</div>
          <div class="text-lg leading-tight">${t.icon}</div>
          <div class="flex-1">
            <div class="${kindCls} font-semibold">${escapeHtml(t.title)}</div>
            <div class="text-slate-400 text-xs mt-0.5">${escapeHtml(t.detail || '')}</div>
          </div>
        </div>`;
      }).join('');
    }

    // 단계별 계획 렌더링
    const stTbody = document.getElementById('stage-plans-tbody');
    if (!stagePlans.length) {
      stTbody.innerHTML = '<tr><td colspan="7" class="text-center text-slate-500 py-6">단계 계획 없음</td></tr>';
    } else {
      // 최종 단계 trigger 표기 (사용자 #5-07 보고): trigger_percent 가 null/빈 값이면
      // backend 기본 20% 적용 — UI 도 그대로 표기 (이전엔 "+null% 도달 시" 처럼 깨졌음).
      const lastStageNo = stagePlans.length;
      stTbody.innerHTML = stagePlans.map(s => {
        const fmtPct = (pct) => {
          if (pct === null || pct === undefined || pct === '') return null;
          const n = Number(pct); if (isNaN(n)) return String(pct);
          return n.toLocaleString('en-US', {maximumFractionDigits: 2});
        };
        const conditionKo = (mode, pct, isLast) => {
          if (mode === 'IMMEDIATE') return '즉시 진입';
          // pct null/빈값 → backend 기본 20% (last_stage_trigger_percent 미지정 시)
          const p = fmtPct(pct) || (isLast ? '20' : '?');
          if (mode === 'PRICE_UP_PCT') return `+${p}% 도달 시`;
          if (mode === 'PRICE_DOWN_PCT') return `-${p}% 도달 시`;
          if (mode === 'LIQUIDATION_BUFFER') return fmtPct(pct) ? `청산가 -${p}%` : '청산 임박 시';
          return mode;
        };
        let stageStatus, badgeClass;
        if (s.is_triggered) {
          stageStatus = '✅ 발동됨';
          badgeClass = 'badge-green';
        } else if (!s.is_enabled) {
          stageStatus = '⏸ 비활성';
          badgeClass = 'badge-gray';
        } else {
          stageStatus = '⏳ 대기';
          badgeClass = 'badge-yellow';
        }
        const triggeredTime = s.triggered_at
          ? new Date(s.triggered_at).toLocaleString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
          : '-';
        const isLast = s.stage_no === lastStageNo;
        const stageLabel = isLast
          ? `${s.stage_no} <span class="text-purple-300" style="font-size:10px" title="마지막 단계 — last_stage_trigger_percent 적용">최종</span>`
          : `${s.stage_no}`;
        // trigger_price 가 비어있으면 (legacy LIQUIDATION_BUFFER 미산정) 명시적 안내
        const trigPriceCell = s.trigger_price
          ? fmtNum(s.trigger_price)
          : (s.trigger_mode === 'LIQUIDATION_BUFFER'
              ? '<span class="text-slate-500" title="청산가 도달 시점에 산정 (보통 청산가의 95%)">청산가 산정</span>'
              : '<span class="text-slate-500">-</span>');
        return `<tr${isLast ? ' class="bg-slate-800/40"' : ''}>
          <td class="text-center font-semibold text-slate-200">${stageLabel}</td>
          <td>${conditionKo(s.trigger_mode, s.trigger_percent, isLast)}</td>
          <td class="num">${trigPriceCell}</td>
          <td class="num">${fmtNum(s.planned_capital)} <span class="text-slate-500 text-xs">USDT</span></td>
          <td class="num">${s.planned_qty ? fmtQty(s.planned_qty) : '<span class="text-slate-500">-</span>'}</td>
          <td><span class="badge ${badgeClass}">${stageStatus}</span></td>
          <td class="text-xs text-slate-400">${triggeredTime}</td>
        </tr>`;
      }).join('');
    }

    // 주문 내역 렌더링
    const tbody = document.getElementById('orders-tbody');
    if (orders.length === 0) {
      tbody.innerHTML = '<tr><td colspan="11" class="text-center text-slate-500 py-6">주문 없음</td></tr>';
    } else {
      tbody.innerHTML = orders.map(o => {
        const oInfo = ORDER_STATUS_MAP[o.status] || { ko: o.status, sig: 'gray' };
        const purpose = PURPOSE_MAP[o.purpose] || o.purpose;
        const sideKo = o.side === 'SELL' ? '매도 📉' : '매수 📈';
        // EXIT 손익 + ROI 표시 (2026-05-03 추가) — backend 가 계산해서 응답
        const isExit = ['EXIT', 'TAKE_PROFIT', 'STOP_LOSS', 'EMERGENCY_CLOSE'].includes(o.purpose);
        let pnlCell = '<td class="num text-slate-600">-</td>';
        let pctCell = '<td class="num text-slate-600">-</td>';
        if (isExit && o.realized_pnl !== null && o.realized_pnl !== undefined) {
          const pnlNum = Number(o.realized_pnl);
          const color = pnlNum >= 0 ? 'text-green-400' : 'text-red-400';
          pnlCell = `<td class="num ${color} font-semibold">${fmtPnL(pnlNum)}</td>`;
          if (o.pnl_pct !== null && o.pnl_pct !== undefined) {
            const pctNum = Number(o.pnl_pct);
            const pctColor = pctNum >= 0 ? 'text-green-400' : 'text-red-400';
            pctCell = `<td class="num ${pctColor}">${fmtPnL(pctNum)}%</td>`;
          }
        }
        return `<tr>
          <td>#${o.id}</td>
          <td>${o.stage_no || '-'}</td>
          <td>${purpose}</td>
          <td>${sideKo}</td>
          <td>${o.order_type}</td>
          <td class="num">${fmtNum(o.price)}</td>
          <td class="num">${fmtQty(o.orig_qty)}</td>
          <td class="num">${fmtQty(o.executed_qty)}</td>
          <td><span class="badge badge-${oInfo.sig}">${oInfo.ko}</span></td>
          ${pnlCell}
          ${pctCell}
        </tr>`;
      }).join('');
    }

    // UX #25: 스크롤은 selectStrategy 시작 시점에 이미 처리됨 (block: 'start')
  } catch (err) { toast('상세 조회 실패: ' + err.message, 'error'); }
}

async function stopStrategy(id) {
  if (!confirm(`전략 #${id} 의 모든 미체결 주문을 취소합니다.\n\n포지션은 그대로 유지됩니다.\n진행할까요?`)) return;
  try {
    await api(`/strategies/${id}/stop`, {method: 'POST', body: {mode: 'cancel_only', reason: '대시보드에서 수동 정지'}});
    toast(`전략 #${id} 미체결 주문 취소 요청 발송`, 'success');
    refreshStrategies();
  } catch (err) {
    // 거래소 키 깨짐 등으로 정지 실패 시 강제 정지 옵션 제공
    if (confirm(`정지 실패: ${err.message}\n\nDB 상에서만 STOPPED 로 강제 마킹하시겠어요?\n(거래소 호출 없음 — 거래소에 미체결 주문이 남아있을 수 있으니 직접 확인 필요)`)) {
      try {
        await api(`/strategies/${id}/force-stop`, { method: 'POST' });
        toast(`전략 #${id} DB 강제 정지 완료`, 'success');
        refreshStrategies();
      } catch (e2) { toast('강제 정지 실패: ' + e2.message, 'error'); }
    }
  }
}
