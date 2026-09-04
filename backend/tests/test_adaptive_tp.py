"""Fix 299 — 변동성 연동 TP1 단위 테스트.

사장님: "급등락하는 심볼투자는 tp1 +15%, 매우 안정적은 상위심볼은 +5%나 +3% 등등
        낮은 익절을 만들어 **경우의 수를 가져가야해**"

실측이 그대로 지지한다 — TP15 가 최선인 구간은 |24h| 15~30% 하나뿐이고,
나머지 구간에서는 기대값이 -0.94 ~ -4.30 으로 전부 음수다.
"""
from app.services import adaptive_tp as A


class _DB:
    """SystemSetting 을 흉내내는 최소 스텁."""

    def __init__(self, **vals):
        self.vals = vals

    def get(self, _model, key):
        if key not in self.vals:
            return None
        return type("R", (), {"value": self.vals[key]})()


class _Boom:
    def get(self, *_a):
        raise RuntimeError("db down")


# ─────────────────────────────────────────────────────────────────────
# 기본 동작 — 사장님 지시 그대로인가
# ─────────────────────────────────────────────────────────────────────

def test_급등락은_TP15_안정은_TP3():
    db = _DB()
    tp_s, why_s, _ = A.pick_tp1(db, 22.0)      # |24h| 22% = 급등락
    tp_c, why_c, _ = A.pick_tp1(db, 4.0)       # |24h| 4%  = 안정
    assert tp_s == 15.0, why_s
    assert tp_c == 3.0, why_c
    assert "급등락" in why_s
    assert "경우의 수" in why_c


def test_음수_변동도_절대값으로_본다():
    """하락 50위(-20%)도 「급등락」이다 — 사장님은 급등과 급락을 함께 보신다."""
    db = _DB()
    tp_up, _, _ = A.pick_tp1(db, 20.0)
    tp_dn, _, _ = A.pick_tp1(db, -20.0)
    assert tp_up == tp_dn == 15.0


def test_경계값():
    db = _DB()
    assert A.pick_tp1(db, 15.0)[0] == 15.0      # 경계 포함
    assert A.pick_tp1(db, 14.99)[0] == 3.0


def test_24h_없으면_높은쪽으로_fail_safe():
    """🚨 낮은 TP 로 잘못 내리면 큰 파도를 조기 익절해 버린다 — 되돌릴 수 없다.
    높은 TP 는 트레일링이 받쳐 준다. 그래서 모르면 급등락 쪽이다."""
    db = _DB()
    tp, why, d = A.pick_tp1(db, None)
    assert tp == 15.0
    assert d.get("fallback") is True


# ─────────────────────────────────────────────────────────────────────
# 설정으로 덮인다 (측정은 한 장세의 것이므로 전부 조정 가능해야 한다)
# ─────────────────────────────────────────────────────────────────────

def test_설정이_기본값을_덮는다():
    db = _DB(adaptive_tp_surge_chg24="20", adaptive_tp_surge_tp1="12",
             adaptive_tp_calm_tp1="5")
    assert A.pick_tp1(db, 22.0)[0] == 12.0
    assert A.pick_tp1(db, 18.0)[0] == 5.0       # 18 < 20 이므로 안정


def test_설정이_손상돼도_기본값으로_돈다():
    for bad in ("", "  ", "abc", "-1", "9999"):
        db = _DB(adaptive_tp_surge_tp1=bad)
        assert A.pick_tp1(db, 22.0)[0] == 15.0, bad


def test_DB가_죽어도_판정은_계속된다():
    tp, _, _ = A.pick_tp1(_Boom(), 22.0)
    assert tp == 15.0


# ─────────────────────────────────────────────────────────────────────
# 기본 OFF (헌법 161)
# ─────────────────────────────────────────────────────────────────────

def test_기본은_꺼져있다():
    assert A.adaptive_tp_enabled(_DB()) is False
    assert A.adaptive_tp_enabled(_DB(adaptive_tp_enabled="0")) is False
    assert A.adaptive_tp_enabled(_DB(adaptive_tp_enabled="1")) is True
    assert A.adaptive_tp_enabled(_DB(adaptive_tp_enabled="true")) is True


def test_조회_실패는_꺼짐으로():
    assert A.adaptive_tp_enabled(_Boom()) is False


# ─────────────────────────────────────────────────────────────────────
# 사다리
# ─────────────────────────────────────────────────────────────────────

def test_사다리는_TP1_비율을_유지한다():
    """🚨 기존 사다리(15/20/25/30)는 간격이 5%p 라 TP1 만 닿고 나머지는 못 닿았다.
    비율을 유지하면 TP1 이 내려갈 때 사다리 전체가 같이 내려와 실제로 도달한다."""
    assert A.tp_ladder_from_tp1(15.0) == [15.0, 30.0, 45.0, 60.0]
    assert A.tp_ladder_from_tp1(3.0) == [3.0, 6.0, 9.0, 12.0]


def test_사다리는_오름차순이고_양수다():
    for tp1 in (0.1, 3.0, 5.0, 15.0, 50.0):
        lad = A.tp_ladder_from_tp1(tp1)
        assert lad == sorted(lad)
        assert all(x > 0 for x in lad)


def test_사다리_길이를_바꿀_수_있다():
    assert len(A.tp_ladder_from_tp1(5.0, levels=2)) == 2
    assert len(A.tp_ladder_from_tp1(5.0, levels=1)) == 1


# ─────────────────────────────────────────────────────────────────────
# 실측 근거가 문서에 남아 있는가 (다음에 무심코 바꾸지 않도록)
# ─────────────────────────────────────────────────────────────────────

def test_실측표가_모듈에_기록돼_있다():
    doc = A.__doc__ or ""
    assert "15~30%" in doc and "+0.51" in doc, "TP15 가 최선인 구간의 근거"
    assert "-4.30" in doc, "안정 구간에서 TP15 가 나쁜 근거"
    assert "R = 1.01" in doc, "실효 손익비가 무너진 사실"


# ─────────────────────────────────────────────────────────────────────
# 진입 경로에 실제로 연결됐는가 (상수만 만들고 안 쓰면 소용없다)
# ─────────────────────────────────────────────────────────────────────

def test_진입경로에_연결돼_있다():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "app" / "workers"
           / "auto_bb_breakdown_worker.py").read_text(encoding="utf-8")
    assert "adaptive_tp_enabled as _atp_on" in src, "게이트를 부르지 않으면 안 돈다"
    assert "tp_ladder_from_tp1" in src, "사다리를 안 쓰면 TP2~4 가 옛값으로 남는다"
    assert 'cfg[f"tp{_i}_percent"]' in src, "템플릿 TP 를 실제로 덮어야 한다"


def test_인스턴스_override도_박는다():
    """🚨 Fix 205 함정 — 템플릿만 바꾸면 strategy_service 의 15% 가 이긴다."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "app" / "workers"
           / "auto_bb_breakdown_worker.py").read_text(encoding="utf-8")
    assert "strategy.tp1_pct_override = Decimal(str(_atp1))" in src
    # 템플릿 덮기가 인스턴스 override 보다 **먼저** 와야 한다
    assert src.find('cfg[f"tp{_i}_percent"]') < src.find("strategy.tp1_pct_override")


def test_적응TP가_꺼져있으면_아무것도_안_바꾼다():
    """기본 OFF 이므로 켜기 전까지 기존 동작이 100% 유지돼야 한다."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "app" / "workers"
           / "auto_bb_breakdown_worker.py").read_text(encoding="utf-8")
    blk = src[src.find("Fix 299 (2026-09-02 사장님)"):src.find("tpl = StrategyTemplate(")]
    assert "if _atp_on(db) and not _is_ladder_tpl:" in blk, "게이트 안에서만 cfg 를 건드려야 한다 (Fix 343: 사다리 제외)"
