"""🛡️ 코드베이스 자동 가드 — 「에이전트가 읽어서는 못 잡는」 종류의 버그를 막는다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사장님 (2026-08-29):
  "에이전트팀이 모두 구성되어있고 모든 검증을 하고 통과 했는데 이런 문제가 없게
   할려면 어떤 에이전트팀을 구성해야 하는지"

정직한 답: **팀을 하나 더 만들어도 못 잡는다.** 오늘 놓친 두 버그는 둘 다
「코드를 읽어서는 안 보이는」 종류였다:

  1. Fix 207 — StrategyStagePlan(side=None) 이 NOT NULL 위반.
     코드만 보면 정상이다. **DB 스키마와 대조**해야 보인다.
     -> 그래서 이 경로는 v130 이후 한 번도 성공한 적이 없었다.

  2. RSI_OVERSOLD_MAX / RSI_MIN_TURNUP / CCI_OVERSOLD_MAX / CCI_MIN_TURNUP —
     정의만 있고 **어디서도 안 쓰이는** 죽은 임계값.
     정의부만 읽으면 정상이다. **참조를 세야** 보인다.
     -> 「진입 조건을 올렸다」고 보고하고 아무 일도 안 일어날 뻔했다.

그리고 사람이 기억해서 호출해야 하는 절차는 **반드시 잊힌다** —
실제로 나는 이 결손들을 찾아서 메모리에 적어두고도 코드를 안 고쳤다.

=> 검사는 **매번 자동으로 도는 자리**에 있어야 한다. 그게 이 파일이다.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import ast
import importlib
import pkgutil
import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"


# ═══════════════════════════════════════════════════════════════════════════
# 가드 1: ORM 생성이 NOT NULL 컬럼을 빠뜨리지 않는가  (Fix 207 이 이걸로 잡힌다)
# ═══════════════════════════════════════════════════════════════════════════
def _not_null_columns() -> dict[str, set[str]]:
    """모델별 「반드시 값을 줘야 하는」 컬럼. 기본값·서버기본값이 있으면 제외."""
    from app.db.base import Base
    import app.models as models_pkg

    for _, name, _ in pkgutil.iter_modules(models_pkg.__path__):
        try:
            importlib.import_module(f"app.models.{name}")
        except Exception:      # 모델 하나가 안 올라와도 나머지는 검사한다
            pass

    out: dict[str, set[str]] = {}
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        required = {
            c.name for c in cls.__table__.columns
            if not c.nullable and not c.primary_key
            and c.default is None and c.server_default is None
        }
        if required:
            out[cls.__name__] = required
    return out


def _model_constructions():
    """app/ 전체에서 `Model(...)` 호출을 찾아 (파일, 줄, 모델명, 준 인자) 로."""
    models = _not_null_columns()
    for path in sorted(APP.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.keywords:
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (
                fn.attr if isinstance(fn, ast.Attribute) else None)
            if name not in models:
                continue
            # **kwargs 로 넘기면 정적으로 판단 불가 → 건너뛴다 (거짓 경보 방지)
            if any(k.arg is None for k in node.keywords):
                continue
            yield path, node.lineno, name, {k.arg for k in node.keywords}, models[name]


def test_orm_constructions_fill_not_null_columns():
    """NOT NULL 컬럼을 빠뜨린 모델 생성이 하나도 없어야 한다.

    🚨 이 테스트가 실패하면 **런타임에 IntegrityError 로 터진다.**
       Fix 207 실측: StrategyStagePlan(side=None) → 「▶ 다음 단계」 버튼이 500.
       v130 부터 계속 죽어 있었는데 아무도 몰랐다 (테스트가 그 경로를 안 탔다).
    """
    violations = [
        f"{p.relative_to(APP.parent)}:{ln}  {name}  누락={sorted(req - given)}"
        for p, ln, name, given, req in _model_constructions()
        if req - given
    ]
    assert not violations, (
        "NOT NULL 컬럼을 빠뜨린 모델 생성 발견 (런타임 IntegrityError):\n  "
        + "\n  ".join(violations)
    )


def test_not_null_detector_actually_works():
    """음성 대조군 (헌법 132) — 검사기가 진짜로 잡는지 증명한다.

    검사기 자체가 고장나면 위 테스트는 **항상 통과**한다. 그게 더 위험하다.
    """
    models = _not_null_columns()
    assert "StrategyStagePlan" in models, "모델을 하나도 못 읽었다 = 검사기 고장"
    required = models["StrategyStagePlan"]
    # Fix 207 이전 코드가 주던 인자 (side / trigger_mode 없음)
    old_kwargs = {"strategy_instance_id", "stage_no", "trigger_mode",
                  "trigger_price", "planned_capital", "planned_qty",
                  "additional_margin_usdt", "is_triggered"}
    missing = required - old_kwargs
    assert "side" in missing, (
        f"검사기가 Fix 207 버그를 못 잡는다. required={sorted(required)}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 가드 2: 진입 판정 상수가 죽어 있지 않은가  (RSI/CCI 죽은 상수 4개가 이걸로 잡힌다)
# ═══════════════════════════════════════════════════════════════════════════
#
# 이미 죽어 있는 것들. 「지금 상태를 얼려두고 **새로 늘어나는 것만** 막는다」.
# 여기 있는 것을 되살리거나 지우면 이 목록에서도 빼야 한다.
KNOWN_DEAD_THRESHOLDS = {
    # 🚨 2026-08-29 발견 — 진입 조건을 올리려다 「올려도 아무 일 없음」을 발견했다.
    #   되살릴지 지울지는 사장님 결정 사항이라 지금은 얼려둔다.
    ("auto_long_at_bottom_worker", "RSI_OVERSOLD_MAX"),
    ("auto_long_at_bottom_worker", "RSI_MIN_TURNUP"),
    ("auto_long_at_bottom_worker", "CCI_OVERSOLD_MAX"),
    ("auto_long_at_bottom_worker", "CCI_MIN_TURNUP"),
    # 코드 주석이 「레거시 상수 = 다른 곳 참조 방지 = 유지!」라고 의도를 밝혀 둔 것
    ("success_pyramiding_worker", "MIN_UNREALIZED_PNL_PCT"),
}

# 진입/청산 판정을 하는 워커만 본다 (전 코드베이스로 넓히면 거짓 경보가 많다)
_DECISION_WORKERS = (
    "auto_long_at_bottom_worker",
    "pump_split_entry_worker",
    "success_pyramiding_worker",
    "stage_trigger_worker",
)

_THRESHOLD_NAME = re.compile(r"^[A-Z][A-Z0-9_]*(PCT|MAX|MIN|LIMIT|THRESHOLD|ROI|BARS)$")


def _dead_thresholds() -> list[tuple[str, str]]:
    dead = []
    for mod in _DECISION_WORKERS:
        path = APP / "workers" / f"{mod}.py"
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        # 모듈 최상위의 숫자 상수만
        names = {
            t.id
            for node in tree.body
            if isinstance(node, ast.Assign)
            for t in node.targets
            if isinstance(t, ast.Name) and _THRESHOLD_NAME.match(t.id)
        }
        # 주석을 걷어낸 코드에서 참조 횟수를 센다 (내 주석이 살려주면 안 된다)
        code = "\n".join(
            ln for ln in src.splitlines() if not ln.lstrip().startswith("#")
        )
        for n in names:
            uses = len(re.findall(rf"\b{re.escape(n)}\b", code))
            if uses <= 1:      # 대입 1회 = 아무도 안 쓴다
                dead.append((mod, n))
    return sorted(dead)


def test_no_new_dead_decision_thresholds():
    """진입 판정 임계값이 「정의만 되고 안 쓰이는」 상태로 늘어나면 안 된다.

    🚨 실측(2026-08-29): RSI_OVERSOLD_MAX / RSI_MIN_TURNUP / CCI_OVERSOLD_MAX /
       CCI_MIN_TURNUP 이 죽은 상수였다. 사장님이 「진입 조건을 올려달라」고 하셨을 때
       이걸 올렸다면 **아무 일도 안 일어나면서 「올렸다」고 보고**했을 것이다.
    """
    found = set(_dead_thresholds())
    new = found - KNOWN_DEAD_THRESHOLDS
    assert not new, (
        "새로 생긴 죽은 임계값 (정의만 있고 아무데도 안 쓰임):\n  "
        + "\n  ".join(f"{m}.{n}" for m, n in sorted(new))
        + "\n→ 실제로 쓰거나, 지우거나, KNOWN_DEAD_THRESHOLDS 에 사유와 함께 등록하라."
    )


def test_dead_threshold_detector_actually_works():
    """음성 대조군 — 이미 아는 죽은 상수를 실제로 잡아내는가."""
    found = set(_dead_thresholds())
    still_dead = KNOWN_DEAD_THRESHOLDS & found
    assert still_dead, (
        "검사기가 이미 알려진 죽은 상수를 하나도 못 잡았다 = 검사기 고장. "
        f"발견={sorted(found)}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 가드 3: 고정 경로가 /{id} 파라미터 경로보다 먼저 등록되는가  (헌법 162)
# ═══════════════════════════════════════════════════════════════════════════
def test_static_routes_registered_before_param_routes():
    """`/strategies/block-reasons` 가 `/strategies/{strategy_id}` 뒤에 있으면 422.

    Fix 201 에서 실제로 걸릴 뻔했다. 순서는 눈으로 안 보이는 계약이다.
    """
    pytest.importorskip("fastapi")
    from app.main import app

    # ⚠️ **메서드가 겹칠 때만** 가려진다.
    #   처음에 메서드를 안 보고 짰더니 5건이 거짓 경보로 나왔다
    #   (GET /v219-monitoring 과 DELETE /{suggestion_id} 는 충돌하지 않는다 — 실측 200).
    #   시끄러운 검사는 결국 무시당하므로, 거짓 경보는 검사 자체를 무력화한다.
    routes = [
        (r.path, frozenset(r.methods or ()))
        for r in app.routes if hasattr(r, "methods")
    ]
    problems = []
    for i, (p, meths) in enumerate(routes):
        if "{" in p:
            continue
        prefix = p.rsplit("/", 1)[0]
        for j, (q, qm) in enumerate(routes[:i]):
            if not q.startswith(prefix + "/{"):
                continue
            if q.count("/") != p.count("/"):
                continue
            shared = meths & qm
            if shared:
                problems.append(
                    f"{sorted(shared)} {p} (idx {i}) 가 {q} (idx {j}) 에 가려짐"
                )
    assert not problems, (
        "고정 경로가 같은 메서드의 파라미터 경로에 가려짐 (422 발생):\n  "
        + "\n  ".join(problems)
        + "\n→ 고정 경로를 /{id} 경로보다 **먼저** 등록하라 (헌법 162)."
    )
