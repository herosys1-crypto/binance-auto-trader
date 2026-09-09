# 「심볼 관리 재진입」 (Fix 365, 2026-09-09) — 첫 진입 실패 → 청산 → 관리 명부 → 신호에 10 USDT 재진입 (10회) → 성공하면 추가

> 사장님 (verbatim): "이렇게 하자 첫 진입에 실패하면 청산하고 재진입 모니터링으로 특별 관리해서 우선 포지션 진입할 심볼로 관리를 하고 재진입 모니터링 후 다시 10usdt로 진입해서 성공하면 포지션추가로 가는걸로 해줘 10usdt로 성공할때까지 10번까지 반복해줘 그리고 한번하락하고 성공하면 다시 급반등하는것도 많이 이것조 잡아서 롱으로 그리고 다시 하락하는 시점을 잡을 수 있게 실시간 감시 모니터링을 해줘 그렇게 개발 가능할까? 포지션 롱이등 숏이든 실패하면 재진입 모니터링관리와 모니터링후 포지션 진입을 하는거야 한번 선택한 종목을 지속적으로 분석하면서 관리 재진입하는거야"

## 0. 한 줄
사장님이 고른 심볼(OBV 자동 모달로 만든 것)은 **관리 명부**에 올라간다. 10 USDT 첫 진입이 지면 **전량 청산**하고, 워커가 1분마다 롱·숏 **양방향** 신호를 보다가 신호가 뜨면 **다시 10 USDT** 로 들어간다. 이기면(이익 지속·지표 확실) 지금 피라미딩(300 × 최대 2회)으로 간다. 연속 실패 **10회**면 명부에서 내린다(성공하면 0 으로 되돌림). 워커는 **새 심볼을 스스로 고르지 않는다**.

## 1. 규칙

| # | 상황 | 시스템이 하는 일 | 근거 코드 |
|---|---|---|---|
| 1 | 사장님이 「📊 새 전략 (OBV 자동)」로 10/300/600/600 인스턴스 생성 | 그 심볼이 관리 명부에 오른다(종료되는 순간 등록, 시도 0) | `managed_symbol_worker.register_closed_instances` |
| 2 | 10 USDT 가 **이익** → 이익 지속 + 지표 확실 | 피라미딩 300 × 최대 2회, 추가 뒤 손절 −5% (Fix 364) | `success_pyramiding_worker` |
| 3 | 10 USDT 가 **손실** → 손절선(인스턴스 −25%, 추가 뒤 −5%) | **전량 청산** (프로브 모드: 손실 구간 300/600 단계 없음, 잔량 10 유지 없음) | `obv_loss_ladder_mode=probe` → `tp_sl_orchestrator._has_next_stage` False + 정리(TRIM) 생략, `stage_trigger_worker` OBV 분기 진입 없음 |
| 4 | 청산된 인스턴스 | **종료 사유**로 센다: 시스템 손절(FORCE_SL/SL/좀비 강제정지, 프로브 전량 청산 마커) → 연속 실패 +1 / 익절(TP·트레일링·수동 익절·COMPLETED) → 성공 +1, 연속 실패 0 / **사장님 ⏸정지·외부 청산·사유 불명 → 세지 않음**(사장님이 버린 심볼을 되살리지 않는다) | `close_outcome` + `apply_closed_instance` |
| 5 | 명부 심볼(WATCHING) 1분마다 | 롱·숏 **둘 다** 운영 진입 로직(`check_stage_entry_signal` = OBV 게이트 + 15분 정점/저점 확인 + 진입창) 판정. 사유는 DB(`last_reasons`)와 화면에 남김 | `managed_symbol_worker` |
| 6 | 한쪽만 신호 + 그 심볼에 우리 포지션 없음 + 슬롯·일일 한도 OK | 같은 템플릿(10/300/600/600)으로 새 인스턴스 → 1단계 **시장가 10 USDT** | `StrategyService.create_strategy_instance` + `ExecutionService.start_stage1` |
| 7 | 양쪽 동시 신호 | 보류(사유 기록). 다음 사이클 다시 | `decide_entry` |
| 8 | 연속 실패 10회(설정 `managed_symbol_max_attempts`) | EXHAUSTED — 명부에 남되 진입 없음. 화면 「↺ 초기화」로 다시 | API |
| 9 | 신호가 7일(설정 `managed_symbol_idle_release_days`) 동안 한 번도 없음 | RELEASED (자동 해제) | worker |
| 10 | 사장님이 직접 | 명부에 심볼 추가 / 초기화 / 해제. **해제(RELEASED)는 끈적인다** — 그 뒤 인스턴스가 종료돼도 자동으로 되살아나지 않고, 사장님이 「➕ 추가/↺ 초기화」할 때만 다시 감시 | `/api/v1/managed-symbols` + 화면 카드 |
| 11 | 재진입 시도(성공·실패 무관) | 일일 카운트 +1, 그 심볼 15분 쿨다운 — 실패 시도가 1분마다 반복되지 않게. Kill-Switch ON 이면 사이클 전체 생략 | worker |
| 12 | 프로브 모드의 OBV 인스턴스 | 2단계 이후 계획(300/600/600)은 130% 예약에서 뺀다(나가지 않는 단계) | `capital_calculator.ladder_reserves_untriggered` |

「한번 하락하고 성공하면 급반등 → 롱, 다시 하락 → 숏」 = 5·6 이 양방향이라 그대로 된다: SHORT 성공 뒤 저점/반전 신호가 뜨면 LONG 10, 그 뒤 정점 신호가 뜨면 SHORT 10.

## 2. 설정 (전부 system_settings, 행 없으면 기본)

| 키 | 기본 | 뜻 | 정한 사람 |
|---|---|---|---|
| `obv_loss_ladder_mode` | `probe` | `probe` = 손실이면 청산·재진입(이 문서) / `ladder` = 오늘 낮 Fix 364 방식(손실 구간 300/600 단계) | 사장님 (이 지시) |
| `managed_symbol_enabled` | 1 | 워커 감시·등록 | 사장님 |
| `managed_symbol_entry_enabled` | 1 | 신호에 10 USDT 실제 진입 | 사장님 |
| `managed_symbol_max_attempts` | 10 | 연속 실패 상한 | 사장님 |
| `managed_symbol_daily_entry_limit` | 10 | 하루 재진입 상한(KST) | Claude가 정함 |
| `managed_symbol_max_symbols` | 20 | 명부 WATCHING 상한 | Claude가 정함 |
| `managed_symbol_idle_release_days` | 7 | 신호 없이 이 일수 지나면 자동 해제 | Claude가 정함 |
| `managed_symbol_allow_hedge` | 0 | 같은 심볼 반대 방향 포지션이 있을 때도 진입 | Claude가 정함 |
| `managed_symbol_entry_cooldown_sec` | 900 | 한 심볼 재진입 시도 뒤 다음 시도까지(실패 시도 반복 방지) | Claude가 정함 |
| (재진입 금액) | 템플릿 1단계 | 사장님이 모달에 넣은 1단계(10 USDT) 그대로 — 별도 설정 없음 | 사장님 「10 USDT」 |

기존 상한도 그대로 적용: 동시보유 상한(`position_limit.check_position_slot`), 심볼 제외 목록(BTC/ETH 계열), API ban, 양방향 실패 blocklist.

## 3. 바뀌는 실자금 경로
- OBV 자동 인스턴스의 **손절 실행**: 프로브 모드에선 부분손절(10 잔량)이 아니라 **전량**. 피라미딩으로 커진 610 도 −5% 에서 전량. 되돌리기 = `obv_loss_ladder_mode=ladder`.
- OBV 자동 인스턴스의 **2단계 이후 자동 진입**: 프로브 모드에선 없음(사장님 「▶ 다음단계」 수동은 그대로).
- **새 주문이 나가는 워커 1개 추가**(`managed_symbols`, 1분): 명부 심볼에만, 10 USDT 만, 하루 10건·연속 실패 10회 안에서.

## 4. 화면
전략 페이지 「🎯 재진입 알람」 카드 옆 **「🧭 관리 심볼」** 카드: 심볼 · 상태 · 시도 n/10 · 마지막 방향/손익 · LONG 사유 · SHORT 사유 · 마지막 판정 시각 · [↺ 초기화] [✕ 해제] · 입력칸 [➕ 심볼 추가]. 30초 갱신. 워커 마지막 사이클 요약 한 줄.

## 5. 검증
- 단위: `tests/test_fix365_managed_symbols.py` — 등록 카운팅(실패/성공/10회), 진입 판정 표, 프로브 모드 술어, 배선 핀.
- 배포 검사기 `scripts/verify_fix364_deploy.py` 에 ④ 관리 명부(행·상태·사유·워커 마지막 사이클) 추가.
- 반박 검증 워크플로(4렌즈) 뒤 배포.
