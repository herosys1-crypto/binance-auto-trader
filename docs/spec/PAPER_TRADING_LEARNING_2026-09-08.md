# 가상 매매 학습 (Fix 361, 2026-09-08)

## 사장님 지시 (verbatim)

> "지금부터 실시간 자동은 종료했어 가상으로 포지션 진입해서 성공과 실패를 기록저장 학습해서
> 다시 실시간 운영시작 하면 그때 적용할 수 있게 학습해줘 꼭 성리할수 있는 롱과숏 포지션 진입하고
> 익절중에 포지션 추가해서 수익을 만들 자리를 찾아줘"

(2026-09-08) 실시간 자동매매를 껐다. 그동안 손을 놓는 대신 **가상으로** 롱·숏에 진입하고, 이기고 있을 때
포지션을 추가하는 자리까지 같이 재서, 다시 실 운영을 켤 때 "이번엔 이 규칙을 켜자"고 근거를 들고 말할 수
있게 만드는 것이 이 기능의 목적이다.

관련: Fix 362(같은 날, 다른 지시) — "기존 방식 새전략은 -25% 손실이면 청산하게 기본옵션을 설정해줘".
가상 매매 엔진의 `live` 청산 잣대(손절 −25% ROI)는 **이 새 기본값과 같은 숫자**를 쓴다(아래 4절).

## 실 주문 0건 보증

가상 매매는 바이낸스에 **읽기만** 한다 — `bc.get_24hr_ticker()` / `bc.get_klines()` 두 호출뿐이고, 주문·포지션
변경·자금 이동 API 는 코드 전체에서 한 곳도 부르지 않는다. 이 기능의 모든 파일:

| 파일 | 역할 |
|---|---|
| `app/services/paper_trading.py` | 엔진(순수 함수) — 규칙 평가, 진입/관리(청산 시뮬), 추가 lot, 백필, 보고서 |
| `app/models/paper_trade.py` | `paper_trades` 테이블 ORM (`alembic/versions/0036_paper_trades.py`) |
| `app/workers/paper_trading_worker.py` | 15분 사이클 · 백필 · CLI |
| `app/api/v1/paper_trading.py` | 읽기 전용 API (`/api/v1/paper-trading/*`) |

실매매 경로(`execution_service`, `stream_service`, 각종 `*_worker` 의 진입/손절 코드)는 이 기능을 **import 하지
않는다** — 반대로 가상 매매 엔진이 실매매 판정식(`chart_events`, `peak_confirmation` 등)을 **읽기 전용으로
재현**해서 쓴다(`chart_learning.RULES` 레지스트리, Fix 353/356 과 동일 원리).

## 언제 무엇이 도나

| 잡 | 주기 | 하는 일 |
|---|---|---|
| `paper_trading` (스케줄러 id) | 매 15분(`CronTrigger(minute="1,16,31,46")`, 15m 봉 마감 1분 뒤) | ① 열린 가상 포지션 전부를 진입 이후 완성봉으로 **처음부터 재계산**(상태 없음)해서 청산 여부 갱신 ② `chart_learning.RULES` 12종 + 기준선 2종(`baseline_LONG`/`baseline_SHORT`) 이 그 봉에서 발동했으면 가상 진입 ③ 사이클 끝에 백필이 안 끝났으면 이어서 진행 |
| 백필(같은 사이클에 얹힘, `paper_trading_backfill_enabled` ON 이고 미완일 때만) | 사이클마다 최대 300행 | `chart_learning_days`(Fix 353, 라벨링 완료 행)을 id 오름차순으로 재생해 **API 호출 없이** 같은 엔진으로 첫 표본을 만든다. 약 3,000행 → 10사이클(2.5시간) 이면 끝난다 |

감시 대상(그 사이클에 훑는 심볼) = 당일 상승/하락 top N(`paper_trading_top_n`, 기본 50) ∪ **지금 열려 있는
가상 포지션의 심볼**(청산 전에는 감시에서 빠지지 않는다). 3·5일 태그·변동률은 따로 계산하지 않고 오늘/어제
`chart_learning_days` 스냅샷에서 병합한다 — 같은 정보를 두 워커가 각자 API 로 다시 재는 낭비를 없앤다
(스냅샷이 없으면 3·5일 태그 없이 진행 = fail-open, 매매를 막지 않는다).

## 두 엔진 + 추가(피라미딩) 변형

한 가상 포지션마다 **같은 진입가·같은 후속봉** 위에서 서로 다른 청산 규칙 두 개를 동시에 돌린다:

- **house** — 9/3 이후 모든 측정의 공통 잣대(`chart_learning.sim`): 레버 2 · SL −5%/TP +15% ROI · 12h.
  다른 학습(차트 학습 일지 등)과 숫자를 맞춰 비교할 수 있게 하는 대조군.
- **live** — 실매매 청산 규칙의 근사: **SL −25% ROI**(Fix 362 새 전략 기본값과 동일) → TP1 부분익절(24h
  변동 연동 3%/15%) 25% → 트레일링 5%p(직전 봉까지의 최고 ROI 기준) → 48h 시간 만료. 봉 고가/저가로
  판정하며, 한 봉 안에서 손절가와 TP1 가를 동시에 건드리면 **손절을 우선**한다(보수적 가정).

추가(피라미딩) lot 은 `live` 위에 **병렬로** 기록한다 — 각 300 USDT, 자기 손절도 같은 −25% ROI, 최대 2회·
쿨다운 1봉, 정점 대비 되돌림 2.5% 이내에서만:

| 변형 | 조건 |
|---|---|
| `live` | 현행 실매매와 같음 — **SHORT 만**, ROI≥5%, 이동≥3%, 15m MACD hist 3봉 가속 |
| `live_both` | `live` + LONG 도 허용 |
| `after_tp1` | 본 포지션이 TP1(부분익절) 을 이미 지난 뒤에만 |
| `body` | `live` + 캔들 몸통 성장(candle_battle G3A) 조건 추가 |
| `noind` | 지표 조건 없이 ROI·이동·되돌림 문턱만 |

## 채택 문턱 (사람이 켠다 — 자동 튜닝 없음)

`GET /api/v1/paper-trading/report` (또는 `report.md`) 는 규칙×방향×자리(태그 그룹: ALL/UP24/DOWN24/
UP35_DOWN24)×엔진 별 n·평균 ROI·승률·기준선 대비 Δ·교차검증(심볼 짝/홀 × 시간 전/후반 4조각)을 보여준다.
"지금 채택 문턱을 넘는 것"(0절) 은 다음을 **전부** 만족해야 뜬다:

1. n ≥ 100 (`ADOPT_MIN_N`)
2. 기준선(같은 자리 무작위 진입) 대비 Δ > 0
3. 교차검증 네 조각 **전부** 양수(`cv.all_positive`)

추가(피라미딩) 변형도 같은 방식(lot 단위 n·평균·CV)으로 별도 추천 목록에 뜬다. 배선은 여기서 끝 —
규칙을 실 운영에 켜는 것은 **사람이 설정으로** 한다(전략 인스턴스에 반영하려면 별도 작업 필요, 이 기능은
재기만 한다).

## 설정 (system_settings, 기본값·되돌리기)

| 키 | 기본값 | 뜻 |
|---|---|---|
| `paper_trading_enabled` | ON | 끄면 사이클이 아무것도 안 하고 `{"skipped": "disabled"}` 반환(재시작 불필요) |
| `paper_trading_top_n` | 50 | 당일 상승/하락 감시 N (5~200) |
| `paper_trading_backfill_enabled` | ON | 학습 일지 백필 진행 여부 |

코드 상수(설정키 아님, 바꾸려면 배포 필요 — `app/services/paper_trading.py`):
`LOT_USDT=300`(추가 lot 크기, 사다리 2단계와 동일), `LIVE_SL_ROI=25`(Fix 362), `LIVE_HORIZON=192`(48h),
`TRAIL_RETRACE=5`(%p), `TP1_CALM=3`/`TP1_SURGE=15`(|24h|≥15% 기준), `ADD_TRIGGER_ROI=5`, `ADD_MIN_MOVE=3`,
`ADD_MAX=2`, `ADD_MAX_RETRACE=2.5`, `ADD_COOLDOWN_BARS=1`, `BASELINE_EVERY=12`(3h), `ADOPT_MIN_N=100`.

되돌리기: `paper_trading_enabled=0` (설정 즉시 반영, 재시작 불필요). 완전히 걷어내려면
`alembic downgrade -1`(0035 로) 뒤 파일 4개를 되돌린다 — 실매매 경로와 import 관계가 없어 걷어내도 다른
기능에 영향 없음.

## 배포 절차

```bash
git pull
docker compose exec api alembic upgrade head    # 0036_paper_trades (paper_trades 테이블 생성)
docker compose restart api scheduler             # scheduler 가 15분 잡을, api 가 새 라우터를 물게
```

배포 직후 확인:

```bash
curl -s $API/api/v1/paper-trading/status          # counts 가 비어 있으면(0건) 다음 :01/:16/:31/:46 까지 대기
python -m app.workers.paper_trading_worker once   # 컨테이너 안에서 즉시 1사이클 수동 실행(디버그용)
```

## 보고서 읽는 법

- `GET /api/v1/paper-trading/report.md` (또는 CLI `python -m app.workers.paper_trading_worker report`) —
  사람이 읽는 markdown. 0절(채택 후보) 만 보면 "지금 켜도 되는 것"이 바로 보인다. 1절은 엔진별(house/live)
  규칙×자리 표, 2절은 추가 변형(lot 단위).
- `GET /api/v1/paper-trading/report?days=60` — 같은 내용 JSON(화면·다른 스크립트용). Redis 10분 캐시(15분
  사이클보다 짧게 잡아 항상 최신 사이클을 반영).
- `GET /api/v1/paper-trading/trades?limit=100&status=&rule=&side=` — 최근 개별 건(디버그·표본 확인용).
- `GET /api/v1/paper-trading/status` — 열림/닫힘 건수(출처별), 마지막 사이클 요약(Redis, 없으면 `null` —
  "사이클 0건"과 "지금 모름"을 구분한다), 백필 진행 커서.
- n 이 작을 때(특히 배포 초기) Δ·CV 값을 그대로 믿지 말 것 — `ADOPT_MIN_N=100` 미만은 표에는 나와도
  0절 추천에는 안 뜬다.

## 미래참조 없음 (구조적으로)

- 진입 스냅샷(`entry_snapshot`)과 규칙 평가(`evaluate_rules`)는 진입 봉 `j` **까지**의 배열만 슬라이스해서
  본다 — `j` 이후 봉을 아무리 바꿔도 결과가 같다(테스트로 검증: 미래봉을 극단값으로 오염시켜도 스냅샷 불변).
- 청산 관리(`manage_trade`)는 진입 봉 `ts` **이후**의 봉만 써서 매 사이클 처음부터 다시 계산한다(상태 없음)
  — 진입 봉 이하를 아무리 바꿔도 청산 결과가 같다(같은 방식으로 검증).
- 백필은 규칙마다 그 24h 창 안 **첫 발동**만 잡고(같은 규칙이 여러 번 참이어도 한 건), 기준선은 3시간(12봉)
  마다 새로 진입한다.

검증: `backend/tests/test_fix361_paper_trading.py` (28개, 엔진 로직 + 정적 배선).

## Fix 362 — 새 전략 강제손절 기본 −25% (사장님 2026-09-08 "기존 방식 새전략은 -25% 손실이면 청산하게 기본옵션을 설정해줘")

- 설정키 `force_sl_roi_new_default` (기본 **25**, `FORCE_SL_ALLOWED_ROI` 안의 값만). 전역 기본(`FORCE_SL_ROI_DEFAULT=5`, 옛 인스턴스가 쓰는 `force_sl_long_roi/short_roi`)은 **그대로** — 기존 포지션 영향 없음.
- 🚨 `strategy_service` 생성 기본만 고쳤더니 **워커 5곳이 생성 직후 `Decimal("5")` 로 다시 덮어쓰고 있었다**(auto_bb_breakdown 2곳(OBV hold·일반), auto_short_at_top, peak_break_reversal·resistance_reversal 의 2단계 진입). 전부 `new_strategy_force_sl_roi(db)` 로 통일 → 새 진입은 어느 워커를 거쳐도 −25%. 테스트가 `Decimal("5")` 덮어쓰기 잔존을 막는다.
- 알람 빠른 진입 폼 기본값도 25. 가상 매매 `live` 엔진의 손절(본 포지션·추가 lot)도 같은 25.
- 되돌리기: 설정 `force_sl_roi_new_default=5` 한 행 (재시작 불필요, 생성 시마다 읽음).

## 실 운영 상태 (2026-09-08, 사장님 "일 최대 1개로 하고 가상만 돌게")
- 사장님이 9/7 19:14 UTC 에 `sajangnim_top_short_daily_limit=0`(v219 정점 SHORT·저점 LONG 공용 캡)·`pump_split_enabled=0` 을 넣어 주력 진입은 이미 차단.
- 남아 있던 경로: 재진입 워커(`sajangnim_reentry_daily_limit=10`, 전용 슬롯이라 캡 0 과 무관) · 중단선 가족(`bb_mid_line_mode=on`) · 예약 진입(`scheduled_entry_enabled=1`) · 열린 사다리 6개의 2·3단계(`sajangnim_ladder_stages_enabled=1`).
- 지시 반영 = `sajangnim_reentry_daily_limit=1` · `bb_mid_line_mode=off` · `scheduled_entry_enabled=0` (사장님 실행). 사다리 2·3단계는 기존 포지션 관리라 유지(멈추려면 `sajangnim_ladder_stages_enabled=0`).
