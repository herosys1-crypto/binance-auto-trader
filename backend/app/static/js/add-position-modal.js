/**
 * 「💉 포지션 추가」 모달 (Phase 3 단계 3p, 2026-05-15).
 *
 * ad-hoc 자유 금액으로 시장가/지정가 추가 진입 — qty 늘림 + 평단 갱신.
 * (증거금 추가 = 같은 qty 로 청산가 완화 — addMargin 별도)
 *
 * - openAddPositionModal(id, symbol, side, leverage) : 모달 열기 + mark price 미리 로드
 * - closeAddPositionModal()                          : 모달 닫기
 * - toggleAddPositionLimitPrice()                    : MARKET ↔ LIMIT 라디오 전환
 * - loadAddPositionMarkPrice(symbol)                 : 현재가 조회 (미리보기 입력값)
 * - updateAddPositionPreview()                       : amount/lev/price → 예상 qty + 명목 표시
 * - submitAddPosition()                              : POST /strategies/{id}/add-position
 *
 * 외부 의존 (script-scope 공유):
 *   - api, toast (전역 헬퍼)
 *   - refreshStrategies (strategies-list.js)
 */

// 2026-05-04 (사용자 요청): 「💉 포지션 추가」 — ad-hoc 자유 금액 시장가/지정가 진입.
// 증거금 추가와 다름: qty 늘림 + 평단 갱신. 모달로 amount + order_type + (지정가) 입력.
function openAddPositionModal(id, symbol, side, leverage) {
  // mark price 가져오기 (api 호출) — 미리보기용
  document.getElementById('ap-strategy-id').value = id;
  document.getElementById('ap-symbol-display').textContent = symbol;
  document.getElementById('ap-side-display').textContent = side;
  document.getElementById('ap-side-display').className = side === 'SHORT' ? 'badge badge-red' : 'badge badge-green';
  document.getElementById('ap-leverage-display').textContent = leverage + 'x';
  document.getElementById('ap-amount').value = '';
  document.getElementById('ap-limit-price').value = '';
  // 시장가 default
  document.getElementById('ap-type-market').checked = true;
  toggleAddPositionLimitPrice();
  // 🌟 헌법 51: 신 진입 모드 default (= 사장님 사상!)
  const _resetEl = document.getElementById('ap-mode-reset');
  const _preserveEl = document.getElementById('ap-mode-preserve');
  if (_resetEl) _resetEl.checked = true;
  if (_preserveEl) _preserveEl.checked = false;
  // 현재가 표시 + 미리보기 갱신
  loadAddPositionMarkPrice(symbol);
  document.getElementById('ap-modal').classList.remove('hidden');
  // 🚨 v108 사장님 신 요구: 여유 자금 표시!
  _loadAddPositionAvailableFunds();
}

// 🚨 v108: 여유 자금 표시 (사장님 사상 = 「포지션 추가」 최대치 안내!)
async function _loadAddPositionAvailableFunds() {
  const el = document.getElementById('ap-available-funds');
  if (!el) return;
  el.textContent = '로딩...';
  try {
    // 대시보드 잔액 카드 값 그대로 사용 (localStorage 캐시)
    const _re = document.getElementById('balance-mini-real');
    const _fr = document.getElementById('balance-mini-free');
    if (_re && _fr) {
      const real = _re.textContent;
      const free = _fr.textContent;
      el.innerHTML = `💰 여유 <strong class="text-green-400">${free} USDT</strong> ` +
        `(실 ${real} USDT lock) — 이 금액까지 = 사장님 최대 추가 가능!`;
    } else {
      el.textContent = '대시보드 재로드 후 확인';
    }
  } catch (e) {
    el.textContent = '조회 실패';
  }
}

function closeAddPositionModal() {
  document.getElementById('ap-modal').classList.add('hidden');
}

function toggleAddPositionLimitPrice() {
  const isLimit = document.getElementById('ap-type-limit').checked;
  document.getElementById('ap-limit-price-row').style.display = isLimit ? '' : 'none';
  updateAddPositionPreview();
}

async function loadAddPositionMarkPrice(symbol) {
  const el = document.getElementById('ap-mark-price');
  el.textContent = '로딩...';
  try {
    const data = await api(`/market/ticker?symbol=${encodeURIComponent(symbol)}`);
    el.textContent = data.price ? Number(data.price).toString() : '?';
    el.dataset.price = data.price || '';
    updateAddPositionPreview();
  } catch (e) {
    el.textContent = '조회 실패';
  }
}

function updateAddPositionPreview() {
  const amount = parseFloat(document.getElementById('ap-amount').value);
  const lev = parseFloat(document.getElementById('ap-leverage-display').textContent) || 1;
  const isLimit = document.getElementById('ap-type-limit').checked;
  const limitPrice = parseFloat(document.getElementById('ap-limit-price').value);
  const markPrice = parseFloat(document.getElementById('ap-mark-price').dataset.price);
  const refPrice = isLimit && limitPrice > 0 ? limitPrice : markPrice;
  const previewEl = document.getElementById('ap-preview');
  if (!amount || amount <= 0 || !refPrice || refPrice <= 0) {
    previewEl.textContent = '— 금액과 가격 입력 시 미리보기 표시 —';
    return;
  }
  const qty = (amount * lev) / refPrice;
  previewEl.innerHTML = `예상 수량: <span class="text-cyan-300 font-semibold">${qty.toFixed(4)}</span> ` +
    `@ ${refPrice} = <span class="text-yellow-300">${(qty * refPrice).toFixed(2)} USDT</span> 명목 ` +
    `(마진 ${amount} USDT × ${lev}x)`;
}

async function submitAddPosition() {
  const id = document.getElementById('ap-strategy-id').value;
  const amount = parseFloat(document.getElementById('ap-amount').value);
  const isLimit = document.getElementById('ap-type-limit').checked;
  const limitPrice = isLimit ? parseFloat(document.getElementById('ap-limit-price').value) : null;
  if (!amount || amount <= 0) {
    toast('추가 금액 (USDT) 을 입력하세요 (양수)', 'warning');
    return;
  }
  if (isLimit && (!limitPrice || limitPrice <= 0)) {
    toast('지정가 가격을 입력하세요 (양수)', 'warning');
    return;
  }
  // 🌟 2026-07-01 사장님 헌법 51 (옵션 A!): mode 라디오 선택 읽기!
  const modeReset = document.getElementById('ap-mode-reset');
  const mode = (modeReset && modeReset.checked) ? 'reset' : 'preserve';
  const modeLabel = (mode === 'reset')
    ? '🚀 신 진입 모드 (TP1 부터 다시!)'
    : '🛡 청산 방지 모드 (TP/SL 유지!)';
  const modeDescription = (mode === 'reset')
    ? '   = TP/SL 초기화 = TP1, TP2, ... 다시 자동!\n   = 신 평단 기준 단계별 익절!\n   = 사장님 가격 더 갈 거 예상 시 추천!'
    : '   = TP/SL 유지 = 옛 진행 계속!\n   = 평단만 개선 + 큰 qty 유지!\n   = 사장님 청산 위험 + 큰 qty 의도 시 추천!';
  const confirmMsg =
    `💉 포지션 추가 = ${amount} USDT ${isLimit ? '지정가' : '시장가'}!\n\n` +
    `🌟 선택 모드: ${modeLabel}\n${modeDescription}\n\n` +
    `📌 공통 동작:\n` +
    `   - qty 추가 + 평단 개선!\n` +
    `   - total_capital 증가!\n` +
    `   - SL 한도 자동 갱신!\n` +
    `   - current_stage 변경 X (= 단계 진행 X!)\n\n` +
    `💡 사장님 = 단계 추가 의도 시 = 다른 옵션!\n` +
    `   → 「✏️ 수정」 → 신 단계 capital + trigger 입력 →\n` +
    `   → 「↻ 설정만 수정」 = 신 stage_plans + 자동 진입!\n\n` +
    `✅ 진행하시겠습니까?`;
  if (!confirm(confirmMsg)) return;
  const body = {
    amount_usdt: amount,
    order_type: isLimit ? 'LIMIT' : 'MARKET',
    mode: mode,  // 🌟 헌법 51!
  };
  if (isLimit) body.limit_price = limitPrice;
  try {
    const btn = document.getElementById('ap-submit');
    btn.disabled = true;
    btn.textContent = '발송 중...';
    const resp = await api(`/strategies/${id}/add-position`, { method: 'POST', body });
    toast(`✅ ${resp.message || '포지션 추가 주문 발송됨'}`, 'success');
    closeAddPositionModal();
    refreshStrategies();
    // 🌟 2026-06-09 사장님 요청: 포지션 추가 시 = 즉시 잔액 갱신
    if (typeof loadBalance === 'function') loadBalance();
  } catch (err) {
    toast(`포지션 추가 실패: ${err.message}`, 'error');
  } finally {
    const btn = document.getElementById('ap-submit');
    btn.disabled = false;
    btn.textContent = '💉 진입';
  }
}
