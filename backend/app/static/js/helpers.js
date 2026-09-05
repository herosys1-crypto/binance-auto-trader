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
  // 🌟 2026-08-25 Fix 82 (사장님 「두 번째 화면처럼」!): 방향 = 한 줄, 컴팩트!
  const lev = (leverage !== undefined && leverage !== null && Number(leverage) > 0)
    ? `<br><span class="text-slate-300" style="font-size:var(--font-xs)">${leverage}x</span>`
    : '';
  if (side === 'SHORT') {
    return `<span style="display:inline-block;background:#dc2626;color:#fff;padding:2px 8px;border-radius:5px;font-weight:bold;font-size:var(--font-sm);line-height:1.15;box-shadow:0 0 4px rgba(239,68,68,0.5);">🐻 SHORT</span>${lev}`;
  }
  if (side === 'LONG') {
    return `<span style="display:inline-block;background:#16a34a;color:#fff;padding:2px 8px;border-radius:5px;font-weight:bold;font-size:var(--font-sm);line-height:1.15;box-shadow:0 0 4px rgba(34,197,94,0.5);">🐂 LONG</span>${lev}`;
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
/**
 * 📅 Fix 182b (2026-08-27): 「예정(예약)」 배지.
 *
 * WAITING 에는 두 종류가 섞인다 — 사장님이 곧 「시작」을 누를 것과,
 * 시스템이 조건 보고 넣어야 할 예약. 화면에서 구별되지 않으면 관리가 안 된다.
 * 구별자 = capital_management_mode === 'scheduled' (scheduled_entry_worker 와 동일).
 *
 * @param {object} s - Strategy row
 * @returns {string} HTML 배지 (해당 없으면 빈 문자열)
 */
function scheduledBadge(s) {
  if (!s) return '';
  if (String(s.capital_management_mode || '') !== 'scheduled') return '';
  const st = String(s.status || '').toUpperCase();
  if (st === 'WAITING') {
    return '<span style="display:inline-block;background:linear-gradient(135deg,#7c3aed,#a78bfa);'
      + 'color:#fff;padding:2px 6px;border-radius:4px;font-size:var(--font-badge);font-weight:bold;'
      + 'margin-left:4px;box-shadow:0 0 8px rgba(124,58,237,0.5)" '
      + 'title="📅 예정 — 아직 주문이 나가지 않았습니다. 시스템이 운영 진입 로직'
      + '(15분 정점·저점 확인 + OBV 게이트)을 감시하다가 조건이 맞으면 자동으로 1단계를 넣습니다. '
      + '기본 7일 후 만료.">📅 예정</span>';
  }
  // 예약이 실제로 진입된 뒤에도 어디서 온 전략인지 보이게 한다
  return '<span style="display:inline-block;background:#3730a3;color:#c7d2fe;padding:2px 6px;'
    + 'border-radius:4px;font-size:var(--font-badge);margin-left:4px" '
    + 'title="📅 예약으로 만들어져 시스템이 조건 충족 시 자동 진입한 전략입니다.">📅 예약진입</span>';
}

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
  // 🚨 Fix 154 (2026-08-26 사장님 스크린샷): 옛 사다리가 하드코딩돼 있었다.
  //   서버 사다리는 [10,300,600] 인데 화면은 [300,600,1800] 을 보여줘
  //   1단계 10U 포지션에 "다음: 600U" 라고 표시됐다 (실제 2단계는 300U).
  //   → 세팅 로드 시 서버 값을 window.__SAJANGNIM_LADDER 에 담아 그걸 쓴다.
  //     (헌법 85 = 화면과 워커가 같은 진실을 봐야 한다)
  const SAJANGNIM_LADDER = (typeof window !== 'undefined'
    && Array.isArray(window.__SAJANGNIM_LADDER)
    && window.__SAJANGNIM_LADDER.length)
    ? window.__SAJANGNIM_LADDER
    : [300, 600, 1800];
  const nextStage = (stage) => (stage >= 1 && stage < SAJANGNIM_LADDER.length) ? SAJANGNIM_LADDER[stage] : null;

  // 1️⃣ 라스트챈스 (Fix 53 = 최종 기회!)
  if (st.includes('_lastchance')) {
    // 🌟 2026-08-25 Fix 80 (사장님 「배지 2줄!」): 라스트/자본 1줄 + 최종 경고 2줄
    return `<span style="display:inline-block;background:linear-gradient(135deg,#dc2626,#7f1d1d);color:#fff;padding:1px 5px;border-radius:4px;font-size:var(--font-badge);font-weight:600;margin-left:3px;line-height:1.15;box-shadow:0 0 12px rgba(220,38,38,1);animation:pulse 1.5s infinite" title="🚨 Fix 53 라스트챈스 = 마틴게일 최종 기회! 자본 ${cap} USDT ${side}. 다음 = 종료 (재진입 없음!)">🚨 라스트 ${cap}U ${side}<br><span style="font-size:9px;opacity:0.9">최종 기회!</span></span>`;
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
    const tooltip = `🎯 v219 마틴게일 ${stageIdx}차재진입 (=${actualStage}단계!) = 자본 ${cap} USDT ${side}. 사장님 사다리: ${SAJANGNIM_LADDER.join("→")}.${nextCap ? ` 실패 시 다음 = ${nextCap} USDT!` : ' ⚠ 3단계 = 최대! (실패 시 종료!)'}`;
    // 🌟 2026-08-25 Fix 80 (사장님 「배지 2줄!」): stageIdx/cap/side 1줄 + nextHint 2줄
    const nextHintLine = nextCap ? `다음: ${nextCap}U` : '⚠최대!';
    return `<span style="display:inline-block;background:${bg};color:#fff;padding:1px 5px;border-radius:4px;font-size:var(--font-badge);font-weight:600;margin-left:3px;line-height:1.15;box-shadow:0 0 10px rgba(239,68,68,0.8)" title="${tooltip}">${emoji} ${stageIdx}차재진입 ${cap}U ${side}<br><span style="font-size:9px;opacity:0.9">${nextHintLine}</span></span>`;
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
    // 🌟 2026-08-25 Fix 80 (사장님 「배지 2줄!」)
    return `<span style="display:inline-block;background:${bg};color:#fff;padding:1px 5px;border-radius:4px;font-size:var(--font-badge);font-weight:600;margin-left:3px;line-height:1.15;box-shadow:0 0 10px rgba(14,165,233,0.9)" title="${tooltip}">🎯 성공재진입 #${pyrN} ${cap}U ${side}${maxTag ? '<br><span style=\"font-size:9px;opacity:0.9\">' + maxTag.trim() + '</span>' : ''}</span>`;
  }

  // 4️⃣ 성공 재진입 (레거시 v204!)
  if (st.includes('_success')) {
    const bg = isLong
      ? 'linear-gradient(135deg,#0ea5e9,#22c55e)'
      : 'linear-gradient(135deg,#0ea5e9,#dc2626)';
    return `<span style="display:inline-block;background:${bg};color:#fff;padding:1px 5px;border-radius:4px;font-size:var(--font-badge);font-weight:600;margin-left:3px;line-height:1.15;box-shadow:0 0 10px rgba(14,165,233,0.9)" title="🚀 v204 성공 재진입 ${side}! 초기 자본 ${cap} USDT!">🚀 성공재진입 ${cap}U ${side}</span>`;
  }

  // 5️⃣ 기본 BB 자동 진입 (신규 = 1단계 초기!)
  const bg = isLong
    ? 'linear-gradient(135deg,#3b82f6,#1d4ed8)'   // 파랑 = 1단계 (원 진입!)
    : 'linear-gradient(135deg,#3b82f6,#1e40af)';
  const nextCap = nextStage(1);  // 실패 시 다음 = 600U (2단계!)
  const tooltip = `🥇 v174 BB 자동 진입 = 1단계 원 진입 (${cap} USDT ${side}). 사장님 신 마틴게일 사다리: 300→600→1800.${nextCap ? ` 실패 시 다음 = ${nextCap} USDT (2단계!)` : ''}`;
  // 🌟 2026-08-25 Fix 80 (사장님 「배지 2줄!」): 단계/자본/side 1줄 + 다음 자본 2줄
  const line2 = nextCap ? `다음: ${nextCap}U` : '';
  return `<span style="display:inline-block;background:${bg};color:#fff;padding:1px 5px;border-radius:4px;font-size:var(--font-badge);font-weight:600;margin-left:3px;line-height:1.15;box-shadow:0 0 8px rgba(59,130,246,0.7)" title="${tooltip}">🥇 1단계 ${cap}U ${side}${line2 ? `<br><span style="font-size:9px;opacity:0.9">${line2}</span>` : ''}</span>`;
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


// ═══════════════════════════════════════════════════════════════════════════
// 🚨 Fix 201 (2026-08-28 사장님): 「가격은 넘었는데 왜 안 들어가지?」를 화면에서
//
// 실사례 #1637 AKEUSDT SHORT — 마크가 2단계 트리거를 넘었는데 1분마다
// "Fix114 정점 미확인 (지표 꺾임 1/2)" 로 차단됐다. 사유는 Redis·로그에 정확히
// 남고 있었지만 화면 어디에도 없어서, 사장님이 물어보셔야만 알 수 있었다.
// 차단을 기록만 하고 보여주지 않으면 기록한 의미가 없다 (헌법 8 취지).
//
// 데이터: window.__BLOCK_REASONS (strategies-list.js 가 GET /strategies/block-reasons 로 채움)
// ═══════════════════════════════════════════════════════════════════════════
function blockBadge(s) {
  if (!s) return '';
  const info = (window.__BLOCK_REASONS || {})[String(s.id)];
  if (!info) return '';
  let out = '';
  if (info.label) {
    const full = escapeHtml(info.reason || '');
    const when = info.blocked_at ? String(info.blocked_at).slice(11, 19) : '';
    // 2026-09-05 사장님 「줄바꿈해서 가로 줄여줘」: 대기 사유 배지는 한 줄에 이어 붙이지 않고
    // **다음 줄에 블록으로**, 긴 사유는 열 폭 안에서 줄바꿈 (white-space:normal). 표가 화면을 안 넘는다.
    out += '<span onclick="event.stopPropagation(); openBlockDetail(' + s.id + ')"'
      + ' style="display:block;width:fit-content;max-width:100%;white-space:normal;line-height:1.2;'
      + 'background:linear-gradient(135deg,#b45309,#78350f);'
      + 'color:#fde68a;padding:2px 6px;border-radius:4px;font-size:var(--font-badge);'
      + 'font-weight:bold;margin:2px 0 0 0;cursor:pointer;border:1px solid #f59e0b"'
      + ' title="다음 단계가 막혀 있습니다 (' + when + ' UTC) — ' + full
      + ' / 눌러서 근거 지표 보기 + 지정가 우선 켜기">&#9208; ' + escapeHtml(info.label) + '</span>';
  }
  if (info.bypass) {
    out += '<span onclick="event.stopPropagation(); openBlockDetail(' + s.id + ')"'
      + ' style="display:inline-block;background:linear-gradient(135deg,#0ea5e9,#6366f1);'
      + 'color:#fff;padding:2px 6px;border-radius:4px;font-size:var(--font-badge);'
      + 'font-weight:bold;margin-left:4px;cursor:pointer;box-shadow:0 0 8px rgba(14,165,233,0.5)"'
      + ' title="지정가 우선 ON — 지표 확인 없이 지정한 가격에 진입합니다. '
      + escapeHtml(String(info.bypass)) + ' / 7일 후 자동 해제. 눌러서 끌 수 있습니다.">'
      + '&#127919; 지정가 우선</span>';
  }
  return out;
}

function _fmtSig(v) {
  if (v === null || v === undefined) return '-';
  const n = Number(v);
  if (!isFinite(n)) return String(v);
  if (Math.abs(n) >= 1) return n.toFixed(2);
  return n.toPrecision(3);
}

function _blockIndicatorRows(det) {
  const ind = (det && det.indicators) || {};
  const names = Object.keys(ind);
  if (!names.length) {
    return '<div style="color:#94a3b8;font-size:12px">지표 상세가 아직 기록되지 않았습니다 '
      + '(다음 차단부터 표시됩니다).</div>';
  }
  let html = '<table style="width:100%;font-size:12px;border-collapse:collapse">'
    + '<tr style="color:#94a3b8"><th style="text-align:left">지표</th>'
    + '<th style="text-align:right">이전</th><th style="text-align:right">현재</th>'
    + '<th style="text-align:center">꺾임</th></tr>';
  for (const n of names) {
    const v = ind[n] || {};
    const turned = !!v.turn;
    html += '<tr style="border-top:1px solid #334155">'
      + '<td style="padding:3px 0;color:#e2e8f0">' + escapeHtml(n.toUpperCase()) + '</td>'
      + '<td style="text-align:right;color:#94a3b8">' + escapeHtml(_fmtSig(v.prev)) + '</td>'
      + '<td style="text-align:right;color:#e2e8f0">' + escapeHtml(_fmtSig(v.now)) + '</td>'
      + '<td style="text-align:center;font-weight:bold;color:' + (turned ? '#22c55e' : '#ef4444')
      + '">' + (turned ? 'O' : 'X') + '</td></tr>';
  }
  return html + '</table>';
}

function openBlockDetail(sid) {
  const info = (window.__BLOCK_REASONS || {})[String(sid)] || {};
  const s = (window._strategiesById || {})[sid] || {};
  const on = !!info.bypass;
  const html =
    '<div class="modal-overlay" onclick="closeBlockDetail()" style="position:fixed;top:0;left:0;'
    + 'right:0;bottom:0;background:rgba(0,0,0,0.85);z-index:9999;display:flex;align-items:center;'
    + 'justify-content:center;">'
    + '<div onclick="event.stopPropagation()" style="background:#1e293b;padding:18px;'
    + 'border-radius:12px;max-width:520px;width:92%;color:#e2e8f0;border:2px solid #f59e0b;'
    + 'max-height:86vh;overflow:auto">'
    + '<h3 style="color:#fbbf24;margin:0 0 10px 0;font-size:17px">&#9208; 다음 단계가 막혀 있습니다</h3>'
    + '<div style="font-size:12px;color:#cbd5e1;margin-bottom:10px"><b>#' + sid + ' '
    + escapeHtml(s.symbol || '') + ' ' + escapeHtml(s.side || '') + '</b>'
    + (info.stage_no ? ' &mdash; ' + info.stage_no + '단계 진입 대기' : '') + '</div>'
    + '<div style="background:#0f172a;padding:9px;border-radius:6px;font-size:12px;line-height:1.6;'
    + 'color:#fde68a;margin-bottom:12px">' + escapeHtml(info.reason || '(사유 없음)') + '</div>'
    + '<div style="font-size:12px;color:#94a3b8;margin-bottom:4px">15분봉 지표 '
    + '(2개 이상 꺾여야 진입)</div>'
    + _blockIndicatorRows(info.detail || {})
    + '<div style="font-size:11px;color:#64748b;margin-top:8px;line-height:1.5">'
    + '이 확인은 <b>아직 오르는(내리는) 중인데 다음 단계를 넣는 것</b>을 막습니다. '
    + '#1488 이 그렇게 -6,981 USDT 까지 갔습니다.</div>'
    + '<div style="border-top:1px solid #334155;margin:12px 0 10px 0;padding-top:10px">'
    + '<div style="font-size:12px;color:#e2e8f0;margin-bottom:6px"><b>&#127919; 지정가 우선</b>'
    + ' <span style="color:#94a3b8">&mdash; 지표 확인 없이 지정한 가격에 진입합니다 '
    + '(7일 후 자동 해제)</span></div>'
    + '<div style="display:flex;gap:8px;align-items:center">'
    + '<button onclick="togglePeakBypass(' + sid + ',' + (on ? 'false' : 'true') + ')"'
    + ' style="padding:6px 12px;border:0;border-radius:5px;cursor:pointer;font-weight:bold;'
    + 'color:#fff;background:' + (on ? '#475569' : 'linear-gradient(135deg,#0ea5e9,#6366f1)') + '">'
    + (on ? '끄기 (게이트 복원)' : '켜기 (지정가에 바로 진입)') + '</button>'
    + '<span style="font-size:11px;color:' + (on ? '#38bdf8' : '#64748b') + '">'
    + (on ? '현재 ON' : '현재 OFF - 게이트 적용 중') + '</span></div>'
    + (on ? '<div style="font-size:11px;color:#94a3b8;margin-top:6px">'
      + escapeHtml(String(info.bypass)) + '</div>' : '')
    + '</div>'
    + '<div id="block-detail-msg" style="font-size:12px;min-height:16px"></div>'
    + '<div style="display:flex;justify-content:flex-end;margin-top:8px">'
    + '<button onclick="closeBlockDetail()" style="padding:6px 14px;background:#475569;color:#fff;'
    + 'border:0;border-radius:5px;cursor:pointer">닫기</button></div></div></div>';
  const div = document.createElement('div');
  div.id = 'block-detail-modal';
  div.innerHTML = html;
  document.body.appendChild(div);
}

function closeBlockDetail() {
  const el = document.getElementById('block-detail-modal');
  if (el) el.remove();
}

async function togglePeakBypass(sid, enabled) {
  const msg = document.getElementById('block-detail-msg');
  if (msg) msg.innerHTML = '<span style="color:#94a3b8">처리 중...</span>';
  try {
    const r = await api('/strategies/' + sid + '/peak-bypass', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !!enabled, reason: '화면에서 켬' }),
    });
    if (msg) {
      msg.innerHTML = '<span style="color:#22c55e;font-weight:bold">OK '
        + escapeHtml((r && r.message) || '완료') + '</span>';
    }
    // 캐시를 즉시 갱신해 배지가 바로 바뀌게 (다음 폴링까지 기다리지 않게)
    const cache = window.__BLOCK_REASONS || (window.__BLOCK_REASONS = {});
    const cur = cache[String(sid)] || {};
    cur.bypass = enabled ? '화면에서 켬 (방금)' : null;
    cache[String(sid)] = cur;
    setTimeout(function () {
      closeBlockDetail();
      if (window.refreshStrategies) window.refreshStrategies();
    }, 900);
  } catch (e) {
    if (msg) {
      msg.innerHTML = '<span style="color:#ef4444;font-weight:bold">실패: '
        + escapeHtml((e && e.message) || String(e)) + '</span>';
    }
  }
}

/**
 * 📁 Fix 275 (2026-09-01 사장님): 긴 리스트를 접는다.
 *
 * 사장님: "왼쪽 메뉴들 간략하게 노출하고 나머진 선택하면 보이게 해서
 *          아래로 긴 리스트를 아주 많이 줄여줘"
 *
 * 화면이 아래로 끝없이 길어지던 원인은 리스트를 **전부 펼쳐서** 그렸기 때문이다
 * (감시 심볼 23개 + 재진입 대기 15개 + 손실 심볼 37건 + 급등 top50 …).
 *
 * 이 헬퍼는 그 자리를 **한 줄 요약**으로 바꾸고, 클릭해야 펼쳐지게 한다.
 * 이미 이 코드베이스가 쓰던 <details>/<summary> 패턴을 그대로 쓴다
 * (strategy-suggestions.js:131, index.html:1098 선례).
 *
 * @param {string} title    요약에 보일 제목 (이모지 포함 가능)
 * @param {number} count    항목 수 — 접힌 상태에서도 규모가 보이게 한다
 * @param {string} bodyHtml 펼쳤을 때 보일 내용
 * @param {object} opt      { open, color, preview, maxHeight }
 *   - open      기본 false. true 면 처음부터 펼침
 *   - color     요약 글자색
 *   - preview   요약 오른쪽에 붙일 짧은 미리보기 (접힌 상태에서 핵심만)
 *   - maxHeight 펼친 내용의 최대 높이(px). 넘으면 그 안에서 스크롤 —
 *               펼쳐도 페이지가 통째로 길어지지 않게 한다
 */
function foldList(title, count, bodyHtml, opt) {
  const o = opt || {};
  if (!count) return '';
  const color = o.color || '#cbd5e1';
  const open = o.open ? ' open' : '';
  const maxH = o.maxHeight == null ? 260 : o.maxHeight;
  const preview = o.preview
    ? `<span style="color:#64748b;font-weight:normal;margin-left:6px;">${o.preview}</span>`
    : '';
  const inner = maxH
    ? `<div style="max-height:${maxH}px;overflow-y:auto;padding-right:2px;">${bodyHtml}</div>`
    : bodyHtml;
  return `<details style="margin-top:6px;"${open}>
    <summary style="cursor:pointer;color:${color};font-size:12px;font-weight:bold;list-style:none;">
      <span style="display:inline-block;width:10px;">▸</span>${title}
      <span style="background:rgba(148,163,184,0.25);color:#e2e8f0;padding:0 6px;border-radius:8px;font-size:11px;margin-left:4px;">${count}</span>${preview}
    </summary>
    ${inner}
  </details>`;
}

/** 접힌 상태에서 보여줄 짧은 미리보기 문자열 (상위 N개 심볼명). */
function foldPreview(items, key, n) {
  if (!items || !items.length) return '';
  const k = key || 'symbol';
  const take = items.slice(0, n || 3)
    .map(x => String((x && x[k]) || x).replace(/USDT$/, ''));
  const rest = items.length - take.length;
  return take.join(', ') + (rest > 0 ? ` 외 ${rest}` : '');
}
