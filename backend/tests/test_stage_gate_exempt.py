"""Fix 321 — 손절 단계 게이트 면제가 **세 곳 모두**에 걸리는가.

## 왜 이 파일이 필요한가

Fix 315 가 신규 자동 전략을 1단계 → 3단계로 바꿨는데
`capital_management_mode = "stage_ladder"` 마커를 **저장하는 코드가 0곳**이었다.
그래서 면제가 안 걸리고 `1 < 3` 이 성립해 **force SL(-5%)이 3단계까지 잠겼다**
— Fix 317 이 "사장님이 잃은 돈의 구조적 원인" 이라 적은 그 교착을 신규 전략
전건에 다시 심은 것이다. (검증이 배포 후 잡았고 실제 피해는 0)

게이트가 **세 곳**에 흩어져 있고 면제는 **한 곳에만** 있던 것이 뿌리다.
"""
import ast
from pathlib import Path

from app.services import risk_service as R

SRC = Path(R.__file__).read_text(encoding="utf-8")


class _S:
    """전략 스텁."""

    def __init__(self, *, retry=False, mode="fixed"):
        self.retry_after_liquidation_enabled = retry
        self.capital_management_mode = mode
        self.id, self.symbol = 1, "X"


class _DB:
    def __init__(self, settings=None, boom=False):
        self.s = settings or {}
        self.boom = boom

    def get(self, _m, k):
        if self.boom:
            raise RuntimeError("db down")
        if k not in self.s:
            return None
        return type("R", (), {"value": self.s[k]})()


def _svc(db):
    svc = R.RiskService.__new__(R.RiskService)
    svc.db = db
    return svc


TRIM_ON = {"stage_trim_before_next_enabled": "1"}


# ── 면제 대상 (전부 「단계마다 손절해야 하는」 설계) ──────────────────

def test_청산후_재진입은_면제():
    assert _svc(_DB())._stage_gate_exempt(_S(retry=True))[0] is True


def test_분할매수는_면제():
    ok, why = _svc(_DB())._stage_gate_exempt(_S(mode="split_entry"))
    assert ok is True and "split_entry" in why


def test_단계_사다리는_면제():
    """🚨 이게 안 걸려서 신규 전략의 손절이 3단계까지 잠겼다."""
    ok, why = _svc(_DB())._stage_gate_exempt(_S(mode="stage_ladder"))
    assert ok is True and "stage_ladder" in why


def test_단계_정리_ON이면_면제():
    ok, why = _svc(_DB(TRIM_ON))._stage_gate_exempt(_S())
    assert ok is True and "Fix304" in why


def test_아무것도_아니면_면제_아님():
    """옛 물타기 전략은 v130 동작 그대로 — 남의 전략을 바꾸지 않는다."""
    assert _svc(_DB())._stage_gate_exempt(_S())[0] is False


def test_판정_실패는_옛_동작():
    """🚨 여기서 fail-open 하면 물타기 전략의 손절까지 앞당겨진다."""
    assert _svc(_DB(boom=True))._stage_gate_exempt(_S())[0] is False


# ── 🚨 세 게이트가 **모두** 같은 판정을 쓰는가 ────────────────────────

def test_게이트가_세_곳이고_전부_공용판정을_쓴다():
    """한 곳만 고치는 사고를 구조적으로 막는다 (이번 사고의 뿌리)."""
    assert SRC.count("self._stage_gate_exempt(strategy)") == 3
    # 옛 개별 조건 잔재가 남아 있으면 안 된다
    assert "_retry_flow or _split_mode" not in SRC


# 손절/청산을 **판정하는** 함수만 대상이다.
#   `_should_trigger_crisis_mode`(모드 전환) / `_maybe_send_loss_threshold_alert`(알림)
#   도 단계를 보지만 **청산을 실행하지 않으므로** 이 규칙의 대상이 아니다.
_SL_JUDGES = (
    "evaluate_stop_loss",
    "evaluate_force_stop_loss",
    # 크라이시스 Stage 2 전용 -1% 검사. **단계 게이트를 쓰지 않으므로**
    # 면제도 필요 없다 — 위 규칙이 "게이트를 쓰면 면제도 써라" 이므로 자동 통과.
    "evaluate_stop_loss_crisis_aware",
)


def test_손절_판정_함수가_전부_면제를_쓴다():
    """🚨 한 곳만 고치면 다른 손절이 잠긴다 — 이번 사고의 뿌리."""
    tree = ast.parse(SRC)
    bad = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.FunctionDef) or n.name not in _SL_JUDGES:
            continue
        seg = ast.get_source_segment(SRC, n) or ""
        if "current_stage" in seg and "_stage_gate_exempt" not in seg:
            bad.append(n.name)
    assert not bad, f"면제 없이 단계 게이트를 쓰는 손절 함수: {bad}"


def test_손절_판정_함수_목록이_고정돼_있다():
    """🚨 새 손절 판정이 생기면 실패 → 면제 적용 여부를 반드시 검토하게 한다.

    이 테스트가 실제로 `evaluate_stop_loss_crisis_aware` 를 찾아냈다 —
    내가 모르던 세 번째 손절 경로였다."""
    tree = ast.parse(SRC)
    names = {n.name for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef)
             and n.name.startswith("evaluate_")
             and "stop_loss" in n.name}
    assert names == set(_SL_JUDGES), f"손절 판정 함수가 바뀌었다: {sorted(names)}"


# ── 🚨 마커가 실제로 저장되는가 (이번 사고의 직접 원인) ───────────────

def test_사다리_전략_생성시_마커를_저장한다():
    """🚨 `is_stage_ladder` 가 읽을 값을 **아무도 저장하지 않으면** 죽은 코드다."""
    from app.workers import auto_bb_breakdown_worker as W
    src = Path(W.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = False
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "create_strategy_instance"
                and any(k.arg == "capital_management_mode" for k in n.keywords)):
            found = True
    assert found, "create_strategy_instance 에 capital_management_mode 를 안 넘긴다"


def test_마커_상수가_읽기와_쓰기_양쪽에_있다():
    """정의만 있고 대입이 0곳이면 그 기능은 존재하지 않는 것과 같다."""
    from app.services import sajangnim_capital as C
    from app.workers import auto_bb_breakdown_worker as W
    assert C.STAGE_LADDER_MODE == "stage_ladder"
    wsrc = Path(W.__file__).read_text(encoding="utf-8")
    assert "STAGE_LADDER_MODE as _LADDER_MODE" in wsrc
    assert "_LADDER_MODE if stages_config" in wsrc


# ═══════════════════════════════════════════════════════════════════════
# Fix 322/323 — 기본 방식과 OBV 자동을 「철저하게」
# ═══════════════════════════════════════════════════════════════════════

class _S2:
    def __init__(self, **kw):
        self.retry_after_liquidation_enabled = kw.get("retry", False)
        self.capital_management_mode = kw.get("mode", "fixed")
        self.force_sl_enabled_override = kw.get("fs_on")
        self.force_sl_roi_override = kw.get("fs_roi")
        self.id, self.symbol = 1, "X"


def test_기본방식_손절이_명시되면_trim과_무관하게_면제():
    """🚨 사장님이 화면에서 만드는 기본 전략은 mode='fixed' + retry 미체크라
    `stage_trim_before_next_enabled` **하나에만** 매달려 있었다.
    그 스위치를 끄는 순간 손절이 다시 마지막 단계까지 잠긴다."""
    from decimal import Decimal
    svc = _svc(_DB())          # trim OFF
    ok, why = svc._stage_gate_exempt(_S2(fs_roi=Decimal("3")))
    assert ok is True and "손절 명시" in why


def test_손절_미설정이면_옛_동작():
    """v130 「물타기 기회」는 손절을 명시하지 않은 전략에만 남는다."""
    assert _svc(_DB())._stage_gate_exempt(_S2())[0] is False


def test_손절_0이나_음수는_면제_아님():
    from decimal import Decimal
    svc = _svc(_DB())
    assert svc._stage_gate_exempt(_S2(fs_roi=Decimal("0")))[0] is False


def test_enabled_플래그만_있어도_면제():
    assert _svc(_DB())._stage_gate_exempt(_S2(fs_on=True))[0] is True


def test_판정_실패해도_다른_면제는_살아있다():
    """손절 필드가 없는 객체여도 예외로 죽으면 안 된다."""
    class _Bare:
        capital_management_mode = "stage_ladder"
        retry_after_liquidation_enabled = False
    assert _svc(_DB())._stage_gate_exempt(_Bare())[0] is True


def test_OBV모달이_재진입을_자동으로_켜지_않는다():
    """🚨 자동 체크가 `stage_trigger_worker` 의 retry 분기를 타게 해
    OBV 전략이 1단계에서 멈췄다."""
    from pathlib import Path
    from app.services import risk_service as _R
    js = (Path(_R.__file__).resolve().parents[1] / "static" / "js"
          / "cm-open-modal.js").read_text(encoding="utf-8")
    assert "_retryEl.checked = true" not in js, "재진입을 자동으로 켜면 2단계가 막힌다"
    assert "Fix 323" in js, "왜 제거했는지 근거가 남아 있어야 한다"


def test_워커가_손절_명시_전략의_단계진입을_막지_않는다():
    from pathlib import Path
    from app.workers import stage_trigger_worker as W
    src = Path(W.__file__).read_text(encoding="utf-8")
    assert "_sl_explicit" in src
    assert "if (not _trim_on and not _sl_explicit" in src
