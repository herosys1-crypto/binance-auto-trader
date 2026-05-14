/**
 * Templates panel — refresh + cleanup + delete (Phase 3 단계 3k, 2026-05-14).
 *
 * 「📋 전략 템플릿」 panel 의 모든 액션.
 *
 * 함수:
 *   - refreshTemplates()           : /admin/strategy-templates → 라디오 목록 + _quick_ 숨김 토글
 *   - cleanupQuickTemplates()      : 3-way 정리 (안전/cascade/force) 모드
 *   - deleteTemplate(id, name)     : 단건 삭제 (비활성화 → cascade 재시도 제안)
 *
 * 외부 의존성 (script-scope 공유):
 *   - api / toast (api.js)
 *   - escapeHtml / fmtNum / setMetric / sideBadge (helpers.js)
 *   - openCreateModalForBatch (template-save.js)
 *   - refreshStrategies (index.html)
 *   - DOM: #templates-tbody, #show-quick, #metric-templates*
 */

async function refreshTemplates() {
  try {
    const data = await api('/admin/strategy-templates');
    const active = data.filter(t => t.is_active).length;
    const showQuick = document.getElementById('show-quick')?.checked;
    const visible = showQuick ? data : data.filter(t => !String(t.name).startsWith('_quick_'));
    const hiddenCount = data.length - visible.length;

    setMetric('templates', data.length + '개',
      `사용 가능 ${active}개${hiddenCount > 0 ? ` (_quick_ ${hiddenCount}개 숨김)` : ''}`,
      data.length ? 'green' : 'gray');

    const tbody = document.getElementById('templates-tbody');
    if (visible.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" class="text-center text-slate-500 py-6">표시할 템플릿 없음</td></tr>';
      return;
    }
    tbody.innerHTML = visible.map(t => {
      const sc = t.stages_config || {};
      const stages = (sc.capitals || []).map(c => fmtNum(c)).join(' / ');
      const isQuick = String(t.name).startsWith('_quick_');
      const nameDisplay = isQuick
        ? `<span class="font-mono text-slate-500">${escapeHtml(t.name)}</span>`
        : `<span class="font-mono text-blue-300">${escapeHtml(t.name)}</span>`;
      // 2026-05-12 v2 (사용자 UX 개선): 「🚀 다중」 버튼 → 「+ 새 전략」 모달 열기 (template select + 다중 모드 pre-set).
      // 단일 진입점 (모달) 으로 통합 — 동일한 다중 심볼 입력 UI 사용.
      const batchBtn = !isQuick && t.is_active
        ? `<button onclick="openCreateModalForBatch(${t.id})" class="btn-primary btn text-xs" style="padding:2px 8px" title="이 템플릿으로 「+ 새 전략」 모달 열기 + 다중 심볼 모드 자동 활성">🚀 다중</button>`
        : '';
      return `<tr>
        <td>${t.id}</td>
        <td>${nameDisplay}</td>
        <td>${sideBadge(t.side)}</td>
        <td class="num">${t.leverage}x</td>
        <td class="num">${fmtNum(t.total_capital)} <span class="text-slate-500">USDT</span></td>
        <td class="text-xs text-slate-400">${stages || '-'}</td>
        <td>${t.is_active ? '<span class="badge badge-green">활성</span>' : '<span class="badge badge-gray">중지</span>'}</td>
        <td class="flex gap-1">
          ${batchBtn}
          <button onclick="deleteTemplate(${t.id}, '${escapeHtml(t.name).replace(/'/g, "\\'")}')" class="btn-danger btn text-xs" style="padding:2px 8px" title="템플릿 삭제 (사용 중이면 비활성화)">🗑</button>
        </td>
      </tr>`;
    }).join('');
  } catch (err) { toast('템플릿 조회 실패: ' + err.message, 'error'); }
}

// 2026-05-14 dead code 제거: deleteTemplate 가 두 번 정의돼 있었음 (이전 라인 + 1506).
// 두 번째 정의 (cascade retry 포함) 가 첫 번째를 override 하던 상태 → 첫 번째 제거.

// UX #19 (2026-04-29): 3-way 선택 (안전 / 강제 / 완전(force))
async function cleanupQuickTemplates() {
  // prompt 로 모드 선택 (1/2/3)
  const choice = prompt(
    '_quick_* 템플릿 정리 — 모드 선택\n\n' +
    '1 = 🟢 안전 정리\n' +
    '    미사용만 삭제, 사용 중은 비활성화만\n\n' +
    '2 = 🟡 강제 정리 (cascade)\n' +
    '    종료된 strategy 까지 삭제, active 는 비활성화만\n\n' +
    '3 = 🔴 완전 정리 (force)\n' +
    '    활성 전략 시장가 청산 + 미체결 취소 → strategy + template 모두 삭제\n' +
    '    ⚠️ 실제 포지션이 청산되어 손실 확정될 수 있음\n\n' +
    '번호 입력 (1 / 2 / 3, 빈값=취소):',
    '1'
  );
  if (!choice) return;
  let cascade = false, force = false, label = '';
  if (choice.trim() === '1') { label = '안전 정리'; }
  else if (choice.trim() === '2') { cascade = true; label = '강제 정리 (cascade)'; }
  else if (choice.trim() === '3') {
    force = true;
    label = '완전 정리 (force)';
    if (!confirm('🔴 완전 정리 — 최종 확인\n\n_quick_* 템플릿을 사용하는 활성 전략을 모두 시장가 청산하고\n strategy + template 을 모두 삭제합니다.\n\n실제 포지션이 시장가에 청산되어 손실이 확정될 수 있습니다.\n\n정말 진행할까요?')) return;
  } else {
    return toast('잘못된 입력. 1/2/3 중 선택해주세요.', 'warning');
  }
  try {
    const params = new URLSearchParams();
    if (cascade) params.set('cascade', 'true');
    if (force) params.set('force', 'true');
    const res = await api(`/admin/strategy-templates/cleanup-quick?${params}`, { method: 'POST' });
    toast(`${label}: ${res.message || '완료'}`, force ? 'warning' : 'success');
    refreshTemplates();
    refreshStrategies();
  } catch (e) { toast('정리 실패: ' + e.message, 'error'); }
}

async function deleteTemplate(id, name) {
  if (!confirm(`템플릿 '${name}' (#${id}) 을 삭제할까요?\n\n사용 중인 strategy 가 있으면 비활성화됩니다.`)) return;
  try {
    let res;
    try {
      res = await api(`/admin/strategy-templates/${id}`, { method: 'DELETE' });
    } catch (e) {
      throw e;
    }
    // 비활성화로 끝났으면 cascade 재시도 제안
    if (res.message && res.message.includes('비활성화')) {
      if (confirm(`${res.message}\n\n참조 strategy 가 모두 종료 상태면 cascade 삭제로 정리할 수 있습니다.\n진행하시겠어요?`)) {
        const cascadeRes = await api(`/admin/strategy-templates/${id}?cascade=true`, { method: 'DELETE' });
        toast(cascadeRes.message || 'cascade 삭제 완료', 'success');
        refreshTemplates();
        refreshStrategies();
        return;
      }
    }
    toast(res.message || '삭제됨', 'success');
    refreshTemplates();
  } catch (e) { toast('삭제 실패: ' + e.message, 'error'); }
}
