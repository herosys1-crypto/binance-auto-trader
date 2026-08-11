# ⚔️ Entry Team = 진입 팀

## 미션
사장님 세팅에 따라 = 정확 진입!

## Agents

### 1. `stage_trigger_agent`
- 목적: 단계별 자동 진입 (가격 도달!)
- 기존 워커: `app/workers/stage_trigger_worker.py`
- 관련 헌법: C01, C02, C07

### 2. `retry_reentry_agent` (v131 신!)
- 목적: 청산 후 자동 재진입!
- 기존 워커: `stage_trigger_worker.py` (LIQUIDATED_WAITING_RETRY 분기!)
- 관련 헌법: C09 (순차 진입!)

### 3. `market_entry_agent`
- 목적: 시작가 없으면 = MARKET 진입!
- 기존 로직: `execution_service._place_stage_entry_order`
- 관련 default: `market_entry_default`

### 4. `manual_entry_agent`
- 목적: 「▶ 강제 진입」 (사장님 클릭!)
- 기존 endpoint: `POST /strategies/{id}/manual-trigger`

## 팀 간 협업
- 진입 완료 → **Monitoring Team** = 감시 시작!
- 손실 감지 → **SL Team** = 판단!
- 재진입 대기 → **Alert Team** = 사장님 인지!
