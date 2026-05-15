/**
 * Strategies list panel — refresh + archive toggle + restore (Phase 3 단계 3m, 2026-05-15).
 *
 * 「🎯 전략 인스턴스」 panel 의 모든 액션 + state.
 *
 * 함수:
 *   - toggleShowArchivedStrategies()    : localStorage 저장 + 목록 갱신
 *   - _initArchiveToggleFromStorage()    : 페이지 진입 시 체크박스 복원
 *   - restoreStrategy(id)                : archived 전략 UI 목록에 다시 표시
 *   - refreshStrategies()                : 메인 전략 목록 fetch + 카드 렌더 (~244줄)
 *   - refreshExchangeAccounts()          : (legacy no-op, 별도 카드 없음)
 *
 * State (이 모듈 소유):
 *   - _showArchivedStrategies : 「📦 보관 보기」 체크박스 상태 (localStorage 동기화)
 *
 * 외부 의존성 (script-scope 공유):
 *   - api / toast (api.js)
 *   - statusInfo / sideBadge / fmtNum / fmtQty / fmtPnL / escapeHtml /
 *     renderStageBar / renderTpBar / setMetric (helpers.js)
 *   - renderWhitelistBadge (dashboard-refresh.js)
 *   - selectStrategy / triggerNextStage / addMargin / addPosition / stopStrategy /
 *     emergencyStop / deleteStrategy / editStrategy / restartStrategy (index.html)
 *   - _computeIsolatedLiqPrice (indicators.js)
 *   - DOM: #strategies-tbody, #show-archived, #metric-active*, #metric-active-symbols
 */

// refreshExchangeAccounts — legacy no-op (별도 카드 없음, 시스템 카드 detail 표시).
async function refreshExchangeAccounts() {
  try {
    await api('/exchange-accounts');
  } catch (err) { /* 무시 */ }
}

// 2026-05-06 (C-full Step 3): archived 보기 토글. localStorage 저장.
let _showArchivedStrategies = localStorage.getItem('show_archived_strategies') === 'true';

function toggleShowArchivedStrategies() {
  // 체크박스 직접 클릭 (DOM 이벤트) 시 호출 — 체크박스 state 가 source of truth.
  const cb = document.getElementById('show-archived');
  _showArchivedStrategies = cb ? cb.checked : !_showArchivedStrategies;
  localStorage.setItem('show_archived_strategies', _showArchivedStrategies ? 'true' : 'false');
  refreshStrategies();
}

// 페이지 로드 시 체크박스 상태 복원 (showDashboard 후 호출).
function _initArchiveToggleFromStorage() {
  const cb = document.getElementById('show-archived');
  if (cb) cb.checked = _showArchivedStrategies;
}

async function restoreStrategy(id) {
  if (!confirm(`↻ 전략 #${id} 복원\n\narchive 상태 → UI 목록에 다시 표시.\nstatus 그대로 유지 (여전히 종료 상태).\n\n진행할까요?`)) return;
  try {
    const r = await api(`/strategies/${id}/restore`, { method: 'POST' });
    toast(r.message || `전략 #${id} 복원 완료`, 'success');
    refreshStrategies();
  } catch (e) { toast('복원 실패: ' + e.message, 'error'); }
}

async function refreshStrategies() {
  try {
    const url = '/strategies' + (_showArchivedStrategies ? '?include_archived=true' : '');
    const data = await api(url);
    const active = data.filter(s => !TERMINAL_STATUSES.includes((s.status || '').toUpperCase()) && !s.is_archived);
    let totalUnrealized = 0;
    let totalMarginUsed = 0;  // 마진 합 = sum(capital / leverage) — 사용자 실제 사용 자본
    active.forEach(s => {
      const pnl = Number(s.unrealized_pnl || 0);
      const cap = Number(s.total_capital || 0);
      const lev = Number(s.leverage || 1) || 1;
      totalUnrealized += pnl;
      if (cap > 0 && lev > 0) totalMarginUsed += cap / lev;
    });
    // 전체 ROI % = 총 USD 손익 / 총 마진 × 100 (사용자 실제 자본 대비 수익률)
    const overallRoiPct = totalMarginUsed > 0 ? (totalUnrealized / totalMarginUsed * 100) : 0;

    setMetric('active', active.length + '건',
      active.length === 0 ? '진행 중인 전략 없음' : `전체 ${data.length}건 중`,
      active.length === 0 ? 'gray' : 'green');

    const pnlSig = totalUnrealized > 0 ? 'green' : totalUnrealized < 0 ? 'red' : 'gray';
    const pnlEl = document.getElementById('metric-pnl');
    const roiSign = overallRoiPct > 0 ? '+' : '';
    pnlEl.innerHTML = `${fmtPnL(totalUnrealized)} USDT <span class="text-xs font-normal">(${roiSign}${overallRoiPct.toFixed(2)}%)</span>`;
    pnlEl.className = 'text-2xl font-bold ' + (totalUnrealized > 0 ? 'pos' : totalUnrealized < 0 ? 'neg' : '');
    setSignal('card-pnl', pnlSig);

    const tbody = document.getElementById('strategies-tbody');
    if (data.length === 0) {
      tbody.innerHTML = '<tr><td colspan="9" class="text-center text-slate-500 py-3 text-xs">전략 없음</td></tr>';
      return;
    }

    // 위험 신호 감지 (청산 임박, 손절 종료, 크라이시스 모드)
    const danger = data.find(s => ['LIQUIDATION_IMMINENT', 'KILL_SWITCH_TRIGGERED'].includes((s.status || '').toUpperCase()));
    const crisisActive = data.find(s => s.crisis_mode_triggered_at && !TERMINAL_STATUSES.includes((s.status || '').toUpperCase()));
    if (danger) {
      showAlert(`전략 #${danger.id} ${danger.symbol} ${danger.side} — 즉시 확인 필요`, statusInfo(danger.status).ko);
    } else if (crisisActive) {
      const stage2 = !!crisisActive.crisis_first_tp_done_at;
      const detail = stage2
        ? `Stage 2 보호 활성 — 트레일링 -5% + 빠른 손절 -1% 동작 중. 최대 손실: ${fmtNum(crisisActive.max_loss_pct)}% / 피크 후 PnL 추적 중.`
        : `Stage 1 — TP1 임계 +5% 활성. 최대 손실: ${fmtNum(crisisActive.max_loss_pct)}% 도달했으니 회복 시 빠른 익절 예정.`;
      showAlert(`🚨 크라이시스 모드 활성 — 전략 #${crisisActive.id} ${crisisActive.symbol} ${crisisActive.side}`, detail);
    } else {
      hideAlert();
    }

    // 종료된 전략 숨김 토글
    const hideTerm = document.getElementById('hide-terminated')?.checked;
    let visible = data;
    if (hideTerm) visible = data.filter(s => !TERMINAL_STATUSES.includes((s.status || '').toUpperCase()));
    const hiddenCount = data.length - visible.length;
    if (visible.length === 0 && hiddenCount > 0) {
      tbody.innerHTML = `<tr><td colspan="9" class="text-center text-slate-500 py-3 text-xs">진행 중인 전략 없음 (종료 ${hiddenCount}건 숨김)</td></tr>`;
      return;
    }

    // 활성 전략 우선 정렬
    const sorted = [...visible].sort((a, b) => {
      const aTerm = TERMINAL_STATUSES.includes((a.status || '').toUpperCase()) ? 1 : 0;
      const bTerm = TERMINAL_STATUSES.includes((b.status || '').toUpperCase()) ? 1 : 0;
      return aTerm - bTerm || b.id - a.id;
    });

    tbody.innerHTML = sorted.map(s => {
      const info = statusInfo(s.status);
      // 단계 진행도 + TP 진행도 두 줄 stack — 분모는 template 의 활성 단계/TP 수 (동적).
      // backend 응답의 total_active_stages / total_active_tps 사용. 옛 backend 호환: fallback 4.
      const totalStages = s.total_active_stages || 4;
      const totalTps = s.total_active_tps || 4;
      // 2026-05-03 fix: backend 의 실제 발동 카운트 (tp_triggered_count) 우선 사용.
      // 옛 backend 면 status 추론 fallback. 종료 사유 (last_close_reason) 도 표시.
      const tpCount = (s.tp_triggered_count !== undefined && s.tp_triggered_count !== null)
        ? s.tp_triggered_count
        : _tpCountFromStatus(s, totalTps);
      const closeReason = s.last_close_reason || 'NONE';
      const stageBar = s.current_stage > 0 ? renderStageBar(s.current_stage, totalStages) : '<span class="text-slate-500">대기</span>';
      const tpBar = renderTpBar(tpCount, totalTps, closeReason);
      const stage = `<div class="text-xs leading-tight"><span class="text-slate-400" style="font-size:10px">진입</span> ${stageBar}<br><span class="text-slate-400" style="font-size:10px">익절</span> ${tpBar}</div>`;
      const pnlNum = Number(s.unrealized_pnl || 0);
      const sCap = Number(s.total_capital || 0);
      const sLev = Number(s.leverage || 1) || 1;
      const sQtyNum = Number(s.current_position_qty || 0);
      const sQtyAbs = Math.abs(sQtyNum);
      const sAvg = Number(s.avg_entry_price || 0);
      const hasPosition = sQtyAbs > 0 && sAvg > 0;
      // 마크 가격 = avg + pnl/qty (LONG) | avg - pnl/qty (SHORT)
      const sMark = hasPosition ? (s.side === 'LONG' ? sAvg + pnlNum/sQtyAbs : sAvg - pnlNum/sQtyAbs) : 0;
      // 청산예정가 = isolated 계산 (체결 평단 기반)
      const MMR = 0.005;
      const sLiq = hasPosition && sLev > 0 ? (s.side === 'SHORT' ? sAvg * (1 + 1/sLev - MMR) : sAvg * (1 - 1/sLev + MMR)) : 0;

      // 2026-05-04 v3 (Binance ROI 일치): 두 가지 ROI 분리.
      //   포지션 ROI = pnl / 현재_사용_마진 × 100  ← Binance UI 와 일치 (실제 진입한 부분만).
      //   전략 ROI   = pnl × leverage / total_capital × 100  ← 전체 전략 자본 대비.
      // 마지막까지 모든 단계 진입하면 두 값이 같아짐 (현재_사용_마진 == 계획_총_마진).
      // 1단계만 진입한 6단계 전략은 두 값이 크게 다름 — 사용자 비교 혼란 원인이었음.
      const positionNotional = hasPosition ? sQtyAbs * sAvg : 0;
      const positionMargin = positionNotional > 0 && sLev > 0 ? positionNotional / sLev : 0;
      const positionRoi = positionMargin > 0 ? (pnlNum / positionMargin * 100) : 0;
      const strategyRoi = sCap > 0 ? (pnlNum * sLev / sCap * 100) : 0;
      // 계획된 마진 (전체 단계 진입 시) — 「수량/마진」 컬럼의 보조 정보용.
      const plannedMargin = sCap > 0 && sLev > 0 ? sCap / sLev : 0;

      // 평단/마크/청산 — 3 줄 stack (Binance 스타일)
      const priceStack = hasPosition
        ? `<div class="text-xs leading-tight"><span class="text-slate-300" title="평단가">${fmtNum(sAvg)}</span><br><span class="text-cyan-300" title="마크가">${fmtNum(sMark)}</span><br><span class="text-red-300" title="청산예정">${fmtNum(sLiq)}</span></div>`
        : '<span class="text-slate-500">-</span>';
      // 수량/마진 — 2 줄 stack + 「💰 증거금 추가」 버튼 (포지션 보유 시).
      // 마진은 「현재 사용 마진 / 계획 총 마진」 형식.
      // 1단계만 진입한 다단계 전략은 둘이 다름 (e.g. 10.58 / 3275 USDT).
      // 2026-05-04 (사용자 요청): 증거금 추가 버튼을 가시성 높은 위치 + 명확한 라벨로
      // 마진 옆에 직접 노출 (이전 액션 컬럼의 🛡 아이콘만 — 발견 어려움 개선).
      const addMarginBtnInQty = hasPosition
        ? `<button onclick="event.stopPropagation(); addMargin(${s.id}, '${s.symbol}', '${s.side}')"
                  class="btn-warning btn text-xs mt-1"
                  style="padding:2px 6px;font-size:10px;line-height:1.2"
                  title="증거금 추가 — ISOLATED 모드 포지션의 청산가 완화 (CROSS 면 거래소 거절)">💰 증거금 추가</button>`
        : '';
      // 2026-05-04 (사용자 요청): 「💉 포지션 추가」 — ad-hoc 자유 금액 시장가/지정가 진입.
      // isTerminal 이 아직 정의 전이라 (line 1581) inline 으로 status 체크.
      const _activeForAddPos = !TERMINAL_STATUSES.includes((s.status || '').toUpperCase());
      const addPositionBtn = _activeForAddPos
        ? `<button onclick="event.stopPropagation(); openAddPositionModal(${s.id}, '${s.symbol}', '${s.side}', ${s.leverage || 1})"
                  class="btn-primary btn text-xs mt-1 ml-1"
                  style="padding:2px 6px;font-size:10px;line-height:1.2"
                  title="포지션 추가 (ad-hoc) — 자유 금액 시장가/지정가 즉시 진입. qty + 평단 갱신, stage 진행 X. v4 안전망: 사용 시 max_loss 임계 도달하면 Crisis 발동 (stage 미완료라도)">💉 포지션 추가</button>`
        : '';
      const qtyStack = hasPosition
        ? `<div class="text-xs leading-tight">
            <span class="${sQtyNum<0?'neg':'pos'} font-semibold" title="포지션 수량">${fmtQty(sQtyNum)}</span><br>
            <span class="text-slate-400" title="현재 사용 마진 (qty×평단÷lev) / 계획 총 마진 (전체 자본÷lev)">${positionMargin.toFixed(2)} / ${plannedMargin.toFixed(2)} USDT</span>
            <br>${addMarginBtnInQty}${addPositionBtn}
          </div>`
        : `<div class="text-xs leading-tight"><span class="text-slate-500">-</span><br><span class="text-slate-400 text-xs" title="계획 총 마진">${plannedMargin > 0 ? plannedMargin.toFixed(2)+' USDT' : '-'}</span>${addPositionBtn ? '<br>'+addPositionBtn : ''}</div>`;
      // PnL/ROI — 3 줄 stack: PnL + 포지션 ROI (Binance 일치) + 전략 ROI (전체 자본 대비, 보조)
      const posSign = positionRoi > 0 ? '+' : '';
      const stratSign = strategyRoi > 0 ? '+' : '';
      const posTooltip = `포지션 ROI = pnl ÷ 현재 사용 마진 × 100 (Binance UI 와 일치). 마진=${positionMargin.toFixed(2)} USDT`;
      const stratTooltip = `전략 ROI = pnl × 레버리지 ÷ 전체 전략 자본 × 100 (전체 단계 모두 진입 시 = 포지션 ROI). 자본=${sCap.toFixed(2)} USDT, lev=${sLev}x`;
      const pnl = hasPosition
        ? `<div class="text-xs leading-tight">
            <span class="${pnlNum>0?'pos':pnlNum<0?'neg':''} font-semibold" title="미실현 손익 (USDT)">${fmtPnL(pnlNum)}</span><br>
            <span class="${positionRoi>0?'pos':positionRoi<0?'neg':'text-slate-400'} text-xs" title="${posTooltip}">${posSign}${positionRoi.toFixed(2)}%</span><br>
            <span class="${strategyRoi>0?'pos':strategyRoi<0?'neg':'text-slate-500'} text-xs" style="font-size:10px; opacity:0.7" title="${stratTooltip}">전략 ${stratSign}${strategyRoi.toFixed(2)}%</span>
          </div>`
        : '<span class="text-slate-500">-</span>';

      // 호환용 alias (기존 변수 사용 위치 보존)
      const entry = priceStack;
      const qty = qtyStack;
      const isTerminal = TERMINAL_STATUSES.includes((s.status || '').toUpperCase());
      // UX #17 (2026-04-29): 종료 상태이고 한번도 체결 안 된 전략 (대기 단계) 에는 삭제 버튼 노출
      const neverEntered = (s.current_stage || 0) === 0 && (!s.avg_entry_price || Number(s.avg_entry_price) === 0);
      // 2026-05-04 v2 (재진입 UX): 1단계 이상 체결됐던 종료 전략 (COMPLETED/REENTRY_READY/STOPPED 등)
      // 에는 "🔄 다시 시작" 버튼 노출 — 같은 설정으로 새 전략 즉시 생성. (이전엔 「🟢 새 전략 시작」
      // 모달 → "이전 전략 불러오기" 탭 → 선택 3단계 — 너무 번거로움)
      // 2026-05-04: 증거금 추가 버튼은 수량/마진 column 으로 이동 (위 addMarginBtnInQty).
      // 「▶ 다음 단계 즉시 진입」 — 활성 strategy + 다음 단계 미발동 시. trigger_price 무시, planned_capital 그대로.
      // 2026-05-04 (사용자 피드백): 액션 버튼 컴팩트화 — 아이콘만 + nowrap + flex inline.
      const totalStagesForBtn = s.total_active_stages || 4;
      const canTriggerNext = !isTerminal && (s.current_stage || 0) < totalStagesForBtn;
      const btnStyle = "padding:3px 6px;font-size:11px;white-space:nowrap;line-height:1.3";
      const triggerNextBtn = canTriggerNext
        ? `<button onclick="event.stopPropagation(); triggerNextStage(${s.id})" class="btn-ghost btn text-xs" style="${btnStyle}" title="현재가에서 다음 단계 즉시 진입 (trigger_price 무시, 사전 계획된 자본 그대로)">▶</button>`
        : '';
      // 2026-05-06 (C-full Step 3): archived row 는 「↻ 복원」 단독 표시.
      let stopBtn;
      if (s.is_archived) {
        stopBtn = `<button onclick="event.stopPropagation(); restoreStrategy(${s.id})" class="btn-ghost btn text-xs" style="${btnStyle}" title="archive 해제 — UI 목록에 다시 표시 (status 그대로)">↻ 복원</button>`;
      } else if (isTerminal) {
        stopBtn = neverEntered
          ? `<button onclick="event.stopPropagation(); deleteStrategy(${s.id})" class="btn-danger btn text-xs" style="${btnStyle}" title="전략 보관 (archive — DB row 보존, UI 숨김, 손익 통계 유지)">🗑</button>`
          : `<div class="flex flex-wrap gap-1" style="max-width:130px">
              <button onclick="event.stopPropagation(); restartStrategy(${s.id})" class="btn-ghost btn text-xs" style="${btnStyle}" title="같은 설정으로 새 전략 시작 (이 전략은 그대로 보존)">🔄</button>
              <button onclick="event.stopPropagation(); deleteStrategy(${s.id})" class="btn-danger btn text-xs" style="${btnStyle}" title="전략 보관 (archive — DB row 보존, UI 숨김, 손익 통계 유지)">🗑</button>
            </div>`;
      } else {
        stopBtn = `<div class="flex flex-wrap gap-1" style="max-width:130px">
            <button onclick="event.stopPropagation(); editStrategy(${s.id})" class="btn-ghost btn text-xs" style="${btnStyle}" title="설정 수정 (in-place 또는 종료+재시작)">✏️</button>
            ${triggerNextBtn}
            <button onclick="event.stopPropagation(); stopStrategy(${s.id})" class="btn-warning btn text-xs" style="${btnStyle}" title="미체결 주문만 취소 (포지션 유지)">⏸</button>
            <button onclick="event.stopPropagation(); emergencyStop(${s.id})" class="btn-danger btn text-xs" style="${btnStyle}" title="긴급 종료 (포지션 시장가 청산)">🛑</button>
          </div>`;
      }
      const startPx = s.start_price && Number(s.start_price) > 0
        ? `<span class="text-yellow-400" title="운영자가 입력한 1단계 LIMIT 가격">${fmtNum(s.start_price)}</span>`
        : '<span class="text-slate-500">-</span>';

      // 크라이시스 모드 배지 (Stage1: TP1 미발동, Stage2: TP1 발동 후 보호 활성)
      let modeBadge;
      if (s.crisis_mode_triggered_at) {
        if (s.crisis_first_tp_done_at) {
          modeBadge = '<span class="badge badge-red" title="크라이시스 [Stage 2] — 트레일링 -5% + 빠른 손절 -1% 활성">🛡 크라이시스 보호</span>';
        } else {
          modeBadge = '<span class="badge badge-yellow" title="크라이시스 [Stage 1] — TP1 임계 +5% (정상 -50% 손절 유지)">🚨 크라이시스</span>';
        }
      } else {
        modeBadge = '<span class="badge badge-gray">정상</span>';
      }

      // 최대 손실/이익
      const maxLoss = s.max_loss_pct !== null && s.max_loss_pct !== undefined
        ? `<span class="text-red-400">${fmtNum(s.max_loss_pct)}%</span>`
        : '<span class="text-slate-500">-</span>';
      const maxProfit = s.max_profit_pct !== null && s.max_profit_pct !== undefined
        ? `<span class="text-green-400">+${fmtNum(s.max_profit_pct)}%</span>`
        : '<span class="text-slate-500">-</span>';
      const maxCell = `<div class="text-xs leading-tight">${maxLoss}<br>${maxProfit}</div>`;

      // 상태 셀에 모드 배지 + 최대손익 tooltip 까지 합쳐 9 컬럼으로 압축.
      const stateCell = `
        <div class="flex flex-col gap-1" title="모드: ${modeBadge.replace(/<[^>]+>/g,'').trim()} / 진입요청가: ${s.start_price ? fmtNum(s.start_price) : '-'} / 최대 손실: ${s.max_loss_pct !== null && s.max_loss_pct !== undefined ? fmtNum(s.max_loss_pct)+'%' : '-'} / 최대 이익: ${s.max_profit_pct !== null && s.max_profit_pct !== undefined ? '+'+fmtNum(s.max_profit_pct)+'%' : '-'}">
          <span class="badge badge-${info.sig}">${info.icon} ${info.ko}</span>
          ${s.crisis_mode_triggered_at ? modeBadge : ''}
        </div>`;
      // 진입일시 (created_at) — 짧게 MM/DD HH:MM 형식
      const createdShort = s.created_at ? (() => {
        const d = new Date(s.created_at);
        const pad = (n) => String(n).padStart(2, '0');
        return `${pad(d.getMonth()+1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
      })() : '-';
      return `<tr class="row-clickable" onclick="selectStrategy(${s.id})">
        <td>#${s.id}</td>
        <td class="font-mono text-blue-300">
          <div class="text-xs leading-tight">
            <span>${s.symbol}</span>${renderWhitelistBadge(s.symbol)}<br>
            <span class="text-slate-500" style="font-size:10px" title="전략 생성 일시">${createdShort}</span>
          </div>
        </td>
        <td>${sideBadge(s.side, s.leverage)}</td>
        <td>${stateCell}</td>
        <td>${stage}</td>
        <td class="num">${entry}</td>
        <td class="num">${qty}</td>
        <td class="num">${pnl}</td>
        <td>${stopBtn}</td>
      </tr>`;
    }).join('');
  } catch (err) { toast('전략 조회 실패: ' + err.message, 'error'); }
}

