"""verify_fix414_418 — 배포 검사기 Fix 414~418 절 (읽기 전용). 운영 DB 실측은 별도로 했고, 여기서는 판정 경계만."""
from __future__ import annotations

import pathlib
import sys
import time
from datetime import datetime, timezone

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import verify_fix414_418 as V  # noqa: E402


class Rec:
    def __init__(self):
        self.ok, self.fail, self.skip = [], [], []


def _run(fn, *a):
    r = Rec()
    fn(*a, r.ok.append, r.fail.append) if fn is V._ops_417_stopping else fn(*a, r.ok.append, r.fail.append, r.skip.append)
    return r


class FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, *_a, **_k):
        rows = self.rows

        class R:
            def fetchall(self):
                return rows
        return R()


class FakeRedis:
    def __init__(self, d=None, h=None):
        self.d, self.h = d or {}, h or {}

    def get(self, k):
        return self.d.get(k)

    def hgetall(self, k):
        return self.h.get(k, {})


def test_code_markers_present():
    r = Rec()
    V._check_code(SCRIPTS.parent, r.ok.append, r.fail.append)
    assert not r.fail and len(r.ok) == len(V.CODE_MARKERS)


def test_promotion_without_evidence_fails_and_with_evidence_passes():
    since = datetime(2026, 10, 4, tzinfo=timezone.utc)
    bad = _run(V._ops_417_promotion, FakeDB([(4527, {"stage_no": 4, "position_amt": "1"})]), since)
    assert bad.fail and "#4527 단계 4" in bad.fail[0]
    good = _run(V._ops_417_promotion, FakeDB([(1, {"stage_no": 2, "fill_evidence": "filled"}),
                                              (2, '{"stage_no": 1}')]), since)          # 문자열 payload 도 읽는다
    assert not good.fail and "2단계+ 1건" in good.ok[0]
    odd = _run(V._ops_417_promotion, FakeDB([(3, {"stage": 2}), (4, [1, 2]), (5, "[]"), (6, None)]), since)
    assert odd.skip and not odd.fail                                                    # 키를 못 읽으면 숨기지 않고 표시


def test_stopping_counts_only_time_under_new_process():
    now = time.time()
    old = datetime.fromtimestamp(now - 3600, tz=timezone.utc)
    rows = [(9, "PHBUSDT", old)]
    # 배포 2분 뒤 검사: 1시간 전부터 STOPPING 이어도 새 감지기 아래 시간은 2분 → 오탐 없음
    r = Rec()
    V._ops_417_stopping(FakeDB(rows), None, now - 120, r.ok.append, r.fail.append)
    assert not r.fail
    # 배포 20분 뒤에도 남아 있으면 감지기 미작동 → FAIL
    r = Rec()
    V._ops_417_stopping(FakeDB(rows), FakeRedis({"stopping_first_seen:9": str(now - 1500)}), now - 1200,
                        r.ok.append, r.fail.append)
    assert r.fail and "#9 PHBUSDT" in r.fail[0]


def test_naive_updated_at_is_utc():
    naive = datetime(2026, 10, 4, 0, 0)
    assert V._epoch(naive) == datetime(2026, 10, 4, tzinfo=timezone.utc).timestamp()


def test_416_ignores_minutes_before_process_start():
    now = int(time.time())
    m_old = time.strftime("%Y%m%d%H%M", time.gmtime(now - 600))
    redis = FakeRedis(h={V.REQ_COUNT_KEY.format(minute=m_old): {b"/fapi/v1/klines|weight_throttled": b"7"}})
    r = Rec()
    V._ops_416(redis, now - 60, r.ok.append, r.skip.append)        # 10분 전 거절은 옛 프로세스 몫
    assert not any("거절 7" in m for m in r.ok + r.skip)
    r = Rec()
    V._ops_416(redis, now - 3600, r.ok.append, r.skip.append)
    assert any("실매매 스캔 거절 7건" in m for m in r.skip)


def test_no_process_start_skips_ops_layer():
    r = Rec()
    V.check_fix414_418(r.ok.append, r.fail.append, r.skip.append, root=SCRIPTS.parent, code_only=False,
                       process_start_epoch=None, db=FakeDB([(1, {"stage_no": 4})]), redis=None)
    assert not r.fail and any("시작 시각 모름" in m for m in r.skip)
