/**
 * 페이지 로드 시점 부트스트랩 (Phase 3 단계 3t — 마지막, 2026-05-15).
 *
 * 두 가지 사이드 이펙트:
 *   1) login-form submit 리스너 등록 — 로그인 → token 저장 → showDashboard + refreshAll
 *   2) localStorage 에 token 있으면 자동 로그인 + 5초 주기 폴링 (각 refresh)
 *
 * 외부 의존 (script-scope 공유):
 *   - API_BASE, token, toast (api.js)
 *   - showDashboard (page-router.js)
 *   - refreshAll, refreshStrategies, refreshHealth, refreshActivity, refreshStats,
 *     refreshSysHealth (dashboard-refresh.js / strategies-list.js)
 *
 * 이 모듈은 마지막에 로드돼야 함 — 위 의존이 모두 정의된 후 init 실행.
 */

// ==================== Auth ====================
document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = document.getElementById('email').value;
  const password = document.getElementById('password').value;
  try {
    const formData = new URLSearchParams();
    formData.set('username', email);
    formData.set('password', password);
    const res = await fetch(API_BASE + '/auth/token', {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: formData,
    });
    if (!res.ok) throw new Error('로그인 실패: ' + res.status);
    const data = await res.json();
    token = data.access_token;
    localStorage.setItem('access_token', token);
    showDashboard();
    refreshAll();
    toast('환영합니다 ' + email, 'success');
  } catch (err) {
    toast(err.message, 'error');
  }
});

// ==================== Init ====================
if (token) {
  showDashboard();
  refreshAll();
  setInterval(() => {
    if (!document.hidden) {
      refreshStrategies();
      refreshHealth();
      refreshActivity();
      refreshStats();
      refreshSysHealth();
    }
  }, 5000);
}
