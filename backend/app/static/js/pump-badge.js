/**
 * 🏷 Fix 476 (2026-10-21 사장님) — 종목 「세력 그림」 배지 (표시 전용, 주문·판정 무관).
 *
 * 사장님: 「이런 코인(심볼) 새전략시 구분되게 해줘 그리고 전략인스턴스에서도 한눈에 구분되게 표시해줘
 *          집중관리와 진입시 알아야 할것 같아」
 *
 * 색: ③ 펌프·덤프 = 빨강 · ② 펌프·회귀 = 주황 · 🐋 소형·큰손 = 보라 · ① 정상 추세 = 초록 · 없으면 아무것도 안 그림.
 * 데이터: GET /symbols/pump-badges (태그 있는 종목 전체, Redis 읽기만). 5분에 한 번만 호출(메모리 캐시) —
 *   목록이 몇 초마다 다시 그려져도 서버를 다시 부르지 않는다. 호출 실패 = 배지 없음 (fail-open).
 * 설명: 마우스를 올리면 title, 탭/클릭하면 작은 말풍선(reasons + 태그 설명). 모바일 360px 에서도 화면 안에 맞춘다.
 *
 * 의존: api() (api.js), escapeHtml() (helpers.js)
 * 노출: pumpBadgeHtml(sym) · pumpBadgeLabel(sym) · loadPumpBadges() · refreshPumpBadgeSlots(root)
 */
const PUMP_BADGE_TTL_MS = 5 * 60 * 1000;      // 「Claude가 정함」 — 사장님 요청 「5분에 한 번」
const PUMP_BADGE_COLORS = {
  red: ['#dc2626', '#fff'],
  orange: ['#f97316', '#1c1917'],
  purple: ['#a855f7', '#fff'],
  green: ['#16a34a', '#fff'],
};
let _pumpBadges = {};
let _pumpBadgesAt = 0;          // 마지막 성공 시각(ms)
let _pumpBadgesTry = 0;         // 마지막 시도 시각(ms) — 실패해도 5분은 다시 안 부른다
let _pumpBadgesInflight = null;

function loadPumpBadges(force) {
  const now = Date.now();
  if (!force && _pumpBadgesTry && now - _pumpBadgesTry < PUMP_BADGE_TTL_MS) return Promise.resolve(_pumpBadges);
  if (_pumpBadgesInflight) return _pumpBadgesInflight;
  if (typeof api !== 'function' || !localStorage.getItem('access_token')) return Promise.resolve(_pumpBadges);
  _pumpBadgesTry = now;
  _pumpBadgesInflight = api('/symbols/pump-badges').then(r => {
    if (r && r.badges) { _pumpBadges = r.badges; _pumpBadgesAt = Date.now(); }
  }).catch(() => { /* 배지는 보조 표시 — 실패해도 화면은 그대로 */ }).then(() => {
    _pumpBadgesInflight = null;
    refreshPumpBadgeSlots(document);
    return _pumpBadges;
  });
  return _pumpBadgesInflight;
}

function _pumpChipHtml(sym, b) {
  const [bg, fg] = PUMP_BADGE_COLORS[b.color] || ['#475569', '#fff'];
  const tip = [b.label].concat(b.reasons || []).join(' · ');
  const extra = (b.tags || []).filter(t => t.tag !== b.main).map(t => t.label).join(' ');
  return `<span class="pump-badge" data-sym="${escapeHtml(sym)}" title="${escapeHtml(tip)}" `
    + `style="display:inline-block;background:${bg};color:${fg};padding:var(--pad-badge);border-radius:4px;`
    + `font-size:var(--font-badge);font-weight:bold;margin-left:4px;cursor:help;white-space:nowrap;line-height:1.3">`
    + `${escapeHtml(b.label)}${extra ? ' ' + escapeHtml(extra) : ''}</span>`;
}

/** 심볼 옆에 붙일 칩 HTML. 캐시에 있으면 칩, 없으면 빈 자리(나중에 채움). 태그 없는 종목 = 빈 문자열. */
function pumpBadgeHtml(sym) {
  const s = String(sym || '').toUpperCase();
  if (!s) return '';
  loadPumpBadges();                           // 5분 캐시 — 오래됐을 때만 실제 호출
  const b = _pumpBadges[s];
  if (b) return _pumpChipHtml(s, b);
  return _pumpBadgesAt ? '' : `<span class="pump-badge-slot" data-sym="${escapeHtml(s)}"></span>`;
}

/** datalist 라벨 등 글자만 필요할 때. */
function pumpBadgeLabel(sym) {
  const b = _pumpBadges[String(sym || '').toUpperCase()];
  return b ? b.label : '';
}

/** 불러오기 전에 그려진 빈 자리를 칩으로 채운다. */
function refreshPumpBadgeSlots(root) {
  try {
    (root || document).querySelectorAll('.pump-badge-slot').forEach(el => {
      const b = _pumpBadges[el.dataset.sym];
      if (b) el.outerHTML = _pumpChipHtml(el.dataset.sym, b);
    });
    if (typeof _pumpBadgeCmUpdate === 'function') _pumpBadgeCmUpdate();
  } catch (_e) { /* silent */ }
}

// ---- 탭/클릭 말풍선 (모바일은 title 이 안 뜬다) ----
function _pumpBadgePopup(el) {
  const old = document.getElementById('pump-badge-popup');
  if (old) old.remove();
  const b = _pumpBadges[el.dataset.sym];
  if (!b) return;
  const lines = (b.tags || []).map(t => `<div><b>${escapeHtml(t.label)}</b> — ${escapeHtml(t.desc)}</div>`).join('')
    + ((b.reasons || []).length ? `<div style="margin-top:4px;color:#fbbf24">${b.reasons.map(escapeHtml).join('<br>')}</div>` : '');
  const pop = document.createElement('div');
  pop.id = 'pump-badge-popup';
  pop.style.cssText = 'position:fixed;z-index:99999;max-width:min(320px,calc(100vw - 16px));background:#0f172a;color:#e2e8f0;'
    + 'border:1px solid #475569;border-radius:6px;padding:8px 10px;font-size:12px;line-height:1.4;box-shadow:0 4px 12px rgba(0,0,0,.5)';
  pop.innerHTML = `<div style="font-weight:bold;margin-bottom:3px">${escapeHtml(el.dataset.sym)} 세력 그림</div>${lines}`;
  document.body.appendChild(pop);
  const r = el.getBoundingClientRect();
  const w = pop.offsetWidth;
  pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8)) + 'px';
  const below = r.bottom + 6;
  pop.style.top = (below + pop.offsetHeight > window.innerHeight ? Math.max(8, r.top - pop.offsetHeight - 6) : below) + 'px';
}
document.addEventListener('click', (ev) => {
  const chip = ev.target && ev.target.closest ? ev.target.closest('.pump-badge') : null;
  if (chip) { ev.stopPropagation(); ev.preventDefault(); _pumpBadgePopup(chip); return; }   // 행 클릭(selectStrategy) 막기
  const old = document.getElementById('pump-badge-popup');
  if (old) old.remove();
}, true);

// ---- 새 전략 만들기 화면: 심볼 입력칸 아래 칩 ----
function _pumpBadgeCmUpdate() {
  const host = document.getElementById('cm-pump-badge');
  const inp = document.getElementById('cm-symbol');
  if (!host || !inp) return;
  const s = (inp.value || '').toUpperCase().trim();
  const b = s ? _pumpBadges[s] : null;
  host.innerHTML = b ? `<span class="text-slate-400">이 종목:</span>${_pumpChipHtml(s, b)}`
    + `<span class="text-slate-400" style="margin-left:6px">${escapeHtml((b.reasons || [])[0] || '')}</span>` : '';
  host.classList.toggle('hidden', !b);
}
document.addEventListener('input', (ev) => { if (ev.target && ev.target.id === 'cm-symbol') _pumpBadgeCmUpdate(); });
document.addEventListener('change', (ev) => { if (ev.target && ev.target.id === 'cm-symbol') _pumpBadgeCmUpdate(); });
// 값만 코드로 바뀌는 경우(심볼 고르기·불러오기) 대비 — 모달이 열려 있을 때만 가볍게 확인
setInterval(() => {
  const host = document.getElementById('cm-pump-badge');
  if (host && host.offsetParent !== null) _pumpBadgeCmUpdate();
}, 1500);
