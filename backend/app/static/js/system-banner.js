/**
 * System Status Banner (Zombie Guardian) — Phase 3 추가 분리 (2026-05-14).
 *
 * 좀비/Kill-Switch/Critical 이벤트 통합 상단 배너.
 * 백엔드 /admin/system-status 엔드포인트가 통합 dump 제공.
 *
 * 함수:
 *   - loadSystemStatus(forceRefresh)
 *     1분마다 자동 호출 + 사용자 「↻ 새로고침」 시 forceRefresh=true.
 *     is_healthy=true 면 배너 숨김. 아니면 KS/zombie/critical 표시.
 *
 *   - clearKillSwitch(accountId)
 *     배너 「🔓 해제」 버튼. /admin/kill-switch/{id}/disable 호출.
 *     백엔드가 row.status TRIGGERED → ACTIVE 도 동시 리셋 (재검사 가능).
 *
 * 의존성:
 *   - api()              → /static/js/api.js
 *   - toast()            → /static/js/api.js
 *   - refreshStrategies() → index.html (clearKillSwitch 후 strategies 갱신)
 *   - DOM: #zg-banner, #zg-banner-title, #zg-banner-body, #zg-banner-detail
 */

async function loadSystemStatus(forceRefresh = false) {
  try {
    const data = await api('/admin/system-status');
    const banner = document.getElementById('zg-banner');
    const titleEl = document.getElementById('zg-banner-title');
    const bodyEl = document.getElementById('zg-banner-body');
    const detailEl = document.getElementById('zg-banner-detail');
    if (!banner) return;
    if (data.is_healthy) {
      banner.classList.add('hidden');
      return;
    }
    banner.classList.remove('hidden');
    const parts = [];
    if (data.kill_switches_active && data.kill_switches_active.length > 0) {
      const accBtns = data.kill_switches_active.map(k => {
        return `account #${k.exchange_account_id} (${k.reason_code}) `
             + `<button onclick="clearKillSwitch(${k.exchange_account_id})" `
             + `class="ml-1 px-2 py-0.5 text-xs bg-red-700 hover:bg-red-600 rounded text-white" `
             + `title="이 계정의 Kill-Switch 해제 — 손실 한도 row 도 ACTIVE 로 리셋">🔓 해제</button>`;
      }).join(' &nbsp; ');
      parts.push(`🔒 <b>Kill-Switch 활성</b>: ${accBtns}<br><span class="text-xs text-slate-400">신규 주문 자동 차단 중. 원인 확인 후 위 버튼으로 해제.</span>`);
    }
    if (data.stuck_zombie_count > 0) {
      parts.push(`🧟 <b>좀비 stuck 카운터</b>: ${data.stuck_zombie_count}건 — reconcile 이 자동 회복 시도 중`);
    }
    if (data.critical_events_recent && data.critical_events_recent.length > 0) {
      parts.push(`🚨 <b>최근 1시간 CRITICAL 이벤트</b>: ${data.critical_events_recent.length}건`);
    }
    titleEl.textContent = '🚨 시스템 경고 — Zombie Guardian 발동';
    bodyEl.innerHTML = parts.join('<br>');
    // 상세 (펼치면 보임)
    const lines = [];
    if (data.kill_switches_active.length > 0) {
      lines.push('=== Kill-Switch 활성 계정 ===');
      data.kill_switches_active.forEach(k => {
        lines.push(`  account #${k.exchange_account_id}`);
        lines.push(`    code: ${k.reason_code}`);
        lines.push(`    msg : ${k.reason_message || ''}`);
        lines.push(`    at  : ${(k.triggered_at || '').replace('T', ' ').slice(0, 19)}`);
      });
    }
    if (data.critical_events_recent.length > 0) {
      lines.push('');
      lines.push('=== 최근 CRITICAL 이벤트 ===');
      data.critical_events_recent.slice(0, 10).forEach(e => {
        const t = (e.created_at || '').replace('T', ' ').slice(0, 19);
        lines.push(`  [${t}] sid=${e.strategy_id || '-'} ${e.event_type}`);
        lines.push(`    ${e.title}`);
        if (e.message) lines.push(`    └ ${e.message.slice(0, 200)}`);
      });
    }
    detailEl.textContent = lines.join('\n');
    if (forceRefresh) {
      // 사용자가 「↻ 새로고침」 누른 경우 짧은 시각 강조
      banner.classList.add('ring-2', 'ring-red-400');
      setTimeout(() => banner.classList.remove('ring-2', 'ring-red-400'), 1500);
    }
  } catch (e) {
    // 인증 만료 등은 silent — 다음 사이클 재시도
  }
}

// Kill-Switch 수동 해제 (2026-05-07 사용자 운영 발견 — 배너 버튼).
// 백엔드가 row.status TRIGGERED → ACTIVE 도 동시 리셋해서 다음 사이클 재검사 가능.
async function clearKillSwitch(accountId) {
  if (!confirm(
    `🔓 계정 #${accountId} Kill-Switch 해제\n\n` +
    `해제 후 신규 주문 가능. 단, 같은 손실 조건이면 다음 1분 사이클에 자동 재발동.\n` +
    `먼저 손실 한도 (DAILY_LOSS_LIMIT_USDT) 확인/조정 권장.\n\n` +
    `진행할까요?`
  )) return;
  try {
    await api(`/admin/kill-switch/${accountId}/disable`, { method: 'POST' });
    toast(`✅ 계정 #${accountId} Kill-Switch 해제됨`, 'success');
    loadSystemStatus(true);  // 배너 즉시 갱신
    refreshStrategies();
  } catch (e) {
    toast(`해제 실패: ${e.message}`, 'error');
  }
}
