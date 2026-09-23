"""🎛 Fix 374 (2026-09-16) — 자동매매 관제실: DB 를 실제로 읽고 쓰는 부분.

레지스트리·가드는 tests/test_fix374_auto_control.py. 여기는 sqlite 세션(JSONB→JSON 변환은 integration conftest)이 필요한 것만.
고정하는 것: 빈 DB = 중단(fail-closed) · 저장 즉시 읽힘 · 한 칸이 틀리면 전부 저장 안 함 · 누가 바꿨는지 남음 · 워커 스위치 기본 켜짐.
"""
import pytest

from app.services import auto_control as AC
from app.services import auto_control_state as ST
from app.services import worker_switch as WS


# ───────────────────────── ④ 빈 DB ─────────────────────────
def test_build_on_empty_db_says_halted(db_session):
    out = ST.build(db_session)
    assert out["halted"] is True and out["halt_reason"]        # 행이 없으면 중단 (fail-closed)
    assert out["summary"]["total"] == len(AC.panels())
    assert out["summary"]["entered_today"] == 0
    assert all(g["is_default"] for g in out["globals"])
    rf = [p for p in out["panels"] if p["fam"] == "rf_s2_short"][0]
    assert rf["state"] == "shadow" and rf["gate"]["value"] == "shadow"
    pyr = [p for p in out["panels"] if p["fam"] == "success_reentry"][0]
    assert pyr["state"] == "on", "피라미딩은 행이 없으면 켜짐 — 화면이 그렇게 보여야 한다"


def test_apply_writes_and_is_read_back(db_session):
    ST.apply(db_session, {"rf_s2_short_mode": "off", "daily_max_top_short": "2"}, user_id=7)
    out = ST.build(db_session)
    rf = [p for p in out["panels"] if p["fam"] == "rf_s2_short"][0]
    assert rf["state"] == "off" and rf["gate"]["is_default"] is False
    top = [p for p in out["panels"] if p["fam"] == "top_short"][0]
    assert top["daily_max"]["value"] == "2"


def test_apply_rejects_unknown_key(db_session):
    with pytest.raises(ValueError, match="다룰 수 없는"):
        ST.apply(db_session, {"drop_table_now": "1"})


def test_apply_is_all_or_nothing(db_session):
    with pytest.raises(ValueError):
        ST.apply(db_session, {"rf_s2_short_mode": "off", "rf_leverage": "999"})
    from app.services.rule_families import mode_of
    assert mode_of(db_session, "rf_s2_short") == "shadow", "한 칸이 틀리면 나머지도 저장되지 않아야 한다"


def test_apply_records_who_changed_it(db_session):
    ST.apply(db_session, {"auto_trading_halt": "0"}, user_id=42)
    from app.models.system_setting import SystemSetting
    row = db_session.get(SystemSetting, "auto_trading_halt")
    assert row.value == "0" and row.updated_by == 42 and "관제실" in (row.description or "")


def test_halt_then_release_flips_the_gate(db_session):
    from app.services import auto_trading_halt as H
    prev, H.FORCE_HALT = H.FORCE_HALT, None
    try:
        assert H.halt_enabled(db_session) is True             # 행 없음 = 중단
        ST.apply(db_session, {"auto_trading_halt": "0"}, user_id=1)
        assert H.halt_enabled(db_session) is False
        ST.apply(db_session, {"auto_trading_halt": "1"}, user_id=1)
        assert H.halt_enabled(db_session) is True
    finally:
        H.FORCE_HALT = prev


def test_switches_default_on_so_behaviour_is_unchanged(db_session):
    for key in WS.SWITCHES:
        assert WS.is_on(db_session, key) is True, key


@pytest.mark.parametrize("value, expect_on", [
    ("0", False), ("off", False), ("false", False), ("no", False), ("1", True), ("on", True), ("", True),
])
def test_switch_values(db_session, value, expect_on):
    ST.apply(db_session, {"realtime_reentry_enabled": "0" if not expect_on else "1"})
    from app.services.system_settings_service import SystemSettingsService
    SystemSettingsService(db_session).set("realtime_reentry_enabled", value)
    assert WS.is_on(db_session, "realtime_reentry_enabled") is expect_on
