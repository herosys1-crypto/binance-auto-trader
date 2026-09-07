"""🎯 Fix 362 — 사장님 2026-09-08: "기존 방식 새전략은 -25% 손실이면 청산하게 기본옵션을 설정해줘"

새 전략 인스턴스의 force_sl_roi_override 기본 = 25 (설정 force_sl_roi_new_default 로 덮음, 허용 목록 안만).
기존 인스턴스·전역 기본(FORCE_SL_ROI_DEFAULT=5)은 손대지 않는다.
"""
from decimal import Decimal
from pathlib import Path

from app.core import risk_constants as RC

ROOT = Path(__file__).resolve().parents[1] / "app"


class _DB:
    def __init__(self, **kv):
        self.kv = kv

    def get(self, _m, key):
        return type("R", (), {"value": self.kv[key]})() if key in self.kv else None

    def execute(self, *a, **k):
        raise AssertionError("not used")


def test_constant_and_allowed():
    assert RC.FORCE_SL_ROI_NEW_DEFAULT == Decimal("25")
    assert RC.FORCE_SL_ROI_NEW_DEFAULT in RC.FORCE_SL_ALLOWED_ROI
    assert RC.FORCE_SL_ROI_DEFAULT == Decimal("5"), "전역 기본은 그대로 (기존 포지션에 영향 없음)"
    assert "FORCE_SL_ROI_NEW_DEFAULT" in RC.__all__ and "FORCE_SL_NEW_ROI_KEY" in RC.__all__


def test_helper_reads_setting_with_guard(monkeypatch):
    from app.services.system_settings_service import SystemSettingsService as S
    svc = S(_DB())
    monkeypatch.setattr(S, "get_decimal", lambda self, key, default=None: default)
    assert svc.get_new_strategy_force_sl_roi() == Decimal("25")
    monkeypatch.setattr(S, "get_decimal", lambda self, key, default=None: Decimal("15"))
    assert svc.get_new_strategy_force_sl_roi() == Decimal("15")
    monkeypatch.setattr(S, "get_decimal", lambda self, key, default=None: Decimal("33"))     # 허용 목록 밖
    assert svc.get_new_strategy_force_sl_roi() == Decimal("25")
    monkeypatch.setattr(S, "get_decimal", lambda self, key, default=None: (_ for _ in ()).throw(RuntimeError("db")))
    assert svc.get_new_strategy_force_sl_roi() == Decimal("25")


def test_creation_sites_use_new_default():
    s = (ROOT / "services" / "strategy_service.py").read_text(encoding="utf-8")
    assert 'force_sl_roi_override=D("5")' not in s, "새 인스턴스에 -5% 하드코딩이 남아 있다"
    assert "force_sl_roi_override=_new_force_sl_roi" in s
    assert "get_new_strategy_force_sl_roi()" in s
    js = (ROOT / "static" / "js" / "live-pump-dump-alerts.js").read_text(encoding="utf-8")
    assert "force_sl_roi_override: 25," in js
    pt = (ROOT / "services" / "paper_trading.py").read_text(encoding="utf-8")
    assert "LIVE_SL_ROI = 25.0" in pt and "sl_roi: float = LIVE_SL_ROI" in pt


def test_no_worker_overwrites_new_default_with_5():
    """Fix 362b: 생성 뒤 워커가 Decimal("5") 로 덮어쓰면 사장님 지시가 무효 — 5곳 전부 설정 기본(25)을 쓴다."""
    import re
    bad = []
    for p in (ROOT / "workers").glob("*.py"):
        txt = p.read_text(encoding="utf-8")
        for m in re.finditer(r"force_sl_roi_override\s*=\s*Decimal\(\"5\"\)", txt):
            bad.append(f"{p.name}:{txt[:m.start()].count(chr(10)) + 1}")
    assert not bad, f"-5% 하드코딩 덮어쓰기 잔존: {bad}"
    for name in ("auto_bb_breakdown_worker.py", "auto_short_at_top_worker.py", "peak_break_reversal_worker.py",
                 "resistance_reversal_worker.py", "auto_long_at_bottom_worker.py"):
        assert "_nfs362(db)" in (ROOT / "workers" / name).read_text(encoding="utf-8"), name
    long_w = (ROOT / "workers" / "auto_long_at_bottom_worker.py").read_text(encoding="utf-8")
    assert "force_sl_roi_override = LONG_FORCE_SL_ROI" not in long_w, "LONG 워커가 아직 상수 5 를 쓴다"


def test_stage2_workers_keep_existing_override():
    """Fix 362c: 2단계 진입 워커는 **기존 인스턴스**의 손절값을 덮어쓰지 않는다 (사장님 지시는 「새전략」)."""
    for name in ("peak_break_reversal_worker.py", "resistance_reversal_worker.py"):
        src = (ROOT / "workers" / name).read_text(encoding="utf-8")
        i = src.find("_nfs362(db)")
        assert i > 0 and "if s.force_sl_roi_override is None:" in src[i - 400:i], name


def test_helper_rejects_zero(monkeypatch):
    from app.services.system_settings_service import SystemSettingsService as S
    monkeypatch.setattr(S, "get_decimal", lambda self, key, default=None: Decimal("0"))
    assert S(_DB()).get_new_strategy_force_sl_roi() == Decimal("25")
