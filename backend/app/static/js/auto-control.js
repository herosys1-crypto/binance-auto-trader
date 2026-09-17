/**
 * 🎛 Fix 374 (2026-09-16 사장님) — 자동매매 관제실 화면 로직.
 *
 * 사장님: "자동매매 준비 가족 12종과 모든 자동매매를 한곳으로 모아서 사용과 관리가 편리하게 ui를 개선해줘"
 *
 * 규칙:
 *  · 이 화면은 설정만 바꾼다. 주문·청산은 없다.
 *  · 바꾼 칸은 파랗게 표시하고, 아래 띠의 「💾 저장」을 누를 때 **한 번에** 보낸다 (한 칸이라도 틀리면 전부 저장 안 함).
 *  · 자동매매 재개와 「on 으로 켜기」는 실자금이 나가는 조작이라 **확인창**을 띄운다 (끄는 쪽은 바로 적용).
 *  · 일괄 버튼은 끄기·그림자만 있다 (켜기 일괄은 서버가 거부한다).
 *
 * API: GET /auto-control/overview · PATCH /auto-control/settings · POST /auto-control/halt · POST /auto-control/bulk
 */
const API = '/api/v1';
let STATE = null;              // 마지막 overview 응답
const CHANGES = {};            // 키 -> 저장할 값 (사장님이 만진 것만)

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
    document.getElementById('banner').innerHTML =
      `<div class="banner halted"><div class="big">❌ 불러오기 실패</div><div>${esc(e.message)}</div>
       <div class="muted">운영 화면에서 한 번 로그인한 뒤 열어야 합니다 (토큰 공유).</div></div>`;
  }
}

// ──────────────────────── 그리기 ────────────────────────
function render() {
  const s = STATE;
  document.getElementById('subtitle').textContent =
    `가족 ${s.summary.total}종 · 갱신 ${new Date(s.generated_at).toLocaleTimeString('ko-KR')}` +
    (s.count_error ? ' · ⚠ 건수 집계 실패' : '');

  document.getElementById('banner').innerHTML = s.halted
    ? `<div class="banner halted">
         <div class="big">⛔ 자동매매 전면 중단 중 (Fix 371)</div>
         <div class="muted">사람이 만든 전략과 사람이 누른 버튼만 주문합니다${s.halt_reason ? ' · ' + esc(s.halt_reason) : ''}.
           재개해도 아래에서 <b>on</b> 인 가족만 실제로 주문합니다.</div>
         <div class="row" style="margin-top:6px"><button class="btn btn-go" onclick="setHalt(false)">▶ 자동매매 재개</button></div>
       </div>`
    : `<div class="banner running">
         <div class="big">▶ 자동매매 허용 중 — on 인 가족 ${s.summary.on}종이 실주문합니다</div>
         <div class="row" style="margin-top:6px"><button class="btn btn-danger" onclick="setHalt(true)">⛔ 전면 중단</button></div>
       </div>`;

  document.getElementById('ks').innerHTML = (s.kill_switches || []).length
    ? `<div class="ks">🛑 <b>Kill-Switch 작동 중</b> (계정 ${s.kill_switches.map(k => '#' + k.account_id).join(', ')}) —
        자동·수동을 가리지 않고 <b>모든</b> 주문이 막혀 있습니다. 운영 화면 상단 배너에서 해제하세요.
        <div class="muted">${s.kill_switches.map(k => esc(k.reason || '') + ' ' + esc(k.message || '')).join(' / ')}</div></div>`
    : '';

  const c = s.summary;
  document.getElementById('summary').innerHTML = [
    ['실주문 on', c.on, 'var(--on)'], ['그림자', c.shadow, 'var(--shadow)'], ['끔', c.off, 'var(--off)'],
    ['오늘 진입(KST)', c.entered_today, ''], ['지금 보유', c.live_now, ''],
  ].map(([l, v, col]) => `<div class="card"><div class="l">${l}</div>
      <div class="v" style="${col ? 'color:' + col : ''}">${v}</div></div>`).join('');

  document.getElementById('globals').innerHTML =
    `<div class="sec"><h2>🌐 전체 <span class="muted">모든 자동매매에 함께 걸리는 값</span></h2>
       <div class="row" style="gap:14px">${s.globals.map(ctlField).join('')}</div></div>`;

  const q = (document.getElementById('q').value || '').trim().toLowerCase();
  const onlyOn = document.getElementById('only-on').checked;
  document.getElementById('groups').innerHTML = s.groups.map((g, gi) => {
    if (g === '전체') return '';
    const list = s.panels.filter(p => p.group === g)
      .filter(p => !onlyOn || p.state === 'on')
      .filter(p => !q || (p.label + ' ' + p.fam + ' ' + (p.gate ? p.gate.key : '')).toLowerCase().includes(q));
    if (!list.length) return '';
    return `<div class="sec">
        <h2>${esc(g)} <span class="row">
          <span class="muted">${list.length}종</span>
          <button class="btn" onclick="bulk('shadow', ${gi})">전부 그림자로</button>
          <button class="btn" onclick="bulk('off', ${gi})">전부 끄기</button>
        </span></h2>
        ${list.map(famRow).join('')}
        ${g === '규칙 가족 12 (가상매매 채택 규칙)' ? sharedRuleBlock() : ''}
      </div>`;
  }).join('');

  document.getElementById('extras').innerHTML =
    `<div class="sec"><h2>🔎 감지 전용 <span class="muted">주문을 만들지 않아 켜기 칸이 없습니다</span></h2>
       <table class="det">${(s.detectors || []).map(d =>
         `<tr><td class="keyref">${esc(d.job)}</td><td>${esc(d.note)}</td></tr>`).join('')}</table></div>`;

  syncSaveBar();
}

function sharedRuleBlock() {
  return `<div class="fam" style="border-left:3px solid var(--accent)">
      <div class="fam-name">⚙ 규칙 가족 12종 공용 값 <span class="muted">한 칸을 고치면 12종에 함께 적용됩니다</span></div>
      <div class="detail"><div class="row">${STATE.shared_rule.map(ctlField).join('')}</div></div>
    </div>`;
}

function famRow(p) {
  const stateCls = p.state === 'on' ? 'is-on' : (p.state === 'shadow' ? 'is-shadow' : 'is-off');
  // 전면 중단 중이면 on 이라도 지금은 주문이 나가지 않는다 — 그걸 배지에 적어 준다 (오해 방지).
  const badge = p.state === 'on'
    ? `<span class="badge b-on">실주문 ON</span>${STATE.halted ? '<span class="badge b-off">중단 중이라 대기</span>' : ''}`
    : (p.state === 'shadow' ? '<span class="badge b-shadow">그림자</span>' : '<span class="badge b-off">끔</span>');
  const cnt = [];
  if (p.today != null) {
    const cap = p.daily_max ? valOf(p.daily_max) : null;
    cnt.push(`오늘 <b>${p.today}</b>${cap != null ? '/' + cap : ''}건`);
  }
  if (p.live != null) cnt.push(`보유 <b>${p.live}</b>`);
  if (p.shadow != null) cnt.push(`그림자 <b>${p.shadow}</b>`);
  const id = 'd_' + (p.gate ? p.gate.key : p.fam || Math.random().toString(36).slice(2));
  return `<div class="fam ${stateCls}">
      <div class="fam-top">
        <div>
          <div class="fam-name">${badge} ${esc(p.label)}</div>
          <div class="fam-meta">${esc(p.job || '')}${p.every ? ' · ' + esc(p.every) : ''}
            ${p.fam ? ' · <span class="keyref">' + esc(p.fam) + '</span>' : ''}</div>
          ${cnt.length ? `<div class="stat">${cnt.join(' · ')}</div>` : ''}
          ${p.note ? `<div class="fam-note">${esc(p.note)}</div>` : ''}
        </div>
        <div class="row">
          ${p.gate ? ctlField(p.gate) : ''}
          ${p.daily_max ? ctlField(p.daily_max) : ''}
          ${(p.ctls && p.ctls.length) ? `<button class="btn" onclick="toggleDetail('${id}')">⚙ 자세히</button>` : ''}
        </div>
      </div>
      ${(p.ctls && p.ctls.length) ? `<div class="detail" id="${id}" style="display:none">
          <div class="row">${p.ctls.map(c => ctlField(c)).join('')}</div></div>` : ''}
    </div>`;
}

function toggleDetail(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

function valOf(c) { return CHANGES[c.key] !== undefined ? CHANGES[c.key] : c.value; }

/** 설정 한 칸. Array.map 으로도 부르므로 두 번째 인자(index)는 쓰지 않는다. */
function ctlField(c) {
  const v = valOf(c);
  const dirty = CHANGES[c.key] !== undefined ? ' dirty' : '';
  const title = [c.help, c.source ? '출처: ' + c.source : '', c.ref ? '코드: ' + c.ref : '',
                 '설정 키: ' + c.key + (c.is_default ? ' (행 없음 = 기본 ' + c.default + ')' : '')]
                .filter(Boolean).join('\n');
  let input;
  if (c.kind === 'gate3') {
    // 🎯 Fix 375 차트 자리 게이트 — on = 차트 자리가 아니면 진입 안 함 (실주문을 켜는 칸이 아니다)
    input = `<select class="${dirty.trim()}" onchange="onEdit('${c.key}', this.value, this)">
        ${[['off', '끔'], ['shadow', '기록만'], ['on', '적용']].map(([m, t]) =>
          `<option value="${m}"${m === v ? ' selected' : ''}>${t}</option>`).join('')}</select>`;
  } else if (c.kind === 'mode3') {
    input = `<select class="${dirty.trim()}" onchange="onEdit('${c.key}', this.value, this)">
        ${['off', 'shadow', 'on'].map(m => `<option value="${m}"${m === v ? ' selected' : ''}>${
          m === 'off' ? '끔' : (m === 'shadow' ? '그림자' : '실주문 ON')}</option>`).join('')}</select>`;
  } else if (c.kind === 'switch') {
    const on = !['0', 'off', 'false', 'no'].includes(String(v).toLowerCase());
    // 🚨 전면 중단 키는 뜻이 거꾸로다 (1 = 중단) — 「켬/끔」으로 적으면 반대로 읽힌다.
    const [yes, no] = c.key === 'auto_trading_halt' ? ['중단', '허용'] : ['켬', '끔'];
    input = `<select class="${dirty.trim()}" onchange="onEdit('${c.key}', this.value, this)">
        <option value="1"${on ? ' selected' : ''}>${yes}</option>
        <option value="0"${on ? '' : ' selected'}>${no}</option></select>`;
  } else if (c.kind === 'int' || c.kind === 'num') {
    input = `<input type="number" class="${dirty.trim()}" value="${esc(v)}"
        ${c.lo != null ? 'min="' + c.lo + '"' : ''} ${c.hi != null ? 'max="' + c.hi + '"' : ''}
        step="${c.kind === 'int' ? 1 : 'any'}" onchange="onEdit('${c.key}', this.value, this)">`;
  } else {
    input = `<input type="text" class="wide ${dirty.trim()}" value="${esc(v)}"
        onchange="onEdit('${c.key}', this.value, this)">`;
  }
  return `<label class="f" title="${esc(title)}">
      <span>${esc(c.label)}${c.is_default ? ' <span class="keyref">기본</span>' : ''}</span>${input}</label>`;
}

// ──────────────────────── 편집 ────────────────────────
function onEdit(key, value, el) {
  const orig = findCtl(key);
  if (orig && String(orig.value) === String(value)) delete CHANGES[key];
  else CHANGES[key] = String(value);
  if (el) el.classList.toggle('dirty', CHANGES[key] !== undefined);
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
    msg(turningOn.length ? `⚠ 실주문을 켜거나 차트 게이트를 푸는 칸이 있습니다: ${turningOn.join(', ')}` : `${n}칸 변경됨`,
        turningOn.length ? 'err' : '');
  }
}

/** 이 변경이 「실주문을 켜는」 방향인가 (확인창 대상). */
function isTurnOn(key, value) {
  const c = findCtl(key);
  if (!c) return false;
  const v = String(value).toLowerCase();
  if (key === 'auto_trading_halt') return ['0', 'off', 'false', 'no'].includes(v);
  if (c.kind === 'mode3') return v === 'on' && String(c.value).toLowerCase() !== 'on';
  // 차트 게이트를 끄거나 기록만으로 바꾸면 차트 자리가 아닌 곳에서도 진입한다 → 확인창 대상
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
      `실주문을 켜거나 차트 게이트를 푸는 설정이 ${on.length}개 있습니다:\n\n${on.join('\n')}\n\n` +
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
    const on = STATE.panels.filter(p => p.state === 'on').map(p => p.label);
    if (!confirm(`자동매매를 재개합니다.\n\n지금 실주문 ON 인 가족 ${on.length}종:\n${on.join('\n') || '(없음 — 재개해도 주문은 없습니다)'}\n\n계속할까요?`)) return;
  }
  try {
    await api('/auto-control/halt', { method: 'POST', body: JSON.stringify({ halt: !!halt }) });
    msg(halt ? '⛔ 전면 중단했습니다' : '▶ 자동매매를 재개했습니다', 'ok');
    await load();
  } catch (e) {
    msg('❌ ' + e.message, 'err');
  }
}

async function bulk(target, groupIndex) {
  const group = STATE.groups[groupIndex];
  if (!group) return;
  if (!confirm(`${group} 의 모든 가족을 ${target === 'off' ? '끄기' : '그림자'} 로 맞춥니다. 계속할까요?`)) return;
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
