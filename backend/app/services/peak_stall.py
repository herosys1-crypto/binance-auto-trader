"""📐 정점-주춤 단계 진입 (Fix 260).

## 사장님 verbatim (2026-09-01)

  "2단계부터는 차트와 보조지표가 조정으로 바뀌면이 아니라 **최고점에서 들어가야** 하는데
   어떻게 설정해야 할까 분석해서 기획해줘.
   **최고점으로 가다가 주춤할때 2단계 진입**
   그리고 **다시 최고점으로 가면 다시 대기해서 꺾이면 3단계 진입**으로 해줘"

기획서: docs/spec/PEAK_STALL_STAGE_ENTRY_SPEC_2026-09-01.md

## 「최고점」의 정의 — 이것부터 틀리면 전부 틀린다

볼밴 분할의 단계 트리거는 **진입 방향에 불리한 쪽**에 깔린다 (실측):

    #1937 PROMUSDT SHORT  진입 5.631   단계2 5.747 (+2.06% **위**)
    #1923 0GUSDT   LONG   진입 0.2091  단계2 0.2050 (-1.95% **아래**)

따라서 사장님의 「최고점」 = **불리 방향 극값**이다.

    SHORT -> 신고점 (running max)
    LONG  -> 신저점 (running min)

🚨 LONG 의 극값을 「가격 최고점」으로 잡으면 가격 트리거와 방향이 반대가 되어
   두 조건이 동시에 참일 수 없다 = 영원히 진입 불가.
   부호는 이 파일의 `_s()` 한 곳에서만 정의한다 (Fix 251 교훈: 부호 분기가
   2곳 이상이면 반드시 어긋난다).

## 왜 판정 「주체」를 바꾸는가 — 조건을 더하면 수학적으로 불가능하다

stage_trigger_worker.py 의 기존 판정:

    should_fire = (mark >= trigger) if SHORT else (mark <= trigger)
    if not should_fire: continue

SHORT 이 신고점 H(>= trigger) 를 찍고 d 만큼 되돌아오면 mark = H(1-d) 가
**trigger 아래로 내려가** 그 자리에서 죽는다. LONG 도 대칭.
사다리 간격이 1.9~2.1% 이므로 H 가 trigger 를 조금만 넘으면 **어떤 되돌림도 통과 불가**다.

=> 「주춤을 기다려라」를 조건으로 **더하면**, 가격 게이트가 그 주춤을 스스로 막는다.
   그래서 조건을 더하지 않고 비교 대상만 `mark` -> `ext`(러닝 극값) 로 바꾼다.
   trigger_price 계산(3/5/7 · 재앵커 Fix 209 · 죽은단계 검산)은 한 줄도 안 건드린다.

## 실측 (split_entry 18건 / 4일, 진입 시각부터 15m 봉 재수신 후 상태기계 시뮬)

    현행(1단계만 도는 지금)                        USDT -12.22

              최소전진 ->   1.0%    1.5%    2.0%    2.5%
    주춤 4봉               +24.3   +83.8   +99.3   +99.3
    주춤 5봉               +15.8   +78.4   +97.4   +97.4
    주춤 6봉               -29.4   +31.3   +25.4   +25.4
    주춤 7봉               -30.3   +29.7   +25.5   +25.5

    과적합 검사 (표본 절반씩)
      최근 9건 : 현행 +15.09 -> 규칙 +23.30
      이전 9건 : 현행 -27.31 -> 규칙 +55.13      <- 양쪽 모두 개선

🚨 처음 시뮬레이션은 현행보다 **나빴다**(-2.56% vs -0.67%).
   원인은 원문의 「최고점으로 **가다가**」를 구현에서 빠뜨린 것이었다
   (아무 극값 갱신이나 다 셌다). 「가다가」= 극값이 trigger 까지 나아갔을 것.
   그 한 조건이 -20 을 +97 로 바꿨다. **이 조건을 빼지 말 것.**

## ⚠️ 한계 (정직한 선언)

- 표본 18건 / 4일. 방향은 견고해 보이나 숫자는 더 쌓이면 다시 재야 한다.
- **3단계는 미검증** — 표본에서 평균 도달 단계가 1.33 이라 거의 발동하지 않았다.
  꺾임 임계를 1.0% 로 두든 2.0% 로 두든 결과가 **완전히 같았다**.
- STALL_MIN / TURN_MIN / RENEW_EPS 는 승/패 실측 분포 사이에 둔 값이 **아니다**.
  사다리 간격(gap) 비율로만 잡은 초기값이다. 배포 후 pull 분포를 보고 재조정한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

__all__ = [
    "PeakStallVerdict",
    "evaluate_peak_stall",
    "update_extreme",
    "gap_pct_between",
    "BAR_MINUTES",
    "STALL_BARS",
    "TURN_BARS",
    "STALL_MIN_RATIO",
    "TURN_MIN_RATIO",
    "RENEW_EPS_RATIO",
]

# 15분봉 (사상 ⑥ 「15분봉 = 진입 타이밍」)
BAR_MINUTES: int = 15

# 「주춤」= 극값 갱신이 이만큼 멈춰 있었다. 실측 최적 4~5봉, 6봉부터 급락.
# 4봉과 손익 차가 2% 뿐이라 whipsaw 에 강한 5봉을 고른다.
STALL_BARS: int = 5
# 「꺾임」의 대기도 같은 5봉. 강도 차이는 되돌림 폭(TURN_MIN_RATIO)으로 준다.
TURN_BARS: int = 5

# 되돌림 임계 — **절대 %가 아니라 사다리 간격(gap) 비율**이다.
#   이유: 사장님이 3/5/7 을 바꿔도 자동으로 정합이 맞는다(죽은 단계가 안 생긴다).
#   3/5/7 기준 실제값: gap ~= 1.94~2.11% 이므로
#     STALL_MIN ~= 0.78~0.84%   /   TURN_MIN ~= 1.07~1.16%
# 🚨 표본 없음 — 초기값. 배포 후 발동 시점의 pull 분포 중앙값으로 재조정할 것.
STALL_MIN_RATIO: float = 0.40
# 「꺾임」 > 「주춤」. 처음 0.70 으로 잡았다가 검산해서 내렸다 —
# ext 가 trigger 를 간신히 넘은 최악의 경우 통과 창이 사실상 0 이 된다.
TURN_MIN_RATIO: float = 0.55

# 「다시 최고점으로 갔다」로 인정할 최소 갱신 폭. 재앵커가 같은 값으로 보는
# 기준이 0.01%(pump_split_entry_worker.py) 이므로 그 30배 = 노이즈 위.
RENEW_EPS_RATIO: float = 0.15


def _s(side: Any) -> int:
    """부호는 **여기서만** 정의한다. s*x 가 클수록 「불리」.

    SHORT = +1 (가격이 오르면 불리)  /  LONG = -1 (가격이 내리면 불리)
    """
    return 1 if str(side or "").upper() == "SHORT" else -1


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


@dataclass
class PeakStallVerdict:
    ok: bool = False
    checks: dict[str, bool | None] = field(default_factory=dict)
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def reason(self) -> str:
        if self.ok:
            return (
                f"정점-주춤 확인 (되돌림 {self.detail.get('pull_pct', 0):.2f}% "
                f"/ 정지 {self.detail.get('stall_min', 0):.0f}분)"
            )
        miss = [k for k, v in self.checks.items() if v is not True]
        return f"정점-주춤 대기 — 미충족: {', '.join(miss) or '데이터 부족'}"


def gap_pct_between(prev_trigger: Any, this_trigger: Any, side: Any) -> float | None:
    """직전 단계 트리거 대비 이번 단계 트리거의 간격 %.

    stage_gap_pcts 와 같은 값을 **plan 행에서 직접** 얻는다. 재앵커(Fix 209)가
    trigger_price 를 실체결가 기준으로 다시 깔아 두므로, 그 두 값의 비가 곧 간격이다.
    설정(3/5/7)을 따로 읽지 않으므로 설정과 DB 가 어긋나도 판정이 흔들리지 않는다.
    """
    a, b = _f(prev_trigger), _f(this_trigger)
    if a is None or b is None or a <= 0 or b <= 0:
        return None
    s = _s(side)
    g = s * (b - a) / a * 100.0
    # 간격이 0 이하 = 사다리가 뒤집혔다 = 판정 불가 (호출자가 기존 경로로 폴백)
    return g if g > 0 else None


def update_extreme(
    side: Any,
    ext: Any,
    mark: Any,
    gap_pct: Any = None,
) -> tuple[float | None, bool]:
    """러닝 극값 갱신.

    Returns:
        (새 극값, 「의미있게 갱신됐는가」)
        두 번째 값이 True 일 때만 3단계용 재갱신 플래그를 세운다 —
        틱 노이즈로 재갱신이 남발되면 「다시 최고점으로 가면」이 무의미해진다.
    """
    m = _f(mark)
    if m is None or m <= 0:
        return _f(ext), False
    e = _f(ext)
    if e is None or e <= 0:
        return m, False
    s = _s(side)
    if s * m <= s * e:
        return e, False
    g = _f(gap_pct)
    eps = (g * RENEW_EPS_RATIO) if (g and g > 0) else 0.0
    moved_pct = abs(m - e) / e * 100.0
    return m, moved_pct >= eps


def evaluate_peak_stall(
    *,
    side: Any,
    stage_no: int,
    mark: Any,
    trigger_price: Any,
    ext: Any,
    ext_seen_at: datetime | None,
    renewed: bool,
    gap_pct: Any,
    now: datetime | None = None,
) -> PeakStallVerdict:
    """「최고점으로 가다가 주춤/꺾임」인가 = 이 단계에 진입할 자리인가.

    Args:
        stage_no: 2 = 주춤(사장님 「주춤할때」) / 3 이상 = 꺾임(「대기해서 꺾이면」)
        ext: 직전 단계 체결 이후의 불리방향 러닝 극값 (peak_price)
        ext_seen_at: 그 극값이 마지막으로 **갱신된** 시각
        renewed: 이 단계 대기 중 극값이 의미있게 재갱신되었는가 (3단계 필수)
        gap_pct: 이 단계의 사다리 간격 % (gap_pct_between 결과)

    ⚠️ 결측은 **통과로 세지 않는다**. 다만 호출자는 이 판정이 예외/데이터 부족으로
       실패했을 때 기존 경로(Fix 218)로 폴백해야 한다 — 판정 하나가 진입을 통째로
       멈추는 사고(Fix 252)를 반복하지 않기 위해서다.
    """
    v = PeakStallVerdict()
    d = v.detail
    c = v.checks
    now = now or datetime.now(timezone.utc)

    s = _s(side)
    m, e, t, g = _f(mark), _f(ext), _f(trigger_price), _f(gap_pct)
    d.update(side=str(side).upper(), stage_no=stage_no, mark=m, ext=e, trigger=t, gap_pct=g)

    if m is None or e is None or t is None or g is None or e <= 0 or g <= 0:
        c["데이터"] = None
        return v

    is_turn = stage_no >= 3
    bars = TURN_BARS if is_turn else STALL_BARS
    ratio = TURN_MIN_RATIO if is_turn else STALL_MIN_RATIO
    need_pull = g * ratio
    need_min = bars * BAR_MINUTES
    d.update(need_pull_pct=need_pull, stall_need_min=need_min, mode="꺾임" if is_turn else "주춤")

    # ── ① 신고점 도달 = 「최고점으로 **가다가**」 ────────────────────────
    # 🚨 이 조건이 없으면 규칙이 무너진다 (실측: -20.94 vs +97.4).
    #    mark 가 아니라 **ext** 로 재는 것이 이 설계의 핵심이다.
    c["신고점 도달"] = (s * e) >= (s * t)

    # ── ② 되돌림 = 「주춤」 / 「꺾임」 ──────────────────────────────────
    pull = s * (e - m) / e * 100.0
    d["pull_pct"] = pull
    c["되돌림"] = pull >= need_pull

    # ── ③ 갱신 정지 = 「주춤」의 지속 / 「대기해서」 ────────────────────
    if ext_seen_at is None:
        c["갱신 정지"] = None
        d["stall_min"] = None
    else:
        seen = ext_seen_at if ext_seen_at.tzinfo else ext_seen_at.replace(tzinfo=timezone.utc)
        stall = (now - seen) / timedelta(minutes=1)
        d["stall_min"] = stall
        c["갱신 정지"] = stall >= need_min

    # ── ④ 재갱신 = 「**다시** 최고점으로 가면」 (3단계 전용) ────────────
    if is_turn:
        d["renewed"] = bool(renewed)
        c["재갱신"] = bool(renewed)

    # 🚨 전부 충족해야 한다. 「N중 M」 다수결은 정의 조건을 덮어쓴다 (Fix 250 사고).
    v.ok = all(r is True for r in c.values())
    return v
