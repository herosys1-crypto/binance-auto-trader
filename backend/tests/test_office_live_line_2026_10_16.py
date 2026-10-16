"""📒 2026-10-16 사장님 「2번 진행」 — 사무실 실주문 가족 책상에 오늘 진입·14일 손익 한 줄."""
from __future__ import annotations

import json
from app.services import office_board as OB

NOW = 1_800_000_000.0


def _desk(d, key):
    return next(k for r in d["rooms"] for k in r["desks"] if k["key"] == key)


def test_live_line_format():
    assert OB.live_line(None) == ""
    s = OB.live_line({"today": 1, "cap": 1, "system": -2.66, "human": -48.6, "closed": 17, "wins": 9})
    assert s == " · 오늘 1/1건 · 14일 시스템 몫 -2.7 (끝난 17·이긴 9) · 사람 추가 몫 -48.6"
    s = OB.live_line({"today": None, "cap": 1, "system": 0.0, "human": 0.0, "closed": 0, "wins": 0})
    assert "오늘 ?/1건" in s and "사람 추가 몫" not in s


def test_build_keeps_old_detail_without_live():
    ex = {"modes": {"rf_zone_s4": "on"}, "active": {"rf_zone_s4": 1}}
    old = _desk(OB.build(recs={}, extras=ex, now=NOW), "rf_zone_s4")["detail"]
    assert old.startswith("모드 켜짐 · 진행 중 1건") and "오늘" not in old
    ex["live"] = {"rf_zone_s4": {"today": 0, "cap": 1, "system": 3.0, "human": 0.0, "closed": 4, "wins": 3}}
    new = _desk(OB.build(recs={}, extras=ex, now=NOW), "rf_zone_s4")["detail"]
    assert new == old + " · 오늘 0/1건 · 14일 시스템 몫 +3.0 (끝난 4·이긴 3)"


class R:
    def __init__(self, cached=None):
        self.kv, self.set = ({OB.LIVE_CACHE_KEY: cached} if cached else {}), []

    def get(self, k):
        return self.kv.get(k)

    def setex(self, k, ttl, v):
        self.set.append((k, ttl)); self.kv[k] = v   # noqa: E702

    def hgetall(self, k):
        return {}

    def exists(self, k):
        return 0

    def pipeline(self, **kw):
        raise RuntimeError("no pipe")


def _fake_modules(monkeypatch, board=None, boom=False, today=0):
    calls = {"build": 0}

    def build(db, days=14):
        calls["build"] += 1
        if boom:
            raise RuntimeError("db down")
        return board

    import app.services.live_family_board as LFB          # 진짜 모듈의 build 를 바꾼다(sys.modules 바꿔치기는 먼저 import 된 경우 안 먹힘)
    monkeypatch.setattr(LFB, "build", build)
    import app.services.auto_family_registry as AF
    monkeypatch.setattr(AF, "daily_max", lambda db, key: 1)
    monkeypatch.setattr(AF, "count_today", lambda db, key: today)
    return calls


BOARD = {"families": [{"key": "rf_zone_s4", "system": -2.7, "human": -48.6, "closed": 17, "wins": 9}]}


def test_collect_uses_cache(monkeypatch):
    calls = _fake_modules(monkeypatch, board={"families": []})
    r = R(cached=json.dumps(BOARD))
    d = OB.collect(None, r, now=NOW)
    assert calls["build"] == 0 and "14일 시스템 몫 -2.7" in _desk(d, "rf_zone_s4")["detail"]


def test_collect_builds_and_caches(monkeypatch):
    calls = _fake_modules(monkeypatch, board=BOARD)
    r = R()
    d = OB.collect(None, r, now=NOW)
    assert calls["build"] == 1 and (OB.LIVE_CACHE_KEY, OB.LIVE_CACHE_TTL) in r.set
    assert "오늘 0/1건" in _desk(d, "rf_zone_s4")["detail"]


def test_collect_survives_build_error_and_count_failed(monkeypatch):
    _fake_modules(monkeypatch, boom=True)
    d = OB.collect(None, R(), now=NOW)
    assert "14일" not in _desk(d, "rf_zone_s4")["detail"]          # 표 실패 → 손익 없음, 화면은 정상
    import app.services.auto_family_registry as AF
    _fake_modules(monkeypatch, board=BOARD, today=AF.COUNT_FAILED)
    d = OB.collect(None, R(), now=NOW)
    assert "오늘 ?/1건" in _desk(d, "rf_zone_s4")["detail"]


def test_failure_is_remembered_60s(monkeypatch):
    calls = _fake_modules(monkeypatch, boom=True)
    r = R()
    OB.collect(None, r, now=NOW)
    assert (OB.LIVE_FAIL_KEY, OB.LIVE_FAIL_TTL) in r.set and calls["build"] == 1
    OB.collect(None, r, now=NOW)                                   # 실패 표시가 있으면 다시 만들지 않는다
    assert calls["build"] == 1


def test_human_rounding_to_zero_hidden():
    assert "사람 추가 몫" not in OB.live_line({"system": 1.0, "human": 0.03, "closed": 1, "wins": 1})
    assert "사람 추가 몫 -0.2" in OB.live_line({"system": 1.0, "human": -0.2, "closed": 1, "wins": 1})
