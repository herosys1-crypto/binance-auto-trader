"""Fix 301 — 재진입 대기 목록 단위 테스트.

사장님 2026-09-03: "99% 청산하고 다음 포지션을 진입하는 로직은 어떤가?
                   ... 대기 모니터링도 전략 인스턴스에 남겨두고
                   종료 숨김 처럼 선택적으로 볼수 있게 하는것도 좋은것 같아"

🚨 1안(99% 잔량)은 **재진입을 완전히 막는다.** 그 사실이 코드에서 사라지지
   않도록 아래 test_99퍼센트_잔량이_왜_불가능한지_코드로_고정 이 지킨다.
"""
import ast
import json
from pathlib import Path

from app.api.v1 import reentry_alerts as A
from app.workers import realtime_reentry_worker as W

WSRC = Path(W.__file__).read_text(encoding="utf-8")


# ── 사유 번역 ─────────────────────────────────────────────────────────

def test_사유가_사장님이_읽는_말로_바뀐다():
    assert A._reason_ko("rebound_too_small") == "아직 반등이 부족"
    assert A._reason_ko("already_active") == "이미 포지션 보유 중"
    assert "3개 필요" in A._reason_ko("indicator_gate_need3")
    assert A._reason_ko(None) == "조건 확인 중"


def test_모르는_사유는_원문을_그대로_보여준다():
    """🚨 임의로 「기타」로 뭉개면 새 차단 사유가 생겨도 눈에 안 보인다."""
    assert A._reason_ko("brand_new_reason") == "brand_new_reason"


# ── 워커 기록부 ───────────────────────────────────────────────────────

def test_카드는_사본이_아니라_객체를_담는다():
    """🚨 사본을 append 하면 이후 _bump/_note 갱신이 반영되지 않아
    모든 심볼이 「조건 확인 중」으로만 보인다."""
    assert "_watch.append(_card)" in WSRC
    assert "_watch.append(dict(" not in WSRC


def test_홀더가_리스트_1칸이다():
    """🚨 dict 하나를 재사용하면 _watch 의 모든 항목이 같은 객체를 가리켜
    마지막 심볼 값으로 전부 덮인다."""
    assert "_cur_ref: list[dict | None] = [None]" in WSRC
    assert "_cur_ref[0] = _card" in WSRC


def test_bump_가_집계와_심볼별을_모두_남긴다():
    fn = WSRC[WSRC.index("    def _bump(reason: str)"):]
    fn = fn[:fn.index("\n    def ", 10)]
    assert "skip_reasons[reason]" in fn, "집계를 없애면 완료 로그가 죽는다"
    assert '_c["reason"] = reason' in fn


def test_기록실패가_재진입을_막지_않는다():
    """🚨 화면용 기록이 매매를 멈추면 안 된다 (fail-open)."""
    blk = WSRC[WSRC.index('payload["watchlist"] = _watch'):]
    blk = blk[:blk.index("_log = getattr")]
    assert "try:" in blk and "except Exception" in blk


def test_TTL_이_있어_낡은_목록을_최신인척_안_보여준다():
    assert W.WATCHLIST_TTL_SEC >= 60
    assert "setex(" in WSRC


# ── API ───────────────────────────────────────────────────────────────

class _R:
    def __init__(self, raw):
        self.raw = raw

    def get(self, _k):
        return self.raw


def _patch_redis(monkeypatch, raw):
    import app.core.redis_client as rc
    monkeypatch.setattr(rc, "get_redis_client", lambda: _R(raw))


def test_워커_기록이_없으면_stale_이다(monkeypatch):
    """🚨 「감시 대상이 없다」와 「워커가 안 돈다」는 완전히 다른 상황이다."""
    _patch_redis(monkeypatch, None)
    out = A.get_reentry_watchlist(user_id=1)
    assert out["stale"] is True and out["items"] == []


def test_정상_목록(monkeypatch):
    _patch_redis(monkeypatch, json.dumps({
        "updated_at": "2026-09-03T00:00:00+00:00",
        "note": "ok",
        "items": [
            {"symbol": "AUSDT", "side": "SHORT", "reason": "rebound_too_small",
             "entered": False, "rebound_pct": 0.2},
            {"symbol": "BUSDT", "side": "LONG", "reason": None,
             "entered": True},
            {"symbol": "CUSDT", "side": "SHORT", "reason": "rebound_too_small",
             "entered": False, "rebound_pct": 0.45},
        ],
    }))
    out = A.get_reentry_watchlist(user_id=1)
    assert out["stale"] is False
    assert out["count"] == 3 and out["waiting"] == 2 and out["entered"] == 1
    # 대기가 위로, 그 안에서 반등이 많이 온 순 (= 곧 들어갈 것부터)
    assert [i["symbol"] for i in out["items"]] == ["CUSDT", "AUSDT", "BUSDT"]
    assert out["items"][0]["reason_ko"] == "아직 반등이 부족"
    assert out["items"][-1]["reason_ko"] == "진입함"


def test_손상된_JSON_이어도_화면이_안_죽는다(monkeypatch):
    _patch_redis(monkeypatch, "{not json")
    assert A.get_reentry_watchlist(user_id=1)["stale"] is True


def test_항목이_dict가_아니면_버린다(monkeypatch):
    _patch_redis(monkeypatch, json.dumps({"items": ["쓰레기", None, 3]}))
    assert A.get_reentry_watchlist(user_id=1)["count"] == 0


# ── 🚨 99% 잔량이 왜 불가능한지 코드로 고정 ───────────────────────────

def test_99퍼센트_잔량이_왜_불가능한지_코드로_고정():
    """사장님 1안을 다시 시도하기 전에 반드시 이 두 관문을 보게 만든다.

    (1) 후보는 **청산 완료(TERMINAL)** 에서만 고른다
    (2) 활성 심볼은 건너뛴다
    → 1% 를 남기면 상태가 STAGE*_OPEN 이라 두 관문에 다 걸려 영구 제외된다.
    """
    assert "StrategyInstance.status.in_(list(TERMINAL_STATUSES))" in WSRC
    assert "if symbol in active_syms:" in WSRC
    # 그 근거가 주석으로 남아 있는가 (다음 사람이 안 지우도록)
    assert "MIN_NOTIONAL" in WSRC
    assert "dust" in WSRC


def test_watch_가_모든_종료경로에서_기록된다():
    """조기 return 경로도 _finish 를 거치므로 화면이 낡은 값을 안 본다."""
    tree = ast.parse(WSRC)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_finish")
    src = ast.get_source_segment(WSRC, fn) or ""
    assert 'payload["watchlist"] = _watch' in src
