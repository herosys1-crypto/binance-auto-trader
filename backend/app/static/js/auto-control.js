/**
 * 🎛 Fix 374 (2026-09-16 사장님) — 자동매매 관제실 화면 로직.
 * 🗂 Fix 381 (2026-09-19 사장님) — "자동매매 전략 모두 한눈에 관리할수 있게 정리해서 한줄로 순서를 정해서 나열하고
 *    선택하면 풀다운 메뉴로 볼수있게 정리해줘 자동매매 전략이 너무 많이 복잡해"
 *    → 전략 한 줄씩(번호 = 서버 auto_control.LINE_ORDER) · 줄을 누르면 그 아래로 설정이 펼쳐진다 · 펼친 줄은 기억한다.
 * 🔘 Fix 383 (2026-09-19 사장님) — "전체 켜고 끄기도 좋은데 각각 자동매매에서도 켜고 끄는 기능을 만들어줘"
 *    → 각 줄 오른쪽에 바로 켜기/끄기 칸 · 각 묶음 제목에 「이 묶음 끄기」「그림자로」 (켜기 일괄 없음 · 게이트는 건드리지 않음).
 *
 * 규칙 (Fix 374 그대로):
 *  · 이 화면은 설정만 바꾼다. 주문·청산은 없다.
 *  · 바꾼 칸은 파랗게 표시하고, 아래 띠의 「💾 저장」을 누를 때 **한 번에** 보낸다 (한 칸이라도 틀리면 전부 저장 안 함).
 *  · 자동매매 재개와 「on 으로 켜기」·게이트 풀기는 실자금이 나가는 조작이라 **확인창**을 띄운다.
 *  · 일괄 버튼은 끄기·그림자만 있다 (켜기 일괄은 서버가 거부한다).
 *
 * API: GET /auto-control/overview · PATCH /auto-control/settings · POST /auto-control/halt · POST /auto-control/bulk
 */
const API = '/api/v1';
let STATE = null;              // 마지막 overview 응답
const CHANGES = {};            // 키 -> 저장할 값 (사장님이 만진 것만)
const OPEN_KEY = 'autoControlOpen';
const OPEN = new Set(readOpen());

function readOpen() {
  try { return JSON.parse(localStorage.getItem(OPEN_KEY) || '[]'); } catch (e) { return []; }
}
function saveOpen() {
  try { localStorage.setItem(OPEN_KEY, JSON.stringify([...OPEN])); } catch (e) { /* 저장 못 해도 화면은 동작 */ }
}

function token() {
  return localStorage.getItem('access_token') || sessionStorage.getItem('access_token')
      || localStorage.getItem('accessToken') || '';
}

async function api(path, opts) {
  const o = Object.assign({ headers: {} }, opts || {});
  o.headers['Authorization'] = 'Bearer ' + token();
  if (o.body) o.headers['Content-Type'] = 'application/json';
  const r = await fetch(API + path, o);
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = { detail: text }; }
  if (!r.ok) throw new Error((data && data.detail) || ('HTTP ' + r.status));
  return data;
}

const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function msg(text, cls) {
  const el = document.getElementById('msg');
  el.className = cls || '';
  el.textContent = text || '';
}

// ──────────────────────── 불러오기 ────────────────────────
async function load() {
  try {
    STATE = await api('/auto-control/overview');
    Object.keys(CHANGES).forEach(k => delete CHANGES[k]);
    render();
  } catch (e) {
    document.getElementById('status').innerHTML =
      `<div class="status halted"><div><div class="big">❌ 불러오기 실패</div><div>${esc(e.message)}</div>
       <div class="muted">운영 화면에서 한 번 로그인한 뒤 열어야 합니다 (토큰 공유).</div></div></div>`;
  }
}

// ──────────────────────── 그리기 ────────────────────────
function render() {
  const s = STATE;
  document.getElementById('subtitle').textContent =
    `전략 ${s.summary.total}개 · 한 줄씩 순서대로 · 줄을 누르면 설정이 펼쳐집니다 · 갱신 ${
      new Date(s.generated_at).toLocaleTimeString('ko-KR')}` + (s.count_error ? ' · ⚠ 건수 집계 실패' : '');

  document.getElementById('status').innerHTML = s.halted
    ? `<div class="status halted">
         <div><div class="big">⛔ 자동매매 전면 중단 중</div>
           <div class="muted">사람이 만든 전략만 주문합니다${s.halt_reason ? ' · ' + esc(s.halt_reason) : ''}.
             재개해도 아래에서 <b>실주문 ON</b> 인 전략만 주문합니다.</div></div>
         <button class="btn btn-go" onclick="setHalt(false)">▶ 자동매매 재개</button>
       </div>`
    : `<div class="status running">
         <div class="big">▶ 자동매매 허용 중 — 실주문 ON ${s.summary.on}개가 주문합니다</div>
         <button class="btn btn-danger" onclick="setHalt(true)">⛔ 전면 중단</button>
       </div>`;

  document.getElementById('ks').innerHTML = (s.kill_switches || []).length
    ? `<div class="ks">🛑 <b>Kill-Switch 작동 중</b> (계정 ${s.kill_switches.map(k => '#' + k.account_id).join(', ')}) —
        자동·수동을 가리지 않고 <b>모든</b> 주문이 막혀 있습니다. 운영 화면 상단 배너에서 해제하세요.</div>`
    : '';

  const c = s.summary;
  document.getElementById('summary').innerHTML = [
    ['실주문 ON', c.on, 'var(--on)'], ['그림자', c.shadow, 'var(--shadow)'], ['끔', c.off, 'var(--off)'],
    ['오늘 진입', c.entered_today, ''], ['지금 보유', c.live_now, ''],
  ].map(([l, v, col]) => `<span class="chip">${l} <b style="${col ? 'color:' + col : ''}">${v}</b></span>`).join('');

  const q = (document.getElementById('q').value || '').trim().toLowerCase();
  const onlyOn = document.getElementById('only-on').checked;
  const match = p => (!onlyOn || p.state === 'on') &&
    (!q || [p.label, p.fam, p.id, p.gate && p.gate.key, ...(p.ctls || []).map(x => x.key + ' ' + x.label)]
      .join(' ').toLowerCase().includes(q));

  let html = globalItem();
  (s.sections || []).forEach(sec => {
    const list = s.panels.filter(p => p.section === sec).filter(match);
    const shared = sec.startsWith('⑤') && !onlyOn && (!q || '공용 규칙 가족'.includes(q) ||
      (s.shared_rule || []).some(x => (x.key + x.label).toLowerCase().includes(q)));
    if (!list.length && !shared) return;
    const sw = list.filter(isSwitchable);
    const hasMode3 = sw.some(p => p.gate.kind === 'mode3');
    html += `<div class="sec-title"><span>${esc(sec)} <span class="muted">${list.length}개</span></span>${sw.length ? `
      <span class="sec-btns">
        ${hasMode3 ? `<button class="btn mini-btn" onclick="sectionSet('${esc(sec)}', 'shadow')">그림자로</button>` : ''}
        <button class="btn mini-btn" onclick="sectionSet('${esc(sec)}', 'off')">이 묶음 끄기</button>
      </span>` : ''}</div>`;
    html += list.map(item).join('');
    if (shared) html += sharedRuleItem();
  });
  if (!onlyOn && !q) html += detectorItem();
  document.getElementById('list').innerHTML = html ||
    '<div class="muted" style="padding:12px">조건에 맞는 전략이 없습니다.</div>';
  syncSaveBar();
}

function stateBadge(p) {
  if (p.state === 'gate_only') return '<span class="badge b-off">게이트만</span>';
  if (p.state === 'on') {
    return STATE.halted ? '<span class="badge b-wait" title="실주문 ON 이지만 전면 중단 중이라 대기">ON·중단 대기</span>'
                        : '<span class="badge b-on">실주문 ON</span>';
  }
  return p.state === 'shadow' ? '<span class="badge b-shadow">그림자</span>' : '<span class="badge b-off">끔</span>';
}

function counts(p) {
  const cnt = [];
  if (p.today != null) {
    const cap = p.daily_max ? valOf(p.daily_max) : null;
    cnt.push(`오늘 <b>${p.today}</b>${cap != null ? '/' + esc(cap) : ''}`);
  }
  if (p.live != null) cnt.push(`보유 <b>${p.live}</b>`);
  if (p.shadow != null) cnt.push(`그림자 <b>${p.shadow}</b>`);
  return cnt.join(' · ');
}

/** 전략 한 줄 + 펼침 칸. */
function item(p) {
  const id = 'L_' + p.id;
  const open = OPEN.has(id) ? ' open' : '';
  const gates = (p.ctls || []).filter(c => c.kind === 'gate3');
  const rest = (p.ctls || []).filter(c => c.kind !== 'gate3');
  const main = [p.gate ? ctlField(p.gate, true) : '', p.daily_max ? ctlField(p.daily_max) : ''].join('');
  const cnt = counts(p);
  return `<div class="item is-${esc(p.state)}${open}" id="${esc(id)}">
      <div class="line" onclick="toggleItem('${esc(id)}')" role="button" aria-expanded="${open ? 'true' : 'false'}">
        <span class="no">${p.order < 999 ? p.order : '·'}</span>
        ${stateBadge(p)}${p.breaker && p.breaker.tripped ? '<span class="badge b-wait" title="최근 손실로 새 전략을 막는 중">⛔ 손실 차단</span>' : ''}
        <span class="name" title="${esc(p.label)}">${esc(p.label)}</span>
        <span class="mini">${cnt}</span>
        <span class="quick" onclick="event.stopPropagation()">${isSwitchable(p) ? inputFor(p.gate, 'quick') : ''}</span>
        <span class="arrow">▼</span>
      </div>
      <div class="drop">
        ${cnt ? `<div class="mini-m">${cnt}</div>` : ''}
        <div class="desc">${[p.job ? '워커 ' + esc(p.job) : '', (p.every && p.every !== '—') ? esc(p.every) + '마다' : '',
          p.fam ? '<span class="keyref">' + esc(p.fam) + '</span>' : ''].filter(Boolean).join(' · ')}
          ${p.note ? '<br>' + esc(p.note) : ''}
          ${p.breaker ? `<br>손실 차단기: 최근 ${p.breaker.days}일 실현 <b>${Number(p.breaker.pnl).toFixed(1)}</b> USDT (${p.breaker.n}건) · 기준 −${p.breaker.limit}${p.breaker.tripped ? ' · <b style="color:#fca5a5">막는 중</b>' : ''}` : ''}</div>
        ${main ? `<div class="fields">${main}</div>` : ''}
        ${gates.length ? `<div class="sub">진입 전 확인 (게이트)</div><div class="fields">${gates.map(x => ctlField(x)).join('')}</div>` : ''}
        ${rest.length ? `<div class="sub">세부 값</div><div class="fields">${rest.map(x => ctlField(x)).join('')}</div>` : ''}
      </div>
    </div>`;
}

function globalItem() {
  const id = 'L__globals';
  const open = OPEN.has(id) ? ' open' : '';
  const groups = (STATE.groups || []).filter(g => g !== '전체');
  return `<div class="item${open}" id="${id}" style="border-left:3px solid var(--accent)">
      <div class="line" onclick="toggleItem('${id}')" role="button">
        <span class="no">⚙</span><span class="badge b-off">전체</span>
        <span class="name">전체 설정 · 한꺼번에 끄기</span><span class="mini">모든 자동매매에 함께 걸리는 값</span>
        <span class="quick"></span><span class="arrow">▼</span>
      </div>
      <div class="drop">
        <div class="fields">${STATE.globals.map(x => ctlField(x)).join('')}</div>
        <div class="sub">한꺼번에 (켜기 일괄은 없습니다)</div>
        <div class="row">${groups.map(g => `<span class="muted">${esc(g)}</span>
          <button class="btn" onclick="bulk('shadow', '${esc(g)}')">전부 그림자</button>
          <button class="btn" onclick="bulk('off', '${esc(g)}')">전부 끄기</button>`).join('<span style="width:10px"></span>')}</div>
      </div>
    </div>`;
}

function sharedRuleItem() {
  const id = 'L__shared_rule';
  const open = OPEN.has(id) ? ' open' : '';
  return `<div class="item${open}" id="${id}" style="border-left:3px solid var(--accent)">
      <div class="line" onclick="toggleItem('${id}')" role="button">
        <span class="no">⚙</span><span class="badge b-off">공용</span>
        <span class="name">규칙 가족 12종 공용 값</span><span class="mini">한 칸을 고치면 12종에 함께 적용</span>
        <span class="quick"></span><span class="arrow">▼</span>
      </div>
      <div class="drop"><div class="fields">${STATE.shared_rule.map(x => ctlField(x)).join('')}</div></div>
    </div>`;
}

function detectorItem() {
  const id = 'L__detectors';
  const open = OPEN.has(id) ? ' open' : '';
  const d = STATE.detectors || [];
  return `<div class="sec-title">🔎 감지 전용 <span class="muted">주문을 만들지 않아 켜기 칸이 없습니다</span></div>
    <div class="item${open}" id="${id}">
      <div class="line" onclick="toggleItem('${id}')" role="button">
        <span class="no">·</span><span class="badge b-off">감지</span>
        <span class="name">감지 전용 워커 ${d.length}개</span><span class="mini"></span><span class="quick"></span><span class="arrow">▼</span>
      </div>
      <div class="drop"><table class="det">${d.map(x =>
        `<tr><td class="keyref">${esc(x.job)}</td><td>${esc(x.note)}</td></tr>`).join('')}</table></div>
    </div>`;
}

function toggleItem(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const open = !el.classList.contains('open');
  el.classList.toggle('open', open);
  const line = el.querySelector('.line');
  if (line) line.setAttribute('aria-expanded', open ? 'true' : 'false');
  if (open) OPEN.add(id); else OPEN.delete(id);
  saveOpen();
}

function openAll(open) {
  document.querySelectorAll('#list .item').forEach(el => {
    el.classList.toggle('open', open);
    if (open) OPEN.add(el.id); else OPEN.delete(el.id);
  });
  saveOpen();
}

function valOf(c) { return CHANGES[c.key] !== undefined ? CHANGES[c.key] : c.value; }

/** 켜기/끄기 칸이 있는 줄인가 (게이트만 있는 줄 = 아니다 — 게이트를 끄면 막아 주던 것이 풀린다). */
function isSwitchable(p) {
  return !!(p && p.gate && (p.gate.kind === 'switch' || p.gate.kind === 'mode3'));
}

/** 묶음 한꺼번에 — 끄기(off) 또는 그림자(shadow)만. 저장은 아래 「💾 저장」으로 (켜기 일괄 없음). */
function sectionSet(sec, target) {
  const list = STATE.panels.filter(p => p.section === sec && isSwitchable(p));
  let n = 0;
  list.forEach(p => {
    const c = p.gate;
    let v = null;
    if (target === 'off') v = c.kind === 'switch' ? '0' : 'off';
    else if (target === 'shadow' && c.kind === 'mode3') v = 'shadow';
    if (v !== null && String(valOf(c)) !== v) { onEdit(c.key, v, null); n += 1; }
  });
  render();
  msg(n ? `${sec}: ${n}칸을 ${target === 'off' ? '끄기' : '그림자'}로 바꿨습니다 — 아래 「💾 저장」을 눌러야 적용됩니다`
        : `${sec}: 바꿀 칸이 없습니다 (이미 그 상태)`, n ? '' : 'ok');
}

/** 입력 칸만. cls = 'quick' 이면 줄 위 작은 칸. */
function inputFor(c, cls) {
  const v = valOf(c);
  const dirty = CHANGES[c.key] !== undefined ? ' dirty' : '';
  const k = `data-key="${esc(c.key)}"`;
  const klass = `class="${[cls || '', dirty.trim()].filter(Boolean).join(' ')}"`;
  const stop = 'onclick="event.stopPropagation()"';
  if (c.kind === 'gate3') {
    return `<select ${k} ${klass} ${stop} onchange="onEdit('${c.key}', this.value, this)">
        ${[['off', '끔'], ['shadow', '기록만'], ['on', '적용']].map(([m, t]) =>
          `<option value="${m}"${m === v ? ' selected' : ''}>${t}</option>`).join('')}</select>`;
  }
  if (c.kind === 'mode3') {
    return `<select ${k} ${klass} ${stop} onchange="onEdit('${c.key}', this.value, this)">
        ${['off', 'shadow', 'on'].map(m => `<option value="${m}"${m === v ? ' selected' : ''}>${
          m === 'off' ? '끔' : (m === 'shadow' ? '그림자' : '실주문 ON')}</option>`).join('')}</select>`;
  }
  if (c.kind === 'switch') {
    const on = !['0', 'off', 'false', 'no'].includes(String(v).toLowerCase());
    // 🚨 뜻이 거꾸로인 키 — 전면 중단(1 = 중단) · ⛔ Fix 384 손실 차단(1 = 막는 중)
    const [yes, no] = c.key === 'auto_trading_halt' ? ['중단', '허용']
      : (c.key.endsWith('_loss_breaker') ? ['막는 중', '허용'] : ['켬', '끔']);
    return `<select ${k} ${klass} ${stop} onchange="onEdit('${c.key}', this.value, this)">
        <option value="1"${on ? ' selected' : ''}>${yes}</option>
        <option value="0"${on ? '' : ' selected'}>${no}</option></select>`;
  }
  return null;
}

/** 설정 한 칸. main = 그 전략의 켜기 스위치(굵게). */
function ctlField(c, main) {
  const v = valOf(c);
  const dirty = CHANGES[c.key] !== undefined ? ' dirty' : '';
  const title = [c.help, c.source ? '출처: ' + c.source : '', c.ref ? '코드: ' + c.ref : '',
                 '설정 키: ' + c.key + (c.is_default ? ' (행 없음 = 기본 ' + c.default + ')' : '')]
                .filter(Boolean).join('\n');
  const stop = 'onclick="event.stopPropagation()"';
  // 선택형(끔·기록만·적용 / 끔·그림자·실주문 ON / 켬·끔 — 🚨 전면 중단 키는 중단·허용)은 inputFor 가 만든다
  let input = inputFor(c, '');
  if (input !== null) {
    /* 위에서 끝 */
  } else if (c.kind === 'int' || c.kind === 'num') {
    input = `<input type="number" data-key="${esc(c.key)}" class="${dirty.trim()}" value="${esc(v)}" ${stop}
        ${c.lo != null ? 'min="' + c.lo + '"' : ''} ${c.hi != null ? 'max="' + c.hi + '"' : ''}
        step="${c.kind === 'int' ? 1 : 'any'}" onchange="onEdit('${c.key}', this.value, this)">`;
  } else {
    input = `<input type="text" data-key="${esc(c.key)}" class="txt ${dirty.trim()}" value="${esc(v)}" ${stop}
        onchange="onEdit('${c.key}', this.value, this)">`;
  }
  return `<label class="f${main ? ' main' : ''}" title="${esc(title)}">
      <span>${esc(c.label)}${c.is_default ? ' <span class="keyref">기본</span>' : ''}</span>${input}</label>`;
}

// ──────────────────────── 편집 ────────────────────────
function onEdit(key, value, el) {
  const orig = findCtl(key);
  if (orig && String(orig.value) === String(value)) delete CHANGES[key];
  else CHANGES[key] = String(value);
  document.querySelectorAll(`[data-key="${key}"]`).forEach(x => {
    if (x !== el && x.value !== String(value)) x.value = String(value);
    x.classList.toggle('dirty', CHANGES[key] !== undefined);
  });
  syncSaveBar();
}

function findCtl(key) {
  const all = [].concat(STATE.globals, STATE.shared_rule);
  STATE.panels.forEach(p => {
    if (p.gate) all.push(p.gate);
    if (p.daily_max) all.push(p.daily_max);
    (p.ctls || []).forEach(c => all.push(c));
  });
  return all.find(c => c.key === key);
}

function syncSaveBar() {
  const n = Object.keys(CHANGES).length;
  document.getElementById('savebar').classList.toggle('hidden', n === 0);
  document.getElementById('save-btn').textContent = `💾 ${n}칸 저장`;
  if (n) {
    const turningOn = Object.entries(CHANGES).filter(([k, v]) => isTurnOn(k, v)).map(([k]) => k);
    msg(turningOn.length ? `⚠ 실주문을 켜거나 차트 게이트를 푸는(세력 CCI 포함) 칸이 있습니다: ${turningOn.join(', ')}` : `${n}칸 변경됨`,
        turningOn.length ? 'err' : '');
  }
}

/** 이 변경이 「실주문을 켜는」 방향인가 (확인창 대상). */
function isTurnOn(key, value) {
  const c = findCtl(key);
  if (!c) return false;
  const v = String(value).toLowerCase();
  if (key === 'auto_trading_halt') return ['0', 'off', 'false', 'no'].includes(v);
  // ⛔ Fix 384: 손실 차단을 푸는 쪽(막는 중 → 허용)이 위험한 방향이다
  if (key.endsWith('_loss_breaker')) return v === '0' && String(c.value) === '1';
  if (key === 'family_loss_breaker_enabled') return v === '0' && String(c.value) !== '0';
  if (c.kind === 'mode3') return v === 'on' && String(c.value).toLowerCase() !== 'on';
  // 게이트를 끄거나 기록만으로 바꾸면 조건이 아닌 곳에서도 진입한다 → 확인창 대상
  if (c.kind === 'gate3') return v !== 'on' && String(c.value).toLowerCase() === 'on';
  if (c.kind === 'switch') return v === '1' && ['0', 'off', 'false', 'no'].includes(String(c.value).toLowerCase());
  return false;
}

function resetChanges() {
  Object.keys(CHANGES).forEach(k => delete CHANGES[k]);
  render();
  msg('');
}

async function save() {
  const keys = Object.keys(CHANGES);
  if (!keys.length) return;
  const on = keys.filter(k => isTurnOn(k, CHANGES[k]));
  if (on.length && !confirm(
      `실주문을 켜거나 차트 게이트를 푸는(세력 CCI 포함) 설정이 ${on.length}개 있습니다:\n\n${on.join('\n')}\n\n` +
      `이 값을 저장하면 조건이 맞는 순간 실자금 주문이 나갑니다. 저장할까요?`)) return;
  const btn = document.getElementById('save-btn');
  btn.disabled = true;
  try {
    const out = await api('/auto-control/settings', { method: 'PATCH', body: JSON.stringify({ changes: CHANGES }) });
    msg(`✅ ${out.changed}칸 저장 (재시작 없이 적용)`, 'ok');
    await load();
  } catch (e) {
    msg('❌ ' + e.message + ' — 아무 칸도 저장되지 않았습니다', 'err');
  } finally {
    btn.disabled = false;
  }
}

async function setHalt(halt) {
  if (!halt) {
    const on = STATE.panels.filter(p => p.state === 'on').map(p => p.order + '. ' + p.label);
    if (!confirm(`자동매매를 재개합니다.\n\n지금 실주문 ON 인 전략 ${on.length}개:\n${on.join('\n') || '(없음 — 재개해도 주문은 없습니다)'}\n\n계속할까요?`)) return;
  }
  try {
    await api('/auto-control/halt', { method: 'POST', body: JSON.stringify({ halt: !!halt }) });
    msg(halt ? '⛔ 전면 중단했습니다' : '▶ 자동매매를 재개했습니다', 'ok');
    await load();
  } catch (e) {
    msg('❌ ' + e.message, 'err');
  }
}

async function bulk(target, group) {
  if (!group || !(STATE.groups || []).includes(group)) return;
  if (!confirm(`${group} 의 모든 전략을 ${target === 'off' ? '끄기' : '그림자'} 로 맞춥니다. 계속할까요?`)) return;
  try {
    const out = await api('/auto-control/bulk', { method: 'POST', body: JSON.stringify({ target, group }) });
    msg(`✅ ${out.changed}칸 적용${(out.skipped || []).length ? ' · 건너뜀: ' + out.skipped.join(', ') : ''}`, 'ok');
    await load();
  } catch (e) {
    msg('❌ ' + e.message, 'err');
  }
}

document.getElementById('q').addEventListener('input', () => STATE && render());
document.getElementById('only-on').addEventListener('change', () => STATE && render());
