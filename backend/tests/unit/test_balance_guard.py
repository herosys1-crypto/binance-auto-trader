"""💰 Fix 264 — 잔액 부족을 「예외」가 아니라 「보이는 상태」로.

## 실측 (2026-09-01, VPS)

    balance             6,576.66 USDT   (활성 39건의 ISOLATED 마진 포함)
    availableBalance       46.73 USDT   <- 실제로 쓸 수 있는 돈
    계획자본 합            9,985.00 USDT

재진입이 매 사이클 이렇게 죽고 있었다:

    ValueError: 💰 잔액 부족 — 필요한 마진 150.00 USDT > 가용 잔액 76.52 USDT

그런데 사이클 요약은 `reentered=0 (fail=0 ...)` 이었다 — **fail=0 은 사실이 아니다.**
워커 집계에는 `entry_exception` 으로만 잡혀 원인이 안 보였고,
매 사이클 전체 스택트레이스가 쌓였으며, 잔액이 없는데도 남은 후보 전부에
지표·캔들 API 를 계속 쳤다.

이 파일이 지키는 것:
  ① 잔액 부족은 **탐지**되어야 한다 (다른 ValueError 와 구별)
  ② **짧은 TTL** 이어야 한다 — 수동 해제가 필요한 잠금은 스스로 상황을 연장시킨다
     (2026-08-26 IP ban 사고에서 내 안전장치가 ban 을 연장한 적이 있다)
  ③ Redis 실패는 **막지 않는다** (fail-open) — 이건 낭비를 줄이는 최적화이지
     안전장치가 아니다. 실제 안전장치는 거래소의 잔액 검증이다.
  ④ 알림은 **1시간에 한 번** — 같은 원인으로 화면을 도배하지 않는다
  ⑤ 워커는 사이클 **앞에서** 확인해 API 낭비를 멈춘다
"""
from __future__ import annotations

from pathlib import Path

from app.services.balance_guard import (
    BLOCK_TTL_SEC,
    check_balance_block,
    clear_balance_block,
    is_insufficient_balance_error,
    mark_insufficient_balance,
)

BACKEND = Path(__file__).resolve().parents[2]
FUNNEL = BACKEND / "app" / "workers" / "auto_bb_breakdown_worker.py"
REENTRY = BACKEND / "app" / "workers" / "realtime_reentry_worker.py"
LONGW = BACKEND / "app" / "workers" / "auto_long_at_bottom_worker.py"

REAL_MSG = "💰 잔액 부족 — 필요한 마진 150.00 USDT > 가용 잔액 76.52 USDT"
STAGE1_MSG = "💰 1단계 마진 부족 — 필요 300.00 USDT > 가용 12.30 USDT"


class _Redis:
    """setex/get/delete 만 있는 최소 스텁."""

    def __init__(self, broken=False):
        self.store: dict[str, str] = {}
        self.ttl: dict[str, int] = {}
        self.broken = broken

    def setex(self, k, ttl, v):
        if self.broken:
            raise RuntimeError("redis down")
        self.store[k] = v
        self.ttl[k] = ttl

    def get(self, k):
        if self.broken:
            raise RuntimeError("redis down")
        return self.store.get(k)

    def delete(self, k):
        self.store.pop(k, None)


# ───────────────────────── ① 탐지

def test_detects_both_balance_messages():
    assert is_insufficient_balance_error(REAL_MSG)
    assert is_insufficient_balance_error(STAGE1_MSG)
    assert is_insufficient_balance_error(ValueError(REAL_MSG))


def test_does_not_swallow_unrelated_errors():
    """🚨 다른 ValueError 까지 삼키면 진짜 버그가 조용히 묻힌다."""
    for m in ("Strategy not found", "planned_qty is missing", "", None):
        assert not is_insufficient_balance_error(m)


# ───────────────────────── 기록 / 조회

def test_mark_then_check_roundtrip():
    r = _Redis()
    mark_insufficient_balance(r, REAL_MSG, source="테스트")
    blocked, d = check_balance_block(r)
    assert blocked
    assert d["required"] == 150.0 and d["available"] == 76.52
    assert d["source"] == "테스트"


def test_numbers_survive_unparseable_message():
    """숫자를 못 뽑아도 **막는 것 자체는** 되어야 한다."""
    r = _Redis()
    mark_insufficient_balance(r, "잔액 부족 (형식이 다름)", source="x")
    blocked, d = check_balance_block(r)
    assert blocked and d["required"] is None


def test_nothing_marked_means_not_blocked():
    assert check_balance_block(_Redis()) == (False, {})


def test_clear_releases():
    r = _Redis()
    mark_insufficient_balance(r, REAL_MSG, source="x")
    clear_balance_block(r)
    assert check_balance_block(r)[0] is False


# ───────────────────────── ② 스스로 풀린다

def test_ttl_is_short_and_self_healing():
    """🚨 수동 해제가 필요한 잠금이면 안 된다.

    2026-08-26 IP ban 사고에서 내 가드가 ban 을 **스스로 연장**했다.
    잔액이 회복되면 다음 사이클부터 저절로 정상이어야 한다.
    """
    assert 60 <= BLOCK_TTL_SEC <= 600
    r = _Redis()
    mark_insufficient_balance(r, REAL_MSG, source="x")
    assert r.ttl["entry_block:insufficient_balance"] == BLOCK_TTL_SEC


# ───────────────────────── ③ fail-open

def test_redis_failure_never_blocks():
    """가드가 못 도는 것 때문에 매매가 멈추면 안 된다."""
    assert check_balance_block(_Redis(broken=True)) == (False, {})


def test_mark_survives_redis_failure():
    mark_insufficient_balance(_Redis(broken=True), REAL_MSG, source="x")  # 예외 X


# ───────────────────────── ④ 알림 도배 금지

def test_alert_is_deduped(monkeypatch):
    sent = []

    class _NS:
        def __init__(self, db):
            pass

        def send_system_alert(self, **kw):
            sent.append(kw)

    import app.services.notification_service as ns
    monkeypatch.setattr(ns, "NotificationService", _NS)

    r = _Redis()
    for _ in range(5):
        mark_insufficient_balance(r, REAL_MSG, source="x", db=object())
    assert len(sent) == 1, f"알림이 {len(sent)}번 나갔다 (1번이어야 함)"
    assert "잔액" in sent[0]["title"]


def test_no_db_means_no_alert():
    r = _Redis()
    mark_insufficient_balance(r, REAL_MSG, source="x")   # db 없음
    assert "entry_block:insufficient_balance:alerted" not in r.store


# ───────────────────────── ⑤ 배선

def _nocomment(p: Path) -> str:
    return "\n".join(
        ln for ln in p.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_funnel_catches_and_returns_none_not_raises():
    """공용 진입 관문이 잔액 부족을 잡아 None 을 돌려줘야 한다.

    호출자는 이미 `if not new_strategy` 경로를 갖고 있으므로 정상 skip 으로 흐른다.
    """
    code = _nocomment(FUNNEL)
    i_try = code.index("try:\n        strategy = svc.create_strategy_instance(")
    i_catch = code.index("is_insufficient_balance_error", i_try)
    assert code.index("mark_insufficient_balance", i_try) > i_try
    assert "return None" in code[i_catch: i_catch + 900]


def test_funnel_reraises_other_valueerrors():
    """🚨 잔액 부족이 아닌 ValueError 는 그대로 올려야 한다."""
    code = _nocomment(FUNNEL)
    i = code.index("is_insufficient_balance_error")
    assert "raise" in code[i: i + 300]


def test_live_workers_check_before_scanning():
    """API 낭비를 멈추려면 **후보 루프보다 앞**이어야 한다.

    ⚠️ 앵커는 「실행 경로」여야 한다. 처음엔 `_create_auto_bb_strategy(` 로 잡았는데,
       롱 워커는 그 호출이 **헬퍼 정의 안**(파일 위쪽)에 있어 위치 비교가 무의미했다.
       각 워커의 **사이클 함수** 안에서 비교한다.
    """
    for p, entry_fn, call_anchor in (
        (REENTRY, "def run_realtime_reentry", "_create_auto_bb_strategy("),
        (LONGW, "def run_auto_long_at_bottom_once", "_create_long_strategy("),
    ):
        code = _nocomment(p)
        assert "check_balance_block" in code, f"{p.name} 에 잔액 가드가 없다"
        body = code[code.index(entry_fn):]
        assert "check_balance_block" in body, f"{p.name} 가드가 사이클 함수 밖에 있다"
        assert body.index("check_balance_block") < body.index(call_anchor), (
            f"{p.name} 가드가 진입 호출보다 뒤에 있다"
        )


def test_evidence_is_recorded():
    src = (BACKEND / "app" / "services" / "balance_guard.py").read_text(encoding="utf-8")
    for token in ("46.73", "entry_exception", "fail=0", "IP ban"):
        assert token in src, f"근거 주석에 '{token}' 이 없다"
