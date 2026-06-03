/**
 * API helper + auth + toast — Phase 3 추가 분리 (2026-05-14).
 *
 * 이전엔 index.html 안에 inline 으로 흩어져 있었던 핵심 helper 들.
 * (1043~1369 + 5336~5362 부분 추출)
 *
 * 포함:
 *   - API_BASE      : /api/v1 절대 경로
 *   - token         : access_token (mutable, 로그인/로그아웃 시 갱신)
 *   - api(path,opts): fetch wrapper + 401 재시도 + JSON 자동 처리
 *   - toast(msg,t)  : 화면 우측 상단 알림 (mobile 가독성 + literal \n 줄바꿈)
 *   - logout()      : token 제거 + 로그인 화면 전환
 *
 * 의존성: 없음 (브라우저 표준 API 만).
 *
 * 호환성:
 *   - HTML inline handler (onclick="logout()") 에서도 작동 — function 선언이
 *     자동으로 window 에 부착되는 비-모듈 script 동작에 의존.
 *   - 다른 inline <script> 와 script-scope 공유 (let token / const API_BASE 등).
 *
 * 사용:
 *   <script src="/static/js/api.js"></script>  // 본문 inline script 보다 먼저
 */

const API_BASE = window.location.origin + '/api/v1';
let token = localStorage.getItem('access_token');

// ==================== Auth helper ====================

function logout() {
  localStorage.removeItem('access_token');
  token = null;
  document.getElementById('login-screen').classList.remove('hidden');
  document.getElementById('dashboard-screen').classList.add('hidden');
}

// ==================== API helper ====================
// 401 카운트 — 연속 3회 이상이면 진짜 토큰 만료로 판단하고 로그아웃.
// 일시적 오류 (서버 재시작, 네트워크 hiccup 등) 는 1~2회 401 후 자동 회복.
let _consecutive401 = 0;

async function api(path, opts = {}) {
  const headers = opts.headers || {};
  if (token) headers['Authorization'] = 'Bearer ' + token;
  if (opts.body && typeof opts.body === 'object' && !(opts.body instanceof URLSearchParams)) {
    headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(API_BASE + path, {...opts, headers});
  if (res.status === 401) {
    _consecutive401 += 1;
    if (_consecutive401 >= 3) {
      // 진짜 토큰 만료 — 로그아웃
      _consecutive401 = 0;
      logout();
      throw new Error('인증 만료 (3회 연속) — 다시 로그인 해주세요.');
    }
    // 일시적 에러로 판단 — 토큰 유지하고 에러만 표시
    throw new Error(`인증 오류 (${_consecutive401}/3) — 일시적일 수 있으니 잠시 후 다시 시도해주세요.`);
  }
  // 성공 응답 받으면 401 카운터 리셋
  _consecutive401 = 0;
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

// ==================== Toast 알림 ====================

function toast(msg, type) {
  // 2026-05-13 (사용자 모바일 UX): backend 에러의 literal "\n" 을 실 줄바꿈으로 표시.
  // 또한 JSON detail 추출 — "400: {\"detail\":\"...\"}" → "400: ..."
  // 2026-06-03 (#18 fix): Pydantic 422 의 list 형식 detail 도 파싱 (필드별 명확 표시).
  const el = document.getElementById('toast');
  let display = String(msg || '');
  // JSON detail 추출 (e.g., '400: {"detail":"..."}' 또는 '422: {"detail":[{"loc":[...],...}]}')
  const jsonMatch = display.match(/^(\d{3}):\s*(\{.*\})$/s);
  if (jsonMatch) {
    try {
      const parsed = JSON.parse(jsonMatch[2]);
      if (parsed && parsed.detail !== undefined && parsed.detail !== null) {
        if (Array.isArray(parsed.detail)) {
          // Pydantic 422 — 필드별 validation 에러 list. 사장님이 어느 필드 invalid 인지 명확 표시.
          const errors = parsed.detail.map(d => {
            // loc = ["body", "field_name", ...] → "field_name" 만 추출 (가독성)
            const loc = (d.loc || []).filter(x => x !== 'body' && typeof x === 'string').join('.') || '(root)';
            const msg = d.msg || JSON.stringify(d);
            const inputHint = d.input !== undefined ? ` (입력: ${JSON.stringify(d.input).slice(0, 50)})` : '';
            return `  • ${loc}: ${msg}${inputHint}`;
          }).join('\n');
          display = `${jsonMatch[1]} 검증 실패 (${parsed.detail.length}개 필드):\n${errors}`;
        } else {
          // 일반 string detail (FastAPI HTTPException)
          display = `${jsonMatch[1]}: ${parsed.detail}`;
        }
      }
    } catch (_) { /* 파싱 실패 시 원본 유지 */ }
  }
  // literal "\n" 을 실 newline 으로 (CSS white-space: pre-line 가 줄바꿈 표시)
  display = display.replace(/\\n/g, '\n');
  el.textContent = display;
  el.className = 'toast toast-' + (type || 'success');
  el.classList.remove('hidden');
  // 긴 메시지는 더 오래 표시 (글자 수 비례, 3.5s ~ 15s)
  const duration = Math.max(3500, Math.min(15000, display.length * 80));
  // 클릭하면 즉시 닫기 (긴 메시지 사용자 제어)
  el.style.cursor = 'pointer';
  el.onclick = () => el.classList.add('hidden');
  setTimeout(() => el.classList.add('hidden'), duration);
}
