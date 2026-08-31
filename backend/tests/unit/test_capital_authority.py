"""🛡️ Fix 236 — **자본은 사장님이 정한 것만 쓴다** (자본 권한 가드).

사장님 지시 (2026-08-31):
  "이런일은 없게 해주고 **우리가 정한거 아닌건 확실하게 찾아서** 문제없게 만들어줘"

## 배경

`REENTRY_MULTIPLIER = 1.5` 를 보고 「무단 마틴게일」로 의심했으나, 실측 결과
**그 규칙 자체는 2026-08-21 사장님 verbatim** 이었다:

    "실패한 심볼은 모니터링 하다가 다시 진입할 시점에 이전 포지션의 1.5배!
     2번까지 할수 있는 로직!"

진짜 무단이었던 것은 **배수의 기준값**이다:

    _base = float(cfg.get("capitals", [500])[0])     <- 설정이 비면 코드가 500 을 지어냄

1.5배 규칙이 사장님 것이어도, **무엇의 1.5배인지**가 사장님이 정한 값이 아니면
결과 금액도 사장님 것이 아니다. 같은 형태가 pending_hc_fast_worker 에도 있었다.
둘 다 현재는 스케줄러 등록이 주석 처리된 죽은 워커지만, **주석 한 줄만 풀면
발사되는 지뢰**였다.

## 이 가드가 하는 일

1. 자본을 정하는 **모든 상수**를 근거(사장님 지시 날짜)와 함께 등록한다.
   값이 바뀌면 테스트가 깨진다 = **소리 없는 변경 불가**.
2. `capitals` 의 **하드코딩 폴백**이 다시 생기면 잡는다.
3. 등록되지 않은 **새 자본 배수**가 생기면 잡는다.

🚨 이 파일을 고쳐서 통과시키려는 순간, 그것이 바로 **사장님 승인이 필요한 지점**이다.
"""
from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"

# ─────────────────────────────────────────────────────────────────────────
# 사장님이 승인한 자본 규칙 — 각 항목은 **날짜 있는 근거**를 반드시 가진다.
#   key   = app/ 기준 상대 경로
#   value = [(소스에 그대로 있어야 하는 문자열, 근거)]
# ─────────────────────────────────────────────────────────────────────────
SANCTIONED: dict[str, list[tuple[str, str]]] = {
    "services/sajangnim_capital.py": [
        ('DEFAULT_CAPITAL_LADDER = [Decimal("10"), Decimal("300"), Decimal("600")]',
         "사장님 자본 사다리 10/300/600 (SystemSetting 으로 변경 가능)"),
        ('DEFAULT_PYRAMID_CAPITAL = Decimal("300")',
         "Fix 176 / 2026-08-27 verbatim: 피라미딩 1회 = 300 고정, 사다리와 독립"),
        ("MAX_REENTRY_STAGE = 3",
         "2026-08-22 사장님 최종: 3단계까지"),
    ],
    "workers/auto_bb_breakdown_worker.py": [
        ("REENTRY_MULTIPLIER = 1.5",
         "2026-08-21 verbatim: 재진입은 이전 포지션의 1.5배, 2번까지"),
        ("MAX_REENTRY_COUNT = 2",
         "2026-08-22 v219 사장님 최종: 재진입 2번 = 3단계까지"),
    ],
    "workers/realtime_reentry_worker.py": [
        ("ENABLE_LAST_CHANCE = True",
         "사장님 verbatim: 최종단계 진입금액으로 한번더 하고 안되면 종료"),
        ("MAX_REENTRY_STAGE_WITH_LAST = 4",
         "위와 동일 — 3단계 + 라스트 챈스 1회. 자본은 증액 없이 동일 금액"),
    ],
    "workers/auto_add_margin_worker.py": [
        ("ROI_TRIGGER = -30.0",
         "2026-08-22 v220 verbatim: 전체 손실 30% 넘어가면"),
        ('return ("per_strategy", None)',
         "2026-08-31 사장님 선택 「B」: 「초기금액으로」 = 그 전략의 1단계 자본. "
         "옛 코드는 DEFAULT_ADD_MARGIN_USDT = 300 일괄이었는데, 그 300 은 "
         "2026-08-22 당시 초기금액(v219 300/600/1800)이라 맞았다가 "
         "2026-08-26 Fix 133 이 사다리를 10/300/600 으로 바꾼 뒤 얼어붙었다"),
    ],
}

# 자본을 돌려주는 함수가 **리터럴을 지어내는** 형태.
#   실측 사고: realtime_reentry_worker `return 500.0`
#   = 사다리가 무너졌을 때 10 이 아니라 500 으로 진입하는 fail-BIG 이었다.
_LITERAL_RETURN_RE = re.compile(r"^\s*return\s+[0-9]+(?:\.[0-9]+)?\s*$")
_CAPITAL_FN_RE = re.compile(r"^\s*def\s+\w*capital\w*\s*\(", re.IGNORECASE)

# 자본의 하드코딩 폴백:  get("capitals", [500])  형태
_FALLBACK_RE = re.compile(r"""get\(\s*["']capitals["']\s*,\s*\[\s*[0-9]""")

# 새로 생긴 자본 배수 상수
_MULTIPLIER_RE = re.compile(
    r"^\s*([A-Z_]*(?:MULTIPLIER|CAPITAL_FACTOR|MARTINGALE)[A-Z_]*)\s*="
)

# 이름은 배수처럼 보이지만 **자본과 무관**한 것 — 면제한다.
# ⚠️ 면제는 공짜가 아니다. test_exemptions_are_honest 가 이 이름들이 정말로
#    자본 계산에 안 쓰이는지 매번 확인한다. 쓰이기 시작하면 면제가 깨진다.
NOT_CAPITAL: dict[str, str] = {
    "MIN_MARTINGALE_STAGE": "단계 **번호** (2단계부터 검사) — 금액이 아니다",
    "VOLUME_REVERSAL_MULTIPLIER": "거래량 배수 (평균 대비 1.3배) — 금액이 아니다",
}


def _src(rel: str) -> str:
    return (APP / rel).read_text(encoding="utf-8")


def _code_lines(path: Path) -> list[str]:
    """주석을 걷어낸 줄 — 주석 안의 예시가 검사를 오염시키면 안 된다."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    return [ln for ln in raw.splitlines() if not ln.lstrip().startswith("#")]


# ─────────────────────────────────────────────────────────────────────────

def test_every_sanctioned_rule_still_has_its_value():
    """🚨 자본 규칙이 소리 없이 바뀌면 실패한다.

    값을 바꾸려면 이 파일의 근거도 함께 고쳐야 한다 = 사장님 승인 지점.
    """
    missing = []
    for rel, items in SANCTIONED.items():
        src = _src(rel)
        for literal, why in items:
            if literal not in src:
                missing.append(f"{rel}: '{literal}'  (근거: {why})")
    assert not missing, (
        "승인된 자본 규칙이 바뀌었거나 사라졌다:\n  "
        + "\n  ".join(missing)
        + "\n→ 값을 바꾸려면 사장님 승인이 필요하고, 이 파일의 근거도 갱신해야 한다."
    )


def test_no_hardcoded_capital_fallback():
    """🚨 `capitals` 가 비었을 때 **코드가 금액을 지어내면** 안 된다.

    실측 사고: `cfg.get("capitals", [500])[0]` 이 두 워커에 있었다.
    설정이 비면 500 USDT 로 실자금이 나간다 — 사장님이 정한 적 없는 금액이다.
    → 자본이 없으면 **진입하지 않는다** (fail-closed).
    """
    hits = []
    for path in sorted(APP.rglob("*.py")):
        for i, line in enumerate(_code_lines(path), start=1):
            if _FALLBACK_RE.search(line):
                hits.append(f"{path.relative_to(APP.parent)}:{i}  {line.strip()[:90]}")
    assert not hits, (
        "자본의 하드코딩 기본값이 있다 = 사장님이 정하지 않은 금액으로 진입한다:\n  "
        + "\n  ".join(hits)
        + "\n→ 비었으면 진입을 skip 하라 (fail-closed)."
    )


def test_no_unregistered_capital_multiplier():
    """🚨 등록되지 않은 **새 자본 배수**가 생기면 잡는다."""
    known = {lit.split("=")[0].strip()
             for items in SANCTIONED.values() for lit, _ in items}
    rogue = []
    for path in sorted(APP.rglob("*.py")):
        for i, line in enumerate(_code_lines(path), start=1):
            m = _MULTIPLIER_RE.match(line)
            if m and m.group(1) not in known and m.group(1) not in NOT_CAPITAL:
                rogue.append(f"{path.relative_to(APP.parent)}:{i}  {line.strip()[:90]}")
    assert not rogue, (
        "등록되지 않은 자본 배수가 있다:\n  "
        + "\n  ".join(rogue)
        + "\n→ 사장님 근거(날짜+verbatim)와 함께 SANCTIONED 에 등록하거나,"
          " 자본과 무관하면 NOT_CAPITAL 에 사유와 함께 넣어라."
    )


def test_capital_functions_do_not_invent_a_number():
    """🚨 자본을 돌려주는 함수가 **리터럴 금액을 지어내면** 안 된다.

    실측 사고: `_get_base_capital_from_instance` 가 조회에 다 실패하면
    `return 500.0` 이었다. 사다리가 무너졌을 때 10 이 아니라 **500 으로 진입**하는
    fail-BIG. 모르면 큰 금액이 아니라 **None** 을 돌려주고 진입을 막아야 한다.
    """
    hits = []
    for path in sorted(APP.rglob("*.py")):
        in_capital_fn = False
        for i, line in enumerate(_code_lines(path), start=1):
            if line.startswith("def ") or line.startswith("    def "):
                in_capital_fn = bool(_CAPITAL_FN_RE.match(line))
            elif in_capital_fn and _LITERAL_RETURN_RE.match(line):
                hits.append(f"{path.relative_to(APP.parent)}:{i}  {line.strip()[:80]}")
    assert not hits, (
        "자본 함수가 금액 리터럴을 지어낸다 (fail-BIG):\n  "
        + "\n  ".join(hits)
        + "\n→ 모르면 None 을 돌려주고 호출자가 진입을 skip 하게 하라."
    )


def test_exemptions_are_honest():
    """🚨 면제한 상수가 **정말로** 자본 계산에 안 쓰이는지 매번 확인한다.

    면제 목록은 고무도장이 되기 쉽다. 「자본과 무관하다」고 적어 두고 나중에
    누군가 그 상수로 금액을 곱하면, 면제가 그대로 구멍이 된다.
    → 그 이름과 capital 이 **같은 줄**에 나오면 면제를 무효로 본다.
    """
    broken = []
    for name, why in NOT_CAPITAL.items():
        for path in sorted(APP.rglob("*.py")):
            for i, line in enumerate(_code_lines(path), start=1):
                low = line.lower()
                if name in line and "capital" in low and "=" != line.strip()[:1]:
                    if _MULTIPLIER_RE.match(line):
                        continue          # 정의 줄 자체는 제외
                    broken.append(
                        f"{path.relative_to(APP.parent)}:{i}  {line.strip()[:90]}"
                        f"   (면제 사유였던 것: {why})"
                    )
    assert not broken, (
        "「자본과 무관」이라고 면제한 상수가 자본 계산에 쓰이고 있다:\n  "
        + "\n  ".join(broken)
        + "\n→ NOT_CAPITAL 에서 빼고 사장님 근거와 함께 SANCTIONED 로 옮겨라."
    )


def test_detectors_actually_discriminate():
    """음성 대조군 (헌법 170) — 검사기가 위험한 형태를 진짜로 알아보는가."""
    assert _FALLBACK_RE.search('    _base = float(cfg.get("capitals", [500])[0])'), (
        "실제로 있었던 사고 형태를 못 잡는다"
    )
    assert _FALLBACK_RE.search("    caps = _pcfg.get('capitals', [300])"), (
        "따옴표 변형을 못 잡는다"
    )
    assert not _FALLBACK_RE.search('    caps = cfg.get("capitals") or []'), (
        "고친 뒤의 정상 코드가 오탐된다"
    )

    assert _MULTIPLIER_RE.match("SIZE_MULTIPLIER = 2.0"), "새 배수를 못 잡는다"
    assert _MULTIPLIER_RE.match("MARTINGALE_STEP = 2"), "마틴게일 이름을 못 잡는다"
    assert not _MULTIPLIER_RE.match("MAX_REENTRY_COUNT = 2"), "배수가 아닌 상수를 오탐한다"

    # 실제로 있었던 fail-BIG 형태를 잡는가
    assert _CAPITAL_FN_RE.match("def _get_base_capital_from_instance(si) -> float:"), (
        "자본 함수 이름을 못 알아본다"
    )
    assert _LITERAL_RETURN_RE.match("    return 500.0"), "금액 리터럴 반환을 못 잡는다"
    assert not _LITERAL_RETURN_RE.match("    return None"), "고친 코드가 오탐된다"
    assert not _CAPITAL_FN_RE.match("def _get_mark_price(symbol):"), (
        "자본과 무관한 함수를 오탐한다"
    )


def test_every_rule_carries_a_dated_reason():
    """근거가 비어 있으면 등록이 아니다 — 「그냥 있길래 등록」을 막는다."""
    weak = [f"{rel}: {lit}" for rel, items in SANCTIONED.items()
            for lit, why in items if len(why.strip()) < 15]
    assert not weak, "근거가 부실한 등록: " + ", ".join(weak)
