/**
 * Create-Modal — TP/SL/Capital input collectors (Phase 3 단계 3a, 2026-05-14).
 *
 * create-modal 의 form 입력 → backend payload object 변환 helper 들.
 * 모두 DOM 만 읽음 (cmState 읽지/수정 X) → 가장 격리된 helper.
 *
 * 함수:
 *   - _collectDirectInputs()  : 단계별 capital/trigger/additional_margin 배열 수집
 *   - _collectTpSl()           : TP1~10 percent/qty_ratio + SL + crisis_max_loss_threshold
 *   - _defaultLeverageForSide(side) : SHORT=2, LONG=2 default leverage (2026-05-15 사용자 요청 — 롱도 2x)
 *
 * 외부 의존성: 없음 (pure DOM 읽기만).
 *
 * 사용처:
 *   - main create-modal (직접 호출)
 *   - multi-symbol.js (submitCreateMulti 에서 _quick_ template 자동 생성 시)
 *   - template-save.js (saveAsTemplate 에서 direct 모드 시)
 */

function _collectDirectInputs() {
  const caps = [];
  const triggers = [];
  const additionalMargins = [];
  // 2026-06-03 사장님 사상 정확 구현: 빈 단계 자동 압축 + trigger 누적.
  // "3단계가 비워져있어도 4단계가 있으면 4단계가 3단계가 되어 한단계식 당기면 되고
  //  3단계 진입금액이 없어도 조건에 10있으면 조건만 적용되고 다음단계에 진입가격에 10%가
  //  변경이 되면 다음 단계진입해야 해"
  //
  // 동작:
  //   - 빈 자본 단계 → skip (압축)
  //   - 빈 단계의 trigger % 는 다음 채워진 단계의 trigger 에 누적
  //   - 결과: 채워진 단계만 1, 2, 3, ... 로 backend 에 전송
  //
  // 예시:
  //   입력  cap-1=50 / cap-2=50 (+10%) / cap-3=빈 (+10%) / cap-4=100 (+10%) / cap-5=150 (+10%)
  //   변환  [50 (IMMED), 50 (+10%), 100 (+20% — cap-3 의 +10% + cap-4 의 +10% 누적), 150 (+10%)]
  let pendingTriggerPct = 0;  // 누적된 빈 단계의 trigger %
  for (let i = 1; i <= 10; i++) {
    const v = document.getElementById('cm-cap-' + i).value;
    const valEmpty = (v === '' || v === null || v === undefined || Number(v) === 0);
    const tVal = document.getElementById('cm-trg-' + i) ? document.getElementById('cm-trg-' + i).value : '';
    const tNum = Number(tVal) || 0;

    if (valEmpty) {
      // 빈 자본 단계 — trigger 가 있으면 다음 채워진 단계에 누적
      if (i > 1 && tNum > 0) {
        pendingTriggerPct += tNum;
      }
      continue;  // 자본 없는 단계는 skip (자동 압축)
    }

    // 자본 있는 단계 — 누적 trigger 합산 후 push
    caps.push(String(v));
    if (caps.length === 1) {
      // 첫 채워진 단계 = 새 1단계 (IMMEDIATE)
      triggers.push(null);
      pendingTriggerPct = 0;  // 첫 단계는 누적 무시
    } else {
      // 2 단계 이상 — 원 trigger + 빈 단계 누적 trigger
      const totalT = tNum + pendingTriggerPct;
      triggers.push(totalT > 0 ? String(totalT) : null);
      pendingTriggerPct = 0;  // 사용 후 리셋
    }
    // 2026-05-11 (사용자 요청): 단계별 추가 증거금. 빈값/0 이면 null (= 추가 안 함).
    const addEl = document.getElementById('cm-add-margin-' + i);
    const addV = addEl ? addEl.value : '';
    additionalMargins.push((addV === '' || Number(addV) === 0) ? null : String(addV));
  }
  // 사용자 기획 변경 (2026-04-30): 마지막 단계도 사용자 입력값 (예: 20%) 으로 진입.
  // 이전엔 LIQUIDATION_BUFFER 로 null 로 비웠으나, 이제는 PRICE_UP_PCT/PRICE_DOWN_PCT
  // 의 % 값으로 분리 전달. 백엔드 기본 mode = PRICE_UP_PCT (SHORT) / PRICE_DOWN_PCT (LONG).
  let last_stage_trigger_percent = null;
  if (triggers.length > 1) {
    const last = triggers[triggers.length - 1];
    last_stage_trigger_percent = last;  // 사용자 입력값 (null 이면 backend 기본 20%)
    triggers[triggers.length - 1] = null;  // trigger_percents 배열에선 last 는 무시되므로 null
  }
  return { capitals: caps, trigger_percents: triggers, additional_margins: additionalMargins, last_stage_trigger_percent };
}

function _collectTpSl() {
  // 2026-05-06: TP1~10 동적 (10단계 익절 확장).
  // TP1~3 = 필수 (default 10/15/20 + 25%/25%/25%), TP4~10 = 선택 (null 이면 미사용).
  const get = id => document.getElementById(id) ? document.getElementById(id).value : '';
  const v = (raw, def) => raw && Number(raw) > 0 ? raw : def;
  const opt = raw => raw && Number(raw) > 0 ? raw : null;
  const _defaults = {
    1: ['10', '25'], 2: ['15', '25'], 3: ['20', '25'],
  };
  const out = {
    stop_loss_percent_of_capital: v(get('cm-sl-pct'), '100'),  // 🌟 2026-06-13 사장님: 100 default
  };
  for (let n = 1; n <= 10; n++) {
    const pct = get(`cm-tp${n}-pct`);
    const qty = get(`cm-tp${n}-qty`);
    if (n <= 3) {
      out[`tp${n}_percent`] = v(pct, _defaults[n][0]);
      out[`tp${n}_qty_ratio`] = v(qty, _defaults[n][1]);
    } else {
      out[`tp${n}_percent`] = opt(pct);
      out[`tp${n}_qty_ratio`] = opt(qty);
    }
  }
  // 2026-05-14 (사용자 결정): 크라이시스 모드 비활성 — 「손절만 적용」.
  // dropdown UI 제거됨 → 모든 새 strategy 자동 -100 (비활성) 전송.
  // -100 sentinel 은 backend 의 risk_service.evaluate_crisis_mode 에서 비활성으로 처리.
  out.crisis_max_loss_threshold = "-100";
  return out;
}

function _defaultLeverageForSide(side) {
  // 2026-05-15 사용자 요청: SHORT/LONG 둘 다 2x default (이전 LONG=1 → 사용자 거의 항상 직접 2 로 변경하는 패턴 발견)
  return 2;
}
