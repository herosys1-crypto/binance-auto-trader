"""Fix 486 — 가상매매 규칙 끄기(`paper_rules_off`)."""
from app.workers import paper_trading_worker as W


def test_parse_comma_list_with_spaces():
    assert W.rules_off_set(" off8_267, mach7_trap_long ,,") == frozenset({"off8_267", "mach7_trap_long"})


def test_empty_or_none_turns_nothing_off():
    assert W.rules_off_set(None) == frozenset()
    assert W.rules_off_set("") == frozenset()


def test_baseline_cannot_be_turned_off():
    assert W.rules_off_set("baseline_LONG,baseline_SHORT,surge_start_346") == frozenset({"surge_start_346"})


def test_entry_loop_checks_rules_off():
    import inspect
    src = inspect.getsource(W)
    assert "key in rules_off" in src and "rules_off_set(_setting(db, RULES_OFF_KEY))" in src
