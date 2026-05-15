/**
 * 헤더 admin 단축 버튼 (Phase 3 단계 3r, 2026-05-15).
 *
 * - testTelegram()    : Telegram 봇 테스트 메시지 발송 → 채팅 확인용
 * - exportCsv(kind)   : strategies / orders CSV 다운로드 (admin/export/{kind})
 *
 * 외부 의존 (script-scope 공유):
 *   - api, toast (전역 헬퍼)
 *   - token (전역 인증 토큰)
 */

async function testTelegram() {
  try {
    const data = await api('/admin/test-telegram', {method: 'POST'});
    toast('Telegram 테스트 발송 완료. 봇 채팅 확인해주세요', 'success');
  } catch (err) { toast('Telegram 발송 실패: ' + err.message, 'error'); }
}

async function exportCsv(kind) {
  try {
    const url = `${window.location.origin}/api/v1/admin/export/${kind}`;
    const res = await fetch(url, { headers: { Authorization: 'Bearer ' + token } });
    if (!res.ok) throw new Error(`${res.status}`);
    const blob = await res.blob();
    // Content-Disposition 의 filename 추출
    const cd = res.headers.get('Content-Disposition') || '';
    const m = cd.match(/filename="?([^"]+)"?/);
    const filename = m ? m[1] : `${kind}_${Date.now()}.csv`;
    // 다운로드 트리거
    const dlUrl = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = dlUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(dlUrl);
    toast(`${kind === 'strategies' ? '전략' : '주문'} CSV 다운로드 완료 — ${filename}`, 'success');
  } catch (err) { toast(`CSV 다운로드 실패: ${err.message}`, 'error'); }
}
