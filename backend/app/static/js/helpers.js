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
  // 🌟 2026-08-25 Fix 79 (사장님 「익절 20개 두 줄로!」):
  //   total > 10 = 2줄로 나누기 (10개씩 wrapping!)
  //   가로 공간 절반 절감!
  const rowSize = 10;
  let dots = '';
  for (let i = 1; i <= total; i++) {
    let cls = 'stage-dot';
    if (i < current) cls += ' done';
    else if (i === current) cls += ' current';
    dots += `<span class="${cls}"></span>`;
    // 10개마다 줄바꿈 (total > 10 일 때만!)
    if (total > rowSize && i % rowSize === 0 && i < total) {
      dots += '<br>';
    }
  }
  const wrapStyle = total > rowSize ? 'display:inline-block;vertical-align:middle;line-height:1.4' : '';
  return `<span class="stage-bar" style="${wrapStyle}">${dots} <span class="text-xs text-slate-400 ml-1">${current}/${total}</span></span>`;
}

/**
 * 🌟 Fix 69 (2026-08-25 사장님 요구): 마틴게일 단계별 UI 배지!
 *
 * 사장님 verbatim: "마틴게일 단계별로 표시해줘 (1단계 300 USDT / 2단계 600 / 3단계 1800!)"
 *
 * strategy_type 문자열 파싱 = 단일 진실 (헌법 6번!)
 * = worker 가 DB 에 write 한 접미사 그대로 활용!
 *
 * 파싱 우선순위 (긴 접미사 먼저 = greedy match!):
 *   1. _lastchance     → 🚨 라스트챈스 (Fix 53!)
 *   2. _reentry{N}     → 🥇🥈🥉 마틴게일 N단계 (v219: 300/600/1800!)
 *   3. _pyramid{N}     → 🎯 성공재진입 #N (Fix 68: 배수 X = 300 flat!)
 *   4. _success (레거시) → 🚀 성공재진입 (옛 v204)
 *   5. auto_bb_break (plain) → 🤖 기본 BB 진입
 *
 * 자본값 = total_capital 필드 그대로 (300/600/1800 이미 DB 에!)
 * 다음 단계 값 = 사장님 신 마틴게일 공식 (300/600/1800) 클라이언트 계산!
 *
 * @param {object} s - Strategy row (strategy_type, side, total_capital 필드 사용!)
 * @returns {string} HTML 배지 (fallback = 빈 문자열)
 */
function parseMartingaleBadge(s) {
  if (!s) return '';
  const st = String(s.strategy_type || '');
  if (!st.startsWith('auto_bb_break')) return '';

  const side = s.side || 'LONG';
  const isLong = side === 'LONG';
  const cap = (s.total_capital !== undefined && s.total_capital !== null)
    ? Number(s.total_capital).toFixed(0)
    : '?';

  // 사장님 신 마틴게일 사다리 (v219 = 300/600/1800!)
  // 사장님 verbatim: "1단계=초기 / 2단계=이전×2 / 3단계=투자금 전체×2"
  const SAJANGNIM_LADDER = [300, 600, 1800];
  const nextStage = (stage) => (stage >= 1 && stage < 3) ? SAJANGNIM_LADDER[stage] : null;

  // 1️⃣ 라스트챈스 (Fix 53 = 최종 기회!)
  if (st.includes('_lastchance')) {
    return `<span style="display:inline-block;background:linear-gradient(135deg,#dc2626,#7f1d1d);color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:bold;margin-left:4px;box-shadow:0 0 12px rgba(220,38,38,1);animation:pulse 1.5s infinite" title="🚨 Fix 53 라스트챈스 = 마틴게일 최종 기회! 자본 ${cap} USDT ${side}. 다음 = 종료 (재진입 없음!)">🚨 라스트 ${cap}U ${side}</span>`;
  }

  // 2️⃣ 마틴게일 재진입 (v219 = 300/600/1800!)
  const mReentry = st.match(/_reentry(\d+)/);
  if (mReentry) {
    const stageIdx = parseInt(mReentry[1], 10);  // 1, 2, 3
    const actualStage = stageIdx + 1;  // reentry1 = 2단계! (초기 이후 재진입 = stage 2)
    // 사장님 verbatim: reentry1 = "1차재진입" = 2단계 진입 = 600 USDT
    //                  reentry2 = "2차재진입" = 3단계 진입 = 1800 USDT
    const stageColors = {
      1: 'linear-gradient(135deg,#f59e0b,#d97706)',   // 🥈 2단계 = 주황 (경고!)
      2: 'linear-gradient(135deg,#ef4444,#b91c1c)',   // 🥉 3단계 = 빨강 (마지막!)
      3: 'linear-gradient(135deg,#7f1d1d,#450a0a)',   // 4단계+ 초과 = 진빨강
    };
    const stageEmojis = {
      1: '🥈', 2: '🥉', 3: '🚨',
    };
    const bg = stageColors[stageIdx] || stageColors[3];
    const emoji = stageEmojis[stageIdx] || '🚨';
    const nextCap = nextStage(actualStage);
    const nextHint = nextCap ? ` | 다음: ${nextCap}U` : ' | ⚠최대!';
    const tooltip = `🎯 v219 마틴게일 ${stageIdx}차재진입 (=${actualStage}단계!) = 자본 ${cap} USDT ${side}. 사장님 신 사다리: 300→600→1800.${nextCap ? ` 실패 시 다음 = ${nextCap} USDT!` : ' ⚠ 3단계 = 최대! (실패 시 종료!)'}`;
    return `<span style="display:inline-block;background:${bg};color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:bold;margin-left:4px;box-shadow:0 0 10px rgba(239,68,68,0.8)" title="${tooltip}">${emoji} ${stageIdx}차재진입 ${cap}U ${side}${nextHint}</span>`;
  }

  // 3️⃣ 성공 피라미딩 (Fix 68 = 배수 X = 300 flat!)
  const mPyramid = st.match(/_pyramid(\d+)/);
  if (mPyramid) {
    const pyrN = parseInt(mPyramid[1], 10);  // 1, 2, 3
    const shades = {
      1: 'linear-gradient(135deg,#38bdf8,#0284c7)',   // 밝은 하늘
      2: 'linear-gradient(135deg,#0ea5e9,#0369a1)',   // 진한 하늘
      3: 'linear-gradient(135deg,#0369a1,#0c4a6e)',   // 최진한 하늘 (MAX)
    };
    const bg = shades[pyrN] || shades[3];
    const maxTag = pyrN >= 3 ? ' MAX!' : '';
    const tooltip = `🎯 Fix 68 성공 피라미딩 #${pyrN}${maxTag} = 자본 ${cap} USDT ${side} (배수 X = 300 USDT flat, 사장님 verbatim!). 익절 후 즉시 재진입 = 수익 누적!`;
    return `<span style="display:inline-block;background:${bg};color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:bold;margin-left:4px;box-shadow:0 0 10px rgba(14,165,233,0.9)" title="${tooltip}">🎯 성공재진입 #${pyrN} ${cap}U ${side}${maxTag}</span>`;
  }

  // 4️⃣ 성공 재진입 (레거시 v204!)
  if (st.includes('_success')) {
    const bg = isLong
      ? 'linear-gradient(135deg,#0ea5e9,#22c55e)'
      : 'linear-gradient(135deg,#0ea5e9,#dc2626)';
    return `<span style="display:inline-block;background:${bg};color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:bold;margin-left:4px;box-shadow:0 0 10px rgba(14,165,233,0.9)" title="🚀 v204 성공 재진입 ${side}! 초기 자본 ${cap} USDT!">🚀 성공재진입 ${cap}U ${side}</span>`;
  }

  // 5️⃣ 기본 BB 자동 진입 (신규 = 1단계 초기!)
  const bg = isLong
    ? 'linear-gradient(135deg,#3b82f6,#1d4ed8)'   // 파랑 = 1단계 (원 진입!)
    : 'linear-gradient(135deg,#3b82f6,#1e40af)';
  const nextCap = nextStage(1);  // 실패 시 다음 = 600U (2단계!)
  const tooltip = `🥇 v174 BB 자동 진입 = 1단계 원 진입 (${cap} USDT ${side}). 사장님 신 마틴게일 사다리: 300→600→1800.${nextCap ? ` 실패 시 다음 = ${nextCap} USDT (2단계!)` : ''}`;
  return `<span style="display:inline-block;background:${bg};color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:bold;margin-left:4px;box-shadow:0 0 8px rgba(59,130,246,0.7)" title="${tooltip}">🥇 1단계 ${cap}U ${side}${nextCap ? ' | 다음: ' + nextCap + 'U' : ''}</span>`;
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
