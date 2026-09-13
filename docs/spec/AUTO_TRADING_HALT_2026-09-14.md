# ⛔ Fix 371 — 자동매매 전면 중단 · 사람이 만든 전략과 사람 버튼만 실주문 (2026-09-14)

## 사장님 지시 (verbatim)

> 모든 자동매매는 중단해줘

> 새전략 기본방식과 새전략 obv 자동만 가능하게 수동으로 전략을 만들수 있게 남기고 모든 자동매매 중단하고 가상으로만 매매하고 학습하고 손실이 발행하는 원일을 학습해서 수정할수 있게 기록해서 우리 자동매매에 적용할수 있게 자료를 만들어줘

## 배경

- 9/13 KOMAUSDT #4500 · 哈基米USDT #4483 (둘 다 「➕ 새 전략 (기존 방식)」) 에 **자동 수익 추가**(success_pyramiding) 300 USDT 가
  급등 막바지에 들어갔다. 미실현 −108 / −172 중 약 −91 / −134 가 추가분. 추가 뒤 손절(Fix 364)은 OBV 자동 가족에만 걸려 멈출 장치가 없었다.
- 9/14 06:1x KST 계정 #1 에 Kill-Switch(MANUAL) 를 켜 전면 정지. 그러나 Kill-Switch 는 **사람의 전략 생성·💉 추가까지** 막는다.
  → 이 Fix 로 「사람 것만 통과」를 만들고, 배포 뒤 Kill-Switch 를 해제한다.

## 무엇이 허용/차단되나 (중단 중)

| 경로 | 결과 |
|---|---|
| 「➕ 새 전략 (기존 방식)」「새 전략 (OBV 자동)」 생성 | ✅ 허용 (그 밖 템플릿 가족·자동 워커 생성은 ⛔) |
| 사람이 누른 버튼 — 「전략 시작」 · ▶ 다음 단계 · 💉 포지션 추가 | ✅ **어떤 전략이든 허용** (배포 전 사람 전략·손절 없는 포지션 방어) |
| 사람이 모달로 만든 전략(entry_origin=manual_modal)의 자동 진행 — 가격/OBV 다음 단계 · 예약 시작 | ✅ 허용 (모달 설정대로) |
| 그 밖 전략의 자동 1단계·다음 단계 (v219 사다리 · 볼밴 분할 · 관리 재진입 복제 · 배포 전 전략) | ⛔ 차단 |
| **자동 포지션 추가**(수익 추가·외부 전략·규칙 가족·급등 사다리) · 자동 시장가 단계(반전 워커) | ⛔ 항상 차단 |
| 청산 · TP 익절 · 손절 · 긴급 종료 | ✅ 그대로 (진입 함수가 아님) |
| 가상매매(paper_trading) · 그림자(shadow) 워커 · 학습 기록 | ✅ 그대로 (주문 없음) |

거래소에 진입 주문을 내는 경로는 `ExecutionService` 의 4개 함수뿐임을 전수 조사·반박 검증 A 로 확인했다
(`start_stage1` · `trigger_next_stage` · `enter_stage_at_market` · `add_position_now`; 워커 직접 발주·batchOrders 0건).
게이트는 4곳 모두 Kill-Switch 검사 바로 뒤, 주문·단계 정리(Fix 304)보다 앞에 있고, 전략 생성에도 있다.
사람 버튼은 호출 인자 `origin="manual"` 로 가른다 — 넘기는 곳은 `control.py`(전략 시작·▶)와 `lifecycle.py`(💉) 뿐 (AST 테스트로 고정). 기본값은 `auto`.

## 「사람이 만든 전략」 판정 = `strategy_instances.entry_origin` (alembic 0040)

- 생성 요청의 출처를 그대로 저장한다: 모달(POST /strategies) = `manual_modal`, 워커 = NULL. 복사·복제되는 경로 없음(반박 검증 A 확인).
- 🚨 `entry_profile` 은 쓸 수 없다 — 템플릿이 OBV_REVERSE 면 **누가 만들든** `obv_auto` 가 찍혀 관리 재진입 복제본도 같은 값이다.
- 소급: `entry_profile = 'legacy_manual'` 행만 `manual_modal` (그 표식은 모달 생성에서만 찍힌다 — 반박 검증 B 확인).
  **소급 안 되는 사람 전략**: 9/11(0039) 이전 모달 전략 전부 · 「새 전략 (OBV 자동)」 모달 전략 전부 · 예약 전략 일부 →
  사람 버튼(💉·▶·시작)은 되지만 **자동 단계 진행은 멈춘다**. 검사기 목록(템플릿·유형 표시)을 보고 사장님이 번호를 고르면
  `UPDATE strategy_instances SET entry_origin='manual_modal' WHERE id IN (...)` 를 보고드린 뒤 실행.

## 설정 (재시작 불필요)

| 키 | 값 | 비고 |
|---|---|---|
| `auto_trading_halt` | 행 없음 · 빈 값 · 읽기 실패 = **중단** / `0` = 옛 동작(자동매매 재개) | Claude가 정함 — 모르면 막는다. 지금은 DB 로만 바꿀 수 있다(화면 없음) |

## 워커 부작용 처리 (반박 검증 A/B)

- `managed_symbol_worker`: Kill-Switch 와 같게 판정 전에 멈춤 (안 그러면 일일 한도·쿨다운만 소비).
- `auto_reentry_worker`: 중단 차단이면 `REENTRY_FAILED` 로 영구 마킹하지 않고 상태 유지 (재개 뒤 재진입 기회 보존).
- `stage_trigger_worker`: 중단 차단이면 「[시스템 오류] Stage 자동 진입 실패」 알림·스택 로그 대신 화면 차단 사유만.
- 그 밖(success_pyramiding · external_strategies · surge_ladder · scheduled_entry): 주문 직전에서 막히고 경고 로그만 (상태 파손 없음 확인).
- 차단 메시지에 `kill-switch` 포함 → `realtime_reentry` 가 Kill-Switch 와 같게 분류(실패 마킹 안 함).

## 🚨 배포 전에 알아야 할 것

1. **운영 헤드는 7970a69** (9/14 확인). 이 브랜치는 **미배포 Fix 369(S1 130% 예약 · S2 가족 판정·워커 제한 · S3 화면·API 창구 분리)** 위에 있어
   **같이 올라간다.** Fix 369 는 9/13 반박 검증을 거쳤지만 운영 검사는 아직 — 배포 뒤 `verify_fix364_deploy.py` 도 PASS 확인.
2. **pull 과 restart 사이에 alembic 을 반드시 먼저.** api·scheduler 는 소스를 볼륨으로 쓰므로 restart(또는 컨테이너 자동 재기동) 순간 새 코드가 올라오고,
   0040 전이면 `entry_origin` 컬럼이 없어 전략 조회가 전부 실패한다. 아래 한 줄로 실행.
3. 이미 거래소에 걸린 진입 지정가는 게이트가 취소하지 않는다 (9/14 거래소 조회: 사장님 哈基米 2건뿐). 검사기가 DB 기준 목록을 보여준다.

## 배포 (사장님)

```bash
cd ~/binance-auto-trader/backend && git pull origin main && docker compose exec -T api alembic upgrade head && docker compose restart api scheduler
```

① 배포 직후에도 Kill-Switch 는 켜진 상태 = 여전히 전면 정지.
② 검사: `docker compose exec -T api python scripts/verify_fix371_halt.py` + `docker compose exec -T scheduler python scripts/verify_fix371_halt.py` + `python scripts/verify_fix364_deploy.py`.
③ 확인되면 화면 배너 「🔓 해제」 = 사람 전략·사람 버튼만 주문.
④ 자동 단계가 계속돼야 할 옛 사람 전략 번호를 알려주시면 `entry_origin` 표시.
⚠️ `alembic upgrade` 가 멈추면(잠금 대기) Ctrl+C 로 끊고 `docker compose restart api scheduler` 뒤 다시 upgrade.

## 되돌리기

- 자동매매 재개: `system_settings` `auto_trading_halt = 0` (재시작 불필요).
- 코드 되돌리기: 이 커밋 revert + `alembic downgrade 0039_si_entry_profile`.

## 알려진 한계 · 다음 작업 후보

- 중단 상태를 화면에 표시하지 않는다 — Kill-Switch 배너를 해제해도 자동 경로는 막혀 있다.
- 재개가 DB 직접 수정뿐 — 설정 화면 허용 목록에 넣을지는 사장님 결정.
- 자동 워커는 계속 돌며 판정 로그를 남긴다 (주문 직전에서 막힘).
- 손실 원인 학습·보고서는 `docs/learning/LOSS_CAUSE_LEARNING_2026-09-14.md`.
