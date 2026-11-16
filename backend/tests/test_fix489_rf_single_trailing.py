"""🪢 Fix 489 — 규칙 가족 단일 진입의 트레일링 익절 폭 5 → 3 %p (설정 `rf_single_trailing_pct`).

사장님 (2026-11-16): "실매매 청산값을 바꾸는 일이라 승인"
근거: 가상매매 같은 거래 짝 36일 — 규칙 가족 재료 LONG +0.149 · SHORT +0.143 %p/건(앞·뒤 절반 모두 +) · 11/15 가설 L(S4) 통과.
범위: 배포 뒤 새로 만들어지는 규칙 가족 **단일 진입** 인스턴스만. 공용 상수(5)·열린 포지션·사람 전략·외부 전략은 그대로.
러너 연결은 tests/test_queue3_rule_families.py, 불변식은 tests/properties/test_pbt_rf_single_trailing.py.
"""
import ast
from pathlib import Path

import pytest

from app.core.risk_constants import TRAILING_RETRACE_PCT
from app.services import rule_families as RF

ROOT = Path(__file__).resolve().parents[1]


class _DB:
    def __init__(self, value=None, boom=False):
        self.value, self.boom = value, boom

    def get(self, _m, key):
        if self.boom:
            raise RuntimeError("db down")
        if key != "rf_single_trailing_pct" or self.value is None:
            return None
        return type("R", (), {"value": self.value})()


def test_whitespace_is_stripped_even_without_setting_helper(monkeypatch):
    """심판 지적(2026-11-16): 공백 낀 숫자도 그 값 — setting() 이 떼지 않아도."""
    monkeypatch.setattr(RF, "setting", lambda db, key: " 5 ")
    assert RF.single_trailing_pct(None) == 5.0
    monkeypatch.setattr(RF, "setting", lambda db, key: chr(9) + "0" + chr(10))   # 탭 · 0 · 줄바꿈
    assert RF.single_trailing_pct(None) is None


def test_default_is_three():
    assert RF.SETTINGS["rf_single_trailing_pct"][0] == "3"
    assert RF.single_trailing_pct(_DB()) == 3.0
    assert RF.single_trailing_pct(_DB(boom=True)) == 3.0          # 설정 읽기 실패 = 기본값 (옛 동작으로 새지 않는다)


@pytest.mark.parametrize("raw,want", [
    ("3", 3.0), ("4.5", 4.5), ("0.5", 0.5), ("20", 20.0), (" 5 ", 5.0),
    ("0", None), ("0.0", None), ("-0", None),                     # 끄는 스위치 = 공용 기본 5 그대로
    ("abc", 3.0), ("", 3.0), ("nan", 3.0), ("inf", 3.0), ("-inf", 3.0), ("-1", 3.0), ("0.2", 3.0), ("20.01", 3.0), ("25", 3.0),
    ("1e-10000", 3.0), ("-1e-400", 3.0),                          # float 로는 0.0 이 되는 값 — 끄기로 오인하면 안 된다 (duel 감사)
    ("0e5", None), ("+0.000", None), ("2e0", 2.0), ("+3", 3.0),
    ("1_0", 3.0), ("３", 3.0), ("0x3", 3.0), ("3%", 3.0), ("1e999999", 3.0),   # 밑줄·전각·16진·단위 붙은 값 = 오타 취급
])
def test_values(raw, want):
    assert RF.single_trailing_pct(_DB(raw)) == want


def test_common_default_untouched():
    """공용 기본(사람 전략·외부 전략·열린 포지션이 쓰는 값)은 5 그대로."""
    assert TRAILING_RETRACE_PCT == 5


def test_only_rule_family_single_entry_passes_trailing():
    """가족 단위 적용 — 규칙 가족 러너만 trailing_pct 를 넘긴다. 외부 전략·급등 사다리·볼밴 중단선 호출부는 그대로."""
    def passes(rel: str) -> list[bool]:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        return [any(k.arg == "trailing_pct" for k in n.keywords) for n in ast.walk(tree)
                if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "create_surge_position"]
    assert passes("app/workers/rule_family_worker.py") == [True]
    for rel in ("app/workers/external_strategies_worker.py", "app/workers/surge_peak_ladder_worker.py"):
        assert passes(rel) == [False], rel                            # 볼밴 중단선은 원래 자기 값(TRAILING_PCT)을 넘긴다 — 그대로


def test_control_room_shows_setting():
    from app.services import auto_control as AC
    ctl = [c for c in AC._shared_rule_ctls() if c.key == "rf_single_trailing_pct"]      # 규칙 가족 공용 칸
    assert ctl and ctl[0].default == "3" and (ctl[0].lo, ctl[0].hi) == (0, 20)
