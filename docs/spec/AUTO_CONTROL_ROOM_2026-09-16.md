# 🎛 자동매매 관제실 (Fix 374, 2026-09-16)

## 사장님 말씀 (verbatim)

> 자동매매 준비 가족 12종과 모든 자동매매를 한곳으로 모아서 사용과 관리가 편리하게 ui를 개선해줘

## 들어가는 곳

운영 대시보드 상단 **「🎛 자동매매」** → 별도 창 `/static/auto-control.html`.
값은 전부 `system_settings` 행이라 **저장 즉시 적용**된다 (컨테이너 재시작 불필요).

## 무엇이 한 화면에 모였나

| 칸 | 전에는 | 이제는 |
|---|---|---|
| 자동매매 전면 중단·재개 (Fix 371) | 화면 없음 — DB 에 직접 SQL | 상단 배너 버튼 (재개는 확인창 + on 인 가족 목록을 보여 준다) |
| 규칙 가족 12종 | 화면 없음 — DB 에 직접 SQL | 가족마다 모드·하루 최대·자리·쿨다운·상한 |
| 실매매 워커 15종 | 전략 제안 패널 · OBV 패널 · 화면 없는 키로 흩어짐 | 한 목록 |
| 외부 매매법 2종 | 화면 없음 | 한 목록 |
| 진입 워커 6종 끄기 | **끌 수 없었다** (공용 한도 키 0 = 다른 워커까지 멈춤, 또는 코드 주석 처리 + 재배포) | 전용 스위치 (Fix 374 신설, 기본 켜짐 = 종전 동작) |
| 가족별 오늘 진입 수 / 지금 보유 / 그림자 기록 수 | 없음 | 가족 줄마다 숫자 |

## 안전 규칙 (화면·API 둘 다)

1. **저장은 전부 또는 전무.** 한 칸이라도 범위·형식이 틀리면 아무 칸도 저장하지 않는다.
2. **화이트리스트 밖 키는 거부.** 관제실이 내놓은 160칸과 `daily_max_<가족키>` 만 쓸 수 있다.
3. **일괄 버튼은 끄는 방향만.** 「전부 끄기」·「전부 그림자로」만 있고 **켜기 일괄은 서버가 거부**한다 — 켜기는 가족마다 사장님이 누른다.
4. **켜는 방향은 확인창.** 전면 재개, 그리고 `off/shadow → on` 이나 `0 → 1` 인 칸이 있으면 목록을 보여 주고 묻는다.
5. **누가 바꿨는지 남는다.** `system_settings.updated_by` + 로그 (Fix 193 설정 변경 감사).
6. **전면 중단은 fail-closed.** `auto_trading_halt` 행이 없거나 읽기 실패면 **중단**으로 본다. 화면도 그렇게 표시한다.
7. **새 워커 스위치는 fail-open.** 행이 없거나 읽기 실패면 **켜짐** = 스위치를 넣기 전과 똑같이 돈다. 전면 정지는 이 스위치가 아니라 중단 게이트와 Kill-Switch 가 한다.
8. **Kill-Switch 는 여기서 풀지 않는다.** 작동 중이면 띠로 알리고, 해제는 운영 화면 배너에서 한다 (자동·수동 모두 막는 장치라 분리).

## 읽을 때 주의할 두 가지

- **`sajangnim_top_short_daily_limit` 은 이름이 「daily」지만 실제 의미는 「동시 보유 상한」**이고, `0` 이면 정점 SHORT·저점 LONG·실시간 재진입·BB 이탈 계열 자동 진입이 **전부** 멈춘다 (`services/position_limit.py:50`). 화면에는 의미대로 「옛 워커 동시 보유 상한」이라고 적었다.
- **`auto_trading_halt` 은 값의 뜻이 거꾸로다** (`1` = 중단). 화면 선택지도 「중단 / 허용」으로 적었다.

## 가족 29종과 키

### 규칙 가족 12 (가상매매 채택 규칙)

| 가족 | 켜기 키 | 기본 | 주기 | 하루 최대 키 |
|---|---|---|---|---|
| 3A 반등 뒤 hist 꺾임 SHORT (SHORT) | `rf_s2_short_mode` | `shadow` | 60초 | `daily_max_rf_s2_short` |
| 3B 저점 반전 LONG (LONG) | `rf_bottom_long_mode` | `shadow` | 60초 | `daily_max_rf_bottom_long` |
| 3D 상승 초입 LONG (당일 하락50) (LONG) | `rf_surge_long_mode` | `shadow` | 60초 | `daily_max_rf_surge_long` |
| 정점 확인 SHORT (SHORT) | `rf_confirm_peak_mode` | `shadow` | 60초 | `daily_max_rf_confirm_peak` |
| 정점 반전 SHORT (SHORT) | `rf_toprev_mode` | `shadow` | 60초 | `daily_max_rf_toprev` |
| 정점 대비 −8% SHORT (SHORT) | `rf_off8_mode` | `shadow` | 60초 | `daily_max_rf_off8` |
| 20봉 신저점 이탈 SHORT (SHORT) | `rf_s1_breakdown_mode` | `shadow` | 60초 | `daily_max_rf_s1_breakdown` |
| 윗꼬리 반전 SHORT (SHORT) | `rf_wick_short_mode` | `shadow` | 60초 | `daily_max_rf_wick_short` |
| 상승 중 조정 LONG (LONG) | `rf_pullback_long_mode` | `shadow` | 60초 | `daily_max_rf_pullback_long` |
| 다일 반등 LONG (LONG) | `rf_multiday_long_mode` | `shadow` | 60초 | `daily_max_rf_multiday_long` |
| hist 상승 전환 LONG (LONG) | `rf_l1_hist_long_mode` | `shadow` | 60초 | `daily_max_rf_l1_hist_long` |
| 아래꼬리 반전 LONG (LONG) | `rf_wick_long_mode` | `shadow` | 60초 | `daily_max_rf_wick_long` |

### 실매매 워커

| 가족 | 켜기 키 | 기본 | 주기 | 하루 최대 키 |
|---|---|---|---|---|
| 급등 정점 SHORT (v219) | `sajangnim_top_short_enabled` | `1` | 30초 | `daily_max_top_short` |
| 저점 LONG (v226) | `sajangnim_bottom_long_enabled` | `1` | 30초 | `daily_max_bottom_long` |
| 실시간 재진입 (마틴게일) | `realtime_reentry_enabled` | `1` | 30초 | `daily_max_bb_reentry` |
| 수익 추가 (피라미딩) | `sajangnim_pyramid_enabled` | `1` | 30초 | `daily_max_success_reentry` |
| 사다리 재시작 | `ladder_restart_enabled` | `1` | 5분 | — |
| 저항 반전 SHORT | `resistance_reversal_enabled` | `1` | 30초 | — |
| 전고점 돌파 반전 | `peak_break_reversal_enabled` | `1` | 30초 | — |
| 통합 15분 진입 (v224) | `unified_entry_enabled` | `1` | 30초 | `daily_max_unified_15m` |
| 볼밴 분할 (급등 분할 진입) | `pump_split_enabled` | `0` | 15분 | `daily_max_pump_split` |
| 볼밴 스윙 | `bb_swing_mode` | `shadow` | 60초 | `daily_max_bb_swing` |
| 볼밴 중단선 | `bb_mid_line_mode` | `shadow` | 15분 | `daily_max_bb_mid_line` |
| 급등 사다리 | `surge_ladder_mode` | `off` | 30초 | `daily_max_surge_ladder` |
| 심볼 관리 재진입 (10 USDT 프로브) | `managed_symbol_entry_enabled` | `1` | 60초 | `daily_max_managed_reentry` |
| OBV 자동 진입 (옛 auto_bb_breakdown) | `auto_obv_enabled` | `0` | 스케줄 등록 안 됨 | — |
| 예약 진입 (사람이 예약한 전략) | `scheduled_entry_enabled` | `0` | 5분 | — |

### 외부 매매법

| 가족 | 켜기 키 | 기본 | 주기 | 하루 최대 키 |
|---|---|---|---|---|
| 후지모토 3역 호전 | `fujimoto_mode` | `shadow` | 50초 | `daily_max_fujimoto` |
| 마하세븐 속임수 돌파 | `mach7_mode` | `shadow` | 50초 | `daily_max_mach7` |

### 감지 전용 (주문을 만들지 않아 켜기 칸이 없다 — 2026-09-16 확인)

`long_bottom_detector` · `pump_top_detector` · `pump_dump_early_detector` · `bb_upper_breakout_short` · `macd_reversal_15m`
— 인스턴스·주문 생성 코드가 0곳이다. 이들이 만든 알람을 위의 진입 워커가 집어간다.

## API

| 메서드 | 경로 | 하는 일 |
|---|---|---|
| GET | `/api/v1/auto-control/overview` | 한 판 (읽기 전용) |
| PATCH | `/api/v1/auto-control/settings` | `{"changes": {"키": "값"}}` — 전부 또는 전무 |
| POST | `/api/v1/auto-control/halt` | `{"halt": true/false}` — 전면 중단/재개 |
| POST | `/api/v1/auto-control/bulk` | `{"target": "off"\|"shadow", "group": "…"}` — 끄는 방향만 |

## 코드

| 파일 | 하는 일 |
|---|---|
| `app/services/auto_control.py` | 레지스트리 (가족 29종 · 설정 160칸 · 검증 규칙). 규칙 가족 기본값은 `rule_families.SETTINGS` 에서 읽어 온다 (두 곳에 적지 않는다) |
| `app/services/auto_control_state.py` | 현황 집계(build) · 저장(apply) |
| `app/services/worker_switch.py` | 진입 워커 6종 전용 스위치 (기본 켜짐) |
| `app/api/v1/auto_control.py` | 위 4개 endpoint |
| `app/static/auto-control.html` + `js/auto-control.js` | 화면 |
| `backend/scripts/verify_fix374_auto_control.py` | 배포 검사 3층 |

테스트: `tests/test_fix374_auto_control.py` (레지스트리·가드·검증) · `tests/integration/test_fix374_auto_control_db.py` (DB 읽기·쓰기).

🛡 **가드 하나가 새로 생겼다**: 관제실이 화면에 내놓는 모든 설정 키에 대해 **그 키를 실제로 읽는 코드가 있는지** 전수 검사한다
(`test_every_exposed_key_is_read_somewhere`). Fix 373 에서 겪은 「아무도 읽지 않는 이름을 코드가 믿고 있는」 조용한 실패를 막는다.

## 배포 (DB 변경 없음)

```bash
cd ~/binance-auto-trader/backend && git pull origin main && docker compose restart api scheduler
docker compose exec -T api python scripts/verify_fix374_auto_control.py
```

## 사장님이 정할 것

1. 자동매매를 재개할지 (`auto_trading_halt` → 허용). 재개해도 **on 인 가족만** 주문한다.
2. 어느 가족을 `on` 으로 켤지. 규칙 가족 12종은 9/21경 7일 사전등록 재판단 뒤에 켜는 것을 권한다.
3. 🚨 **수익 추가(피라미딩)** 는 행이 없어 기본 켜짐이다. 9/13 KOMAUSDT·哈基米USDT 손실의 직접 원인이었으므로,
   재개 전에 이 칸을 「끔」으로 둘지 먼저 정하시는 것이 좋다.
