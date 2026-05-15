/**
 * Health Dashboard 페이지 (운영 점검) — Phase 3 추가 분리 (2026-05-14).
 *
 * 사용자 요청 (2026-05-09 Layer 2): 「🩺 점검」 탭 — 직전 N시간 거래/이벤트/손익 요약.
 * health_check.py CLI 와 동일 데이터 형식.
 *
 * navigation 에서 #health hash 로 진입 시 호출:
 *   loadHealthDashboard(hours)
 *     - hours: 24 (기본) / 1 / 6 / 72 등 사용자가 toggle
 *
 * Backend endpoint: GET /admin/health/dashboard?hours=N
 *
 * 의존성:
 *   - api()  → /static/js/api.js (loaded earlier)
 *   - DOM elements: #page-health / #health-content / #health-meta (index.html)
 */

async function loadHealthDashboard(hours) {
  hours = hours || 24;
  window._hpHours = hours;
  // 버튼 active 상태
  document.querySelectorAll('#page-health button[onclick^="loadHealthDashboard"]').forEach(b => {
    const m = b.getAttribute('onclick').match(/loadHealthDashboard\((\d+)\)/);
    const isActive = m && Number(m[1]) === hours;
    b.classList.toggle('btn-primary', isActive);
    b.classList.toggle('btn-ghost', !isActive);
  });
  const content = document.getElementById('health-content');
  const meta = document.getElementById('health-meta');
  content.innerHTML = '<p class="text-sm text-slate-400">⏳ 로딩 중...</p>';
  try {
    const data = await api(`/admin/health/dashboard?hours=${hours}`);
    meta.textContent = `직전 ${hours}h | 마지막 갱신: ${new Date().toLocaleTimeString()}`;
    const healthEmoji = data.is_healthy ? '🟢' : '⚠️';
    const healthLabel = data.is_healthy ? '정상' : '주의 필요';
    const fmtPnl = (v) => {
      const n = Number(v);
      const sign = n >= 0 ? '+' : '';
      const cls = n >= 0 ? 'text-green-400' : 'text-red-400';
      return `<span class="${cls}">${sign}${n.toFixed(2)}</span>`;
    };
    const sev = data.events.by_severity || {};
    const sevRow = ['CRITICAL', 'ERROR', 'WARN', 'INFO']
      .filter(s => sev[s])
      .map(s => {
        const color = { CRITICAL: 'text-red-400', ERROR: 'text-orange-400', WARN: 'text-yellow-400', INFO: 'text-slate-300' }[s];
        return `<span class="${color} font-mono mr-3">${s}: ${sev[s]}</span>`;
      }).join('') || '<span class="text-green-400">✅ 0건</span>';
    const top5 = (data.events.top_5 || []).map(e => {
      const marker = e.is_benign ? ' <span class="text-slate-500 text-xs">(정상)</span>' : '';
      return `<div class="text-xs"><span class="font-mono text-blue-300">${e.count}건</span> ${e.event_type}${marker}</div>`;
    }).join('');
    const recs = (data.recommendations || []).map(r => `<li class="text-sm text-yellow-300">${r}</li>`).join('') ||
      '<li class="text-sm text-green-400">없음 — 그대로 운영</li>';
    const actionItems = (data.action_needed.items || []).map(it => {
      const ts = new Date(it.created_at).toLocaleString();
      const sid = it.strategy_instance_id ? `#${it.strategy_instance_id}` : '-';
      const color = it.severity === 'CRITICAL' ? 'text-red-400' : 'text-orange-400';
      return `<tr class="border-t border-slate-700">
        <td class="py-1 px-2 text-xs text-slate-400 font-mono">${ts}</td>
        <td class="py-1 px-2 text-xs ${color} font-mono">${it.severity}</td>
        <td class="py-1 px-2 text-xs text-slate-300 font-mono">${sid}</td>
        <td class="py-1 px-2 text-xs">${it.title}</td>
      </tr>`;
    }).join('');
    content.innerHTML = `
      <div class="grid grid-cols-1 md:grid-cols-4 gap-3 mb-4">
        <div class="card" style="padding:12px">
          <div class="text-xs text-slate-400">전체 상태</div>
          <div class="text-2xl font-bold mt-1">${healthEmoji} ${healthLabel}</div>
          <div class="text-xs text-slate-400 mt-1">검토 필요: ${data.action_needed.count}건</div>
        </div>
        <div class="card" style="padding:12px">
          <div class="text-xs text-slate-400">거래 활동</div>
          <div class="text-sm mt-1">신규: <span class="font-mono">${data.trading.new_strategies}</span></div>
          <div class="text-sm">진입: <span class="font-mono text-green-400">${data.trading.entries}</span> / 청산: <span class="font-mono text-orange-400">${data.trading.exits}</span></div>
        </div>
        <div class="card" style="padding:12px">
          <div class="text-xs text-slate-400">손익 (USDT)</div>
          <div class="text-sm mt-1">미실현: ${fmtPnl(data.pnl.unrealized)} (${data.pnl.active_count}건)</div>
          <div class="text-sm">누적 실현: ${fmtPnl(data.pnl.realized_total)}</div>
        </div>
        <div class="card" style="padding:12px">
          <div class="text-xs text-slate-400">텔레그램</div>
          <div class="text-sm mt-1">발송: <span class="font-mono">${data.telegram.sent}</span></div>
          <div class="text-sm">실패: <span class="font-mono ${data.telegram.failed > 0 ? 'text-red-400' : 'text-green-400'}">${data.telegram.failed}</span></div>
        </div>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
        <div class="card" style="padding:12px">
          <div class="text-sm font-semibold mb-2">⚠️ 위험 이벤트 (${data.events.total}건)</div>
          <div class="text-sm">${sevRow}</div>
        </div>
        <div class="card" style="padding:12px">
          <div class="text-sm font-semibold mb-2">📋 빈도 top 5</div>
          ${top5 || '<div class="text-xs text-slate-400">이벤트 없음</div>'}
        </div>
      </div>

      <div class="card" style="padding:12px;margin-bottom:12px">
        <div class="text-sm font-semibold mb-2">💡 권장 조치</div>
        <ul class="ml-4 list-disc">${recs}</ul>
      </div>

      ${data.action_needed.count > 0 ? `
      <div class="card" style="padding:12px">
        <div class="text-sm font-semibold mb-2">🚨 검토 필요 항목 (top 20)</div>
        <table class="w-full text-xs">
          <thead><tr class="text-left text-slate-400 border-b border-slate-700">
            <th class="py-1 px-2">시각</th><th class="py-1 px-2">심각도</th><th class="py-1 px-2">전략</th><th class="py-1 px-2">제목</th>
          </tr></thead>
          <tbody>${actionItems}</tbody>
        </table>
      </div>` : ''}
    `;
  } catch (e) {
    content.innerHTML = `<p class="text-sm text-red-400">로딩 실패: ${e.message}</p>`;
  }
}
