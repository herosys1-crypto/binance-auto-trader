/**
 * 페이지 전환 + hash routing + 섹션 스크롤 (Phase 3 단계 3s, 2026-05-15).
 *
 * 로그인 → 대시보드 진입 (showDashboard) + #dashboard / #ranking / #health hash 라우팅 +
 * 브라우저 back/forward 대응 + 섹션 점프 스크롤 + 하이라이트.
 *
 * - showDashboard()         : 로그인 화면 숨기고 대시보드 표시 + 초기 hash 적용
 * - _pageFromHash()         : 현재 URL hash → 페이지 키 (dashboard/ranking/health)
 * - navigateTo(page)        : 페이지 전환 + hash 갱신 + nav 활성 토글 + 페이지별 초기 로딩
 * - refreshCurrentPage()    : 현재 페이지의 새로고침 호출 (refreshAll / loadRankingPage / loadHealthDashboard)
 * - scrollToSection(id)     : 섹션으로 부드럽게 스크롤 + 1.4초 하이라이트
 *
 * 외부 의존 (script-scope 공유):
 *   - _initArchiveToggleFromStorage (strategies-list.js)
 *   - loadRankingPage  (ranking-page.js)
 *   - loadHealthDashboard (health-page.js)
 *   - refreshAll       (dashboard-refresh.js)
 *
 * 부수 효과:
 *   - window 에 hashchange 리스너 등록 (스크립트 로드 시점)
 */

function showDashboard() {
  document.getElementById('login-screen').classList.add('hidden');
  document.getElementById('dashboard-screen').classList.remove('hidden');
  const email = document.getElementById('email').value;
  document.getElementById('user-info').textContent = '👤 ' + email;
  // 2026-05-06: archive 토글 체크박스 초기 상태 복원 (localStorage)
  if (typeof _initArchiveToggleFromStorage === 'function') {
    _initArchiveToggleFromStorage();
  }
  // hash 기반 page routing 초기화 (2026-05-06: 시장 순위 별도 페이지)
  navigateTo(_pageFromHash() || 'dashboard');
}

// ==================== Page Navigation (2026-05-06: 시장 순위 별도 페이지) ====================
// hash routing — #dashboard / #ranking. URL 공유 가능 + 새 탭 열기 가능.
let _currentPage = 'dashboard';

function _pageFromHash() {
  const h = (window.location.hash || '').replace(/^#/, '').toLowerCase();
  if (h === 'ranking') return 'ranking';
  if (h === 'health') return 'health';
  return 'dashboard';
}

function navigateTo(page) {
  if (!['dashboard', 'ranking', 'health'].includes(page)) page = 'dashboard';
  _currentPage = page;
  // URL hash 갱신 (popstate 도 같이 트리거)
  if (window.location.hash !== '#' + page) {
    history.replaceState(null, '', '#' + page);
  }
  // page 표시/숨김
  document.getElementById('page-dashboard').classList.toggle('hidden', page !== 'dashboard');
  document.getElementById('page-ranking').classList.toggle('hidden', page !== 'ranking');
  const healthEl = document.getElementById('page-health');
  if (healthEl) healthEl.classList.toggle('hidden', page !== 'health');
  // nav 활성 표시
  ['dashboard', 'ranking', 'health'].forEach(p => {
    const btn = document.getElementById('nav-' + p);
    if (!btn) return;
    if (p === page) {
      btn.classList.add('btn-primary'); btn.classList.remove('btn-ghost');
    } else {
      btn.classList.add('btn-ghost'); btn.classList.remove('btn-primary');
    }
  });
  // page 별 초기 로딩
  if (page === 'ranking') {
    if (!window._rpState) window._rpState = { period: '1d', direction: 'gainers' };
    loadRankingPage(window._rpState.period, window._rpState.direction);
  } else if (page === 'health') {
    if (!window._hpHours) window._hpHours = 24;
    loadHealthDashboard(window._hpHours);
  } else {
    refreshAll();
  }
}

function refreshCurrentPage() {
  if (_currentPage === 'ranking') loadRankingPage(null, null);
  else if (_currentPage === 'health') loadHealthDashboard(window._hpHours || 24);
  else refreshAll();
}

// 브라우저 back/forward 대응
window.addEventListener('hashchange', () => navigateTo(_pageFromHash()));

// ==================== UI 네비게이션 ====================
function scrollToSection(sectionId) {
  const el = document.getElementById(sectionId);
  if (!el) return;
  el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  // 하이라이트 애니메이션 (1.4초)
  el.classList.remove('section-highlight');
  void el.offsetWidth;  // reflow 트릭
  el.classList.add('section-highlight');
  setTimeout(() => el.classList.remove('section-highlight'), 1500);
}
