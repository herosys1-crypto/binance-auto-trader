---
name: 2026-08-26-fix113-fix114-stage-progression
description: 🎯 단계별 자동 진입이 안 되던 2대 원인 (Fix 113/114) — trigger_price 게이트가 모드 분기보다 먼저 / 24h 절대 필터가 마틴게일 2단계 영구 차단. 헌법 91~93.
metadata: 
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-08-26T06:08:10.252Z
---

# 단계별 자동 진입이 진행되지 않던 문제 (2026-08-26)

**사장님 보고**: "새전략 기본방식 / 새전략 OBV 자동 단계별 진입이 진행되지않아"

진단 열쇠 = 워커가 Redis 에 남기는 차단 사유 (헌법 8):
```bash
docker compose exec redis redis-cli --scan --pattern 'stage_trigger_block:strategy:*' \
  | while read k; do printf "%s = " "$k"; docker compose exec -T redis redis-cli GET "$k"; done
```

## 🎯 Fix 113 (`536c404`) — 게이트 순서 역전

`stage_trigger_worker.py:369` 의 `if not next_plan.trigger_price: continue` 가
**모드 분기(L427)보다 58줄 먼저** 실행됨 → 가격 트리거를 **애초에 안 쓰는** 3개 모드 영구 차단:

| 모드 | 실제 기준 | 옛 결과 |
|---|---|---|
| `OBV_REVERSE` | OBV 신호 (가격 무관) | 차단 |
| `LIQUIDATED_WAITING_RETRY` | 청산가 기준 (가격 무관) | 차단 |
| `LIQUIDATION_BUFFER` | 청산가 −5% | 차단 (**산출 코드 자체가 없었음**) |

- 워커가 스스로 `"LIQUIDATION_BUFFER 미구현"` 이라고 기록 중이었음
- 주석엔 `trigger_price=None,  # 청산가 산출 시점에 채움` 인데 **그 코드가 존재하지 않음**
- ⚠️ `Decimal("0")` 도 falsy → `trigger_price=0` 도 같이 막힘
- **fix**: 모드 판정을 게이트 앞으로 이동 + LIQUIDATION_BUFFER 산출 구현
  (SHORT = 청산가 ×(1−buf%), LONG = ×(1+buf%); `Position.liquidation_price` → `last_liquidation_price`)

## 🎯 Fix 114 (`23277b1`) — 24h 절대 필터가 마틴게일을 영구 봉쇄

실측 차단 기록이 **단 하나**였고 그게 전부를 설명:
```
#1488 SHORT stage=2 = "Fix55 24h 필터 차단 (chg=+153.00%)"
```

`_check_stage_24h_filter`: `SHORT + 24h ≥ +15% → 무조건 차단`

**왜 잘못됐나**
1. **헌법 68** = 헌법 64(급등 반대매매 금지)의 **예외**가 바로 사장님 정점 SHORT.
   **헌법 72** = "급등해서 볼밴 상단돌파 했을때 마틴게일로 진입해야 확실한 수익" → 영구 봉쇄됨
2. 이건 신규 진입이 아니라 **이미 열린 포지션의 계획된 2단계**.
   막으면 물타기 없이 1단계만 물린 채 방치 = **진입 안 한 것보다 나쁜 상태**
3. 24h 숫자 하나로는 「아직 오르는 중」과 「정점 지나 꺾임」을 구별 못 함

**fix**: 24h 절대 차단 → `confirm_peak`(15m 반복 + 지표 꺾임) 로 교체.
24h 는 참고값으로 계속 조회, +15% 초과인데 정점 확인되면 **「헌법 68 예외 발동」 WARNING 명시**.
(B) 지표 반전 STRICT(2단계 2/3, 3단계+ 3/3)는 **그대로 유지** → 완화가 아니라 정확도 교체.

## 🚨 헌법 신설

**헌법 91: 공통 게이트는 「모드 분기」보다 뒤에 둘 것!**
- 모드마다 필요한 전제가 다르다. 앞에 두면 그 값을 안 쓰는 모드까지 죽는다
- 조건 추가 시 「이 조건이 필요 없는 모드가 있는가?」를 먼저 물을 것

**헌법 92: 「신규 진입 필터」를 「진행 중 포지션」에 그대로 쓰지 말 것!**
- 진입 금지 조건 ≠ 단계 진행 금지 조건
- 계획된 마틴게일을 막으면 1단계만 물린 최악 상태가 된다

**헌법 93: 차단은 반드시 사유를 남길 것 — 그게 유일한 진단 수단!**
- `stage_trigger_block:strategy:{id}` (TTL 600s) 하나로 이번 두 원인을 다 찾았다
- 새 게이트를 넣을 때 `_record_block_reason` 을 같이 넣지 않으면 다음에 못 찾는다

## 관련
- [[2026-08-26-fix111-fix112-concurrent-cap]] (confirm_peak = Fix 111)
- [[2026-08-26-stop-switch-broken]] (헌법 83~85)
- [[2026-06-22-stage-trigger-markprice-silent-block]] ⚠️ 그 노트의 "v51 미배포" 는 **오래됨** — 이미 배포돼 있음
