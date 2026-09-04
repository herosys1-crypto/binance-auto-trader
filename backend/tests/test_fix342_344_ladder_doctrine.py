"""📐 Fix 342 / 343 / 344 — 사장님 2026-09-04 결정 ①②③ 을 코드가 실제로 따르는가.

사장님 verbatim (2026-09-04):
  "내가 언제 이렇게 로직을 만들었나?"  (= 2·3단계 +1.5% 가격 진입은 Claude 가 만든 것)
  "2단계는 차트와 보조지표가 최고점에서 조정이 시작되는 시점에 진입하고 … 다시 최고점을 찍고
   하락과 상승을 반복하고 다시 하락시작하는 시점에 3단계 진입하는 로직"
  "빠른 익절은 볼밴 분할전략에서 만든건데 확인해줘 정말 너 맘대로구나"
  "실자금으로 운영하고 123으로 진행해줘"

  ① 사다리 2·3단계 = 정점-주춤(Fix 260) 하나로 (LONG 포함)   → Fix 342
  ② 사다리 TP1 15% 복원 / 볼밴 분할 TP1 5% 복원 (적응 TP 분리) → Fix 343
  ③ 사다리 미진입 단계는 130% 예약에서 제외 + 발주 직전 가용 잔고 검사 → Fix 344

정적 검사만으로는 못 잡는다(Fix 318/311/315/326 교훈) — 정점-주춤은 **실제 판정 함수**를 돌리고,
예약 계산은 **실제 함수**에 가짜 DB 를 꽂아 값을 본다.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app"


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ═════════════════════════════════════════════════════════════════════
# ① Fix 342 — 사다리도 정점-주춤으로 판정한다
# ═════════════════════════════════════════════════════════════════════

def test_사다리도_정점주춤_게이트를_탄다():
    s = _src("workers/stage_trigger_worker.py")
    assert '== "stage_ladder"' in s, "_is_ladder 판정이 없다"
    assert 'get_bool("ladder_peak_stall_enabled", True)' in s, "사다리 정점-주춤은 기본 ON 이어야 한다"
    assert "if (_is_split or _is_ladder) and next_stage_no >= 2:" in s, "정점-주춤 게이트에 사다리가 안 들어갔다"
    # 정점-주춤이 켜진 동안 「기본방식은 가격만 본다」 로그는 찍히지 않는다
    assert "if _is_price_mode and next_stage_no >= 2 and not _ps_on:" in s


def test_사다리_주춤_OFF_면_볼밴의_지표게이트를_얹지_않는다():
    """되돌리기(설정 0) 시 사다리는 옛 경로(가격 + Fix 312)로 가야지, 볼밴 전용 Fix 218 게이트로 가면 안 된다."""
    s = _src("workers/stage_trigger_worker.py")
    assert s.count("if _is_split and next_stage_no >= 2 and not _ps_on:") == 1, "Fix 218 지표 게이트는 split 전용이어야 한다"


def test_Fix312_대기는_사다리_정점주춤이_켜지면_생략():
    """같은 사상을 두 구현이 이중으로 막으면 정점-주춤 OK → Fix 312 대기 → 미진입이 된다."""
    s = _src("services/execution_service.py")
    assert 'get_bool("ladder_peak_stall_enabled", True)' in s
    assert "Fix 312 대기 생략" in s
    assert s.find("_ladder_ps = False") < s.find("from app.services.stage_entry_timing import should_enter_now")


def test_정점주춤_실판정_사다리_간격_1_5():
    """실제 evaluate_peak_stall 로: 가격만 닿으면 진입 안 함 / 신고점 찍고 주춤하면 진입 / 3단계는 재갱신 필수 / LONG 대칭."""
    from app.services import peak_stall as P
    now = datetime(2026, 9, 4, 0, 0, tzinfo=timezone.utc)
    start = 1520.69                       # #2264 SNDKUSDT 1단계 체결가
    trig = start * 1.015                  # 사다리 2단계 트리거 (+1.5%)
    gap = P.gap_pct_between(start, trig, "SHORT")
    assert gap is not None and abs(gap - 1.5) < 1e-6

    # (a) 옛 Fix 232 가 들어가던 자리: 가격이 트리거에 **닿기만** 함 (되돌림 0, 갱신 정지 0)
    v = P.evaluate_peak_stall(side="SHORT", stage_no=2, mark=trig, trigger_price=trig,
                              ext=trig, ext_seen_at=now, renewed=False, gap_pct=gap, now=now)
    assert v.ok is False, "가격 도달만으로 2단계가 들어가면 사장님 규칙 위반"

    # (b) 신고점(트리거 위)을 찍고 → 간격×비율만큼 되돌림 → N봉 갱신 정지 = 「가다가 주춤」
    ext = trig * 1.002
    need_pull = gap * P.STALL_MIN_RATIO
    mark = ext * (1 - (need_pull + 0.05) / 100)
    seen = now - timedelta(minutes=P.STALL_BARS * P.BAR_MINUTES + 1)
    v = P.evaluate_peak_stall(side="SHORT", stage_no=2, mark=mark, trigger_price=trig,
                              ext=ext, ext_seen_at=seen, renewed=False, gap_pct=gap, now=now)
    assert v.ok is True, v.checks

    # (c) 3단계는 「다시 최고점으로 가면」(재갱신) 없이는 안 들어간다
    v3 = P.evaluate_peak_stall(side="SHORT", stage_no=3, mark=mark, trigger_price=trig,
                               ext=ext, ext_seen_at=seen, renewed=False, gap_pct=gap, now=now)
    assert v3.ok is False and v3.checks.get("재갱신") is False

    # (d) LONG 도 대칭 — 사장님 "최저점도 같은 전략이고"
    trig_l = start * 0.985
    gap_l = P.gap_pct_between(start, trig_l, "LONG")
    assert gap_l is not None and abs(gap_l - 1.5) < 1e-6
    ext_l = trig_l * 0.998
    mark_l = ext_l * (1 + (gap_l * P.STALL_MIN_RATIO + 0.05) / 100)
    vl = P.evaluate_peak_stall(side="LONG", stage_no=2, mark=mark_l, trigger_price=trig_l,
                               ext=ext_l, ext_seen_at=seen, renewed=False, gap_pct=gap_l, now=now)
    assert vl.ok is True, vl.checks


# ═════════════════════════════════════════════════════════════════════
# ② Fix 343 — 적응 TP 는 사다리·볼밴 분할에 붙지 않는다
# ═════════════════════════════════════════════════════════════════════

def test_사다리에는_적응TP_를_안_붙인다():
    s = _src("workers/auto_bb_breakdown_worker.py")
    assert "if _atp_on(db) and not _is_ladder_tpl:" in s, "사다리가 적응 TP(3%) 를 받으면 사장님 15% 가 사라진다"
    assert '_is_ladder_tpl = int(stages_config.get("stages_count", 1) or 1) > 1' in s, \
        "사다리 판정은 stage_ladder 마커와 같은 조건(stages_count > 1)이어야 한다"


def test_볼밴분할은_적응TP_배선이_없고_TP1_은_5():
    s = _src("workers/pump_split_entry_worker.py")
    assert "_atp_pick" not in s, "Fix 336-c 배선이 남아 있다 — 볼밴 후보는 전부 |24h|≥15 라 항상 15% 가 된다"
    from app.workers import pump_split_entry_worker as W
    assert float(W.TP_PERCENTS[0]) == 5.0, "사장님 8/29 확정 TP1 5%"


# ═════════════════════════════════════════════════════════════════════
# ③ Fix 344 — 사다리 미진입 단계는 예약이 아니다 + 발주 직전 가용 잔고
# ═════════════════════════════════════════════════════════════════════

class _Plan:
    def __init__(self, cap, triggered):
        self.planned_capital = Decimal(cap)
        self.is_triggered = triggered


class _S:
    id = 2264
    leverage = 2
    current_position_qty = Decimal("0")
    avg_entry_price = None

    def __init__(self, mode):
        self.capital_management_mode = mode


class _DB:
    """실제 함수에 꽂는 가짜 세션 — 설정 없음(= 코드 기본), plans 는 주어진 대로."""
    def __init__(self, plans):
        self._plans = plans

    def execute(self, _stmt):
        plans = self._plans

        class _R:
            def scalars(self_):
                class _A:
                    def all(s2):
                        return plans
                return _A()
        return _R()

    def get(self, _model, _key):
        return None


def test_사다리_미진입_단계는_예약이_아니다():
    from app.services import capital_calculator as C
    plans = [_Plan("300", False), _Plan("600", False)]
    assert C.calc_untriggered_margin_for_strategy(_DB(plans), _S("stage_ladder")) == Decimal("0")
    # 다른 방식은 그대로 예약한다
    assert C.calc_untriggered_margin_for_strategy(_DB(plans), _S("fixed")) == Decimal("900")
    assert C.calc_untriggered_margin_for_strategy(_DB(plans), _S("split_entry")) == Decimal("900")


def test_설정으로_옛_동작_복귀():
    from app.services import capital_calculator as C

    class _DBOn(_DB):
        def get(self, _model, key):
            if key == "ladder_reserve_untriggered_enabled":
                return type("R", (), {"value": "1"})()
            return None
    plans = [_Plan("300", False), _Plan("600", False)]
    assert C.calc_untriggered_margin_for_strategy(_DBOn(plans), _S("stage_ladder")) == Decimal("900")


def test_생성시_검사도_같은_규칙():
    s = _src("services/strategy_service.py")
    assert "ladder_reserves_untriggered" in s, "생성 시 검사와 워커 검사가 다른 답을 내면 안 된다"


def test_발주직전_가용잔고_검사가_있다():
    s = _src("workers/stage_trigger_worker.py")
    assert "availableBalance" in s and "Fix 344" in s, "예약을 뺐으면 -2019 를 막는 실잔고 검사가 있어야 한다"
