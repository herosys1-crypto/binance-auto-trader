---
name: project_2026-08-31_last_stage_trigger_dual_storage
description: 마지막 단계 트리거가 두 곳에 저장돼 화면 30% / 엔진 120% 로 갈라진 사고 (#1873) 와 Fix 234
metadata:
  type: project
---

# 🚨 2026-08-31 «화면이 거짓말한다» 2번째 유형 — 마지막 단계 트리거

사장님 보고: "처음에 500 1000 1500 단계별 세팅값이였어" + 수정 모달 스크린샷
(2단계 트리거 **30**, 2단계 진입가 **0.14919**).
DB 의 단계 계획은 **0.252472** (= +120%). **화면과 엔진이 다른 값을 쓰고 있었다.**

## 근본 원인 — 같은 칸이 두 곳에 저장된다

    stages_config["trigger_percents"][last]      <- 화면(모달)이 읽고 쓴다
    stages_config["last_stage_trigger_percent"]  <- 엔진(calculator)이 읽었다

세 겹이 겹쳐 잔재가 영구화됐다:

1. `strategy_calculator.py` `if is_last: pct = last_pct` — 배열을 **아예 안 봄**
2. `cm-collectors.js` `_collectDirectInputs` 가 배열 마지막 칸을 **null 로 지움**
3. `cm-preview.js` 는 null 이면 **전송 안 함** + `control.py` 는 null 이면 **갱신 안 함**
   → 한 번 들어간 옛 값이 **지워질 방법이 없다**

## Fix 234 (main 308d601)

- calculator: 마지막 단계도 `trigger_percents[i]` 가 있으면 **그것이 이긴다** + 불일치 시 warning
- collectors: 마지막 칸을 **더 이상 지우지 않는다** = 화면값 = 저장값
- control.py PATCH /settings: 배열 마지막 값으로 `last_stage_trigger_percent` **잔재 자동 소거**
- 가드 8건 (`test_last_stage_trigger_single_source.py`) — 음성 대조군 + 소스 가드 3종

## 함께 확인된 것 (버그 아님 / 잔재)

- `instance.total_capital`(6000, 실제 투입 누적) vs `template.total_capital`(3000, 계획) = **설계상 다름**
  (`control.py:443` 사장님 사상 / `lifecycle.py:69` 가 추가 시 누적)
  → 다만 **한 화면이 두 분모를 섞어 쓴다** (`1051/6000` 옆에 `-18.63% = -558.88/3000`) = 미수정
- 템플릿 `stage1~3_capital` 컬럼(500/1000/1500) vs `stages_config`(2칸) 불일치는
  `_resolve_stages_config` 가 JSON 을 우선하므로 **런타임 무해**, 표시용 잔재
- 단계 수 감소는 `new_n = len(payload.capitals)` 로 **의도된 동작** — 빈 칸으로 저장하면 그 단계가 삭제된다

## 교훈

「화면 = 진실」이 아니다. 저장 위치가 둘이면 **반드시 갈라진다** (헌법 6).
[[project_2026-08-28_failoff_settings_screen]] 과 같은 계열이고,
[[feedback_measure_before_hypothesis]] 대로 **코드 대조**로만 잡혔다.

⚠️ #1873 의 기존 단계 계획 row 는 자동으로 안 고쳐진다 —
배포 후 「↻ 설정만 수정」을 눌러야 재계산된다.

## Fix 235 — 도달 불가 단계가 강제손절을 영구히 잠갔다 (같은 사고의 뒷부분)

`#1873` 실측: force_sl **5%** 인데 미실현 **-735**. v130 게이트가
「다음 단계 남으면 손절 보류」로 잠그고 있었는데, 그 2단계 트리거가
**현재가의 10.8배**(도달 시 ROI **-958%**) = 살아서 도달 불가.

    손절 -> 단계가 남아서 잠김 / 단계 -> 도달 불가로 안 열림 => 청산까지 보유

판정은 **임의 상수가 아니라 산술**: 그 단계 도달 시 ROI 가 **-100% 이하**면
증거금이 이미 다 사라진 뒤라 거래소 청산이 먼저 온다 = 증명 가능한 도달 불가.
정상 물타기(-20/-50/-80%)는 영향 없음 — **실측으로 대상 1건뿐**임을 확인했다.

🛡 **기본값 OFF + 예고 warning 로그**로 배포(Fix 198 의 교훈).
사장님이 대상 집계(1건, -735.36)를 보고 직접 켜셨다:
`force_sl_unlock_unreachable_stage = true` (재시작 불필요, 다음 사이클 반영).

### 진단 순서가 유효했다 (재사용할 것)
관문을 **하나씩 읽기 전용으로 찍는** 스크립트가 결정적이었다 —
status / current_position_qty / enabled·threshold / mark_price / is_force /
retry·split 분기 / stage n/N / 다음단계 ROI. 로그가 비었을 때 추측 대신 이걸 돌렸고,
원인은 「재시작 직후라 사이클이 안 돎」이었다. [[feedback_measure_before_hypothesis]]
