"""🔓 Fix 339 — 수량 불일치가 해소되면 Kill-Switch 를 자동 해제한다.

## 왜 — 같은 사고의 **네 번째**

Fix 221 이 자동 해제를 만들었지만 사유가 `ORPHAN_EXCHANGE_POSITION` 하나뿐이었다.
2026-09-04 05:22, **다른 사유**로 같은 일이 났다:

    reason_code : ZOMBIE:QTY_MISMATCH_PERSISTENT
    사유        : 좀비 strategy #2477 (XMRUSDT SHORT) — 5 cycles 연속 qty 불일치
    규모        : 명목 약 20 USDT (수량 -0.038, 증거금 9.74)
    결과        : 계정 전체가 **5시간 넘게** 잠김
                  · 사장님 수동 「포지션 추가 +500」 → 400 kill-switch is enabled
                  · 자동 피라미딩 0건 / 자동 증거금 추가 정지 / 신규 진입 차단
                  · #2351 SNOWUSDT 는 ROI +17.3%, 카운터 0/2 로 조건을 다 갖추고 대기

확인 결과 불일치는 **이미 해소**돼 있었다 (DB -0.038 = 거래소 -0.038,
평단 512.57 = 512.57, 전 계정 17/17 일치). 원인은 사라졌는데 잠금만 남았다.
발동은 자동인데 해제만 수동이라 구조적으로 반복된다 —
07-21 ACE / 08-26 CL / 08-29 INJ / 09-04 XMR.

## 이 테스트가 지키는 경계

🚨 **좁게 연다.** 아래를 전부 만족할 때만 푼다:
  · 사유가 정확히 `ZOMBIE:QTY_MISMATCH_PERSISTENT` (수동/손실한도 등은 손대지 않는다)
  · 연속 불일치 카운터가 남은 전략 **0건**
  · Redis 를 못 읽으면(**모름**) 풀지 않는다 — 모르는 채로 여는 것이 가장 위험하다
"""
import ast
from pathlib import Path

import pytest

from app.services import zombie_guardian as Z


class _KSRow:
    def __init__(self, enabled=True, reason="ZOMBIE:QTY_MISMATCH_PERSISTENT"):
        self.is_enabled = enabled
        self.reason_code = reason
        self.reason_message = "좀비 strategy #2477 (XMRUSDT SHORT) — 5 cycles 연속 qty 불일치"
        self.triggered_at = "2026-09-04 05:22"


class _DB:
    def __init__(self, row):
        self._row = row
        self.added = []
        self.committed = False

    def execute(self, _stmt):
        row = self._row

        class _R:
            def scalar_one_or_none(self_inner):
                return row
        return _R()

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass


@pytest.fixture
def cleared(monkeypatch):
    """AccountKillSwitchService.clear 호출을 가로챈다."""
    seen = []
    import app.services.account_kill_switch_service as M

    class _Svc:
        def __init__(self, db):
            pass

        def clear(self, account_id):
            seen.append(account_id)

    monkeypatch.setattr(M, "AccountKillSwitchService", _Svc)
    return seen


def _stuck(monkeypatch, value):
    monkeypatch.setattr(Z, "any_stuck_strategy", lambda: value)


# ═════════════════════════════════════════════════════════════════════
# 🔓 푸는 경우 — 딱 하나
# ═════════════════════════════════════════════════════════════════════

def test_불일치가_해소되면_자동_해제한다(monkeypatch, cleared):
    _stuck(monkeypatch, False)
    db = _DB(_KSRow())
    assert Z.maybe_auto_clear_qty_mismatch_ks(db, 1) is True
    assert cleared == [1]
    assert db.committed and len(db.added) == 1, "RiskEvent 기록이 없다"


# ═════════════════════════════════════════════════════════════════════
# 🚨 풀면 안 되는 경우 — 이쪽이 훨씬 중요하다
# ═════════════════════════════════════════════════════════════════════

def test_불일치가_남아_있으면_풀지_않는다(monkeypatch, cleared):
    _stuck(monkeypatch, True)
    db = _DB(_KSRow())
    assert Z.maybe_auto_clear_qty_mismatch_ks(db, 1) is False
    assert cleared == []


def test_카운터를_못_읽으면_풀지_않는다(monkeypatch, cleared):
    """🚨 None(모름)을 False(없음)로 다루면 안 된다."""
    _stuck(monkeypatch, None)
    db = _DB(_KSRow())
    assert Z.maybe_auto_clear_qty_mismatch_ks(db, 1) is False
    assert cleared == []


@pytest.mark.parametrize("reason", [
    "MANUAL",                          # 사장님이 직접 켰다
    "DAILY_LOSS_LIMIT",                # 손실 한도
    "ZOMBIE:ORPHAN_EXCHANGE_POSITION",  # Fix 221 소관
    "",
    None,
])
def test_다른_사유는_손대지_않는다(monkeypatch, cleared, reason):
    """🚨 이 함수는 수량 불일치 사유 **하나만** 푼다."""
    _stuck(monkeypatch, False)
    db = _DB(_KSRow(reason=reason))
    assert Z.maybe_auto_clear_qty_mismatch_ks(db, 1) is False
    assert cleared == []


def test_이미_꺼져_있으면_아무것도_안_한다(monkeypatch, cleared):
    _stuck(monkeypatch, False)
    db = _DB(_KSRow(enabled=False))
    assert Z.maybe_auto_clear_qty_mismatch_ks(db, 1) is False
    assert cleared == [] and not db.committed


def test_행이_없으면_아무것도_안_한다(monkeypatch, cleared):
    _stuck(monkeypatch, False)
    assert Z.maybe_auto_clear_qty_mismatch_ks(_DB(None), 1) is False
    assert cleared == []


def test_예외가_나도_터지지_않는다(monkeypatch, cleared):
    """자동 해제 실패가 reconcile 사이클을 멈추면 안 된다."""
    _stuck(monkeypatch, False)

    class _Boom(_DB):
        def execute(self, _s):
            raise RuntimeError("DB 끊김")

    assert Z.maybe_auto_clear_qty_mismatch_ks(_Boom(None), 1) is False


# ═════════════════════════════════════════════════════════════════════
# any_stuck_strategy — fail 방향
# ═════════════════════════════════════════════════════════════════════

def test_redis가_없으면_None(monkeypatch):
    monkeypatch.setattr(Z, "_redis", lambda: None)
    assert Z.any_stuck_strategy() is None


def test_키가_있으면_True(monkeypatch):
    class _R:
        def scan_iter(self, match=None, count=None):
            yield b"zombie:stuck:2477"
    monkeypatch.setattr(Z, "_redis", lambda: _R())
    assert Z.any_stuck_strategy() is True


def test_키가_없으면_False(monkeypatch):
    class _R:
        def scan_iter(self, match=None, count=None):
            return iter(())
    monkeypatch.setattr(Z, "_redis", lambda: _R())
    assert Z.any_stuck_strategy() is False


def test_scan이_터지면_None(monkeypatch):
    class _R:
        def scan_iter(self, match=None, count=None):
            raise RuntimeError("redis down")
    monkeypatch.setattr(Z, "_redis", lambda: _R())
    assert Z.any_stuck_strategy() is None


# ═════════════════════════════════════════════════════════════════════
# 🚨 실제로 호출되는가 (Fix 247/318 의 교훈)
# ═════════════════════════════════════════════════════════════════════

def test_reconcile_이_실제로_부른다():
    """🚨 안 부르면 이 코드는 있으나 마나다 — 사장님이 또 수동으로 풀어야 한다."""
    from app.workers import reconcile_worker as W
    src = Path(W.__file__).read_text(encoding="utf-8")
    assert "maybe_auto_clear_qty_mismatch_ks" in src, "reconcile 이 자동 해제를 안 부른다"
    # 거래소 대조가 끝난 뒤(orphan 감지 이후)에 있어야 카운터가 최신이다
    i_orphan = src.index("detect_orphan_exchange_positions(")
    i_clear = src.index("maybe_auto_clear_qty_mismatch_ks(db")
    assert i_orphan < i_clear, "대조 전에 풀면 낡은 카운터로 판단하게 된다"


def test_판정이_한_곳에만_정의된다():
    """Fix 221 과 따로 놀면 한쪽만 고치는 사고가 난다."""
    src = Path(Z.__file__).read_text(encoding="utf-8")
    assert src.count("def maybe_auto_clear_qty_mismatch_ks") == 1
    assert src.count("def any_stuck_strategy") == 1
    from app.workers import reconcile_worker as W
    wsrc = Path(W.__file__).read_text(encoding="utf-8")
    assert "def any_stuck_strategy" not in wsrc
    assert 'reason_code or "") != "ZOMBIE:QTY_MISMATCH_PERSISTENT"' not in wsrc, \
        "사유 판정이 워커에 복제됐다"


def test_실측_근거가_주석에_남아_있다():
    src = Path(Z.__file__).read_text(encoding="utf-8")
    for token in ("XMRUSDT", "2477", "네 번째", "07-21", "5시간"):
        assert token in src, token
