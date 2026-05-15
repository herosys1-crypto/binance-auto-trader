/**
 * Common UI helpers — Phase 3 추가 분리 (2026-05-14).
 *
 * index.html 의 Helpers 섹션 (~102줄) 추출. 다른 모듈 (stats-modals 등) 도 의존.
 *
 * 포함 함수:
 *   - statusInfo(status)        → STATUS_MAP lookup + fallback
 *   - sideBadge(side)            → SHORT/LONG 배지 HTML
 *   - renderStageBar(cur,total) → 단계 진행 dot bar
 *   - _tpCountFromStatus(s,n)   → status 에서 TP 발동 카운트
 *   - renderTpBar(cur,total,r)  → TP 진행도 + 종료 사유 마크
 *   - fmtNum / fmtQty / fmtPnL  → 숫자 포맷팅
 *   - setMetric / setSignal     → 카드 metric 표시
 *   - showAlert / hideAlert / dismissAlert → alert bar 제어
 *   - escapeHtml(s)              → HTML 이스케이프
 *
 * 의존성:
 *   - STATUS_MAP → /static/js/constants.js (loaded earlier)
 *   - DOM elements: #metric-*, #alert-bar, #alert-title, #alert-detail
 */

function statusInfo(status) {
  if (!status) return { ko: '알 수 없음', sig: 'gray', icon: '?' };
  return STATUS_MAP[status.toUpperCase()] || { ko: status, sig: 'blue', icon: '•' };
}

function sideBadge(side, leverage) {
  // 2026-05-15 사용자 요청: 방향 옆에 leverage 같이 표시 (전략 인스턴스 컬럼 한눈에 파악).
  // leverage 인자 생략 시 배지만 (templates-panel 처럼 별도 컬럼 있는 곳은 그대로 호환).
  const lev = (leverage !== undefined && leverage !== null && Number(leverage) > 0)
    ? ` <span class="text-xs text-slate-300 ml-1">${leverage}x</span>`
    : '';
  if (side === 'SHORT') return '<span class="badge badge-red">📉 숏</span>' + lev;
  if (side === 'LONG')  return '<span class="badge badge-green">📈 롱</span>' + lev;
  return '<span class="badge badge-gray">' + side + '</span>' + lev;
}

function renderStageBar(current, total) {
  let dots = '';
  for (let i = 1; i <= total; i++) {
    let cls = 'stage-dot';
    if (i < current) cls += ' done';
    else if (i === current) cls += ' current';
    dots += `<span class="${cls}"></span>`;
  }
  return `<span class="stage-bar">${dots} <span class="text-xs text-slate-400 ml-1">${current}/${total}</span></span>`;
}

// status 에서 TP 카운트 산출. totalTps 는 template 의 활성 TP 수 (분모, 1~5).
// COMPLETED/REENTRY_READY w/ realized>0 → totalTps (= "모든 활성 TP 발동 완료")
function _tpCountFromStatus(strat, totalTps) {
  const st = (strat.status || '').toUpperCase();
  const total = Math.max(1, Math.min(totalTps || 4, 5));
  const m = { 'TP1_DONE_PARTIAL':1, 'TP2_DONE_PARTIAL':2, 'TP3_DONE_PARTIAL':3, 'TP4_DONE_PARTIAL':4, 'TP5_DONE_PARTIAL':5 };
  if (st in m) return Math.min(m[st], total);  // 안전 clamp
  if (st === 'COMPLETED') return total;          // ← 이전 하드코딩 4 였던 부분, 이제 동적
  if (st === 'REENTRY_READY' && Number(strat.realized_pnl || 0) > 0) return total;
  return 0;  // 진행 중 / SL / 대기
}

// TP 진행도 바 — 색상 다르게 (시안 계열, 단계 바와 구분)
// 2026-05-03 fix: closeReason 인자로 종료 사유 마크 표시
//   TP_FINAL → 마지막 TP 까지 발동 (정상 종료)
//   TRAILING → 트레일링 -5% 회귀로 조기 종료 (TP 일부만 발동)
//   SL → 손절
//   MANUAL → 사용자 수동 정지
function renderTpBar(current, total, closeReason) {
  const safeC = Math.max(0, Math.min(current, total));
  let dots = '';
  for (let i = 1; i <= total; i++) {
    const filled = i <= safeC;
    const color = filled ? '#06b6d4' : '#475569';
    dots += `<span class="inline-block rounded-full mr-1" style="width:8px;height:8px;background:${color}"></span>`;
  }
  // 종료 사유 마크 (COMPLETED / REENTRY_READY / STOPPED 일 때만 의미 있음)
  let reasonBadge = '';
  if (closeReason === 'TRAILING') {
    reasonBadge = ` <span class="text-xs px-1 rounded bg-purple-900 text-purple-300" title="트레일링 -5% 회귀로 조기 종료">🌀 트레일링</span>`;
  } else if (closeReason === 'TP_FINAL') {
    reasonBadge = ` <span class="text-xs px-1 rounded bg-emerald-900 text-emerald-300" title="모든 활성 TP 발동 후 종료">✅ 완료</span>`;
  } else if (closeReason === 'SL') {
    reasonBadge = ` <span class="text-xs px-1 rounded bg-red-900 text-red-300" title="손절 발동">🛑 손절</span>`;
  } else if (closeReason === 'MANUAL') {
    reasonBadge = ` <span class="text-xs px-1 rounded bg-amber-900 text-amber-300" title="수동 정지/청산">✋ 수동</span>`;
  }
  return `<span class="inline-flex items-center" title="익절 진행도">${dots}<span class="text-xs text-cyan-300 ml-1">${safeC}/${total}</span>${reasonBadge}</span>`;
}

function fmtNum(v) {
  if (v === null || v === undefined) return '-';
  const n = Number(v); if (isNaN(n)) return v;
  if (Math.abs(n) >= 1) return n.toLocaleString('en-US', {maximumFractionDigits: 2});
  return n.toLocaleString('en-US', {maximumFractionDigits: 8});
}
function fmtQty(v) {
  if (v === null || v === undefined) return '-';
  const n = Number(v); if (isNaN(n)) return v;
  return n.toLocaleString('en-US', {maximumFractionDigits: 8});
}
function fmtPnL(v) {
  const n = Number(v || 0);
  if (isNaN(n)) return '0';
  const formatted = n.toLocaleString('en-US', {maximumFractionDigits: 2, minimumFractionDigits: 2});
  return n > 0 ? '+' + formatted : formatted;
}

function setMetric(name, value, detail, signal) {
  document.getElementById('metric-' + name).textContent = value;
  if (detail !== undefined) document.getElementById('metric-' + name + '-detail').textContent = detail;
  setSignal('card-' + name, signal);
}
function setSignal(cardId, sig) {
  const el = document.getElementById(cardId);
  if (!el) return;
  el.classList.remove('signal-green','signal-yellow','signal-red','signal-gray');
  el.classList.add('signal-' + (sig || 'gray'));
}

function showAlert(title, detail) {
  document.getElementById('alert-title').textContent = title;
  document.getElementById('alert-detail').textContent = detail;
  document.getElementById('alert-bar').classList.remove('hidden');
}
function hideAlert() { document.getElementById('alert-bar').classList.add('hidden'); }
function dismissAlert() { hideAlert(); }

function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]); }
