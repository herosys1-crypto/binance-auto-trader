/**
 * 「⭐ 즐겨찾기 템플릿 5개」 카드 + 1 클릭 신 전략 (2026-06-09 사장님 요구).
 *
 * 사장님 명시: "기본 세팅 5개 만들수 있게 + 1 클릭 신 전략"
 * = 「외부 포지션」 카드 위 = 신 「⭐ 즐겨찾기 템플릿」 카드
 * = 사장님 자주 쓰는 template 5개 = 카드 표시 + 클릭 1번 신 전략
 *
 * 함수:
 *   - refreshFavoriteTemplates()      : 즐겨찾기 목록 fetch + 카드 렌더
 *   - openTemplateFavoritePicker()    : 모든 template 중 ⭐ 토글 모달
 *   - toggleTemplateFavorite(id)      : 즐겨찾기 마킹 ON/OFF
 *   - startStrategyFromTemplate(id)   : 1 클릭 신 전략 (= 「새 전략」 모달 + template 자동 선택)
 *
 * 외부 의존:
 *   - api / toast (전역)
 *   - openCreateModal (cm-open-modal.js) — 신 전략 모달
 */

async function refreshFavoriteTemplates() {
  const grid = document.getElementById('favorite-templates-grid');
  if (!grid) return;
  try {
    const tpls = await api('/admin/strategy-templates/favorites');
    if (!tpls || tpls.length === 0) {
      grid.innerHTML = `<div class="col-span-full text-center text-slate-500 text-xs py-4">
        즐겨찾기 템플릿 없음. <button onclick="openTemplateFavoritePicker()" class="text-blue-400 underline">「+ 즐겨찾기 관리」</button> 에서 추가하세요.
      </div>`;
      return;
    }
    grid.innerHTML = tpls.map(t => _renderFavoriteCard(t)).join('');
  } catch (err) {
    grid.innerHTML = `<div class="col-span-full text-center text-red-400 text-xs py-4">조회 실패: ${err.message}</div>`;
  }
}

function _renderFavoriteCard(t) {
  const stagesCount = (t.stages_config?.capitals || []).filter(c => c && Number(c) > 0).length || 0;
  const sideColor = t.side === 'SHORT' ? 'text-red-400' : 'text-green-400';
  const sideIcon = t.side === 'SHORT' ? '📉' : '📈';
  const sideLabel = t.side === 'SHORT' ? '숏' : '롱';
  const tp1 = t.tp1_percent != null ? `+${Number(t.tp1_percent)}%` : '-';
  const sl = t.stop_loss_percent_of_capital != null ? `-${Number(t.stop_loss_percent_of_capital)}%` : '-';
  const totalCap = Number(t.total_capital || 0).toLocaleString('en-US', {maximumFractionDigits: 0});
  const name = (t.name || '').replace(/_inplace_s\d+_\d+.*$/, '').substring(0, 24);
  return `<div class="bg-slate-800 border border-slate-700 rounded p-3 hover:border-blue-500 transition cursor-pointer" onclick="startStrategyFromTemplate(${t.id})" title="클릭 = 1 클릭 신 전략 시작 (시작가 = 현재가 자동)">
    <div class="flex items-center justify-between mb-1">
      <span class="font-semibold text-sm truncate" title="${t.name}">${name}</span>
      <button onclick="event.stopPropagation(); toggleTemplateFavorite(${t.id})" class="text-yellow-400 text-base" title="즐겨찾기 해제">⭐</button>
    </div>
    <div class="text-xs ${sideColor} mb-1">${sideIcon} ${sideLabel} ${t.leverage}x</div>
    <div class="text-xs text-slate-400">자본 <span class="text-cyan-300">${totalCap}</span> USDT</div>
    <div class="text-xs text-slate-400">단계 <span class="text-purple-300">${stagesCount}</span>개 | TP1 <span class="text-green-400">${tp1}</span> | SL <span class="text-red-400">${sl}</span></div>
    <button onclick="event.stopPropagation(); startStrategyFromTemplate(${t.id})" class="btn-primary btn w-full mt-2" style="padding:4px 8px;font-size:11px">➕ 신 전략 시작</button>
  </div>`;
}

async function startStrategyFromTemplate(templateId) {
  // 🚨 2026-07-06 사장님 critical fix v2: template 자동 반영 강화!
  // 옛 silent bug: setTimeout 500ms = template 로드 안 끝남 = radio 못 찾음!
  // 신 fix: template mode 강제 + 값 직접 채우기 (= radio 실패해도 반영!)
  try {
    if (typeof openCreateModal !== 'function') {
      toast('「새 전략」 모달 함수 X — 페이지 새로고침', 'error');
      return;
    }
    // 1️⃣ template 데이터 = 사전 조회 (= 확실 반영!)
    let tplData = null;
    try {
      tplData = await api(`/admin/strategy-templates/${templateId}`);
    } catch (e) {
      console.warn('[startStrategy] template 사전 조회 실패:', e);
    }
    openCreateModal(null);
    // 2️⃣ 모달 열림 대기 (= 1초 = 확실!)
    setTimeout(async () => {
      try {
        // template mode 강제 전환!
        if (typeof setCmMode === 'function') setCmMode('template');
        // radio 선택 시도!
        const radio = document.querySelector(`input[name="cm-template"][value="${templateId}"]`);
        if (radio) {
          radio.checked = true;
          radio.dispatchEvent(new Event('change'));
        }
        // 3️⃣ 값 직접 채우기 (= template 사전 조회 성공 시!)
        if (tplData && tplData.stages_config) {
          // Side + leverage!
          if (tplData.side && typeof setCmSide === 'function') setCmSide(tplData.side);
          const lvEl = document.getElementById('cm-leverage');
          if (lvEl && tplData.leverage) lvEl.value = tplData.leverage;
          // Capitals + triggers!
          const caps = tplData.stages_config.capitals || [];
          const trigs = tplData.stages_config.trigger_percents || [];
          for (let i = 1; i <= 10; i++) {
            const cap = caps[i-1];
            const trg = trigs[i-1];
            const capEl = document.getElementById('cm-cap-' + i);
            const trgEl = document.getElementById('cm-trg-' + i);
            if (capEl) capEl.value = (cap && Number(cap) > 0) ? cap : '';
            if (trgEl) trgEl.value = (trg && Number(trg) > 0) ? trg : '';
          }
          // 미리보기 갱신!
          if (typeof onCapitalsChange === 'function') onCapitalsChange();
          if (typeof _refreshLiveCalc === 'function') _refreshLiveCalc();
          toast(`✅ 템플릿 #${templateId} 값 반영 완료 (자본: ${caps.join(', ')})`, 'success');
        } else {
          toast(`⚠️ 템플릿 조회 실패 — 「템플릿 선택」 탭에서 수동 선택`, 'warning');
        }
      } catch (e) {
        console.warn('template auto-select fail:', e);
        toast(`⚠️ 자동 반영 실패: ${e.message}`, 'warning');
      }
    }, 1000);  // 옛 500ms → 신 1000ms 확실!
  } catch (err) {
    toast(`신 전략 시작 실패: ${err.message}`, 'error');
  }
}

async function toggleTemplateFavorite(templateId) {
  try {
    const updated = await api(`/admin/strategy-templates/${templateId}/toggle-favorite`, { method: 'POST' });
    toast(`✅ ${updated.is_favorite ? '⭐ 즐겨찾기 추가' : '☆ 즐겨찾기 해제'}: ${updated.name}`, 'success');
    refreshFavoriteTemplates();
    // 모달 열려 있으면 = 모달도 갱신
    const pickerModal = document.getElementById('fav-picker-modal-backdrop');
    if (pickerModal) openTemplateFavoritePicker();
  } catch (err) {
    toast(`즐겨찾기 변경 실패: ${err.message}`, 'error');
  }
}

async function openTemplateFavoritePicker() {
  let tpls;
  try {
    tpls = await api('/admin/strategy-templates');
  } catch (err) {
    toast(`템플릿 조회 실패: ${err.message}`, 'error');
    return;
  }
  const favoriteCount = tpls.filter(t => t.is_favorite).length;
  const rowsHtml = tpls.map(t => {
    const star = t.is_favorite ? '⭐' : '☆';
    const sideKo = t.side === 'SHORT' ? '📉 숏' : '📈 롱';
    const name = (t.name || '').replace(/_inplace_s\d+_\d+.*$/, '');
    return `<tr style="border-bottom:1px solid #334155">
      <td style="padding:6px;text-align:center;cursor:pointer;font-size:18px" onclick="toggleTemplateFavorite(${t.id})" title="즐겨찾기 토글">${star}</td>
      <td style="padding:6px"><span class="font-mono text-blue-300">#${t.id}</span></td>
      <td style="padding:6px">${name}</td>
      <td style="padding:6px;text-align:center">${sideKo}</td>
      <td style="padding:6px;text-align:right">${Number(t.total_capital||0).toLocaleString('en-US',{maximumFractionDigits:0})}</td>
    </tr>`;
  }).join('');
  const modalHtml = `
    <div id="fav-picker-modal-backdrop" style="position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:9999;display:flex;align-items:center;justify-content:center" onclick="if(event.target.id==='fav-picker-modal-backdrop')closeTemplateFavoritePicker()">
      <div style="background:#1e293b;border-radius:8px;padding:20px;max-width:640px;width:90%;max-height:80vh;overflow-y:auto">
        <h3 style="font-size:16px;font-weight:bold;margin-bottom:8px;color:#fbbf24">⭐ 즐겨찾기 관리 (${favoriteCount}/5 권장)</h3>
        <p style="font-size:12px;color:#94a3b8;margin-bottom:12px">⭐ 클릭 = 즐겨찾기 추가/제거. 카드에 노출되는 최대 5개 권장.</p>
        <table style="width:100%;border-collapse:collapse;margin-bottom:12px">
          <thead>
            <tr style="border-bottom:1px solid #475569;font-size:12px;color:#94a3b8">
              <th style="text-align:center;padding:6px;width:40px">⭐</th>
              <th style="text-align:left;padding:6px;width:50px">ID</th>
              <th style="text-align:left;padding:6px">이름</th>
              <th style="text-align:center;padding:6px">방향</th>
              <th style="text-align:right;padding:6px">자본</th>
            </tr>
          </thead>
          <tbody>${rowsHtml}</tbody>
        </table>
        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button onclick="closeTemplateFavoritePicker()" class="btn-ghost btn text-xs" style="padding:6px 16px">닫기</button>
        </div>
      </div>
    </div>
  `;
  document.body.insertAdjacentHTML('beforeend', modalHtml);
}

function closeTemplateFavoritePicker() {
  const m = document.getElementById('fav-picker-modal-backdrop');
  if (m) m.remove();
}

// 페이지 로드 시 자동 호출 (= 대시보드 첫 진입)
document.addEventListener('DOMContentLoaded', () => {
  // 약간 지연 (= 다른 init 후)
  setTimeout(() => { try { refreshFavoriteTemplates(); } catch (e) {} }, 1000);
});
