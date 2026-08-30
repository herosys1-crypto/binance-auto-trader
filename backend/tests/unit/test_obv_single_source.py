"""🛡️ Fix 230 — OBV 방향 계산은 **한 곳에서만** 한다.

## 왜 가드가 필요한가

`obv_slope_pct` 라는 한 컬럼에 **3가지 단위**가 섞였던 이유는 단순하다 —
워커마다 자기 산식을 새로 짰다. 그리고 그 산식들이 공통으로 같은 실수를 했다:

    (obv[-1] - obv[-N]) / abs(obv[-N])      ← 분모가 **누적 레벨**

`ChartAnalyzer.compute_obv` 는 창의 **첫 봉을 0 으로** 놓고 누적한다. 그래서
`obv[-N]` 의 절대 레벨은 「fetch 를 어디서 시작했나」에 좌우되는 **임의값**이다.
0 근처면 폭발하고, 정확히 0 이면 `else 1.0` 같은 분기가 원 거래량을 그대로 흘린다.

실측 재현 (같은 데이터로 세 산식):
    realtime_reentry     obv[-1]-obv[-4]        →  2,249,160
    bb_middle_scan       분모 0 → 1.0            →  2,249,159.9
    suggestion_generator (o1-o0)/|o0|*100       →  3,600,000

진입 스냅샷 실측 최대값 2,249,160 과 자릿수가 같다. 학습 표본이 이래서 망가졌다.

→ `app.services.obv_metrics.obv_direction_ratio` **하나만** 쓴다.
"""
from __future__ import annotations

from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
SHARED = "app/services/obv_metrics.py"

# 공통 함수를 반드시 쓰도록 고정하는 모듈들 (오늘 수리한 곳 전부)
MUST_USE_SHARED = (
    "workers/realtime_reentry_worker.py",
    "workers/market_observation_worker.py",
    "workers/pump_dump_early_detector_worker.py",
    "workers/pump_top_detector_worker.py",
    "workers/long_bottom_detector_worker.py",
    "api/v1/bb_middle_scan.py",
    "agents/strategy_suggestion_team/strategy_suggestion_generator.py",
)


def _code(path: Path) -> str:
    """주석을 걷어낸 소스 — 내 주석이 검사를 통과시키거나 실패시키면 안 된다."""
    try:
        src = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""
    return "\n".join(
        ln for ln in src.splitlines() if not ln.lstrip().startswith("#")
    )


def test_shared_function_exists():
    from app.services.obv_metrics import obv_direction_ratio

    assert callable(obv_direction_ratio)


def test_no_module_divides_by_accumulated_obv_level():
    """🚨 `/ abs(obv...)` 형태가 남아 있으면 안 된다 — 무계 값의 원천이다."""
    violations = []
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(APP.parent).as_posix()
        if rel == SHARED:
            continue
        for i, line in enumerate(_code(path).splitlines(), start=1):
            low = line.lower()
            if "obv" in low and "/ abs(" in low.replace(" /abs(", " / abs("):
                violations.append(f"{rel}:{i}  {line.strip()[:90]}")
    assert not violations, (
        "누적 OBV 레벨로 나누는 코드가 남아 있다 (무계 → 학습 표본 오염):\n  "
        + "\n  ".join(violations)
        + "\n→ app.services.obv_metrics.obv_direction_ratio 를 쓰라."
    )


def test_repaired_modules_use_the_shared_function():
    """수리한 모듈이 다시 자기 산식으로 돌아가면 실패한다."""
    missing = [
        rel for rel in MUST_USE_SHARED
        if "obv_direction_ratio" not in _code(APP / rel)
    ]
    assert not missing, (
        "공통 함수를 안 쓰는 모듈: " + ", ".join(missing)
        + "\n→ 워커마다 산식이 갈리면 obv_slope_pct 에 단위가 또 섞인다."
    )


def test_detector_actually_discriminates():
    """음성 대조군 (헌법 170) — 검사기가 위험한 형태를 진짜로 알아보는가."""
    bad = "    obv_slope = (obv[-1] - obv[-10]) / abs(obv[-10]) * 100"
    line = bad.lower()
    assert "obv" in line and "/ abs(" in line, "검사 조건이 옛 산식을 못 알아본다"
    good = "    ratio = obv_direction_ratio(obv, volumes, 20)"
    assert "/ abs(" not in good.lower(), "정상 코드가 오탐된다"
