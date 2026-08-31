"""🛡️ Fix 247 — 두 번 측정된 신호를 진입에 실제로 쓰는가.

## 두 번의 실측이 같은 것을 말한다

**① v139 백테스트** (strategy_confluence.py 주석에 이미 적혀 있던 것):

    AVOID      227건  ->  -19,207 USDT = 전체 손실 -22,068 의 **87%**
    CONFLICT    67건  ->  4h 적중률 **16.4%** / 평균 -1.86%  <- 금지보다도 나쁨
    AGREE       40건  ->  57.5% / +2.00%

**② 2026-08-31 실측** (자동매매 4일, 진입 스냅샷 112건 = 승 23 / 패 89):

    confluence.blocked        승 중앙값 0.000 / 패 중앙값 1.000   효과크기 -2.06
    sar_ichimoku.cloud_15m_ok 승 1.000 / 패 0.000                 효과크기 +2.09
    ema_vcp.trend_ok          승 1.000 / 패 0.000                 효과크기 +2.02

64개 필드 중 상위가 전부 이 한 신호였다(추세 정렬을 6가지로 본 것).

## 그런데 진입에는 안 쓰였다

`strategy_confluence.evaluate` 호출자는 `api/v1/analysis.py`(화면) 와
`learning_sync_worker.py`(학습 저장) 둘뿐이었다.
시스템이 「하지 마라」를 계산해 놓고 **그대로 들어갔다.**
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from app.services.confluence_gate import (
    SETTING_KEY,
    check_confluence_gate,
    confluence_gate_enabled,
)

APP = Path(__file__).resolve().parents[2] / "app"
FUNNEL = APP / "workers" / "auto_bb_breakdown_worker.py"


class _Boom:
    def get_klines(self, **_kw):
        raise RuntimeError("boom")


# ───────────────────────────────── fail-open (막는 게이트의 안전 방향)

def test_no_client_passes():
    allow, why, _d = check_confluence_gate(None, "X", "LONG")
    assert allow and "client_none" in why


def test_kline_failure_passes():
    """🚨 조회 실패로 자동매매가 통째로 멈추면 안 된다 (obv_gate 와 같은 원칙)."""
    allow, why, _d = check_confluence_gate(_Boom(), "X", "LONG")
    assert allow and "pass" in why


def test_empty_klines_pass():
    bc = MagicMock()
    bc.get_klines.return_value = []
    allow, why, _d = check_confluence_gate(bc, "X", "SHORT")
    assert allow and "klines_missing" in why


# ───────────────────────────────── 기본 OFF

def test_gate_defaults_to_off():
    """🚨 얼마나 막는지 사장님이 먼저 보셔야 한다. 기본 ON 이면 매매가 급감할 수 있다."""
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    assert confluence_gate_enabled(db) is False
    assert SETTING_KEY == "confluence_gate_enabled"


def test_enabled_when_setting_says_so():
    from types import SimpleNamespace
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = SimpleNamespace(value="1")
    assert confluence_gate_enabled(db) is True


# ───────────────────────────────── 연결 확인

def _funnel_code() -> str:
    return "\n".join(
        ln for ln in FUNNEL.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_gate_is_wired_into_the_shared_entry_funnel():
    """모든 자동 진입이 지나는 한 곳에 있어야 5개 워커가 함께 보호된다."""
    code = _funnel_code()
    assert "check_confluence_gate" in code
    assert "def _create_auto_bb_strategy" in code
    i_fn = code.index("def _create_auto_bb_strategy")
    i_gate = code.index("check_confluence_gate")
    assert i_gate > i_fn, "게이트가 공용 진입 함수 밖에 있다"


def test_blocked_entry_returns_none_when_enabled():
    """차단이면 전략을 만들지 않고 None 을 돌려줘야 한다."""
    code = _funnel_code()
    i = code.index("if not _allow:")
    window = code[i: i + 500]
    assert "_cg_on(db)" in window, "설정 확인 없이 차단한다"
    assert "return None" in window, "차단인데 전략이 만들어진다"


def test_preview_log_exists_while_off():
    """🚨 OFF 여도 「막았을 것」이 보여야 사장님이 켤지 판단할 수 있다."""
    src = FUNNEL.read_text(encoding="utf-8")
    assert "막았을 것" in src
    assert "confluence_gate_enabled" in src, "켜는 방법이 로그에 없다"


def test_gate_runs_after_other_checks_not_per_candidate():
    """캔들 3회 x 후보 40~100 이면 IP ban 위험(Fix 117/122 실제 사고).

    진입 생성 직전 = 사이클당 몇 건뿐인 자리에 있어야 한다.
    """
    code = _funnel_code()
    assert "check_confluence_gate" in code
    # 스캔 루프가 아니라 생성 함수 안에 있어야 한다
    assert code.count("check_confluence_gate") == 1, "여러 곳에서 부르면 weight 가 는다"
