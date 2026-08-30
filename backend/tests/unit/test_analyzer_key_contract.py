"""🛡️ Fix 229 — `analyze_timeframe` 이 **주지 않는 키**를 읽는 워커를 자동으로 잡는다.

## 실측 사고 (2026-08-30 발견)

`pump_dump_early_detector_worker` 가 6중 지표 중 **4개를 없는 키로 읽고 있었다**:

    읽은 키          실제 키
    bb_up        →  bb_up_last
    bb_mb        →  bb_mid_last
    bb_lo        →  bb_lo_last
    close_now    →  closes[-1]
    macd_hist_now →  macd_hist   (리스트)
    obv_slope    →  (아예 없음)

전부 None 이 되어 신호 4개가 **영구 False**. 살아 있는 신호는 rsi/cci/vol 3개뿐인데
`MIN_PASSED = 5` 라 **수학적으로 알람을 한 건도 낼 수 없었다.**
5분마다 API weight 만 쓰고 산출은 0 — 「조용한 실패」의 전형이다.

🚨 이건 **코드를 읽어서는 안 보인다.** 오타가 없고 문법도 맞다.
   `analyze_timeframe` 의 반환 키와 **대조해야만** 보인다 (헌법 169).
   그래서 매번 도는 자리에 검사를 둔다.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
ANALYZER = APP / "services" / "chart_analyzer.py"

# analyze_timeframe 을 부른 결과에서 흔히 찾는, 그러나 **존재하지 않는** 이름들.
# 실제 사고에서 쓰인 것 + 헷갈리기 쉬운 변형.
BAD_KEYS = {
    "bb_up", "bb_mb", "bb_mid", "bb_lo", "bb_middle",
    "close_now", "macd_hist_now", "obv_slope", "obv_now",
    "rsi", "cci", "volume_now",
}


def _analyzer_return_keys() -> set[str]:
    """chart_analyzer.analyze_timeframe 이 실제로 돌려주는 키를 AST 로 뽑는다."""
    tree = ast.parse(ANALYZER.read_text(encoding="utf-8"))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
            continue
        cur = {
            k.value for k in node.value.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
        # 반환 dict 중 "closes" 를 담은 것이 analyze_timeframe 의 것이다
        if "closes" in cur and "obv" in cur:
            keys |= cur
    return keys


def test_analyzer_contract_is_readable():
    """계약을 못 읽으면 아래 검사가 전부 무의미해진다."""
    keys = _analyzer_return_keys()
    assert {"closes", "obv", "volumes", "rsi_now", "macd_hist",
            "cci_now", "bb_up_last", "bb_mid_last", "bb_lo_last"} <= keys, sorted(keys)


def test_no_worker_reads_nonexistent_analyzer_keys():
    """🚨 `analyze_timeframe` 결과에서 **없는 키**를 읽는 곳이 없어야 한다.

    실패하면 그 워커는 그 신호가 **영구 False** 인 채로 돌고 있다는 뜻이다.
    """
    real = _analyzer_return_keys()
    bad = BAD_KEYS - real          # 진짜로 없는 것만 검사 대상
    assert bad, "대조군 무효 — BAD_KEYS 가 전부 실제 키가 됐다"

    # `result = ChartAnalyzer.analyze_timeframe(...)` 처럼 받은 변수명을 찾고,
    # 그 변수에 대한 .get("...") 만 본다 (다른 dict 의 같은 키는 무관하다).
    violations: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "analyze_timeframe" not in src:
            continue
        code = "\n".join(
            ln for ln in src.splitlines() if not ln.lstrip().startswith("#")
        )
        varnames = set(re.findall(r"(\w+)\s*=\s*ChartAnalyzer\.analyze_timeframe", code))
        varnames |= set(re.findall(r"(\w+)\s*=\s*\w*\.?analyze_timeframe", code))
        for var in varnames:
            for key in re.findall(rf"\b{re.escape(var)}\.get\(\s*[\"'](\w+)[\"']", code):
                if key in bad:
                    violations.append(f"{path.relative_to(APP.parent)}  {var}.get('{key}')")
    assert not violations, (
        "analyze_timeframe 이 주지 않는 키를 읽는다 = 그 신호가 영구 False:\n  "
        + "\n  ".join(sorted(set(violations)))
        + "\n→ 올바른 이름: bb_up_last / bb_mid_last / bb_lo_last / macd_hist(리스트) / "
          "closes[-1] / obv+volumes"
    )


def test_detector_would_have_caught_the_real_bug():
    """음성 대조군 (헌법 170) — 사고 당시 코드를 넣으면 실제로 걸리는가."""
    real = _analyzer_return_keys()
    old_reads = {"bb_up", "bb_mb", "bb_lo", "close_now", "macd_hist_now", "obv_slope"}
    missing = old_reads - real
    assert missing == old_reads, (
        f"옛 코드가 읽던 키 중 일부가 실제로 존재한다 = 대조군 무효: {old_reads & real}"
    )
