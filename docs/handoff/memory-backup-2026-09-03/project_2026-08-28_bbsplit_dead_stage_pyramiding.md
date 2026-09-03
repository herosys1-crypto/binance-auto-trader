---
name: project_2026-08-28_bbsplit_dead_stage_pyramiding
description: 볼밴 3차가 -24%에 걸려 300 USDT가 영원히 미진입 + 피라미딩이 포지션 없는 전략에 시장가 진입해 단계 진행을 영구 차단 (Fix 195/196)
metadata: 
  node_type: memory
  type: project
  originSessionId: 9810b26c-b7e1-4349-8e91-83e3a14b072a
  modified: 2026-08-29T08:12:28.511Z
---

# 🚨 2026-08-28 볼밴 「죽은 3차」 + 피라미딩이 손실구간 재반응을 죽이고 있었다

사장님: "볼밴전략 분석 + 롱이 잘 안되는 원인" / "손실구간에서 다시 반응하거나 수익구간에서 포지션 추가를 검정해줘"

## 🚨 Fix 195 — 볼밴 3차(300 USDT)가 -7% 가 아니라 **-24%**

계산기를 직접 실행해 재현 (에이전트 주장 → 내가 독립 확인):
```
LONG  3차 = base × 0.95 × 0.80 = 기준선 -24.00%  (의도 -7%)
SHORT 3차 = base × 1.05 × 1.20 = 기준선 +26.00%  (의도 +7%)
2차까지 물린 평단의 손절가       = 기준선  -9.13%
```
**손절이 압도적으로 먼저 온다 = 계획 자본 600 중 300(절반)이 한 번도 진입된 적 없음.**
운영 DB 실측으로도 활성 3건 전부 `-24.01 / -24.01 / -24.03%` 확인.

원인 2겹:
1. `stages_config` 에 `last_stage_trigger_percent` 미전달 → 마지막 단계가
   `trigger_percents[2]=7` 을 **읽지도 않고** `DEFAULT_LAST_*_TRIGGER_PCT=20` 으로 떨어짐
2. **7 을 넣어도 안 고쳐진다** — `StrategyCalculator` 는 앵커를 직전 단계 가격에 이어붙이는
   **복리**라 `base×0.95×0.93 = -11.65%` = 여전히 손절(-9.13%)보다 뒤

🚨 **막으려고 만든 `check_no_dead_stage` 가 거짓 안심을 주고 있었다.**
자기 의도값(절대 기준)으로만 계산해 「정합성 OK」를 찍었다 — 계산기는 복리인데 검산은 절대 기준.

해법: `compounded_trigger_pcts()` 로 환산(LONG 3차 2.10526% / SHORT 1.90476%) +
`last_stage_*` 명시 + **DB 에 저장된 `trigger_price` 로 재검산**(`verify_stage_plans`),
죽은 단계면 **주문 전에** 전략을 STOPPED+archived 로 차단.
기존 활성 3건은 코드로 안 고쳐져서 사장님 승인 후 DB 직접 수정 → 전부 **-7.00%** 확인.

## 🚨 Fix 196 — 피라미딩이 「포지션 없는 전략」에 시장가 진입

후보 쿼리가 `status.in_(ACTIVE_LIKE)` + **잔량 조건 없음**.
`ACTIVE_LIKE` 는 「신규 진입을 **차단**해야 할 상태」 집합이지 「포지션 보유」 집합이 아니다.
포지션 없는 상태가 셋 포함: `LIQUIDATED_WAITING_RETRY` / `STOPPING` / `MANUAL_CLEANUP_REQUIRED`.

청산 시 `stream_service` 는 qty·unrealized 만 0 으로 하고 **`avg_entry_price` 를 남긴다**
→ 옛 평단 + 살아있는 mark_price 로 ROI 통과 → `add_position_now(mode="reset")` 가
① 시장가로 **새 포지션을 열고** ② status 를 `STAGE{n}_OPEN` 으로 덮어쓴다.

💀 `stage_trigger_worker` 는 재진입을 `status=="LIQUIDATED_WAITING_RETRY"` 일 때만 진행
→ **한 번 덮이면 계획된 다음 단계가 영구 차단** = 사장님이 원하신 「손실구간 재반응」이 죽는다.
`MANUAL_CLEANUP_REQUIRED` 였다면 「확인 필요」 표식까지 조용히 지워진다.

⚠️ **내 Fix 185 의 전제가 깨져 있었다** — 「`add_position_now` 라 건수가 안 는다」는 이유로
상한 게이트를 뺐는데 이 세 상태에선 **실제로 새 포지션이 열린다.**

**Fix 196-2**: `pyramid_count:{symbol}:{side}` + 7일 TTL + **삭제 코드 없음**.
전략 id 가 키에 없어 A 전략이 2회 쓰고 끝나면 같은 심볼의 B 전략이 **첫 진입부터 탈락**.
(어제 본 `max_pyramid_count=3` 이 이것.) 반대로 7일 지나면 조용히 리셋 = 평생 상한도 아님.
→ `pyramid_count:sid:{id}` = 「이 포지션에 최대 2회」라는 원래 의미로.

## 📊 데이터 결손 — 「학습」이 애초에 불가능했다

| 결손 | 실측 |
|---|---|
| `StrategyInstance.started_at` | **1160건 전부 NULL** — 채우는 코드가 없음. 보유시간 측정 불가 |
| `TradeLearningRecord.close_reason` | **항상 NULL** — `learning_sync_worker:203` 이 없는 컬럼을 `getattr` |
| `COMPLETED` 의 `stopped_at` | **미기록** → 기간 집계에서 성공 거래 234건(+23,302) 통째 누락 |
| `max_profit_pct` | 7일 종료건 138 중 **85건(62%) NULL** |

🚨 **이 함정에 내가 직접 빠졌다** — `stopped_at` 으로 걸러 「LONG 승률 15.2% / 7일 -3976」이라고
보고했는데, 실제로는 `COMPLETED` LONG 71건 +6,008 / SHORT 163건 +17,294 가 빠진 숫자였다.
**손실 건만 세어놓고 전체인 양 말했다.**

## ✅ Fix 197~201b — 학습 결손 수리 + 차단 사유를 화면에

**Fix 197** (매매 무변경 8건): `on_exit` 입구가 `status == "STOPPED"` **단일 문자열**이라
익절 완주(COMPLETED)가 두 번 걸러졌다 → `TERMINAL_STATUSES` + `coalesce(stopped_at, updated_at)`.
`learning_sync_worker` 의 활성 조회가 **`STAGE_1_OPEN`(언더스코어) 오타**라 5개월간
`entry_context` 가 전건 `{}` 였다 → 상수에서 유도 + backlog 오염 방지 fresh 가드.
`close_reason` 은 **RiskEvent 로 유도**(`resolve_close_reason`) — **과거분에 소급된다.**
승패를 `pnl_usdt` 기준으로(COMPLETED 는 `total_capital=0` 이라 `pnl_pct` 가 0).

**Fix 198** (사장님 결정): `time_reverse_exit_worker`(4시간 강제청산)는
`started_at.isnot(None)` 필터 때문에 **배포 후 한 번도 동작한 적이 없었다.**
→ 「조건 때문에 우연히 안 도는」 상태가 가장 위험하므로 **명시적으로 OFF**(스케줄러 등록 제거).
`started_at` 은 체결 순간에 기록(학습 전용). **과거 백필 금지** — 열린 포지션이 대량청산된다.

**Fix 199**: `/api/*` 응답에 **캐시 지시가 아예 없었다** → `no-store` 명시.
오류 알림이 **저장 버튼 아래**(화면 밖)라 로드 실패를 볼 수 없었다 → 카드 맨 위로.
실패했는데 「불러오는 중…」이 계속 떠 있었다(글자가 거짓말) → 「불러오지 못함」.

**Fix 200/201/201b**: #1637 AKEUSDT SHORT 가 트리거를 넘겼는데 안 들어간 이유 =
`Fix114 정점 미확인 (지표 꺾임 1/2)`. 게이트는 의도대로였지만 **사유가 화면에 없어서**
사장님이 나에게 물어야만 알 수 있었다 → **차단 사유 배지 + 상세 모달 + 「🎯 지정가 우선」 토글**
(`GET /strategies/block-reasons`, `POST /strategies/{id}/peak-bypass`, Redis 7일 TTL).
Fix55 경로는 `_rev_detail` 을 쥐고도 안 넘겨 표가 비었다 → 변환해 전달.

🚨 **에이전트가 「배포 차단급」이라 한 캐시버스터 지적은 실행으로 반증했다** —
Fix 190 이 `?v=` 를 내용 해시로 교체하므로 위험 없음(`ede76399e100`/`cda815a092ce`).

## ⚠️ 내가 이번에 틀린 것

- 「트레일링이 `tp1_pct_override` 미설정으로 죽어 있다」 → **틀림.** 종료건 397개 전부 `TP1=15.00`.
- 「LONG 승률 15.2%」 → **틀림.** 표본이 손실 건만이었다.
- Fix 185(상한 게이트 제거)의 전제가 세 상태에서 성립하지 않았다 → Fix 196 으로 보완.

- 「Fix 200 예외가 필요하다」고 판단하기 전에 `retry_after_liquidation_enabled` 를
  **스크린샷의 파란 강조 박스를 체크 표시로 오독**해 원인이라고 단정했다 (실제 False).
- 🚨 **`index.html` 을 0바이트로 날렸다** — 파이썬 문자열에 이모지를 `\uXXXX` 로 넣어
  짝 없는 서로게이트가 생겼고, `write_text` 는 **쓰기 전에 파일을 비운다.**
  `git checkout` 으로 완전 복구(213,172B). **통짜 덮어쓰기 금지, append 나 편집 도구를 쓸 것.**

## 헌법 150~163

**150** 계산기가 앵커를 **이어붙이는지(복리)** 절대 기준인지 확인하고 값을 넣을 것
**151** 안전 검산은 **실제 저장된 값**으로 다시 할 것 — 의도값 검산은 자기 자신만 증명한다
**152** 「차단 대상 집합」을 **「보유 판정 집합」으로 재사용하지 말 것** (`ACTIVE_LIKE`)
**153** Redis 카운터의 **키 범위(심볼/전략/계정)가 그 카운터의 의미와 일치**하는지 볼 것
**154** 「종료」 조회를 **status 문자열 하나로 하지 말 것** — 이긴 거래가 빠진다
**155** 상태 문자열을 하드코딩하지 말고 **상수에서 유도**할 것 (오타가 5개월을 먹었다)
**156** 기록 결손 수정이 **매매 동작을 켜지 않는지** 확인할 것 (`started_at` → 4시간 강제청산)
**157** 「조건 때문에 우연히 안 도는」 기능은 **명시적으로 끌 것** — 가장 위험한 상태다
**158** **API 응답에 캐시 지시를 반드시 명시**할 것 (없으면 브라우저·프록시가 대신 정한다)
**159** 실패한 상태를 **「진행 중」으로 표시하지 말 것** (글자가 거짓말을 한다)
**160** 오류 알림은 **사용자가 보는 자리**에 둘 것 (저장 버튼 아래 = 화면 밖)
**161** 차단을 기록했으면 **화면에 보여줄 것** — 기록만 하면 없는 것과 같다
**162** 고정 경로는 **`/{id}` 파라미터 경로보다 먼저 등록**할 것 (아니면 422)
**163** 에이전트 지적도 **실행으로 확인**할 것 — 「배포 차단급」이 사실이 아닐 수 있다

## ⚠️ 배포 함정 (또 겪음)

`git pull` 이 브랜치 ref 만 받아오고 **`Already up to date`** 를 찍는다 = **PR 미머지**.
`git log --oneline -3` 로 해당 커밋이 main 에 있는지 확인해야 한다.

관련: [[project_2026-08-28_failoff_settings_screen]] [[project_2026-08-27_pyramid_bbsplit_tp20]]
