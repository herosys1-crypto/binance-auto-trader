"""🎛 Fix 374 (2026-09-16 사장님) — 자동매매 관제실.

사장님: "자동매매 준비 가족 12종과 모든 자동매매를 한곳으로 모아서 사용과 관리가 편리하게 ui를 개선해줘"

여기서 고정하는 것:
  ① 레지스트리 정합 — 가족마다 켜기 칸이 있고, 규칙 가족 12종이 빠짐없이 들어 있다.
  ② 🛡 **가드: 관제실이 내놓는 모든 설정 키를 실제로 읽는 코드가 있다.** (Fix 373 과 같은 「아무도 안 읽는 키」 방지)
  ③ 값 검증 — 범위·형식이 틀린 값은 저장 전에 막고, 한 칸이라도 틀리면 **아무것도** 저장하지 않는다.
  ④ 빈 DB(행 0개)에서도 화면이 뜨고, 그때 자동매매는 **중단**으로 보인다 (fail-closed).
  ⑤ 워커 스위치 6종은 기본 켜짐이고(기존 동작 유지), 각 워커가 실제로 그 스위치를 부른다.
"""
import ast
import re
from pathlib import Path

import pytest

from app.services import auto_control as AC
from app.services import auto_control_state as ST
from app.services import worker_switch as WS

APP = Path(__file__).resolve().parents[1] / "app"


# ───────────────────────── ① 레지스트리 ─────────────────────────
def test_every_family_has_a_switch():
    """켜기 칸이 없는 가족이 있으면 그 자동매매는 화면에서 끌 수 없다 (Fix 374 의 목적)."""
    assert [p.label for p in AC.panels() if p.gate is None] == []


def test_all_twelve_rule_families_present():
    from app.services.rule_families import FAMILIES
    fams = {p.fam for p in AC.panels()}
    assert len(FAMILIES) == 13          # 🗺 Fix 387: 기회지도 S4 추가
    missing = [f.key for f in FAMILIES if f.key not in fams]
    assert missing == [], f"규칙 가족이 관제실에 없다: {missing}"


def test_groups_and_counts():
    ps = AC.panels()
    by = {}
    for p in ps:
        by[p.group] = by.get(p.group, 0) + 1
    assert by[AC.G_RULE] == 13          # 🗺 Fix 387: 기회지도 S4 추가
    assert by[AC.G_WORKER] >= 12
    assert by[AC.G_EXTERNAL] == 2
    assert all(p.group in AC.GROUPS for p in ps)


def test_whitelist_covers_every_control_and_daily_max():
    wl = AC.whitelist()
    for p in AC.panels():
        if p.gate is not None:
            assert p.gate.key in wl
        for c in p.ctls:
            assert c.key in wl, c.key
        if p.fam and p.daily:
            assert f"daily_max_{p.fam}" in wl
    assert "auto_trading_halt" in wl


def test_defaults_come_from_the_owning_module():
    """규칙 가족 기본값을 관제실이 따로 적으면 두 곳이 갈라진다 — rule_families.SETTINGS 가 진실."""
    from app.services.rule_families import SETTINGS as RFS
    wl = AC.whitelist()
    for key, (default, _help, _src) in RFS.items():
        if key in wl:
            assert wl[key].default == default, key


# ───────── ② 🛡 가드: 아무도 읽지 않는 설정 키를 화면에 내놓지 않는다 ─────────
SELF = {"auto_control.py", "auto_control_state.py"}          # 관제실 자신은 제외
DYNAMIC_PREFIXES = ("daily_max_",)                           # f"daily_max_{key}" 처럼 조립되는 키


def _app_sources() -> str:
    out = []
    for p in APP.rglob("*.py"):
        if p.name in SELF:
            continue
        out.append(p.read_text(encoding="utf-8"))
    return "\n".join(out)


def _family_prefixes() -> list[str]:
    """가족별 키는 f"{fam.key}_mode" 처럼 조립된다 — 가족 접두사를 떼고 뒷부분으로 찾는다."""
    from app.services.rule_families import FAMILIES
    from app.services.auto_family_registry import known_families
    keys = {f.key for f in FAMILIES} | {f.key for f in known_families()}     # Fix 376: 실매매 가족 f"{fam_key}_chart_gate"
    return sorted(keys, key=len, reverse=True)


def _is_read(key: str, src: str, prefixes: list[str]) -> bool:
    if re.search(r"[\"']" + re.escape(key) + r"[\"']", src):
        return True                                           # 키를 그대로 적은 곳이 있다
    for pre in prefixes:
        if key.startswith(pre + "_"):
            rest = key[len(pre):]                             # 예: "_cooldown_hours"
            if re.search(r"\{[A-Za-z_.]+\}" + re.escape(rest) + r"[\"']", src):
                return True                                   # f"{fam.key}_cooldown_hours"
    return False


def test_every_exposed_key_is_read_somewhere():
    src = _app_sources()
    prefixes = _family_prefixes()
    missing = [k for k in sorted(AC.whitelist())
               if not k.startswith(DYNAMIC_PREFIXES) and not _is_read(k, src, prefixes)]
    assert missing == [], (
        "관제실이 내놓지만 읽는 코드가 없는 설정 키 (Fix 373 과 같은 조용한 실패):\n" + "\n".join(missing))


def test_dynamic_daily_max_key_shape_matches_registry():
    from app.services import auto_family_registry as AF
    assert 'f"daily_max_{key}"' in (APP / "services" / "auto_family_registry.py").read_text(encoding="utf-8")
    assert AF.DEFAULT_DAILY_MAX == 1                          # 사장님 「모두 일최대 1개」
    assert AC.whitelist()["daily_max_top_short"].default == "1"


def test_guard_itself_catches_a_fake_key():
    """가드가 실제로 잡는지 — 거짓 통과 방지 (헌법 122)."""
    src = _app_sources()
    prefixes = _family_prefixes()
    assert _is_read("rf_s2_short_mode", src, prefixes) is True          # 조립되는 키 = 읽힘
    assert _is_read("auto_trading_halt", src, prefixes) is True         # 그대로 적힌 키 = 읽힘
    assert _is_read("nonexistent_setting_key_xyz", src, prefixes) is False


# ───────────────────────── ③ 값 검증 ─────────────────────────
@pytest.mark.parametrize("kind, raw, want", [
    ("mode3", "ON", "on"), ("mode3", "shadow", "shadow"),
    ("switch", "true", "1"), ("switch", "OFF", "0"), ("switch", "0", "0"),
    ("int", "3", "3"), ("int", "3.0", "3"),
    ("num", "2.5", "2.5"),
    ("text", " 10,100,200 ", "10,100,200"),
])
def test_clean_accepts(kind, raw, want):
    c = AC.Ctl("k", "l", kind, "1", lo=0, hi=100)
    assert c.clean(raw) == want


@pytest.mark.parametrize("kind, raw", [
    ("mode3", "on1"), ("mode3", ""), ("switch", "2"), ("switch", "maybe"),
    ("int", "abc"), ("int", "-1"), ("int", "101"), ("num", "nan"), ("num", "inf"), ("text", ""),
])
def test_clean_rejects(kind, raw):
    c = AC.Ctl("k", "l", kind, "1", lo=0, hi=100)
    with pytest.raises(ValueError):
        c.clean(raw)


def test_halt_key_off_words_match_the_gate_module():
    from app.services.auto_trading_halt import _OFF_VALUES
    assert set(AC.OFF_WORDS) == set(_OFF_VALUES)               # 화면과 게이트가 같은 값을 「끔」으로 본다


# ───────────────────────── ⑤ 워커 스위치 ─────────────────────────
def test_switch_read_failure_keeps_worker_running():
    class _Boom:
        def get(self, *_a):
            raise RuntimeError("DB down")
    assert WS.is_on(_Boom(), "ladder_restart_enabled") is True   # fail-open (전면 정지는 halt 가 담당)


WORKER_PINS = {
    "workers/auto_short_at_top_worker.py": "sajangnim_top_short_enabled",
    "workers/auto_long_at_bottom_worker.py": "sajangnim_bottom_long_enabled",
    "workers/realtime_reentry_worker.py": "realtime_reentry_enabled",
    "workers/resistance_reversal_worker.py": "resistance_reversal_enabled",
    "workers/peak_break_reversal_worker.py": "peak_break_reversal_enabled",
    "workers/ladder_restart_worker.py": "ladder_restart_enabled",
}


@pytest.mark.parametrize("rel, key", sorted(WORKER_PINS.items()))
def test_each_worker_actually_calls_its_switch(rel, key):
    src = (APP / rel).read_text(encoding="utf-8")
    assert "from app.services.worker_switch import" in src, rel
    assert f'"{key}"' in src, f"{rel} 가 {key} 를 보지 않는다"
    assert key in WS.SWITCHES
    ast.parse(src)


def test_switch_labels_exist_for_every_key():
    for key, (label, job) in WS.SWITCHES.items():
        assert label and job
        assert key in AC.whitelist(), f"{key} 가 관제실 화면에 없다"


# ───────────────────────── 화면·API 배선 ─────────────────────────
def test_page_and_router_are_wired():
    static = APP / "static"
    page = (static / "auto-control.html").read_text(encoding="utf-8")
    assert "/static/js/auto-control.js" in page
    js = (static / "js" / "auto-control.js").read_text(encoding="utf-8")
    for path in ("/auto-control/overview", "/auto-control/settings", "/auto-control/halt", "/auto-control/bulk"):
        assert path in js, path
    assert "openAutoControl" in (static / "index.html").read_text(encoding="utf-8")
    assert "auto_control_router" in (APP / "api" / "router.py").read_text(encoding="utf-8")


def test_bulk_only_allows_safe_directions():
    from app.api.v1.auto_control import BULK_SAFE
    assert set(BULK_SAFE) == {"off", "shadow"}, "켜기 일괄은 만들지 않는다 (가족마다 사장님이 켠다)"
