// 2026-11-20 모바일 로그인 직후 튕김 재현 — node 로 api.js 를 실제 실행한다.
// 실행: node backend/tests/js/api_401_race.test.js  (pytest: tests/test_api_js_401_race.py)
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const src = fs.readFileSync(path.join(__dirname, '../../app/static/js/api.js'), 'utf8');

function makeEnv() {
  const store = {};
  const pending = [];
  const classes = () => ({ add() {}, remove() {} });
  const ctx = {
    window: { location: { origin: 'http://x' } },
    localStorage: {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); },
      removeItem: (k) => { delete store[k]; },
    },
    document: { getElementById: () => ({ classList: classes(), textContent: '', className: '' }) },
    setTimeout: () => 0, clearTimeout: () => {},
    // 요청마다 보낸 헤더를 기록하고, 응답은 테스트가 나중에 풀어 준다 (순서 경합 재현)
    fetch: (url, o) => new Promise((resolve) => {
      pending.push({ auth: (o.headers || {}).Authorization || null, resolve });
    }),
    console,
  };
  vm.createContext(ctx);
  vm.runInContext(src + '\n;globalThis.__get = () => ({ token, c: _consecutive401 });'
    + '\nglobalThis.__login = (t) => { token = t; _consecutive401 = 0; localStorage.setItem("access_token", t); };', ctx);
  const respond = (req, status) => req.resolve({ status, ok: status < 400, json: async () => ({}), text: async () => '' });
  return { ctx, pending, respond };
}

(async () => {
  // ① 로그인 전 토큰 없이 나간 요청 3건이 로그인 뒤 401 로 도착 → 새 토큰은 유지돼야 한다
  {
    const { ctx, pending, respond } = makeEnv();
    const calls = [ctx.api('/a'), ctx.api('/b'), ctx.api('/c')].map((p) => p.catch((e) => e));
    assert.strictEqual(pending.every((r) => r.auth === null), true);
    ctx.__login('NEW');
    pending.forEach((r) => respond(r, 401));
    await Promise.all(calls);
    assert.strictEqual(ctx.__get().token, 'NEW', '로그인 전 요청의 401 이 새 토큰을 지우면 안 된다');
    assert.strictEqual(ctx.localStorage.getItem('access_token'), 'NEW');
  }
  // ② 현재 토큰으로 보낸 요청이 3번 연속 401 → 기존처럼 로그아웃 (진짜 만료)
  {
    const { ctx, pending, respond } = makeEnv();
    ctx.__login('OLD');
    for (let i = 0; i < 3; i++) {
      const p = ctx.api('/x').catch((e) => e);
      respond(pending[pending.length - 1], 401);
      await p;
    }
    assert.strictEqual(ctx.__get().token, null, '진짜 만료는 3회 연속 401 에 로그아웃');
  }
  // ③ 옛 토큰 요청 401 은 다시 로그인한 새 토큰을 지우지 않는다
  {
    const { ctx, pending, respond } = makeEnv();
    ctx.__login('OLD');
    const calls = [ctx.api('/a'), ctx.api('/b'), ctx.api('/c')].map((p) => p.catch((e) => e));
    ctx.__login('NEW');
    pending.forEach((r) => respond(r, 401));
    await Promise.all(calls);
    assert.strictEqual(ctx.__get().token, 'NEW');
  }
  console.log('api_401_race: 3/3 OK');
})().catch((e) => { console.error(e); process.exit(1); });
