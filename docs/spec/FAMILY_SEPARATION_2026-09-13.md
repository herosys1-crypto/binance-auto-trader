# Fix 369 — 「➕ 새 전략 (기존 방식)」 / 「새 전략 (OBV 자동)」 완전 분리 (2026-09-13)

사장님 verbatim: "새 전략기존방식 과 새전략 obv 자동 둘을 완전 다르게 둘로 분리해서 개발을해줘 두개가 계속 겹치는것 같아"

## 0. 계기 — LSKUSDT 기존 방식 SHORT 2단계 미진입 (9/12~13)
- #4496(계획 100/100/100/600)·#4506(100/200/200/500): 2단계 가격 도달 → `[Fix232/price] 가격 도달로 진입` 직후 `130% 초과 차단`
  (예약 10,680 / 8,769 > 허용 지갑×1.3 ≈ 5,058) → 사장님 💉 지정가 추가 → ROI −70~−78% → 거래소 강제청산(청산 주문 없음) → reconcile STOPPED.
- 예약 구성 실측(9/13, `capital_calculator` 실제 함수): 7,159 중 **기존 방식 7건 = 6,509**(건당 미진입 800 + 실 마진), v219 DASH 610,
  OBV 자동 4건 ≈40(프로브 모드라 미진입 0). = **기존 방식끼리 서로의 2단계를 막는 구조.**
  (처음에 「OBV 예약이 막았다」고 보고한 것은 오진 — 실제 함수로 구성을 뽑아 정정.)
- 부 원인: Fix 41 `peak_break_reversal_worker` 가 모든 활성 SHORT(기존 방식 포함)의 다음 단계를 넣으려다 `ExecutionService(db)` TypeError
  — 8/23 도입 이후 한 번도 진입 성공 못 한 경로. 같은 잘못된 호출: resistance_reversal:330 · time_reverse_exit:43 · bb_mid_line:145.

## 1. 겹침 감사 (읽기 전용 3렌즈, 9/13)
| 층 | 핵심 발견 |
|---|---|
| 화면·생성 | 같은 모달 DOM·`cmState`·`POST /strategies`·템플릿 목록. OBV 모달에서 가격 템플릿 선택 → 기존 방식 생성(토스트는 OBV) / 새 모달이 가족 무관 최근 전략으로 자동 채움 / 다시 시작 조회 실패·옛 가격 전략 → 손절 없는 기존 방식으로 바뀜 / OBV 인스턴스엔 표식 없음 |
| 워커 | 가족 판정 기준이 없음(OBV = trigger_mode 4곳 따로, 기존 방식 = entry_profile 1곳). Fix 41·29 반전 워커·시간 역행 청산이 두 가족 모두 대상. 수익 추가가 손절 없는 기존 방식에 300×2. OBV 용 「이익 중 대기」가 기존 방식에도. AUTO_ENTRY_MISSED 가 OBV 에서 오탐 |
| 자본 | 130% 가드 = 계정 합(가족 무구분), 한도 env `WALLET_LIMIT_PCT`=130, 판정값은 예약 하나(로그 「실 + 예약 =」 라벨 오류). 예약 제외 선례: v219 사다리(Fix 344 ③-a) · 프로브 OBV(Fix 365b) |

## 2. 구현
### S1 — 130% 가드 (사장님 결정 9/13 「기존 방식 미진입 단계 예약 제외」)
- `capital_calculator.legacy_manual_skips_reserve` + `calc_reserved_for_account(..., exclude_legacy_untriggered=True)`:
  **기존 방식 전략이 자기 다음 단계를 넣을 때의 판정에서만** 기존 방식 미진입 단계를 예약에서 뺀다. 되돌리기 `legacy_reserve_untriggered_enabled=1`.
  - 반박 검증(9/13) 반영: 처음엔 공용 규칙(`ladder_reserves_untriggered`)에 넣었는데, 그러면 OBV·볼밴 분할·기타 가족의 130% 판정과
    생성 시 검사까지 느슨해졌다 → 기본값(공용 합계·생성 검사·화면·다른 가족 판정)은 옛 합계 그대로. 기존 방식 판정에서도 다른 가족의 예약은 센다.
- `stage_trigger_worker`: Fix 344 발주 직전 가용 잔고 검사를 기존 방식에도 적용. 기존 방식은 더 엄격하게
  ① 필요 금액 = `_stage_order_margin369` = Binance 주문 비용(개시 증거금 + 개시 손실):
     SHORT = qty × max(mark, 트리거) ÷ lev + qty × max(0, mark − 트리거) / LONG = qty × 트리거 ÷ lev + qty × max(0, 트리거 − mark),
     max(planned_capital, 그 값) × `legacy_stage_margin_buffer`(기본 1.05 — Claude가 정함, MARKET preflight 와 같은 값) + additional_margin_usdt.
     (기존 방식 단계는 가격이 트리거를 넘어선 뒤 LIMIT @ 트리거로 나가 바로 체결 → 트리거가만 보면 레버리지 10 · 1% 초과에서 11% 모자람 = -2019.
      수량은 planned_qty — 단계 수정이 qty 를 다시 계산하지 않는 경로가 있다)
  ② 잔고 조회 실패 = 보류 후 다음 주기 재시도(fail-closed). 사다리 경로는 그대로.
  ③ 보류 시 사장님 텔레그램(1시간 dedup) · WARNING 로그는 10분에 한 번 (워커 15초 주기).
  ④ 기존 방식 판정 = `family_of` 단일 권한 (생성 뒤 분할로 바꾼 인스턴스는 제외 대상 아님).
- 로그·텔레그램 라벨 정정: 판정값은 「예약 합계(실 마진 포함)」 하나 — 옛 「실 + 예약 = 합」은 틀린 표기.
- 표식 없는 옛 가격 전략(Fix 367 이전)은 그대로 예약.
- 넣지 않음(보고만): 여유 잔고 하한(다른 가족 몫 남기기) — 필요하면 설정 키로.

### S2 — 가족 판정 단일 권한 + 워커 제한
- `app/services/strategy_family.py` `family_of`: split → single → obv_auto(표식 또는 OBV_REVERSE) → legacy_manual(표식) → ladder → other, 실패 unknown.
- 생성 시 두 가족 모두 표식: `entry_profile` = legacy_manual / **obv_auto**(템플릿 OBV_REVERSE — 모달·관리 재진입 복제). 마이그레이션 없음(String(20)).
- Fix 41 peak_break · Fix 29 resistance · time_reverse_exit: 두 수동 가족 제외(`drop_families`, unknown 도 제외).
  **호출 오류(ExecutionService(db))는 일부러 고치지 않음** — 고치면 한 번도 돈 적 없는 시장가 단계 진입이 자동 워커·사다리에 켜진다 → 사장님 결정 사항.
- 수익 추가(success_pyramiding): **기존 방식도 그대로 대상.** 처음엔 제외했으나 반박 검증에서 Fix 185 사장님 verbatim
  「모든 전략 — 수동/모달 전략도 수익 나면 추가 진입」과 충돌이 확인돼 되돌림 (배포 시점 LONG 활성 5건이 영향 대상이었다).
- AUTO_ENTRY_MISSED: OBV 자동 제외(가격 트리거로 판정하면 오탐).
- 손대지 않고 보고: Fix 363b 「이익 중이면 단계 대기」(사장님 지시 규칙) · managed_symbols 같은 심볼 반대/같은 방향 잠금(거래소 제약) · position_limit 범위(VPS = ladder).

### S3 — 화면·생성 경로 (구현 에이전트, 리드 검토)
- API:
  - `POST /strategies` 에 `family`(legacy_manual | obv_auto, 선택) — 템플릿 trigger_mode 와 다르면 400(한국어 메시지), 없으면 경고 로그만(옛 호출자 호환).
  - 응답 `family` = `family_of()` (생성·목록·단건·blueprint). blueprint 에 `trigger_mode` 추가.
  - `GET /admin/strategy-templates?family=` 필터(모르는 값 무시) + 응답에 `trigger_mode`(NOT NULL 컬럼).
- 화면:
  - 새 `cm-family.js` = 가족 판정·OBV 표시 단일 소스.
  - 두 버튼이 family 를 보냄 · 템플릿 목록·이전 전략 불러오기·자동 채움 = 같은 가족만.
  - ✏️ 수정·🔄 다시 시작 = 원 전략 가족을 먼저 조회해 확정(조회 실패면 모달을 열지 않음 — 옛 「조용히 가격 방식으로」 폴백 제거).
  - 즐겨찾기 = 템플릿 trigger_mode 로 맞는 모달 · 토스트·배지 = 실제 생성 가족.
- 테스트 `tests/test_fix369_ui_separation.py` + `test_fix367` UI 핀 갱신.
- S3 반박 검증(9/13) → 수정 반영 · 재검증 통과 (node 실행 테스트 7건 · 수정 JS 9개 `node --check` · 템플릿 목록 필터도 `_triggerMode` 로 통일):
  - 🔴 차단: ✏️/🔄 로 OBV 전략을 연 뒤 닫고 「➕ 기존 방식」을 누르면 OBV 플래그가 남아 OBV 전략이 만들어짐.
    서버는 템플릿과 family 가 둘 다 OBV 라 통과 → TP1·강제손절 기본값이 OBV 값으로 들어감.
    → 모달 가족은 이번 열기의 입력으로만 정하고, 플래그는 쓰고 나면 지운다(닫기 포함).
  - 🟠 높음: 표식 없는 전략(other/ladder/split/single) 재시작 확인창의 「확인」이 OBV 로 전환.
    → trigger_mode 로 판정(OBV_REVERSE 만 OBV, 나머지는 기존 방식, 확인창 없음 = Fix 367d 동작), 조회 실패면 열지 않음.
  - 🟡 OBV 모달 자동 채움에서 관리 재진입 복제본 제외. 보고만: 'other' 전략의 「➕ 기존」 배지 사라짐 · perp-terminal 생성은 family 없이 경고 로그.
  - 교훈: 문자열 핀 테스트는 「열기→닫기→다른 버튼」 같은 상태 순서 결함을 못 잡는다 → 판정을 순수 함수로 빼서 node 로 실행 테스트.

## 3. 검증
- 테스트 `tests/test_fix369_family_separation.py`(S1·S2) + 검사기 ⑨.
- 반박 검증 2렌즈 완료(9/13):
  - S1 자본 안전 = 공용 합계가 느슨해짐 · 주문 크기(planned_qty) 불일치 · 잔고 조회 실패 시 fail-open · 라벨 → 모두 반영 (위 S1).
  - S2 가족 라우팅 = 주문 경로 결함 없음. 수익 추가 제외만 사장님 지시와 충돌 → 되돌림.
  - S1 재검증 = HEAD 보다 나빠지는 경로 없음. H1 트리거 초과 체결 비용 · M1 텔레그램 · M2 로그 반복 · L3 가족 판정 단일화 → 반영.
    사장님께 알릴 것: ① 다른 가족(OBV·볼밴 분할·기타)의 단계 판정과 신규 생성 검사는 여전히 기존 방식 미진입분을 세서
    (7건 × 800 ≈ 5,600 > 한도 ≈ 5,058) HEAD 처럼 계속 막힌다 ② 화면 예약률은 별도 계산(exchange_accounts._reserved_one)이라
    130% 초과로 보여도 기존 방식 단계는 진입한다 ③ 배포 직전 130% 차단이 남긴 30분 쿨다운 키가 있으면 최대 30분 늦게 시작.
  - 보고만 (Fix 369 가 만든 문제 아님): resistance_reversal 워커가 DASH 사다리 1단계에서 진입 시도 전 텔레그램을 30초마다 반복할 수 있음 ·
    auto_reentry 가 entry_origin 을 넘기지 않음(현재 도달 불가 — 모달은 manual_ready) · 가족 판정이 어긋나는 두 경우(OBV 템플릿 + stage_ladder,
    생성 뒤 admin API 로 trigger_mode 변경).
- 사장님 결정 대기: Fix 41·29 반전 워커를 살릴지(호출 오류 수정 = 자동 워커·사다리 SHORT 에 시장가 단계 진입이 새로 켜짐) 끌지.
