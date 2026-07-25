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
  // 🌟 2026-07-01 사장님 요구: 아이콘 완전히 다른 것 + 색상 쉬운 구분!
  //   LONG = 🐂 (황소, 상승!) + 진한 초록 + 강력 시각!
  //   SHORT = 🐻 (곰, 하락!) + 진한 빨강 + 강력 시각!
  const lev = (leverage !== undefined && leverage !== null && Number(leverage) > 0)
    ? ` <span class="text-xs text-slate-300 ml-1">${leverage}x</span>`
    : '';
  if (side === 'SHORT') {
    return `<span style="display:inline-block;background:#dc2626;color:#fff;padding:3px 10px;border-radius:6px;font-weight:bold;font-size:13px;box-shadow:0 0 6px rgba(239,68,68,0.6);">🐻 SHORT</span>${lev}`;
  }
  if (side === 'LONG') {
    return `<span style="display:inline-block;background:#16a34a;color:#fff;padding:3px 10px;border-radius:6px;font-weight:bold;font-size:13px;box-shadow:0 0 6px rgba(34,197,94,0.6);">🐂 LONG</span>${lev}`;
  }
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

// status 에서 TP 카운트 산출. totalTps 는 template 의 활성 TP 수.
// 🚀 v118 (2026-07-22): TP20 확장 → totalTps 최대 20!
// COMPLETED/REENTRY_READY w/ realized>0 → totalTps (= "모든 활성 TP 발동 완료")
function _tpCountFromStatus(strat, totalTps) {
  const st = (strat.status || '').toUpperCase();
  const total = Math.max(1, Math.min(totalTps || 10, 20));  // v118: max 20
  // TP1_DONE_PARTIAL ~ TP20_DONE_PARTIAL 매핑!
  const m = {};
  for (let i = 1; i <= 20; i++) m[`TP${i}_DONE_PARTIAL`] = i;
  if (st in m) return Math.min(m[st], total);
  if (st === 'COMPLETED') return total;
  if (st === 'REENTRY_READY' && Number(strat.realized_pnl || 0) > 0) return total;
  return 0;
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
  // v122 (2026-07-22): 사장님 요구 = 가로 30% 축소!
  //   기존: 8px + mr-1 (4px) = 12px × 20 = 240px
  //   신: 5px + mr 2px = 7px × 20 = 140px (약 40% 축소, 사장님 요구 30% 이상!)
  for (let i = 1; i <= total; i++) {
    const filled = i <= safeC;
    const color = filled ? '#06b6d4' : '#475569';
    dots += `<span class="inline-block rounded-full" style="width:5px;height:5px;margin-right:2px;background:${color}"></span>`;
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
  // v11 fix: null-safe (= metric-balance-detail 삭제 가능 = 안전 처리)
  const valEl = document.getElementById('metric-' + name);
  if (valEl) valEl.textContent = value;
  if (detail !== undefined) {
    const detEl = document.getElementById('metric-' + name + '-detail');
    if (detEl) detEl.textContent = detail;
  }
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
