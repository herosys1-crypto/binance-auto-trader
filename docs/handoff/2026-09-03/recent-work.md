## 이번 세션에서 한 일과 다음 할 일

> 작성: 2026-09-03 (세션 인수인계 담당)
> 대상 커밋: `ded22f3` (main, VPS 배포 완료 — 아래 §1 에서 실측 확인)
> ℹ️ 그 뒤에 문서 전용 커밋 `e51d9a8`(`chore(handoff)`)이 하나 더 있다. **backend 파일 0개**(실측: `git show --name-only e51d9a8 | grep -c '^backend/'` → 0)라 **배포 대상 코드는 여전히 `ded22f3` 이다.** §7 에서 `git log` 를 돌리면 맨 위에 `e51d9a8` 이 보이는데 정상이다.
> 🔒 이 문서에는 **비밀 값이 없다**(2026-09-03 비밀 누출 검토 완료 — 키 **이름**과 「어디서 얻는가」만 기록). 비밀은 `secrets.md` 로, 값은 어디에도 적지 않는다.
> 이 섹션만 읽고도 새 세션이 이어받을 수 있게 썼다. **추측한 곳은 「⚠️ 확인 못 함」으로 표시**했다.

---

### 0. 30초 요약

| 항목 | 상태 |
|---|---|
| 이번 세션 커밋 | **Fix 325 / 326 / 327** (`0459e8f` → `1d04598` → `ded22f3`) |
| VPS 배포 | ✅ **완료** — 파일 mtime `2026-09-03 08:51 UTC`, api 컨테이너 기동 `08:51:26 UTC`, scheduler `08:51:57 UTC` |
| Fix 325 (순위 100개 진입 대상) | 🚨 **이미 살아서 돌고 있다** — 스위치를 안 눌러도 기본값이 `rank` 다 |
| Fix 326 (잔량 유지 손절) | 🚨 **이미 살아 있다** (`stage_trim_before_next_enabled='1'`). **다만 배포 후 손절 이벤트 0건 = 아직 실검증 안 됨** |
| Fix 327 (지지선 7점 게이트) | ⏸ **OFF** (`support_score_gate_enabled` 행 자체가 없음). 켜야 동작한다 |
| 신규 문서 | `docs/spec/*_2026-09-03.{md,json}` 5건 (차트분석 에이전트팀 4명 실측) |
| 🚨 제일 먼저 할 일 | **Fix 326 실검증** (§6 P1) — 실자금이 도는 손절 경로를 바꿔놓고 아직 한 번도 안 돌았다 |
| 🧭 읽는 순서 | 새 PC 면 **`local-env.md` → `secrets.md` → 이 문서 §7 → §6**. §7 의 3개 명령이 다 돌아야 §6 이 의미가 있다 |
| 🚨 **새 PC 로 가기 전에 반드시** | 이 worktree 에 **커밋 안 된 3,666줄**(`terminal.py` / `perp-terminal.html` / `router.py` 수정)이 있다. GitHub·VPS·백업 폴더 **어디에도 없다** → 클론하면 **영구 소실**. 살리는 명령은 §6-3 끝 |

---

### 1. 배포·운영 상태 (전부 실측, 읽기 전용 조회)

#### 1-1. 배포 판정 근거

메모리 교훈대로 **「프로세스 시작 시각 vs 파일 수정 시각」**으로 판정했다 (`docker exec grep` 은 디스크일 뿐이라 배포 판정이 안 된다).

| 확인 | 값 |
|---|---|
| VPS `git log -1` | `ded22f3 feat(Fix 327) …` (branch `main`) |
| `backend/app/services/support_score.py` mtime | `2026-09-03 08:51` (UTC) |
| api 컨테이너 `StartedAt` | `2026-09-03T08:51:26Z` |
| scheduler 컨테이너 `StartedAt` | `2026-09-03T08:51:57Z` |
| 조회 시각 | `2026-09-03 09:03 UTC` (= 18:03 KST) |

→ 컨테이너 기동이 파일 갱신보다 **뒤**이므로 세 Fix 모두 **배포됨**.

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader && git log --oneline -3 && ls -la backend/app/services/support_score.py && docker inspect binance-auto-trader-api --format "{{.State.StartedAt}}" && docker inspect binance-auto-trader-scheduler --format "{{.State.StartedAt}}" && date -u'
```

#### 1-2. 관련 설정 실측값 (2026-09-03 09:03 UTC, `system_settings` 63행)

| 키 | 값 | 의미 |
|---|---|---|
| `entry_chg24_gate_enabled` | `1` (2026-09-02 23:39) | 진입 대상 게이트 **ON** |
| `entry_chg24_gate_mode` | **행 없음** | → 기본 `rank` = 🚨 **Fix 325 순위 방식이 지금 돌고 있다** |
| `entry_rank_top_n` | 행 없음 | → 기본 `50` (상승 50 + 하락 50) |
| `entry_min_abs_chg24` | 행 없음 | (구 절대값 기준, 지금 미사용) |
| `stage_trim_before_next_enabled` | `1` (2026-09-02 22:33) | 🚨 **Fix 326 경로 활성** |
| `stage_keep_notional_usdt` | 행 없음 | → 기본 `10` USDT (증거금 기준) |
| `adaptive_tp_enabled` | `1` (2026-09-02 17:47) | 적응 TP ON — **단, 배선된 경로는 하나뿐** (§6 P5) |
| `confluence_gate_enabled` | `true` (2026-08-31) | 합의 게이트 ON |
| `support_score_gate_enabled` | **행 없음** | ⏸ Fix 327 **OFF** |
| `support_score_min_long` / `_max_short` | 행 없음 | → 기본 6 / 1 |

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
for r in db.execute(text(\"select key, value, updated_at from system_settings order by key\")).fetchall():
    print(r[0], \"=\", r[1], \"|\", str(r[2])[:19])
"'
```

> 🚨 **DB 는 로컬 `db` 컨테이너가 아니라 외부 Neon 이다.** `docker compose exec db psql` 로 조회하면 **빈 DB** 가 나와 「테이블이 없다」는 오진에 이른다. 반드시 위처럼 **api 컨테이너의 `SessionLocal`** 을 경유할 것. (옛 롤백 가이드에 적힌 `docker compose exec db psql …` 명령들은 **이 이유로 지금은 틀렸다** — 그 문서를 그대로 따라 하면 안 된다. 정확한 위치와 줄번호는 §9-6 에 정리했다.)

#### 1-3. 배포 후 25분 로그 (실측)

| 확인 | 결과 |
|---|---|
| scheduler 로그 줄 수 (최근 25분) | **8,716줄** (로그 자체는 정상적으로 흐름) |
| `Fix310` / `Fix318` / `Fix319` / `Fix325` / `Fix326` / `Fix327` 태그 | **전부 0회** (scheduler 25분 창, 그리고 scheduler+api 30분 창 — 두 번 따로 확인) |
| `chart_patterns` 행 수 | **0** (§6 P4 의 원인은 그대로) |
| 전략 상태 분포 | STOPPED 1173 / COMPLETED 290 / REENTRY_READY 16 / STAGE1_OPEN 8 |

→ 배포 후 **신규 1단계 진입도, 손절 이벤트도 아직 한 건도 없다.** 그래서 Fix 325/326/327 은 전부 **로그로 확인된 바가 없다** (⚠️ 코드는 배포됐고 테스트는 통과했으나 실서버 실행 증거는 아직 0).

> ✅ **재확인 (2026-09-03 09:38 UTC = 배포 후 47분, 위험 검토 담당이 독립 실행)**: 같은 명령을 `scheduler api` 두 컨테이너 60분 창으로 다시 돌렸다 — `Fix310|318|319|325|326|327` **여전히 전부 0회**. `system_settings` 도 63행 그대로, 위 §1-2 의 10개 키 값이 **한 글자도 다르지 않았다**. 즉 §1-2·§1-3 은 **두 사람이 따로 재서 일치한 값**이다.
> 🚨 **다만 「0회」를 「고장」으로 읽지 말 것.** 지금 STAGE1_OPEN 이 8건뿐이라 손절·진입 이벤트 자체가 드물다. 태그가 0인 것은 **아직 그 코드에 도달할 사건이 없었다**는 뜻이고, 「배포가 안 됐다」는 뜻이 **아니다**(배포 판정은 §1-1 의 mtime vs StartedAt 으로 이미 끝났다).
> ✅ **세 번째 재확인 (2026-09-03 09:36~09:50 UTC, 재현성 검증 담당)**: §1-1·§1-2·§1-3 의 명령을 **그대로 복사해 실행**했고 표의 값이 전부 일치했다 (`ded22f3` / mtime `Sep 3 08:51` / api `08:51:26Z` / scheduler `08:51:57Z` / `system_settings` 63행 / 10개 키 동일 / `chart_patterns` 0 / 상태분포 `1173·290·16·8` / Fix 태그 0회). **이 세 명령은 새 PC 에서 그대로 붙여 넣어도 돈다.**
> ✅ 추가 실측: 배포(`08:51 UTC`) 이후 `strategy_instances` 에 **`created_at` 기준 신규 0건**(09:45 UTC 확인) — 「신규 1단계 진입이 없었다」가 로그뿐 아니라 DB 로도 확인됐다. 재실행 명령은 §6-1 끝에 있다.

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 60m --tail 40000 --no-log-prefix scheduler 2>/dev/null | grep -oE "Fix3(10|18|19|25|26|27)" | sort | uniq -c'
```

---

### 2. 2026-09-03 신규 문서 5건 — 요약과 핵심 숫자

전부 **차트분석 전문가 에이전트팀 4명**이 실측으로 만든 것이다. 숫자를 지우지 말 것.

| 문서 | 무엇인가 | 표본 | 코드 반영 |
|---|---|---|---|
| `SUPPORT_BOUNCE_VS_BREAKDOWN_2026-09-03.md/.json` | **지지선 7점 판정식** (BOUNCE vs BREAKDOWN) | 접촉 264건 / 30심볼 / 15m 75시간 | ✅ `app/services/support_score.py` (Fix 327) |
| `CHART_REGIME_ANALYSIS_2026-09-03.md` | **차트 5국면 분류** (급등·급락·보합·지지반등·추가하락) 수치화 | 5,916봉 / 30심볼 / 15m·1h·4h 300봉 | ❌ 코드 미반영 (의도적 — 아래 참조) |
| `REGIME_THRESHOLDS_2026-09-03.json` | 위 문서의 **기계용 임계값** 2,460줄 | 동일 | ❌ 아직 읽는 코드 없음 |
| `REGIME_REAL_TRADE_VALIDATION_2026-09-03.md` | **실거래 DB 로 이론 검증** | 손익 확정 **1,419건** / 315심볼 / 2026-07-05~09-03 | ❌ (다음 할 일의 근거로 쓰임) |
| `REGIME_WIRING_AUDIT_2026-09-03.md` | **어디에 꽂아야 하는가** 배선 감사 (코드 0줄 수정) | 파일:줄번호 전수 | ✅ Fix 327 이 이 감사대로 배선됨 |

#### 2-1. `SUPPORT_BOUNCE_VS_BREAKDOWN` — 핵심 숫자

- 지지선 정의 **9개를 전부 재서** `swing_low`(좌우 3봉 피벗 저점) 채택 — OOS 평균 |d| **+0.517** 1위, 안정 지표 23개.
- **기각**: 볼밴 하단 OOS **−0.125** (안정 지표 6개뿐) / fib 0.5 **−0.724** / fib 0.618 **−0.656** → 그룹을 바꾸면 판정이 **정반대**. 「밴드 하단 = 지지」로 코딩하면 안 된다.
- 7점 판정식 결과 (기준선 **55.0%**, n=264):

  | 구간 | n | 승률 | A그룹 | B그룹 |
  |---|---:|---:|---:|---:|
  | score ≥ 7 → LONG 강 | 47 | **76.9%** | 78.3 | 75.0 |
  | score ≥ 6 → LONG | 80 | **70.6%** | 75.0 | 64.3 |
  | 2~5 → 관망 | — | — | — | — |
  | score ≤ 1 → SHORT | 67 | **63.9%** | 72.2 | 60.5 |
  | score = 0 → SHORT 강 | 22 | **71.4%** | 80.0 | 63.6 |

- TP/SL 근거(가격 %, 8시간 지평): LONG(≥6) → **SL −3% / TP1 +3% / TP2 +5%** (TP+3% 도달 70.0%, TP+5% 53.8%, SL−3% 터치 36.2%). SHORT(≤1) → SL +3% / TP1 −3% / TP2 −5% (−3% 도달 74.6%).
- 🚨 **재진입 반증**: 직전 접촉이 손절이어도 다음 접촉 승률 **49.1%**(n=55) — 기준선 55.0% **아래**. 「손절했으니 확률이 오른다」는 성립하지 않는다. → **재진입 전용 규칙을 만들지 않는다. 같은 score 로 판정한다. 자본을 배수로 키우지 않는다.**
- 🚨 **미래참조 경고**: 순진하게 재면 「직전손절 36.8% / 직전반등 69.7%」라는 극적인 값이 나오는데, 연결된 234건 중 **102건(43.6%)** 이 이번 접촉 시점에 아직 결착이 안 난 상태였다. **그 숫자로 코딩하면 안 된다.**

#### 2-2. `CHART_REGIME_ANALYSIS` — 핵심 숫자

- 국면 정의(순서대로 첫 번째로 맞는 것): RANGE(밴드폭 자기순위 ≤0.25 & 6봉 변화 ≤0) → SURGE(`ret12 ≥ +4.07%`) → CRASH(`ret12 ≤ −3.13%`) → BOUNCE(`px_pos48 ≤ 0.25 & ret48 < 0 & ret4 ≥ +1.17%`) → BREAKDOWN(`px_pos48 ≤ 0.25 & ret48 < 0 & ret4 ≤ −0.92%`) → RANGE(잔여). **모든 경계는 실측 분위수**다.
- 국면별 표본: SURGE 815(13.8%) / CRASH 786(13.3%) / RANGE 4,076(68.9%) / **BOUNCE 40(0.7%)** / BREAKDOWN 199(3.4%).
- 국면 확정 후 2시간 실측: SURGE +0.73%/승률 57.3% ✅재현 / CRASH −0.46%/46.2% ❌**두 그룹 부호 뒤집힘** / RANGE +0.30%/52.5% ✅ / **BOUNCE −1.94%/31.6%** ✅재현 / **BREAKDOWN +0.53%/57.4%** ✅재현.
- 🚨 **절대 임계값은 종목 스케일이 바뀌면 무력해진다** — AKEUSDT 밴드폭 절대 13.21%(넓음)인데 자기 50봉 순위는 **0.02**(최대 수축). v1 판정식은 이 보합을 **CRASH 85%** 로 오판했다. → **모든 국면 지표는 자기 이력 백분위로 정규화**할 것. 이 함정에 이번 분석에서 **세 번**(밴드폭·ATR·RSI/CCI) 걸렸다.
- 🚨 **ATR 정규화는 과교정**(v2 폐기): 급락이 ATR 을 부풀려 −23.7% 하락이 −1.5 배수밖에 안 돼 CRASH 문턱에 못 미쳤다. → **현재 변동성으로 그 변동성을 만든 움직임을 정규화하면 안 된다.**
- 🚨 **지표 수준 교차검증을 통과해도 결과 수준에서 뒤집힐 수 있다**: SURGE vs CRASH 방향 판정기를 표본외로 돌리니 A→B **+0.74%p** / B→A **−0.43%p** 로 부호 반전. **효과크기만 보고 채택하면 안 된다.**
- 문서 스스로 **「BOUNCE 는 표본 40건뿐, 지금 수치로 로직을 만들면 안 된다」** 고 못 박았고, **BREAKDOWN 정밀도 15.6%** = 독립 진입 신호로 쓰면 안 된다고 적었다. → 그래서 이 문서의 국면은 **코드에 들어가지 않았다.**

#### 2-3. `REGIME_REAL_TRADE_VALIDATION` — 핵심 숫자 (실거래 1,419건)

| 확정된 것 (앞/뒤 절반 모두 방향 일치) | 숫자 |
|---|---|
| 수동이 손실의 **94.3%** | 수동 791건 −13,401.7 / 자동 628건 −803.7 |
| **BOTTOM(저점LONG) 하나가 자동을 적자로 만든다** | BOTTOM 156건 **−1,049.0** PF 0.28. 빼면 자동 472건 **+245.4** PF 1.07 (전반 +0.16 / 후반 +0.88) |
| SHORT 는 **24h +10~+30%** 에서만 이긴다 | 106건 +5.44/건 PF 1.70. 경계는 +5% 아니라 **+10%** ([+5,+20) 은 차이 없음) |
| LONG 은 **어느 국면에서도** 이기지 않는다 | 잰 네 칸 전부 음수 |
| `macd_4h_direction=up` **LONG** | 43건 **승률 2.3%** PF 0.00 (앞뒤 4.5% / 0.0%) |
| `PATTERN_B_AFTER_CORRECTION` | 45건 승률 11.1% 건당 −11.25 **PF 0.04** — 43/45가 24h ±10% = **평탄 구간을 「조정」으로 오인** |
| 손절 후 **6시간 이내 재진입 금지** | 93건 −4.25 (전반 −3.16 / 후반 −8.21) |
| `MACD_15M_REVERSAL_SHORT` 는 안정 양수 | 188건 +1.09 (전 +1.22 / 후 +1.00) |
| 피라미딩은 계속 손실 | SUCCESS_PYRAMID 26건 **−559.5** (최악 SKRUSDT SHORT −724.80) |
| 🚨 `max_profit_pct` 결손 = **패배** | 결손 285건 중 **94.4% 가 손실**. → 자동 628건 중 **최소 269건(42.8%)이 한 번도 +로 못 갔다** = **익절 구조가 아니라 진입 자리 문제** |
| 🚨 자동에 「청산 후 재진입」이 켜진 적 없음 | 확정 자동 628건 **전부 False**. 51건 True 는 **전부 수동** |

#### 2-4. `REGIME_WIRING_AUDIT` — 핵심

- **`chart_patterns` 0건의 확정 원인**: 신뢰도 컷도 예외 삼킴도 아니고 **잡 본문이 한 번도 실행된 적이 없다.**
  - `scheduler_runner.py:74` `BlockingScheduler(timezone="Asia/Seoul")` 에 `job_defaults` 가 없다 → `misfire_grace_time` = APScheduler **기본 1초**. 부팅 직후 첫 실행이 `missed by 0:00:01.95` 로 **폐기**된다.
  - 다음 기회는 「부팅 + 6시간」인데 스케줄러가 **72시간에 57회 재시작**한다 → 6시간 잡은 **구조적으로 굶는다**. 실측: `interval[6:00:00]` Running **0** / missed 18, 반면 `interval[1:00:00]` Running **424**.
  - 같은 이유로 굶는 잡: `binance_changelog_monitor` (`scheduler_runner.py:580`).
- 🚨 **되살려도 진입에는 안 쓰인다** — `ChartPattern` 을 읽는 코드는 **쓰기 2곳 + 화면 2곳뿐**, 진입 판정 **0곳**. 스케줄만 고치면 **Fix 247 과 똑같은 모양**(계산·저장만 하고 진입은 안 봄)이 된다.
- **신규 1단계 진입의 단일 관문 = `app/services/execution_service.py:188 start_stage1`.** 직접 호출 7곳 + 공용 깔때기(`_create_auto_bb_strategy`) 경유 7곳 = **전부** 여기를 지난다.
- 🚨 **`trigger_next_stage`(`execution_service.py:305`, 2026-09-03 실측 — `grep -n "def trigger_next_stage" app/services/execution_service.py`)에는 절대 걸지 않는다.** 자본이 들어간 사다리가 그 자리에서 영원히 멈춘다 (Fix 203 / Fix 235 전력).
- 🚨 **국면 판정이 이미 둘 있다**: `app/services/pump_dump_regime.py`(진입 8곳에서 호출) 와 `app/api/v1/bb_middle_scan.py:170 _detect_regime`(사장님 v169 4구간 — API 라우터 안에 숨어 있는데 `auto_bb_breakdown_worker.py:133-142` 가 import 해서 **실제로 진입에 닿는다**). **세 번째를 만들지 말 것** — `_detect_regime` 을 `app/services/market_regime.py` 로 끌어올려 확장하는 것이 권고안이다.

---

### 3. 🚨 두 문서가 모순처럼 보이는 이유 — 새 세션이 반드시 읽을 것

**표면상 정반대로 보이는 두 결론**

| 문서 | 결론 |
|---|---|
| `CHART_REGIME_ANALYSIS` §5, §8 | **BOUNCE(지지반등) 승률 31.6% / 평균 −1.94% → LONG 진입 금지.** BREAKDOWN(추가하락) 57.4% / +0.53% → SHORT 진입 금지 |
| `SUPPORT_BOUNCE_VS_BREAKDOWN` §6 | **score ≥ 6 → LONG 승률 70.6%.** score ≤ 1 → SHORT 승률 63.9% |

**모순이 아니다. 두 문서는 「지지선 근처의 서로 다른 시점」을 재고 있다.**

#### 3-1. 결정적 차이 — 라벨 정의를 실제로 읽으면 드러난다

| | CHART_REGIME 의 BOUNCE | SUPPORT 의 「접촉」 |
|---|---|---|
| 정의 | `px_pos48 ≤ 0.25` **AND** `ret48 < 0` **AND** **`ret4 ≥ +1.17%`** | `low[i] ≤ S×(1+tol)` **AND** `close[i−1] > S×(1+tol)` **AND** 24봉 고점 대비 `≤ −1.0%` |
| `ret4` / 접촉의 뜻 | 직전 **4봉(1시간) 수익률이 상위 25%(p75)** = **이미 1시간 동안 크게 올랐다** | **지금 막 위에서 내려와 지지선을 찍었다** = 아직 안 올랐다 |
| 시점 | 반등을 **눈으로 확인한 뒤** | 반등이 **일어나기 전** |
| 미래 창 | 15m × 8봉 = **2시간** | 15m × 32봉 = **8시간**, ±3% 선도달 |
| 표본 | **n=38~40 (전체의 0.7%)** | **n=264** |

> **즉 CHART_REGIME 의 「BOUNCE」는 「지지반등이 일어날 자리」가 아니라 「이미 반등이 1시간치 일어난 자리」다.** 그 자리에서 사면 비싸게 사는 것이고, 그래서 승률 31.6% 다.
> `SUPPORT` 의 score ≥ 6 은 **닿는 순간**의 자리다. 여기서는 70.6% 다.

#### 3-2. 같은 이야기를 SUPPORT 문서가 지표로 못 박아 놨다

`SUPPORT` 의 7규칙 중 **3번은 일부러 역방향**이다:

```
m15_macdh_not_rising3 :  NOT ( MACD_hist[i] > MACD_hist[i-3] )    ← 15분봉
```

- 효과크기 d(3분위) **−0.380** / d(트레이드) −0.364 — **15분 MACD hist 가 3봉 상승 중이면 그 접촉은 더 잘 깨진다.**
- 이게 「이미 올라서 비싸게 사는」 아티팩트인지 **재검증**했다: 지지선 대비 종가 위치를 층으로 고정해도 **−0.401 / −0.490**, 지지선 지정가를 가정해도 **−0.298** 로 **살아남는다**.
- 반면 같은 계열로 의심됐던 것들은 통제하면 **사라졌다**: RSI 상향전환은 지정가 가정에서 **+0.080 으로 부호가 뒤집혔다**(= 순수 아티팩트, 버림), 아래꼬리 비율도 대부분 소멸(버림).

**해석(문서 §4-1 원문 취지)**: 지지선에 닿는 순간까지 하락 모멘텀이 살아 있으면 그건 빠른 투매고 V자 반등이 나온다. 반대로 hist 가 이미 3봉째 올라오는데도 여전히 지지선을 찍고 있으면 **반등 시도가 이미 한 번 실패했다는 뜻**이라 다음 이탈이 온다.

#### 3-3. BREAKDOWN 쪽도 같은 구조다

- CHART_REGIME 의 BREAKDOWN 정의는 `ret4 ≤ −0.92%` = **이미 1시간 내려간 뒤** → 「이미 다 빠졌다」 → 이후 +0.53%. 게다가 **인식 정밀도 15.6%** (그렇게 부른 것 6~7건 중 1건만 진짜, 나머지는 대부분 CRASH).
- SUPPORT 의 score ≤ 1 은 **접촉 순간에 1H 방향축이 죽어 있는** 상태 → 이후 −3% 도달 74.6%.

#### 3-4. 그래서 코드에는 무엇이 들어갔는가

| 것 | 코드 반영 | 이유 |
|---|---|---|
| SUPPORT 7점 판정식 | ✅ `support_score.py` + `start_stage1` 배선 | n=264, 두 그룹 모두 기준선 초과, 6개 다른 지지선 정의로 이식해도 재현 |
| CHART_REGIME 의 BOUNCE/BREAKDOWN 국면 | ❌ **의도적으로 넣지 않음** | 문서 스스로 「BOUNCE n=40, 교차검증 통과 지표 0개, 지금 수치로 로직을 만들면 안 된다」 / 「BREAKDOWN 정밀도 15.6%, 독립 진입 신호로 쓰지 말 것」이라고 결론 |

> **한 줄로**: 두 문서 모두 같은 결론을 말한다 — **「반등한 걸 보고 들어가면 진다. 지지선에 미리 걸어놔야 이긴다.」** 이는 사장님 사상(「4H 조정 구간에 미리미리 분할, 바닥 확인 X」)과도 정확히 같다.
> 🚨 **새 세션 주의**: CHART_REGIME 의 「BOUNCE 승률 31.6%」를 근거로 `support_score` 게이트를 끄거나 뒤집으면 **오독이다.** 두 숫자는 서로 다른 시점을 재고 있다.

---

### 4. Fix 325 / 326 / 327 — 무엇이 문제였고, 어떻게 고쳤고, 어떻게 되돌리나

| Fix | 커밋 | 무엇이 문제였나 | 어떻게 고쳤나 | 되돌리는 법 | 현재 상태 |
|---|---|---|---|---|---|
| **325** | `0459e8f` | 진입 대상이 절대값 `\|24h\| ≥ 10%` 라 조용한 날 대상이 급감 (실측: 거래대금 5M 이상 **252심볼 중 26개 = 10.3%**) | 사장님 지시대로 **상승 50위 + 하락 50위 = 100개 순위**로 전환 | `entry_chg24_gate_mode='abs'` (DB) → 옛 절대값 / 게이트 자체를 끄려면 `entry_chg24_gate_enabled='0'` / 코드 되돌리려면 `git revert 0459e8f` | 🚨 **동작 중** (mode 행 없음 = 기본 rank) |
| **326** | `1d04598` | 부분 손절로 10 USDT 를 남겨도 **다음 사이클이 전량 청산해 지워버렸다** | `compute_trim` 이 `ACTION_SKIP` 을 주면 **손절하지 않고 그대로 둔다** (두 손절 경로 모두) | `stage_trim_before_next_enabled='0'` (DB) → 부분손절 자체가 꺼져 옛 동작(전량) / `git revert 1d04598` | 🚨 **동작 중**, 단 실검증 0건 |
| **327** | `ded22f3` | 사장님 「분석해서 저장해서 **진입에 모두 사용**해줘」 — 계산만 하고 진입에 안 쓰이는 자리를 또 만들지 않기 위해 | 지지선 7점 판정(`support_score.py`)을 **`start_stage1` 단일 관문**에 배선. **기본 OFF / fail-open / 수동 제외 / 접촉 아니면 미적용** | 켜지 않으면 아무 일도 안 일어남. 껐다 켜기는 `support_score_gate_enabled` 행 삭제 또는 `'0'` / `git revert ded22f3` | ⏸ **OFF** |

##### 🚨 「되돌리는 법」을 실제로 쓰기 전에 — 위험 검토 담당의 경고

1. 🚨 **`git revert` 는 로컬만 바꾼다. 그것만으로는 운영이 되돌아가지 않는다.**
   순서는 `git revert <커밋>` → `git push origin HEAD:main` → **VPS 에서 `git pull`** → **컨테이너 재시작**. 마지막 재시작은 **사장님 몫**이다(실자금이 돌고 있다). 커밋만 되돌리고 「되돌렸다」고 보고하면 오보다 — 이 저장소는 그 사고(「fix 브랜치만 push 하고 main 은 옛 코드」)를 이미 겪었다.
2. ✅ **먼저 DB 설정으로 되돌려라 — 즉시 적용되고 재시작이 필요 없다.**
   Fix 325·326·327 세 개 다 **설정 한 줄로 옛 동작으로 돌아간다**(위 표의 왼쪽 방법). 코드 revert 는 설정으로 안 될 때만 쓴다. 배포·재시작이 끼면 그 자체가 새로운 위험이다.
3. 🚨 **`git revert 1d04598`(Fix 326) 은 「고친 것을 다시 고장내는」 revert 다.**
   되돌리는 순간 §4-2 의 실서버 사고(부분 손절 → **12~300초 뒤 전량 청산**)가 그대로 돌아온다. Fix 326 을 끄고 싶으면 revert 가 아니라 **`stage_trim_before_next_enabled='0'`** 으로 **부분 손절 자체를 끄는 것**이 맞다(그러면 원래대로 전량 손절이라 잔량이 남지 않는다).
4. 🚨 **`git reset --hard` / `git checkout .` / `git clean -fd` / `git push --force` 로 되돌리지 마라.**
   이 저장소는 worktree 를 공유하고 **커밋 안 된 작업이 실재한다**(§6-3 의 `terminal.py` 등 3,666줄). 위 명령들은 **묻지 않고 즉시 지우며 되돌릴 수 없다.** `git revert`(=새 커밋을 쌓는 방식)만 쓴다.
5. 🚨 **`git stash` / `git stash pop` 도 맨손으로 쓰지 마라.** 이 저장소엔 이미 오래된 stash 3개가 쌓여 있다(실측 `git stash list` → `stash@{0}` 는 **2026-08-24** 백업). 아무 생각 없이 `pop` 하면 **8월 24일 코드가 9월 3일 코드 위에 얹힌다.**
6. ✅ **되돌린 뒤에는 반드시 「되돌아갔는가」를 재서 확인한다** — §1-1 의 mtime vs `StartedAt` 명령. 「revert 했다」는 배포 증거가 아니다.

#### 4-1. Fix 325 상세

- 변경 파일 (`git show 0459e8f --numstat` 실측): `backend/app/services/chg24_entry_gate.py` **+86/−23**, `backend/tests/test_chg24_entry_gate.py` **+90/−12** (테스트 **23건** 통과 — §7 ② 로 재확인 가능)
- 신설 설정: `entry_rank_top_n`(기본 50, 허용 1~500 — `chg24_entry_gate.py:98 top_n()`), `entry_chg24_gate_mode`(`"rank"`(기본) | `"abs"` — `:113 gate_mode()`)
- 🚨 **「clamp」가 아니라 「기본값 복귀」다** (2026-09-03 코드 재확인). 범위 밖(예: `entry_rank_top_n=900`)이나 숫자가 아닌 값을 넣으면 **500 으로 깎이는 게 아니라 기본 50 으로 되돌아간다.** 로그에 `[Fix325] entry_rank_top_n=900 범위밖(1~500) → 기본 50` 이 한 줄 남는 것이 유일한 신호다. `entry_chg24_gate_mode` 도 `rank`/`abs` 가 아니면 조용히 `rank` 가 된다. **값을 넣은 뒤 반드시 로그로 실제 적용값을 확인할 것.**
- 판정 위치: `chg24_entry_gate.py:124 passes()` → `execution_service.py:207-228` 에서 호출 (start_stage1 안)
- 유지된 안전장치: **수동 `_quick_` 제외**, **fail-open**(시세/순위 조회 실패 시 통과), **`start_stage1` 에만 적용**(사다리를 끊지 않는다)
- 🚨 **순위 풀에 하드코딩 하한이 있다**: `app/services/market_movers.py:48 MIN_QUOTE_VOLUME = 5_000_000.0` — 설정으로 빠져 있지 않다. 「감으로 정한 값」이라고 주석에 적혀 있다(`market_movers.py:36-47`). 대상이 이상하면 여기부터 볼 것.
- 🚨 테스트에서 배운 함정(커밋 메시지): `top_movers` 는 심볼 풀이 `top_n*2` 보다 작으면 **상승/하락 목록이 겹친다**. 순위 테스트는 반대편을 두껍게 깔아야 한다.

#### 4-2. Fix 326 상세 — 실서버 사고 로그가 근거

커밋 메시지에 남은 2026-09-03 실서버 로그:

| 시각 | 사건 |
|---|---|
| 07:55:00 | MARSCOIN #2091 부분 손절 → 184 잔여(명목 20.04) ✅ |
| 08:00:22 | MARSCOIN #2091 「남길 것이 없다」 → **전량 청산** ❌ (5분 뒤) |
| 08:01:52 | HEMI #2095 부분 손절 → 1173 잔여(명목 20.01) ✅ |
| 08:02:09 | HEMI #2095 「남길 만큼 크지 않다」 → **전량 청산** ❌ (17초 뒤) |
| 07:44:03 / 07:44:15 | UAI #2089 부분 손절 → 52 잔여 ✅ → **전량 청산** ❌ (12초 뒤) |

- 원인: 남긴 잔량은 여전히 손절 ROI 아래라 **다음 사이클에 또 손절 대상**이 된다. 그때 `compute_trim` 이 돌려주는 `ACTION_SKIP`(=이미 잔량 수준)을 **전량 청산으로 처리**하고 있었다.
- 정정된 판단: *"손절을 건너뛰면 손실이 무한정 커진다"* 는 **틀렸다** — 잔량 증거금이 10 USDT 면 **최대 손실도 10 USDT** 다.
- 변경 위치 (2곳 모두 고침):
  - `backend/app/services/tp_sl_orchestrator.py:545 _execute_force_stop_loss` → `:615 elif _act == ACTION_SKIP: … return`
  - `backend/app/services/tp_sl_orchestrator.py:686 _execute_stop_loss` → `:739 elif _act == ACTION_SKIP: … return`
- 동작표: `ACTION_TRIM` → 부분 손절(변경 없음) / `ACTION_SKIP` → **손절 안 함, 잔량 유지** / `ACTION_BLOCK` → 전량 청산(판정 불가, 안전측) — 세 갈래 모두 코드에서 확인함(TRIM/SKIP/전량 = `tp_sl_orchestrator.py:609 / :615 / :625`, 그리고 `:733 / :739 / :748`).

##### 🚨 위험 검토 — Fix 326 을 만지기 전에 반드시 읽을 것 (2026-09-03 실측)

**(가) 코드 주석이 지금 코드와 정반대다 — 속지 마라.**
`app/services/stage_trim.py:320-321` 에 이렇게 적혀 있다:

```
⚠️ 손절 경로는 SKIP 을 받으면 스스로 전량으로 떨어진다(손절은 반드시
   나가야 한다). 단계 진입 경로만 「그냥 진입」이 된다.
```

🚨 **이 주석은 Fix 326 이전 이야기이고, 지금은 틀렸다.** Fix 326 이 바로 그 「전량으로 떨어진다」를 없앴다 — 지금 손절 경로는 SKIP 을 받으면 **`return` 해서 아무것도 하지 않는다**(`tp_sl_orchestrator.py:615`, `:739`). 이 저장소가 반복해서 당한 함정(「주석은 정답을 적어 놨는데 코드가 안 함」)의 **부호만 뒤집힌 형태**다. 코드를 만질 사람은 **주석 말고 `tp_sl_orchestrator.py:615/739` 를 직접 볼 것.** (📌 다음 세션 작은 할 일: 이 주석 3줄을 현재 동작에 맞게 고치기. 이번 검토는 **문서만** 고쳤고 코드는 손대지 않았다.)

**(나) 🚨 `stage_keep_notional_usdt` 를 키우면 손절이 사실상 전면 중단된다.**

| 실측 | 값 |
|---|---|
| 허용 범위 | `0 < v ≤ 10000` (`stage_trim.py:176`) — **상한이 10,000 이다** |
| 목표 잔량(명목) | `keep_notional × 레버리지` (`stage_trim.py:294`) |
| 보유 명목 ≤ 목표 잔량이면 | `ACTION_SKIP` (`stage_trim.py:322-326`) → **Fix 326 이후 손절 자체를 건너뛴다** |

→ 예: `stage_keep_notional_usdt = 1000`, 레버 10 이면 목표 잔량 명목 **10,000 USDT**. 사실상 **모든 포지션이 SKIP** 이 되어 **손절이 하나도 나가지 않는다.** 기본값 10 에서는 최대 노출이 증거금 10 USDT 라 안전하지만, **이 값을 키우는 것은 「손절 끄기」와 같다.**
- 🚨 §6-3(P3)에서 이 키에 UI 를 붙일 때 **입력 상한을 코드 상한(10000)에 맞추지 말 것.** 화면에서는 **10~50 정도로 좁게 clamp** 하고, 그보다 큰 값은 경고와 함께 거부하는 편이 안전하다.
- 🚨 되돌리기: 값을 지우거나(행 삭제) `10` 으로 되돌리면 즉시 원복된다(재시작 불필요 — 매 호출마다 DB 를 읽는다).

**(다) 「최대 손실 10 USDT」는 격리(ISOLATED) 전제다.** 이 시스템은 모든 진입에서 `ensure_isolated_margin()` 을 부르지만(`execution_service.py:270`), 누군가 바이낸스 앱에서 그 심볼을 CROSS 로 바꿔 놓으면 그 전제가 깨진다. 「손절을 건너뛰어도 안전하다」는 판단의 **바닥이 격리 마진**이라는 점을 기억할 것.
- 🚨 기대를 뒤집은 테스트: `test_1단계_소액은_손절하지_않는다` — 원래 「전량 손절되어야 한다」였는데 사장님 사양과 **반대**였다(「첫진입이 10이라 손절없이 그냥 좋은 포지션에 2단계 300으로 진입」).
- 테스트: `tests/test_stop_loss_execution_path.py`(실서버 사고 2건 재현 포함) — 커밋 당시 16건, **2026-09-03 현재 17건**(Fix 327 이후 1건 추가). §7 ② 명령이 `62 passed` 를 내면 정상.
- 🔁 **교훈**: 부분 청산을 만들면 「남긴 것」이 **다음 사이클에 어떻게 취급되는지 반드시 따라가라.** 한 번의 부분 손절이 성공해도 다음 사이클이 지우면 사양은 구현되지 않은 것과 같다.

#### 4-3. Fix 327 상세 — 배선 위치와 5중 안전장치

```
backend/app/services/execution_service.py:188  start_stage1()
  ├ :207-228   Fix 310/325  chg24 게이트 (본보기)
  ├ :230-268   Fix 327      지지선 7점 게이트   ← 이번에 추가
  └ :270       ensure_isolated_margin()  ← 실주문 부수효과는 여기부터
```

| 안전장치 | 구현 위치 |
|---|---|
| ① 기본 OFF (`support_score_gate_enabled`) | `support_score.py:128 gate_enabled` |
| ② fail-open (조회/판정 실패는 통과) | `support_score.py:365, 401` + `execution_service.py:257-259` |
| ③ **지지선 접촉이 아니면 막지 않음** (판정식 표본 밖) | `support_score.py:397-398` |
| ④ 1H 데이터 없으면 판정 보류 | `support_score.py:289-290` |
| ⑤ 진행 중인 봉 잘라내기 | `support_score.py:371-372` (`kl[:-1]`) |
| 🚨 `trigger_next_stage` 에는 안 검 | 사다리 정지 방지 (Fix 203/235 전력) |

- 신설 파일: `backend/app/services/support_score.py` (403줄), 테스트 `backend/tests/test_support_score.py` **22건** (진입 경로 통합 154건, 전체 통과)
- 사전 검증(실 캔들 30심볼): 상승 +12~+49% → 6~7점 LONG / 하락 −8~−31% → 0~4점 SHORT·관망. **AKEUSDT(사장님 차트) = 1점 SHORT** — 급등 후 급락·보합을 정확히 잡았다.
- ⚠️ **확인 못 함**: 이 게이트는 실서버에서 **한 번도 실행된 적이 없다**(§1-3). 「한 번도 실행 안 된 분기는 런타임이 못 잡는다」(Fix 298 교훈).

---

### 5. `app/services/support_score.py` 7점 판정식 — 그대로 재현 가능한 표

#### 5-1. 1단계 — 지지선 찾기 `find_swing_low(lows)` (`support_score.py:220`)

| 상수 | 값 | 코드 |
|---|---|---|
| `LOOKBACK_BARS` | 96 | `:106` |
| `PIVOT_HALF_WIDTH` | 3 | `:107` |
| `EXCLUDE_RECENT` | 4 | `:108` |

```
가장 최근 i 부터 거꾸로 내려가며:
  left  = lows[i-3 : i]
  right = lows[i+1 : i+4]
  all(lows[i] < x for x in left) and all(lows[i] < x for x in right)  →  S = lows[i]
탐색 범위: max(3, n-96) ≤ i < n-4     (최근 4봉은 오른쪽 3봉이 없어 피벗 확정 불가)
없으면 (None, None) → 판정하지 않고 통과(fail-open)
```

#### 5-2. 2단계 — 접촉 판정 `is_touching(...)` (`support_score.py:244`)

| # | 조건 | 코드 | 불만족 시 사유 |
|---|---|---|---|
| 0 | `len(closes) >= 25` | `:256` | "데이터 부족" |
| — | `tol = max(0.002, 0.25 × ATR14/close)` | `:260` | (ATR 없으면 0.002) |
| 1 | `lows[-1] <= S × (1 + tol)` | `:263` | "지지선까지 안 내려옴" |
| 2 | `closes[-2] > S × (1 + tol)` | `:265` | "직전 봉이 이미 지지선 아래 (접촉이 아니라 이탈)" |
| 3 | `(close / max(highs[-24:]) − 1) × 100 <= −1.0` | `:270` | "…(고점권)" |

→ 셋 다 만족해야 **접촉**. 접촉이 아니면 score 는 계산해서 **로그에만 남기고 막지 않는다** (`:397-398`).

#### 5-3. 3단계 — 7점 채점 `compute_score(kl_15m, kl_1h)` (`support_score.py:279`)

전제: `len(kl_15m) >= 100` (`:287`), `len(kl_1h) >= 40` (`:289`). 아니면 **`None` = 판정 보류**.

| # | 규칙 id | TF | 정확한 판정식 | 코드 | 해당시 승률 | 미해당시 | Δ%p | d(A) / d(B) |
|---:|---|---|---|---|---:|---:|---:|---|
| 1 | `h1_macdh_pos` | 1h | `MACD_hist(12,26,9)[-1] > 0` | `:300` | 65.5% | 43.9% | **+21.6** | +0.688 / +0.211 |
| 2 | `h1_above_ema20` | 1h | `close[-1] > EMA20[-1]` | `:301` | 65.4% | 45.7% | **+19.7** | +0.514 / +0.223 |
| 3 | `h1_rsi12_ge_50` | 1h | `Wilder RSI(12) >= 50` | `:302-303` | 64.7% | 46.6% | **+18.1** | +0.445 / +0.185 |
| 4 | `m15_macdh_not_rising3` | 15m | 🚨 **`NOT ( hist[-1] > hist[-4] )`** (역방향) | `:310-312` | 61.5% | 42.9% | **+18.7** | −0.437 / −0.285 |
| 5 | `m15_rsi24_ge_45` | 15m | `Wilder RSI(24) >= 45` | `:313-314` | 62.7% | 46.1% | **+16.6** | +0.412 / +0.224 |
| 6 | `m15_drop96_ge_m15` | 15m | `(close[-1] / max(high[-96:]) − 1) × 100 >= −15.0` | `:315-317` | 61.6% | 41.9% | **+19.8** | +0.188 / +0.337 |
| 7 | `m15_above_ema50` | 15m | `close[-1] > EMA50[-1]` | `:318` | 67.7% | 50.0% | **+17.7** | +0.302 / +0.294 |

- **등가중 합** = `score` (0~7). 가중치를 붙여도 개선되지 않아 **등가중 채택**(단순 = 과적합 방어).
- 지표 구현: EMA `k=2/(n+1)`, 시드 = 첫 값(`:161-168`) / MACD hist = EMA12−EMA26 의 EMA9 뺀 값, **40봉 미만이면 None**(`:171-178`) / RSI = **Wilder**(`:181-198`) / ATR14 = 단순평균(`:201-213`).
- 🚨 4번 규칙은 **부호가 직관과 반대**다. 「이미 오르고 있으면 점수를 주지 않는다」. 이게 이 판정식의 핵심이다(§3-2).

#### 5-4. 4단계 — 결론 `decide(score, side)` (`support_score.py:327`)

| 방향 | 조건 | 기본값 | 설정 키 | 실측 |
|---|---|---|---|---|
| LONG | `score >= min_long` | **6** (`MIN_LONG_DEFAULT`, `:103`) | `support_score_min_long` (허용 0~7) | 승률 70.6% (n=80) |
| SHORT | `score <= max_short` | **1** (`MAX_SHORT_DEFAULT`, `:104`) | `support_score_max_short` (허용 0~7) | 승률 63.9% (n=67) |

🚨 **여기도 clamp 가 아니라 「기본값 복귀」다** (`support_score.py:134 _int_setting`, 2026-09-03 재확인). `support_score_min_long=9` 를 넣으면 7 로 깎이는 게 아니라 **기본 6 으로 되돌아간다** — 즉 **게이트가 느슨해지는 게 아니라 원래대로 돌아간다.** 로그 `[Fix327] support_score_min_long=9 범위밖(0~7) → 기본 6` 이 유일한 신호다. 값을 넣은 뒤 반드시 로그로 실제 적용값을 확인할 것.
| 그 외 방향 문자열 | — | 판정 안 함(통과) | — | `:341` |

전체 스위치: `support_score_gate_enabled` (`:99`) — `"1"/"true"/"on"/"yes"` 만 ON.

#### 5-5. 공용 진입점 `evaluate(db, bc, symbol, side)` (`support_score.py:348`) 흐름

```
gate_enabled 아니면 → (True, "", d)                       # 아무것도 안 함
get_klines(15m limit=200) / get_klines(1h limit=120)      # 실패 → fail-open 통과
kl15c = kl15[:-1] / kl1hc = kl1h[:-1]                     # 진행 중 봉 제거
find_swing_low → 없으면 fail-open 통과
is_touching → touching / why_t
compute_score → None 이면 fail-open 통과
decide(score, side, min_long, max_short)
  ├ 접촉 아님 → (True, "지지선 접촉 아님 … [n/7점]")       # 기록만
  └ 접촉      → (ok, why)                                  # 여기서만 실제로 막는다
예외 → fail-open 통과
```

---

### 6. 다음 할 일 — 우선순위와 시작 지점

> 🚨 **순서 주의 — 이 절의 명령을 돌리기 전에 §7 을 먼저 끝내라.** 아래는 전부 **VPS SSH** 또는 **로컬 클론**이 이미 준비돼 있다고 전제한다. 새 PC 라면 `local-env.md`(클론·파이썬) → `secrets.md`(SSH 키·`.env`) → **§7 ①②③** → 그다음이 이 절이다. §7 이 문서 뒤쪽에 있는 것은 참고용이라서가 아니라 **분량 때문**이다.

우선순위 근거: **① 이미 실자금에 영향을 주는 것 → ② 켜지 않으면 아무 효과도 없는 것 → ③ 사장님이 조작할 수 없는 것 → ④ 데이터가 안 쌓이는 것 → ⑤ 실측 근거가 확실한 개선 → ⑥ 실측이 반대인 것(재측정 먼저)**

| 순위 | 할 일 | 왜 지금 | 시작 파일 : 함수 | 위험 |
|---:|---|---|---|---|
| **P1** | **Fix 326 실검증** (손절 이벤트 시 잔량이 유지되는가) | 실자금 손절 경로를 바꿔놓고 **배포 후 이벤트 0건 = 증거 0** | `tp_sl_orchestrator.py:545 _execute_force_stop_loss` / `:686 _execute_stop_loss` — 로그 태그 `[Fix326]` | 🚨 잘못되면 손절이 **안 나간다** |
| **P2** | **Fix 327 게이트 실전 검증** (현재 OFF) | 코드는 배포됐으나 **한 번도 실행된 적 없음**. 「한 번도 실행 안 된 분기는 런타임이 못 잡는다」 | `support_score.py:348 evaluate` / 설정 `support_score_gate_enabled` | 🚨 켜면 **즉시 차단**한다 — 관찰 모드가 없다(아래 참조) |
| **P3** | **신설 스위치 UI/API** | 신설 키 **10개 전부 「쓰기(변경) 경로 0곳」** = 사장님이 켜거나 끌 방법이 DB 직접 쓰기뿐 (⚠️ 「grep 0건」은 §6-3 에서 **정정됨** — 7개는 읽기 전용 API 에 이미 있으나 **그 API 자체가 미커밋·미배포**) | `app/api/v1/strategy_suggestions.py:541 set_sajangnim_settings` 의 `fields` dict + `app/static/js/strategy-suggestions.js:1023 / :1095` | 저장 검증 실패가 **다른 필드까지 소실**시킨 전력(Fix 181) |
| **P4** | **6시간 잡 굶음 수정** (`chart_patterns` 0건) | 실측 재확인 — 오늘도 `chart_patterns = 0` | `app/workers/scheduler_runner.py:74` (`job_defaults` 신설) + `:520 chart_pattern_scan` + `:580 binance_changelog_monitor` | 🚨 되살려도 **진입엔 안 쓰인다** + 한 사이클 **API 200회**(IP ban 418 전력) |
| **P5** | **적응 TP 를 기본·OBV 경로에도** | `adaptive_tp` 호출처가 **`auto_bb_breakdown_worker` 한 곳뿐** (grep 결과). 주력인 볼밴 분할 68건은 못 받는다 | `app/workers/auto_bb_breakdown_worker.py:1826-1857`(본보기) → `pump_split_entry_worker.py:1040` / `surge_ladder_entry.py:311` / `scheduled_entry_worker.py:231` | TP 를 낮추면 큰 파도를 **조기 익절**하고 되돌릴 수 없다 |
| **P6** | **LONG 손절 −5% → −10%** | 🚨 **실측이 정반대다**(아래 6-6). 재측정 먼저 | `app/workers/auto_long_at_bottom_worker.py:164 LONG_FORCE_SL_ROI` (+ `auto_bb_breakdown_worker.py:1353, :1981`, `strategy_service.py:578`) | 🚨 Fix 253 을 되돌리는 변경 |
| (추가 후보) | **BOTTOM(저점LONG) 끄기 또는 조건 좁히기** | 156건 **−1,049.0** PF 0.28. 빼면 자동이 **흑자**(+245.4, 앞뒤 절반 모두 양수) | `app/workers/auto_long_at_bottom_worker.py` (워커 스위치) / `PATTERN_B_MIN_CHG` **`:139`** (`:140` 은 `PATTERN_B_MAX_CHG`) | **사장님 결정 사안** — 사상 변경이므로 임의로 끄지 말 것 |

#### 6-1. P1 — Fix 326 실검증 절차

「부분 손절 직후 몇 분 안에 전량 청산이 뒤따르지 않는가」를 본다.

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 24h --tail 200000 --no-log-prefix scheduler api 2>/dev/null | grep -E "\[Fix31[89]\]|\[Fix326\]" | tail -60'
```

🚨🚨 **이 명령을 돌리기 전에 반드시 읽을 것 — 그냥 보면 「Fix 326 이 고장났다」고 오독하게 된다.**

- **로그 타임스탬프는 UTC 다** (컨테이너 TZ. `date -u` 와 같은 시계다. KST = +9h).
- **배포 시각은 `2026-09-03 08:51 UTC`**(= 17:51 KST, §1-1). 그보다 **앞선 줄은 전부 옛 바이너리**가 찍은 것이다.
- 2026-09-03 09:40 UTC 에 실제로 돌려 보니 `--since 24h` 창 안에 **`전량 손절 (skip)` 이 3건 나온다**(07:44:15 UAI #2089 / 08:00:22 MARSCOIN #2091 / 08:02:09 HEMI #2095). **이건 Fix 326 이 고친 바로 그 버그의 원본 증거**이고, 셋 다 배포 **이전**이다. 실패로 세지 말 것.
- 따라서 **판정은 `08:51 UTC` 이후 줄로만** 한다. 배포 이후만 보려면 `--since` 를 배포 시각 기준으로 좁힌다:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 2026-09-03T08:52:00Z --tail 200000 --no-log-prefix scheduler api 2>/dev/null | grep -E "\[Fix31[89]\]|\[Fix326\]" | tail -60'
```

판정 기준 (**배포 시각 이후 줄만**):

| 로그 | 뜻 | 기대 |
|---|---|---|
| `[Fix319] … **부분 손절**: N 청산 / M 잔여` (강제손절 경로) / `[Fix318] … 부분 손절: …` (일반 손절 경로) | 부분 손절 성공 | 발생해도 됨 |
| `[Fix326] … 잔량 유지 — 손절하지 않음 (skip)` | **Fix 326 이 작동한 증거** | ✅ 이게 나와야 한다 |
| 같은 `#id` 에 대해 부분 손절 **직후** `전량 손절 (skip)` | Fix 326 미작동 | ❌ **배포 이후 줄에** 나오면 안 된다 |

> 태그 대응(`tp_sl_orchestrator.py` 실측): `_execute_force_stop_loss`(:545) → **`[Fix319]`**, `_execute_stop_loss`(:686) → **`[Fix318]`**. 번호가 함수 순서와 반대라 헷갈리기 쉽다.
> `[Fix326]` 은 `logger.info` 다. 컨테이너 로그 레벨은 `app/core/logging.py` 에서 **INFO** 로 고정돼 있으니 레벨 때문에 안 보일 일은 없다.
> **아무 줄도 안 나오면 「고장」이 아니라 「아직 손절 이벤트가 없음」이다.** 그때는 아래 DB 확인으로 최근 상태 변화 자체가 있었는지부터 본다.

> 🚨🚨 **최악의 시나리오와 즉시 되돌리는 법 (위험 검토 2026-09-03 추가)**
>
> P1 의 위험은 「손절이 **안** 나간다」이다. 아래가 보이면 **판단을 미루지 말고 즉시 되돌린다.**
>
> **위험 신호**: `[Fix326] … 잔량 유지 — 손절하지 않음` 이 **같은 `#id` 에 계속 반복**되는데 그 포지션의 손실이 **커지고 있다** (= 남은 잔량이 「10 USDT 급 소액」이 아니라는 뜻).
>
> **즉시 되돌리기 — 재시작 불필요, 다음 사이클부터 옛 동작(전량 손절)으로 돌아간다**:
>
> ```bash
> # 🚨 운영 DB 쓰기. 부분 손절 기능 자체를 끈다 = 손절이 다시 전량으로 나간다.
> ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
> from app.core.database import SessionLocal
> from app.models.system_setting import SystemSetting
> db = SessionLocal()
> row = db.get(SystemSetting, \"stage_trim_before_next_enabled\")
> if row:
>     row.value = \"0\"
>     db.commit()
> print(\"stage_trim_before_next_enabled =\", (row.value if row else \"(행 없음 = OFF)\"))
> "'
> ```
>
> - ✅ **왜 이게 옳은 되돌리기인가**: `trim_enabled` 가 False 면 `compute_trim` 자체를 부르지 않아 `ACTION_SKIP` 이 나올 수 없고, 손절은 **전량**으로 나간다(`tp_sl_orchestrator.py:603`, `:727` 의 `if trim_enabled(...)` 가 통째로 건너뛰어진다). **`git revert` 도 재배포도 필요 없다.**
> - 🚨 **`git revert 1d04598` 로 되돌리지 마라** — §4 의 경고대로 그건 §4-2 의 실서버 사고(부분 손절 12~300초 뒤 전량 청산)를 **되살린다.**
> - ⚠️ **다시 켜기**: 같은 명령에서 `"0"` → `"1"`. 켜기 전에 왜 껐는지 로그를 남길 것.

같은 전략이 살아남았는지 DB 로도 확인:

> 🚨 **이 문서의 이전 판에 있던 `now() - interval %(w)s` 는 돌지 않는다.** 2026-09-03 실행 결과 `psycopg2.errors.SyntaxError: syntax error at or near "s"`. Postgres 에서 `interval` 뒤에는 **리터럴만** 올 수 있어 바인딩 파라미터를 그대로 붙일 수 없다. 아래처럼 **`cast(:w as interval)`** 로 써야 한다. (그리고 SQLAlchemy `text()` 의 바인딩 표기는 `%(w)s` 가 아니라 **`:w`** 다.)
> 🚨 쿼리가 한 번 실패하면 그 세션은 죽는다 — **다음 쿼리 전에 `db.rollback()`** 을 부를 것.

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
sql = text(\"select id, symbol, side, status, current_stage, updated_at from strategy_instances where updated_at > now() - cast(:w as interval) order by updated_at desc limit 30\")
for r in db.execute(sql, {\"w\": \"24 hours\"}).fetchall():
    print(r)
"'
```

> ⚠️ `updated_at` 은 **가격 갱신에도 찍힌다** — 2026-09-03 09:42 UTC 실행에서 `STAGE1_OPEN` 8건이 전부 **동일한 초**로 나왔다(일괄 갱신). 「배포 후 새 진입이 있었는가」를 보려면 `updated_at` 이 아니라 **`created_at`** 을 봐야 한다:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
sql = text(\"select id, symbol, side, status, created_at from strategy_instances where created_at > cast(:t as timestamptz) order by created_at desc limit 20\")
rows = db.execute(sql, {\"t\": \"2026-09-03T08:51:00Z\"}).fetchall()
print(\"배포 이후 생성 건수:\", len(rows))
for r in rows: print(r)
"'
```

2026-09-03 09:45 UTC 실측 = **0건**. 즉 배포 후 55분간 신규 1단계 진입이 없었다는 §1-3 의 진술은 그 시점까지 유효하다. **`:t` 값을 새 배포 시각으로 바꿔서 다시 재라.**

#### 6-2. P2 — Fix 327 게이트 켜기 / 끄기

🚨 **이 명령은 운영 DB 쓰기다. 실자금 진입 판정이 즉시 바뀐다. 사장님이 판단해 실행할 것.**
🚨 **관찰 모드(막았을 것만 로그)가 구현돼 있지 않다.** 현재 구현은 켜는 즉시 `raise ValueError` 로 **실제 차단**한다 (`execution_service.py:260-265`). Fix 247 이 쓴 「먼저 로그만 남기고 사장님이 켠다」 방식을 원하면 **먼저 그 모드를 만들어야 한다.**

> 확인함(2026-09-03 재검증): 게이트가 OFF 면 `evaluate` 가 **첫 줄에서 그냥 통과**하고 점수 계산조차 하지 않는다(§5-5, `support_score.py:128`). 그래서 **켜기 전에는 「몇 점이 나왔을지」를 알 방법이 로그에도 없다.** 이게 관찰 모드가 필요한 이유다.
> 🚨 반면 `GET /api/v1/terminal/symbol-status` 는 **`support_gate_enabled`(on/off)만** 돌려주고 **점수는 돌려주지 않는다**(`terminal.py:1029-1035`). 「터미널 화면에서 미리 볼 수 있다」고 **오해하지 말 것** — 미리 보이는 것은 24h 순위 게이트의 통과 여부뿐이다(§6-3). 🚨 게다가 그 라우터는 **운영 VPS 에 배포조차 돼 있지 않다**(실측: VPS `router.py` 에 `terminal` 0건 → **404**). §6-3 의 「커밋 안 됨」 경고를 볼 것.
> 💡 위험을 낮추는 순서: **관찰 모드를 먼저 만든다 → 하루 로그를 본다 → 켠다.** 지금 바로 켜면 첫 차단이 실자금 진입을 막는 순간에 처음 실행된다.

켜기:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from app.models.system_setting import SystemSetting
db = SessionLocal()
row = db.get(SystemSetting, \"support_score_gate_enabled\")
if row: row.value = \"1\"
else: db.add(SystemSetting(key=\"support_score_gate_enabled\", value=\"1\", description=\"Fix 327 지지선 7점 게이트\"))
db.commit()
print(\"support_score_gate_enabled =\", db.get(SystemSetting, \"support_score_gate_enabled\").value)
"'
```

끄기 (되돌리기):

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from app.models.system_setting import SystemSetting
db = SessionLocal()
row = db.get(SystemSetting, \"support_score_gate_enabled\")
if row: row.value = \"0\"; db.commit()
print(\"support_score_gate_enabled =\", (row.value if row else \"(행 없음 = OFF)\"))
"'
```

켠 뒤 관찰 (차단·통과 사유가 전부 로그로 나온다):

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 3h --tail 100000 --no-log-prefix scheduler api 2>/dev/null | grep "\[Fix327\]" | tail -60'
```

> 참고: 재시작 없이 적용된다 — `gate_enabled` 가 매 호출마다 DB 를 읽는다(`support_score.py:128-131`).
> 임계값만 완화하고 싶으면 같은 방식으로 `support_score_min_long`(0~7) / `support_score_max_short`(0~7) 를 넣는다.

##### 🚨 켜기 전에 — 위험 검토 담당이 추가한 3가지 (2026-09-03 실측)

1. 🚨 **차단이 로그에 「❌ 실 진입 실패」로 보인다. 고장으로 오진하지 말 것.**
   게이트는 `start_stage1` 안에서 `raise ValueError("[Fix327] … 진입 차단: …")` 를 던지고, 호출자들은 그것을 **일반 예외로 받아** 「실 진입 실패」로 찍고 **좀비 정리 경로**로 넘어간다 (`auto_bb_breakdown_worker.py:2036-2042` / `surge_ladder_entry.py:312-313`).
   → 켠 뒤에는 **① 전략 인스턴스가 만들어졌다가 곧바로 STOPPED 로 남는 건수가 늘고 ② 「실 진입 실패」 경고가 늘어난다.** 이건 **정상이고 설계대로**다. 진짜 고장과 구별하려면 **같은 줄에 `[Fix327]` 이 있는지**를 보면 된다.
   ✅ 확인함: 호출자 8곳이 전부 `try/except` 로 감싸고 있어 **게이트가 워커를 죽이지는 않는다**(다른 심볼 처리는 계속된다).
2. ✅ **켜기 전에 현재 값을 먼저 적어 둬라** — 되돌릴 기준점이다. 위 §1-2 조회 명령을 한 번 돌려 출력을 남긴 뒤 켠다. (지금은 **행 자체가 없음** = OFF 가 기준점이다.)
3. 🚨 **켠 뒤 30분 안에 「진입이 통째로 멈추지 않았는지」를 확인하라.**
   이 게이트는 지지선 **접촉일 때만** 막지만, 접촉 시 score 2~5 구간은 **LONG·SHORT 양쪽 다 막힌다**(LONG 은 ≥6, SHORT 는 ≤1). 진입이 0 이 되면 즉시 위 「끄기」로 되돌린다 — **끄기는 재시작 없이 다음 호출부터 적용된다.**

```bash
# 켠 뒤 관찰: 차단 건수 vs 통과 건수 (숫자만 빠르게)
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 3h --no-log-prefix scheduler api 2>/dev/null | grep -c "\[Fix327\].*진입 차단"'
```

#### 6-3. P3 — 신설 스위치 UI/API

**실측 (2026-09-03 재검증에서 정정됨)**: 아래 10개 키는 **쓰기(설정 변경) 경로가 0곳**이다 — 사장님이 켜거나 끌 방법이 **DB 직접 쓰기뿐**이라는 결론은 그대로다.

🚨 **다만 「grep 결과 전부 0」은 틀렸다.** 재검증하니 7개 키가 **읽기 전용으로는 이미 API 에 노출돼 있다** — 🚨 **단, 아래 「커밋 안 됨」 경고를 먼저 읽을 것**:

- `app/api/v1/terminal.py:942 GET /api/v1/terminal/symbol-status?symbol=<심볼>` (`router = APIRouter(prefix="/terminal")`, `app/api/router.py:49` 에서 등록)
- 돌려주는 것: `chg24_gate.{enabled,mode,top_n,min_abs,passes,reason}` (`:1000-1027`) / **`support_gate_enabled`** (`:1029-1035`) / `trim.{enabled,keep_notional_usdt}` (`:1037-1044`) / `reentry` (Fix 301)
- 즉 `entry_chg24_gate_enabled` · `entry_chg24_gate_mode` · `entry_rank_top_n` · `entry_min_abs_chg24` · `support_score_gate_enabled` · `stage_trim_before_next_enabled` · `stage_keep_notional_usdt` **7개는 SSH 없이도 상태를 볼 수 있다.**
- 이 라우터는 「모름」을 `passes=null` 로 주고 `false` 로 뭉개지 않는다(2026-08-28 fail-OFF 사고 반영). 화면을 만들 때 이 규약을 깨지 말 것.

여전히 **읽기조차 없는 것**: `support_score_min_long` / `support_score_max_short` / `adaptive_tp_enabled` / `confluence_gate_enabled` / `force_sl_unlock_unreachable_stage`.

> 🔁 **교훈**: 「grep 0건」이라고 적을 때는 **어떤 디렉터리에서 무슨 패턴으로** 쟀는지 같이 적어라. 위 5개 키는 `terminal.py:954-955` 주석에 문자열로 실재해서, 새 세션이 grep 하면 곧바로 문서와 어긋난다.

##### 🚨🚨 위 터미널 API 는 **커밋되지 않았다 — 운영에도 GitHub 에도 없다** (2026-09-03 위험 검토 실측)

이 한 줄을 놓치면 새 PC 에서 **3,666줄이 통째로 사라진다.**

| 확인 | 명령 | 결과 |
|---|---|---|
| 저장소에 추적되는가 | `git ls-files backend/app/api/v1/terminal.py` | **출력 없음 = 추적 안 됨** |
| 작업트리 상태 | `git status --porcelain` | `?? backend/app/api/v1/terminal.py` (1,185줄) / `?? backend/app/static/perp-terminal.html` (2,481줄) / ` M backend/app/api/router.py` (터미널 라우터 등록 2줄) |
| **운영 VPS 에 있는가** | `ssh … 'grep -c "terminal" backend/app/api/router.py'` | **`0`** — VPS `router.py` 에 terminal 라우터가 **등록돼 있지 않다** |
| VPS 파일 | `ssh … 'ls backend/app/api/v1/terminal.py'` | **`No such file or directory`** |
| 백업(`docs/handoff/wip-backup-2026-09-03/`)에 들어 있는가 | `find … -name terminal.py` | **없음.** 백업은 `main` / `charming-albattani` / `loving-rhodes` **3개 worktree 만** 담았고 **이 worktree(`infallible-euler-6dc297`)는 빠져 있다** |

**그래서 실제로는 이렇다:**

1. 🚨 **운영 서버에서 `GET /api/v1/terminal/symbol-status` 는 404 다.** 「SSH 없이도 상태를 볼 수 있다」는 **지금 사장님에게 해당되지 않는다.** 배포하려면 먼저 커밋·푸시하고 VPS 에 배포해야 한다.
2. 🚨 **새 PC 에서 GitHub 을 클론하면 이 세 파일 변경은 따라오지 않는다.** `terminal.py` + `perp-terminal.html` + `router.py` 수정이 **영구 소실**된다.
3. ✅ **살리는 방법 (사무실 PC 에서 먼저 할 것 — 새 PC 로 가기 전)**: 아래 중 하나.

```bash
# (A) 권장 — 커밋해서 GitHub 으로 보낸다. 문서·화면 파일이라 배포와 무관하게 안전하다.
cd "C:/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297" \
  && git add backend/app/api/v1/terminal.py backend/app/static/perp-terminal.html backend/app/api/router.py \
  && git status --short           # ← 무엇이 담겼는지 눈으로 확인하고 나서 커밋
```

```bash
# (B) 커밋하고 싶지 않으면 최소한 백업 폴더에 복사해 둔다 (파괴적 명령 없음).
cd "C:/Users/user/바이낸스/binance-auto-trader/.claude/worktrees/infallible-euler-6dc297" \
  && mkdir -p docs/handoff/wip-backup-2026-09-03/infallible-euler_terminal/untracked/backend/app/api/v1 \
  && mkdir -p docs/handoff/wip-backup-2026-09-03/infallible-euler_terminal/untracked/backend/app/static \
  && cp backend/app/api/v1/terminal.py       docs/handoff/wip-backup-2026-09-03/infallible-euler_terminal/untracked/backend/app/api/v1/ \
  && cp backend/app/static/perp-terminal.html docs/handoff/wip-backup-2026-09-03/infallible-euler_terminal/untracked/backend/app/static/ \
  && git diff backend/app/api/router.py > docs/handoff/wip-backup-2026-09-03/infallible-euler_terminal/router.patch
```

> 🚨 **절대 하지 말 것**: `git stash`, `git reset --hard`, `git checkout .`, `git clean -fd`.
> 이 저장소는 worktree 를 공유하고, 위 세 파일은 **추적조차 안 되는 상태**라 그 명령 하나로 **경고 없이 즉시 소멸**한다. 되돌릴 방법이 없다 (`claude-state.md:338-339` 와 같은 경고).
>
> 🚨 **배포까지 하려면**: 커밋·푸시한 뒤 **VPS 에서 `git pull` + 컨테이너 재시작**이 필요하다. 재시작은 **사장님 몫**이다(실자금이 돌고 있다). 커밋만 해서는 운영 404 가 그대로다.

| 키 | 관련 Fix | 기본값 |
|---|---|---|
| `support_score_gate_enabled` / `support_score_min_long` / `support_score_max_short` | 327 | OFF / 6 / 1 |
| `entry_chg24_gate_enabled` / `entry_chg24_gate_mode` / `entry_rank_top_n` | 310, 325 | ON(DB) / rank / 50 |
| `adaptive_tp_enabled` | 299 | OFF (DB 엔 1) |
| `stage_trim_before_next_enabled` | 304~326 | OFF (DB 엔 1) |
| `confluence_gate_enabled` | 247 | OFF (DB 엔 true) |
| `force_sl_unlock_unreachable_stage` | 235 | OFF |

착수 지점: `app/api/v1/strategy_suggestions.py:541 @router.put("/sajangnim-settings")` 안의 `fields` dict(`:552~579`)에 `(payload_key, sanitizer)` 를 추가하고, `app/api/v1/strategy_suggestions.py:251 @router.get("/sajangnim-settings")` 에 읽기를 추가한 뒤, `app/static/js/strategy-suggestions.js:1023`(읽기) / `:1095`(저장)에 입력칸을 붙인다.

🚨 주의 5가지:
1. **`?v=` 캐시 버스터** — 정적 파일을 고치면 반드시 갱신(과거 18개가 낡아 화면만 옛 코드였던 전력).
2. **검증 실패 시 `HTTPException(400)`** 으로 던질 것. `return {"error": …}` 는 HTTP 200 이라 프론트가 「저장 완료」를 띄우고 **그 요청의 다른 필드까지 소실**된다(Fix 181, `:637-644` 주석).
3. **HTML 기본값이 DB 를 덮는 사고 전력**(Fix 188~194) — 화면 기본값과 코드 기본값을 반드시 일치시킬 것.
4. 🚨 **화면에 붙이는 순간 이 키들은 「한 번의 오타로 실자금 동작이 바뀌는 스위치」가 된다.** 특히 `stage_keep_notional_usdt` 는 **코드 상한이 10,000** 이라 큰 값을 넣으면 **손절이 사실상 전면 중단**된다(§4-2 (나)). **화면에서는 10~50 으로 좁게 clamp** 하고, 그 밖의 값은 저장을 거부할 것.
5. 🚨 **끄는 방법을 켜는 방법과 같은 화면에 같이 놓을 것.** 이 저장소는 「0 을 넣으면 20 으로 둔갑해 끄기가 작동 안 하던」 사고(Fix 107~110)를 겪었다. 저장 후 **DB 에서 다시 읽어 화면에 되비추는지** 반드시 확인하라 — 「저장했다」는 「저장됐다」가 아니다.

#### 6-4. P4 — 6시간 잡 굶음

원인 두 겹 (§2-4). 고칠 자리:

| 무엇 | 어디 | 어떻게 |
|---|---|---|
| misfire 1초 | `app/workers/scheduler_runner.py:74` | `BlockingScheduler(timezone="Asia/Seoul", job_defaults={"misfire_grace_time": 300, "coalesce": True})` — ⚠️ **잡 전체에 영향**. 2026-09-03 실측으로 `scheduler.add_job` 이 **62회**(무조건 등록 60 + 조건부 2)다: `grep -c "^    scheduler\.add_job" app/workers/scheduler_runner.py`. 먼저 어떤 잡이 미스파이어를 재실행하면 위험한지 확인할 것 |
| 6시간 주기 자체 | `:520 chart_pattern_scan`, `:580 binance_changelog_monitor` | 주기를 **≤4시간**으로 낮추거나 `CronTrigger` 로 고정 시각화. **72시간에 57회 재시작**하는 환경에선 6시간 잡이 구조적으로 굶는다 |
| 재시작 원인 | ⚠️ **확인 못 함** | 배포인지 크래시 루프인지 미확인. `[scheduler] another node is leader; exiting` 이 15초에 5회 연속 찍힌 구간이 있어 **리더 경합 루프** 가능성 (감사 부록 B-3) |
| 부수 결함 | `pattern_collector.py:28`(수집 `>=60`) vs `pattern_detector.py:33-34`(탐지 `<100` 이면 **조용히** 빈 리스트) | 60~99봉 심볼은 수집만 되고 탐지가 통째로 스킵된다. 로그 없음 |
| 🚨 **진입에 안 쓰임** | `ChartPattern` 읽기 = 쓰기 2곳 + 화면 2곳, **진입 0곳** | 스케줄만 고치면 **Fix 247 과 같은 자리**가 된다. 반드시 같이 고칠 것 |

> 🚨🚨 **위험 검토 — 위 표 첫 줄(`job_defaults` 전역 설정)을 그대로 하지 마라.**
>
> `BlockingScheduler(..., job_defaults={"misfire_grace_time": 300})` 는 **등록된 62개 잡 전부**의 동작을 한 번에 바꾼다. 이 스케줄러는 **72시간에 57회 재시작**하는 환경이고, 재시작 직후에는 **1분·2분 주기 진입/손절/청산 잡들이 전부 「놓친 실행」 상태**다. 지금은 그것들이 `misfire_grace_time=1초` 때문에 **조용히 폐기**되고 있는데, 300초로 늘리면 **부팅하자마자 수십 개 잡이 한꺼번에 발사된다.**
> - → **바이낸스 API 버스트 → 418 IP ban**(Fix 117/122 와 정확히 같은 모양). ban 이 나면 **손절도 못 나간다.**
> - → 진입 워커가 한 번에 몰려 돌면 **의도치 않은 동시 진입**이 날 수 있다.
> - `coalesce: True` 는 「밀린 여러 번을 한 번으로」 합쳐줄 뿐, **여러 잡이 동시에 뜨는 것**은 막지 못한다.
>
> ✅ **안전한 방법 — 전역이 아니라 그 두 잡에만 건다** (`add_job` 은 잡별 `misfire_grace_time` 을 받는다):
>
> ```python
> # scheduler_runner.py — chart_pattern_scan / binance_changelog_monitor 각각의 add_job 에만 추가
> misfire_grace_time=3600,   # 이 잡만. 전역 job_defaults 는 건드리지 않는다.
> ```
>
> 이러면 **다른 60개 잡의 부팅 시 동작이 한 글자도 바뀌지 않는다.** 전역 변경은 되돌리기도 어렵다(무엇이 달라졌는지 로그로 분리되지 않는다).
> 🚨 **되돌리는 법**: 이건 **코드 변경**이라 DB 토글로 못 되돌린다 → `git revert` + push + VPS `git pull` + **재시작(사장님)**. 그래서 P4 는 **P1·P2 를 끝낸 뒤**에 손대는 것이 맞다.

수동으로 한 번 돌려볼 수 있는 경로(⚠️ **DB 쓰기 + 바이낸스 API 약 200회** — IP ban 전력 Fix 117/122):

🚨 **주의 — `curl -X POST http://159.65.137.250/api/v1/chart-patterns/scan-now` 는 그냥은 안 된다.**
이 엔드포인트는 `user_id: int = Depends(get_current_user_id)` 가 붙어 있어(`app/api/v1/chart_patterns.py:124-128`) **JWT 없이는 401** 이다. 2026-09-03 실측:

```
$ curl -s http://159.65.137.250/api/v1/chart-patterns/summary
{"detail":"Not authenticated"}          # HTTP 401
```

토큰을 받아오려면 사장님 로그인 계정이 필요하다(`POST /api/v1/auth/token`, form-encoded). **비밀번호를 이 문서나 채팅에 적지 말 것.**
토큰 없이 같은 일을 하려면 **스케줄러가 부르는 함수를 컨테이너 안에서 직접 부른다** — `scheduler_runner.py:515-518` 과 동일한 코드다:

```bash
# 🚨 실행 전 사장님 승인 필요 — 바이낸스 API 약 200회 연속 호출 + chart_patterns DB 쓰기
# 🚨 IP ban(418) 전력이 있다(Fix 117/122). 한 번만, 관찰하면서 돌릴 것.
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from app.core.crypto import decrypt_text
from app.agents.chart_pattern_learning_team.team_lead import ChartPatternLearningTeamLead
with SessionLocal() as db:
    print(ChartPatternLearningTeamLead().run_full_scan(db, decrypt_text, top_n=100))
"'
```

🚨 **위험 검토 담당의 보충 (2026-09-03 실측) — 위 스캔을 돌리기 전에**

| 항목 | 실측 | 뜻 |
|---|---|---|
| 실제 호출 수 | `get_24hr_ticker()` **1회** + `get_klines(4h, limit=200)` **최대 100회** = **≈101 요청** (`pattern_collector.py:20-33` 수집 / `:34` 심볼 목록) | 「200회」는 **요청 수가 아니라 가중치**에 가깝다. 4h/limit200 은 요청당 가중치 2 → **총 ≈205** |
| 지연 없음 | `team_lead.py:68` `for sym in symbols:` — **sleep 이 하나도 없다** | 101 요청이 **연달아** 나간다. IP ban(418) 이 바로 이 모양에서 났다(Fix 117/122) |
| 🚨 **부담을 줄이려면** | `top_n=100` 을 **`top_n=10` 으로 먼저** 돌려 본다 | 같은 코드 경로를 **1/10 비용**으로 검증할 수 있다. 잘 돌면 그때 100 으로 올린다 |
| 🚨 **되돌리는 법** | **없다 — `chart_patterns` 에 행이 쌓이고 지우는 명령은 이 문서에 싣지 않는다** | 운영 DB 를 **DELETE 하는 명령을 문서에 두지 않는 것이 의도**다. 이 스캔은 **읽기 전용이 아니다**. 그래서 「사장님 승인」이 필요하다 |
| ✅ 안전한 점 | 이 잡은 **주문을 만들지 않는다**(패턴 탐지·저장·결과 갱신뿐) | 자금이 나가지는 않는다. 위험은 **IP ban 과 DB 쓰기**뿐이다 |

> 🚨 **IP ban 이 나면 자동매매 전체가 멈춘다.** 이 시스템은 **하나의 계정·하나의 IP** 로 진입·손절·청산을 전부 처리한다. 418 을 맞으면 **손절도 못 나간다.** 「패턴 데이터를 채우려다 손절을 못 하는」 교환은 절대 하지 말 것 — 그래서 P4 는 **P1·P2 다음**이다.
> ✅ **돌리기 좋은 때**: 포지션이 적을 때(지금은 `STAGE1_OPEN` 8건). 포지션이 많은 날에는 돌리지 마라.

돌린 뒤 결과 확인(읽기 전용):

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose exec -T -e PYTHONPATH=/app api python -c "
from app.core.database import SessionLocal
from sqlalchemy import text
db = SessionLocal()
print(\"chart_patterns:\", db.execute(text(\"select count(*) from chart_patterns\")).scalar())
"'
```

현재 상태 재확인:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 72h --tail 400000 --no-log-prefix scheduler 2>/dev/null | grep -c "interval\[6:00:00\].*Running job"'
```

🚨 **`--since 72h` 라고 써도 72시간이 나오지 않는다.** 2026-09-03 09:50 UTC 실측: 이 명령이 실제로 훑는 로그의 **가장 오래된 줄이 `2026-09-02 14:45 UTC`** = 약 **19시간분**뿐이다(컨테이너 재생성 시 로그가 함께 사라진다). 먼저 이걸 확인하고 해석할 것:

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader/backend && docker compose logs --since 72h --tail 400000 --no-log-prefix scheduler 2>/dev/null | head -1 | cut -c1-30'
```

- **재현되는 것**: `interval[6:00:00]` **Running job = 0**. 2026-09-03 09:50 UTC 재실측에서도 **0** 이었다 = 핵심 주장은 살아 있다.
- **재현되지 않는 것**: 감사 당시의 「missed 18」·「72시간에 57회 재시작」. 같은 시각 재측정은 **missed 3** 이었다 — 로그 창이 19시간으로 줄었기 때문이다. **숫자가 다르다고 감사가 틀린 게 아니다.** 개수를 다시 인용하려면 위 `head -1` 로 **실제 창 길이를 먼저 재고** 함께 적을 것.

#### 6-5. P5 — 적응 TP 를 다른 경로에도

**실측 (grep)**: `adaptive_tp` 를 import 하는 곳은 `app/workers/auto_bb_breakdown_worker.py:1827` **한 곳뿐**이다. 즉 `adaptive_tp_enabled='1'` 인데도 아래 경로는 여전히 고정 TP 를 쓴다.

| 경로 | 1단계 발주 위치 | 적응 TP |
|---|---|---|
| v219 사다리 (`_create_auto_bb_strategy`) | `auto_bb_breakdown_worker.py:2029` | ✅ 적용됨 (`:1826-1857`) |
| **볼밴 분할** (`pump_split`, 주력 68건) | `pump_split_entry_worker.py:1040` | ❌ |
| 급등 사다리 | `surge_ladder_entry.py:311` | ❌ |
| 예약 진입 | `scheduled_entry_worker.py:231` | ❌ |
| 청산 후 재진입 / 사다리 재시작 | `auto_reentry_worker.py:163` / `ladder_restart_worker.py:310` | ❌ |
| 화면 수동 시작 | `api/v1/strategies/control.py:47` | ❌ (수동은 제외가 맞을 수 있음 — 사장님 판단) |

근거 숫자(`adaptive_tp.py` 헤더): 구간별 기대값에서 **TP15 가 최선인 구간은 `|24h| 15~30%` 하나뿐**(+0.51)이고 나머지는 **−0.94 ~ −4.30**. 설계 R=3.00 인데 실효 R=1.01 이 된 원인이다.
⚠️ 이 측정은 **손절 ROI −10% 를 가정**했다. 현재 자동 LONG 실운영은 **−5%**(P6 참조)이므로 **손절을 바꾸면 이 표를 다시 재야 한다.**

#### 6-6. P6 — 🚨 「LONG 손절 −5% → −10%」는 실측과 반대다

| 근거 | 내용 |
|---|---|
| `auto_long_at_bottom_worker.py:141-164` (Fix 253, 2026-09-01) | **10% → 5% 로 조인 것**이 최근 변경이다. 「LONG 이 이틀 연속 승자 0명(08-31 12건 0% / 09-01 11건 0%)」, 「이익 중인 LONG 13건의 최저 ROI 가 −0.1~−4.3% = **−5% 를 건드린 승자가 한 건도 없다**」, 「느슨한 손절이 승률을 올린 게 아니라 **잃는 크기만 2배로 키웠다**」 |
| `REGIME_REAL_TRADE_VALIDATION` §2-3 | BOTTOM(저점LONG)의 **최대손실 중앙값 −5.02%** vs TOP(정점SHORT) −1.48%. 손절을 늘리면 이 꼬리가 그대로 커진다 |
| 반대쪽 근거 | `adaptive_tp` 기대값 표가 **SL −10% 가정**이므로, TP 를 3%로 낮추면서 SL 은 −5% 로 두면 표의 전제와 어긋난다 |

> **권고**: 값을 바꾸기 전에 **재측정**한다 — 「현재 이익 중인 LONG 이 −5% 아래로 간 적이 있는가」(Fix 253 주석이 지정한 그 질문). 바꾸기로 하면 **한 줄만** 고치면 된다: `auto_long_at_bottom_worker.py:164 LONG_FORCE_SL_ROI = Decimal("5")` → `Decimal("10")`.
> 🚨 다만 같은 −5% 가 **네 군데에 흩어져 있다**: `auto_long_at_bottom_worker.py:164`(LONG 전용 상수) / `auto_bb_breakdown_worker.py:1353`·`:1981`(하드코딩 `Decimal("5")`) / `strategy_service.py:578`(모든 신규 인스턴스 기본값). **한 곳만 고치면 방향에 따라 손절이 달라진다.** 설정으로 빼는 편이 낫다.
> 🚨 그리고 `spec_audit_worker.py:109-119` 가 「Fix 49 SL −5%」를 **누락 검사**하고 있다. 값을 바꾸면 이 감사 워커도 같이 봐야 한다.

---

### 7. 새 세션이 처음 30분에 할 일 (순서대로)

> 🚨 **새 PC 라면 아래 명령은 그대로는 하나도 안 돈다. 먼저 `secrets.md` 와 `local-env.md` 를 끝내고 올 것.**
> - **경로**: 아래 경로는 `local-env.md` §2 가 지정한 **메인 클론 위치**(`/c/Users/user/바이낸스/binance-auto-trader`)다. 다른 곳에 클론했으면 그 경로로 바꿔 읽을 것. 🚨 옛 PC 는 워크트리(`.claude/worktrees/infallible-euler-6dc297`)에서 작업했지만 **워크트리는 `git clone` 에 딸려오지 않는다**(`local-env.md` §9) — 새 PC 에서는 그냥 `main` 을 보면 된다. 이 세션 작업은 **전부 `origin/main`(= `e51d9a8`)에 있다**(실측 확인).
>   🚨 **정정(위험 검토 2026-09-03)**: 「이 세션 작업은 전부 `main` 에 있다」는 **틀렸다.** Fix 325/326/327 은 `main` 에 있지만, 이 worktree 에는 **커밋조차 안 된 `terminal.py`(1,185줄) / `perp-terminal.html`(2,481줄) / `router.py` 수정**이 남아 있고 **GitHub 에도 VPS 에도 백업 폴더에도 없다.** 클론하면 **사라진다.** → **새 PC 로 가기 전에 §6-3 끝의 (A) 또는 (B) 를 먼저 하라.**
> - **SSH**: `ssh root@159.65.137.250` 은 **개인키가 있어야만** 된다. 서버는 비밀번호 로그인이 꺼져 있어(`passwordauthentication no`) 키가 없으면 **우회로가 없다** (`secrets.md` §위험 3).
> - **pytest**: 2026-09-03 실측 — 아래 ②의 **3개 파일은 `backend/.env` 없이도 통과한다**(`.env` 가 아예 없는 워크트리에서 `62 passed`). `.env` 는 앱을 **띄울** 때 필요하다.
> - 🚨 **`pytest tests/` 전체는 건강 검진용으로 쓰지 말 것 — 지금도 초록이 아니다.** 같은 날 실측에서 `tests/integration/test_admin_stats_breakdown.py::TestStatsBreakdown::test_strategies_view_includes_all` 등이 **이번 세션과 무관하게** 실패한다(전체 1,766건 수집). 전체를 돌리면 없는 사고를 쫓게 된다. 아래 ②의 3개 파일만 볼 것.
>
> 🚨 **`ENCRYPTION_KEY` 경고 (이전에서 가장 위험한 지점 — `secrets.md` §3)**
> `.env` 의 `ENCRYPTION_KEY` 는 DB 의 바이낸스 API 키를 푸는 **Fernet 대칭키**다. 이걸 잃거나 **새로 생성해서 기존 DB 에 붙이면** `exchange_accounts.api_key_enc` / `api_secret_enc` 는 **수학적으로 복구 불가능**해진다. 백도어도, 복구 절차도, 「관리자 재설정」도 없다 — 바이낸스에서 **키를 새로 발급**받는 것 말고는 방법이 없다 (`backend/app/core/crypto.py`).
> - 따라서 새 PC 로 옮길 때는 **글자 하나도 바꾸지 말고 그대로 옮긴다.**
> - `deploy/generate-secrets.sh` 를 그냥 돌리면 **`ENCRYPTION_KEY` 도 새로 만든다.** 기존 DB 를 계속 쓸 거면 그 출력을 통째로 붙여 넣지 말 것.
> - 🚨 **옮기는 방법**: 카카오톡·이메일·채팅·이 대화창에 **비밀 값을 붙여 넣지 마라.** 비밀번호 관리자나 USB 같은 오프라인 경로를 쓰고, 옮긴 뒤 `history -c` 로 셸 히스토리를 정리한다. 값은 이 저장소의 **어떤 문서에도 적지 않는다** (이 문서 포함 — 여기엔 키 **이름**만 있다).
> - 🚨 `local-env.md`/`secrets.md` §7-2 경고: 로컬 `.env` 의 `DATABASE_URL` 을 최신값으로 채우는 순간, 새 PC 가 **운영 Neon DB 에 붙어 실계좌로 매매하는 엔진이 하나 더** 뜬다. 개발용으로 쓸 거면 DB 를 분리할 것.

> 🚨🚨 **처음 30분에 절대 하면 안 되는 것 3가지** (위험 검토 2026-09-03 추가)
>
> | 하지 말 것 | 왜 |
> |---|---|
> | **로컬(내 PC)에서 스케줄러·워커·`docker compose up` 을 띄우기** | `.env` 에 운영 `DATABASE_URL` 을 채운 상태로 띄우면 **운영 Neon DB 에 붙은 매매 엔진이 하나 더** 생긴다. 스케줄러는 Redis 리더 선출을 쓰는데(`scheduler_runner.py:75-77` `DistributedSchedulerGuard.try_become_leader()`) **로컬 Redis 는 별개**라 로컬도 자기가 리더인 줄 알고 **실계좌에 주문을 낸다.** 새 PC 에서는 **읽기 명령과 pytest 까지만** 한다 |
> | **로컬에서 바이낸스 API 를 직접 호출하기** (분석 스크립트, `get_klines` 반복, `python -c "…BinanceClient…"`) | 🚨 **IP ban(418)** 전력이 있다(Fix 117/122). ban 은 **IP 단위**라 집·사무실 IP 가 막히는 것과 별개로, 같은 **API 키에 대한 rate limit** 을 소모해 **VPS 의 손절·청산까지 굶길 수 있다.** 시세·캔들이 필요하면 **VPS 에서 조회**하거나(위 §들의 `docker compose exec` 방식) **DB 에 저장된 값**을 읽어라 |
> | **`git stash` / `git stash pop` / `git reset --hard` / `git checkout .` / `git clean -fd` / `git push --force`** | 이 저장소는 **worktree 를 공유**하고 **커밋 안 된 작업이 실재한다**. 특히 `git stash list` 에 **2026-08-24 백업 stash 가 아직 남아 있다** — 무심코 `pop` 하면 **8월 24일 코드가 9월 3일 코드 위에 얹힌다.** 상태를 맞추고 싶으면 `git status` 로 **보기만** 하고, 지우는 대신 **커밋하거나 복사**하라 |

**① 코드가 맞는 자리에 있는가** (`local-env.md` §2 대로 클론했다면 경로가 아래와 같다)

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && git fetch origin && git status -sb | head -1 && echo "--- 내 체크아웃 ---" && git log --oneline -1 && echo "--- origin/main ---" && git log --oneline -6 origin/main
```

기대(2026-09-03 실측): `origin/main` 목록의 맨 위가 `e51d9a8 chore(handoff) …` → `ded22f3` → `1d04598` → `0459e8f` → `61e19a8` → `fcd8462`.
`e51d9a8` 은 **문서만** 바꾼 커밋이다(`backend/` 변경 0건). 그래서 VPS 가 `ded22f3` 인 것은 **뒤처진 게 아니라 정상**이다.

첫 줄이 `## main...origin/main` 이면 최신이고, **`## main...origin/main [behind 30]` 처럼 `behind` 가 붙으면 뒤처진 것**이다(2026-09-03 옛 PC 메인 클론 실측값이 정확히 `[behind 30]` 이었다).

🚨🚨 **「--- 내 체크아웃 ---」이 `e51d9a8` 이 아니면 여기서 멈추고 먼저 당겨라.** `git fetch` 는 원격만 갱신할 뿐 **작업 트리를 바꾸지 않는다.** 2026-09-03 실측: 옛 PC 의 메인 클론은 로컬 `main` 이 **`2586555`(8월 말)** 에 멈춰 있었고, 그 상태에서 아래 ②를 돌리면 **`test_support_score.py` 등 3개 파일이 아예 없어서** `ERROR: file or directory not found` 가 난다. 「테스트가 깨졌다」가 아니라 **「코드를 안 당겼다」**이다.

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader" && git checkout main && git pull --ff-only origin main && git log --oneline -1
```

(`--ff-only` 를 쓰는 이유: 로컬에 커밋이 남아 있으면 조용히 머지하지 말고 **실패해서 알려야** 한다. 실패하면 로컬 커밋이 있다는 뜻이니 지우지 말고 §6-3 의 「살리는 방법」을 먼저 볼 것.)

**② 회귀 테스트가 도는가** — 이 3개가 Fix 325/326/327 의 테스트다 (**①에서 체크아웃이 `e51d9a8` 인 것을 확인한 뒤에** 돌릴 것)

```bash
cd "/c/Users/user/바이낸스/binance-auto-trader/backend" && PYTHONIOENCODING=utf-8 python -m pytest tests/test_support_score.py tests/test_chg24_entry_gate.py tests/test_stop_loss_execution_path.py -q
```

기대: **`62 passed`** (support_score 22 + chg24_entry_gate 23 + stop_loss_execution_path 17). 2026-09-03 옛 PC 실측.
`PYTHONIOENCODING=utf-8` 을 빼지 말 것 — 이 저장소의 테스트 이름이 한글(`test_1단계_소액은_손절하지_않는다`)이라 Windows 기본 코드페이지에서 깨질 수 있다.

> ✅ **안심해도 되는 점 (위험 검토 실측)**: 이 3개 테스트는 **네트워크도 운영 DB 도 건드리지 않는다.**
> 실측 `grep -n "SessionLocal\|create_engine\|DATABASE_URL\|BinanceClient\|requests\|httpx" <세 파일>` → **출력 0줄**. 공용 `tests/conftest.py` 의 DB 픽스처조차 **`sqlite+pysqlite:///:memory:`** 이고(끝나면 `drop_all`), 이 세 파일은 그 픽스처도 쓰지 않는다(전부 가짜 객체).
> → 즉 **pytest 는 실계좌·운영 DB·바이낸스 API 에 아무 영향을 주지 않는다.** 새 PC 에서 제일 먼저 돌려도 되는, 유일하게 완전히 안전한 명령이다.

**③ VPS 가 어느 커밋으로 돌고 있는가**

```bash
ssh -o StrictHostKeyChecking=no root@159.65.137.250 'cd ~/binance-auto-trader && git log --oneline -1 && docker inspect binance-auto-trader-api --format "{{.State.StartedAt}}" && docker inspect binance-auto-trader-scheduler --format "{{.State.StartedAt}}" && date -u'
```

그다음 §6-1(P1 Fix 326 실검증)의 로그 명령을 돌린다.

---

### 8. 🚨 이 저장소에서 반복해서 사고가 난 자리 (이번 세션 문서들이 다시 확인한 것)

| 함정 | 이번 세션의 증거 |
|---|---|
| **「저장했다」는 「쓴다」가 아니다** | `chart_patterns` 를 진입에서 읽는 코드 **0곳**. Fix 247(`strategy_confluence`)과 같은 모양 |
| 🚨 **고친 뒤 옛 주석이 남으면 다음 사람을 정확히 반대로 속인다** | `stage_trim.py:320-321` 은 아직 「손절 경로는 SKIP 을 받으면 전량으로 떨어진다」라고 적혀 있는데, **Fix 326 이 바로 그것을 없앴다**(§4-2). 이 저장소는 「주석은 정답인데 코드가 안 함」을 겪었고, 이번엔 **부호만 반대**다 |
| 🚨 **커밋 안 된 것은 「있는 것」이 아니다** | `terminal.py`+`perp-terminal.html`+`router.py` **3,666줄**이 GitHub·VPS·백업 어디에도 없다. 그래서 그 API 는 **운영에서 404** 다(§6-3) |
| 🚨 **전역 기본값 한 줄이 62개 잡을 동시에 바꾼다** | P4 의 `job_defaults` 제안 — 부팅 시 밀린 잡이 한꺼번에 발사되어 **418 IP ban** 으로 갈 수 있다. 잡별로 걸어라(§6-4) |
| **부분 청산은 「남긴 것」의 다음 사이클까지 따라가야 한다** | Fix 326 — 부분 손절 12~300초 뒤에 전량 청산이 지웠다 |
| **한 번도 실행 안 된 분기는 런타임이 못 잡는다** | Fix 327 게이트는 지금까지 실행 0회 |
| **6시간 주기 잡은 이 환경에서 굶는다** | 72시간 `interval[6:00:00]` Running **0** / missed 18 |
| **절대 임계값은 종목 스케일이 바뀌면 무력해진다** | AKEUSDT: 밴드폭 절대 13.21%(넓음) vs 자기순위 0.02(최대 수축) |
| **효과크기가 교차검증을 통과해도 결과 수준에서 뒤집힐 수 있다** | SURGE/CRASH 방향 판정기 A→B +0.74%p / B→A −0.43%p |
| **같은 지표라도 용도가 다르면 결과가 다르다** | 4H MACD 상승: 종목 선정엔 d=2.08 최강급인데 **LONG 진입 타이밍으로 쓰면 43건 승률 2.3%** |
| **결손률 40% 넘는 컬럼은 결손 자체가 정보일 수 있다** | `max_profit_pct` 결손 285건 중 **94.4%가 손실** |
| **미래참조는 「이미 알 수 있었는가」로 검사한다** | 재진입 분석 234건 중 **102건(43.6%)** 이 아직 결착 전이었다 |
| **DB 는 Neon 이다** | `docker compose exec db psql` 은 **빈 DB** — 반드시 api 컨테이너 `SessionLocal` 경유 |

---

### 9. ⚠️ 이번 인수인계에서 확인하지 못한 것

1. **Fix 325 / 326 / 327 의 실서버 실행 증거** — 배포 후 25분 로그에 해당 태그 **0회**. 코드·테스트는 통과했으나 실운영 확인은 아직 없다.
2. **스케줄러가 재시작을 반복하는 원인** — 배포인지 크래시 루프인지 구분 못 함(감사 부록 B-3 과 동일).
3. **`StrategySuggestion.strategy_config["regime"]` 이 진입을 막거나 방향을 바꾸는지** — `auto_bb_breakdown_worker.py:232` 가 읽는 것은 확인됐으나 소비처는 미추적(감사 부록 B-1 그대로).

   ⬇️ **아래 3-1 ~ 3-4 는 2026-09-03 위험 검토 담당이 추가한 「확인 못 함」이다.**

   - **3-1. `perp-terminal.html`(2,481줄)이 실제로 주문을 낼 수 있는지** — 짝인 `terminal.py` 는 **`@router.get` 6개뿐**(POST 0개)이라 그 라우터만으로는 주문이 안 나간다. 그러나 HTML 이 **다른 기존 주문 API 를 부르는지는 읽지 않았다.** 새 PC 에서 이 화면을 열기 전에 확인할 것.
   - **3-2. 스케줄러 부팅 시 실제로 몇 개 잡이 미스파이어로 폐기되는지** — 「misfire_grace_time 을 늘리면 한꺼번에 발사된다」는 **APScheduler 동작에서 나온 추론**이다. 실제 폐기 건수를 부팅 로그로 세지는 않았다. P4 를 하기 전에 `grep "missed by"` 로 **먼저 세어 볼 것.**
   - **3-3. 스캔 1회의 진짜 rate-limit 비용** — 요청 수 ≈101 은 코드로 셌지만, **바이낸스가 매기는 실제 가중치와 현재 남은 한도**는 재지 않았다. 「200회」라는 기존 표현은 **요청 수로는 과대**, 가중치로는 대략 맞다.
   - **3-4. `stage_keep_notional_usdt` 를 크게 넣었을 때의 실제 동작** — 코드 경로(`stage_trim.py:176 → :294 → :322-326` → `tp_sl_orchestrator.py:615/739`)로만 추적했다. **운영에서 시험하지 않았다(해서도 안 된다 — 손절이 멈춘다).**
4. **`chart_pattern_scan` 을 `/scan-now` 로 부르면 몇 건이 탐지되는지** — DB 쓰기 + API 약 200회라 호출하지 않았다.
   🚨 **정정**: 이 문서의 이전 판이 적어 둔 `curl -X POST …/chart-patterns/scan-now` 는 **애초에 돌지 않는 명령이었다**(JWT 필요 → 실측 **401 `{"detail":"Not authenticated"}`**). 토큰 없이 같은 일을 하는 컨테이너 내부 명령으로 §6-4 를 바꿔 놓았다. **여전히 사장님 승인 후에만 실행할 것.**
5. **`REGIME_THRESHOLDS_2026-09-03.json` (2,460줄) 전문** — 구조와 주요 임계값만 확인했다. `indicator_recognition.rules.BOUNCE` 와 `.RANGE` 는 **빈 dict** 이고(= 인식 규칙 없음), `gate = 0.25`, `threshold_quantile = 0.5` 인 것까지 확인했다.
   ✅ **2026-09-03 재현성 검증에서 위 네 가지를 전부 재확인**했다(2,460줄 / `rules.BOUNCE`·`rules.RANGE` 둘 다 `{}` / `gate` 0.25 / `threshold_quantile` 0.5). 덤으로 §2-2 의 국면 표본수(SURGE 815 · CRASH 786 · RANGE 4,076 · BOUNCE 40 · BREAKDOWN 199)와 2시간 결과(SURGE +0.73%/57.3% `reproducible:true`, CRASH −0.46%/46.2% `reproducible:false`, RANGE +0.30%)도 이 JSON 과 **정확히 일치**했다. 아래 명령으로 언제든 다시 잴 수 있다:

   ```bash
   cd "/c/Users/user/바이낸스/binance-auto-trader" && PYTHONIOENCODING=utf-8 python -c "
import json; d=json.load(open('docs/spec/REGIME_THRESHOLDS_2026-09-03.json', encoding='utf-8'))
ir=d['indicator_recognition']
print('gate', ir['gate'], '| quantile', ir['threshold_quantile'])
print('빈 규칙:', [k for k,v in ir['rules'].items() if not v])
print('표본수:', d['regime_sample_counts'])
"
   ```

   🚨 **`encoding='utf-8'` 을 빼면 Windows 에서 파일이 아예 안 열린다.** 최상위 키 4개가 한글이라 실측으로 `UnicodeDecodeError: 'cp949' codec can't decode byte 0xec in position 7` 이 난다. `PYTHONIOENCODING=utf-8` 도 같이 붙여야 출력의 한글이 안 깨진다. **이 저장소의 한글 JSON·문서를 파이썬으로 열 때는 매번 둘 다 붙일 것.**
6. **옛 롤백 가이드의 나머지 명령이 지금도 유효한지** — 나머지는 미검증. 단 아래 두 가지는 **재검증에서 정정**했다.

   🚨 **경로가 틀렸다**: `docs/ROLLBACK_GUIDE_2026-08-24.md` 는 **저장소에 없다**(`git ls-files` 미추적 = 클론해도 안 딸려온다). 실제 위치는 백업본 한 곳뿐이다:

   ```
   docs/handoff/wip-backup-2026-09-03/main/untracked/docs/ROLLBACK_GUIDE_2026-08-24.md   (328줄)
   ```

   🚨 **줄번호도 불완전했다**. 그 파일에서 로컬 `db` 컨테이너를 때리는 줄 **전체**는 다음과 같다 (실측 `grep -n psql`):

   | 줄 | 명령 | 왜 틀렸나 |
   |---:|---|---|
   | 163 | `exec -T db psql … < backup_2026-08-24.sql` | **옛 목록에서 빠져 있었다** |
   | 181 | `exec db psql … COPY system_settings TO STDOUT` | |
   | 184 | `exec db pg_dump -t system_settings` | psql 은 아니지만 **같은 로컬 db 오인** |
   | 190 | `exec -T db psql … TRUNCATE + COPY FROM STDIN` | 🚨 복원인 줄 알고 돌리면 **빈 로컬 DB 를 지운다** |
   | 193 | `exec -T db psql … < system_settings_2026-08-24.sql` | |
   | 239 | `exec db psql -U postgres -d binance_auto_trader` | **옛 목록에서 빠져 있었다** |

   (78행은 psql 명령이 아니라 그 흐름 안의 `UPDATE system_settings …` SQL 이다.)
   → **이 가이드로 롤백하려면 위 6줄을 전부 §1-2 의 api 컨테이너 `SessionLocal` 방식으로 바꿔야 한다.** 그대로 돌리면 **운영 Neon 이 아니라 빈 로컬 DB** 를 상대로 백업·복원한 뒤 「했다」고 착각하게 된다 — 이 저장소가 반복해서 겪은 「조용한 실패」와 같은 모양이다.
