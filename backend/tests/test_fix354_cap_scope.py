"""🎯 Fix 354 — 동시 보유 상한의 「범위」 설정: all(전 전략) / ladder(v219 사다리 가족만).

사장님 2026-09-07: "v219와 볼밴 분할 전략의 동시포지션을 10 10으로 수정했는데 적용되고 있는지?"
실측: 전역 키가 사다리 14 + 중단선 3 = 17 을 세서 10 도달 → v219 신규 진입 전면 차단.
"""
from pathlib import Path

from sqlalchemy.dialects import postgresql

from app.services import position_limit as PL

ROOT = Path(__file__).resolve().parents[1] / "app"


class _DB:
    def __init__(self, v=None):
        self._v = v

    def get(self, _model, key):
        if key == PL.SETTING_SCOPE_KEY and self._v is not None:
            return type("R", (), {"value": self._v})()
        return None


def _sql(q) -> str:
    return str(q.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_기본_범위는_all_옛_동작():
    assert PL.cap_scope(_DB()) == PL.SCOPE_ALL
    assert PL.cap_scope(_DB("ladder")) == PL.SCOPE_LADDER
    assert PL.cap_scope(_DB("LADDER ")) == PL.SCOPE_LADDER
    assert PL.cap_scope(_DB("weird")) == PL.SCOPE_ALL


def test_all_범위_SQL_은_가족_필터가_없다():
    s = _sql(PL.active_positions_query())
    assert "stage_ladder" not in s and "strategy_templates" not in s
    assert "is_archived IS false" in s


def test_ladder_범위_SQL_은_사다리만_세고_전용상한_가족을_뺀다():
    s = _sql(PL.active_positions_query(scope=PL.SCOPE_LADDER))
    assert "JOIN strategy_templates" in s and "capital_management_mode = 'stage_ladder'" in s
    assert s.count("strategy_templates.name NOT ILIKE") == 5
    for word in ("REENTRY", "LASTCHANCE", "SURGE_LADDER", "PUMPSPLIT", "BB_MIDLINE"):
        assert word in s, word


def test_check_position_slot_이_범위를_읽고_사유에_적는다(monkeypatch):
    monkeypatch.setattr(PL, "get_max_concurrent", lambda db: (10, "sajangnim_top_short_daily_limit"))
    seen = {}

    def fake_count(db, side=None, scope=PL.SCOPE_ALL):
        seen["scope"] = scope
        return 17 if scope == PL.SCOPE_ALL else 4

    monkeypatch.setattr(PL, "count_active_positions", fake_count)
    ok, why, active, limit = PL.check_position_slot(_DB(), "t")
    assert ok is False and active == 17 and "17/10" in why and seen["scope"] == PL.SCOPE_ALL
    ok, why, active, limit = PL.check_position_slot(_DB("ladder"), "t")
    assert ok is True and active == 4 and "Fix354" in why and seen["scope"] == PL.SCOPE_LADDER
