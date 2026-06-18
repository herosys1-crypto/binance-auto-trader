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
  // 현재가 표시 + 미리보기 갱신
  loadAddPositionMarkPrice(symbol);
  document.getElementById('ap-modal').classList.remove('hidden');
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
  // 🚨 2026-06-19 사장님 critical fix: SYNUSDT 사건 영구 인지!
  // 사장님: "수동으로 설정한 3단계 4단계가 실행되지 않은거야"
  // 사장님 = 「💉 포지션 추가」 = 단계 진행 의도 = But 시스템 = qty 추가만!
  // = 사장님 사상 ↔ 시스템 = 불일치 = SYNUSDT Liquidation -585 USDT 손실!
  // = 신 fix: 사장님 사전 인지 명확 안내!
  const confirmMsg =
    `💉 포지션 추가 = ${amount} USDT 시장가 진입!\n\n` +
    `🚨 critical 사전 인지 (= 사장님 SYNUSDT 사건!):\n` +
    `   = 즉시 qty 추가 + 평단 개선!\n` +
    `   = But 단계 진행 X = 자동 진입 trigger 영향 X!\n` +
    `   = current_stage 변경 X = stage_plans 추가 X!\n\n` +
    `💡 사장님 = 단계 추가 의도 시 = 다른 옵션!\n` +
    `   → 「✏️ 수정」 → 신 4단계, 5단계 capital + trigger 입력 →\n` +
    `   → 「↻ 설정만 수정 (시작가 유지)」 클릭!\n` +
    `   = 신 stage_plans 추가 + 자동 진입 작동!\n\n` +
    `📊 사장님 SYNUSDT 사건:\n` +
    `   - strategy = 2단계만 (capitals = [200, 600])\n` +
    `   - 사장님 = 「💉 포지션 추가」 × 2 = 단계 X = trigger 미도달!\n` +
    `   - 결과 = Liquidation = -585 USDT 손실! 🚨\n\n` +
    `✅ 진행하시겠습니까? (= 즉시 시장가 진입!)`;
  if (!confirm(confirmMsg)) return;
  const body = {
    amount_usdt: amount,
    order_type: isLimit ? 'LIMIT' : 'MARKET',
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
