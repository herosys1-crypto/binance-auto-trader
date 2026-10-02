"""
kline_incremental.py — 바이낸스 선물 /fapi/v1/klines 증분 캐시 (표준 라이브러리만, 네트워크 코드 없음)

2026-10-02 가상매매 IP 무게 절감 (Duel_Lab kline-incremental: Claude 초안 바탕, GPT 반례(A2 전제) 문서화,
리드 추가 = get_closed — 완료봉만 쓰는 호출자는 마지막 완료봉이 이미 확정 값으로 캐시에 있으면 fetch 하지 않는다).
가상매매가 15분마다 515종목 × (15m 262 + 4h 82) 를 통째로 받던 것(≈1,545 weight/사이클)을
15m 꼬리 1회(무게 1) + 4h 는 새 4h 봉이 닫힐 때만으로 줄인다.

목표 불변식
    get(s, i, n) == 같은 시점의 fetch(s, i, n)

불변식이 성립하려면 다음 두 가지 거래소 계약이 필요하다.
    A1. fetch(s, i, n) 은 open_time 오름차순의 '가장 최근 n개'. n개보다 적으면 상장 이후 전부다.
    A2. 진행 중일 수 있는 것은 마지막 행뿐이고, 확정된 봉은 나중에 바뀌지 않는다.

증분 병합이 맞는 이유
    캐시 C = (시각 T 의) 최근 cap개, 새 꼬리 N = (지금의) 최근 req개 (req ≤ cap).
    N[0] ≤ C[-1](겹침) 이면, C 가운데 N[0] 이전 행은 T 시점에 이미 확정(A2)이었으므로 지금도 같다.
    진행 중이었을 수 있는 C[-1] 은 반드시 N 이 덮어쓴다. 따라서 C[:k] + N 은 지금의 연속된 최근 구간이다(A1).
    앞을 잘라 최근 cap개 = fetch(cap), 그 마지막 n개 = fetch(n).

방어선 (하나라도 실패하면 즉시 전체 조회로 대체한다. 틀린 값을 주느니 무게를 더 쓴다)
    형식(행이 list · 정수 open_time · 엄격 오름차순 · 길이 ≤ req) / 비어 있음 / 겹침 없음 /
    역행(N 이 C 보다 과거에서 끝남) / 겹친 확정 봉의 값 불일치(A2 위반 = 정정) / 줄어듦 /
    병합 후 모든 인접 간격 == interval
    A2 위반이 겹침 구간보다 오래된 봉에서 일어나면 증분으로는 알 수 없다.
    이 경우는 full_refresh_s 주기의 전체 재조회로만 복구된다(테스트에 한계로 명시).

명세 해석(설계 결정)
    - '보관 행 수' = 보관 한도 cap(지금까지 받은 가장 큰 limit). 상장 직후 종목은 실제 행이 cap 보다
      적지만 A1 에 의해 '전체 이력'이므로 증분이 안전하다.
    - 전체 조회는 fetch(max(limit, cap)) → cap 이 줄지 않고, 마지막 limit 개 = fetch(limit) (A1).
    - 증분 꼬리 길이 = max(tail, 시계로 추정한 빠진 봉 수 + 2), 단 ≤ 100(무게 1) 이고 ≤ cap.
      워커가 몇 사이클 멈춰도 100봉 이하면 무게 1 로 따라잡는다. 추정이 틀려도 겹침 검사가 지킨다.
    - 전체 조회 결과가 비었거나 형식이 깨졌으면 그대로(복사본) 돌려주되 캐시하지 않는다.
    - 전체 조회 결과 자체에 봉 누락(거래 정지)이 있으면 캐시는 하되, 누락이 창 밖으로 밀려날 때까지
      증분을 시도하지 않고 바로 전체 조회한다(어차피 연속성 검사에서 실패할 무게 1 을 아낀다).
    - 규칙 4(짧은 재사용): 마지막 실제 fetch 뒤 min(interval 초, reuse_window_s) 이내면 fetch 없이 응답한다.
      이때 결과는 '마지막 실제 fetch 시점'의 fetch(n) 과 같다. reuse_window_s=0 이면 끈다(엄격 불변식).
    - cap 은 줄지 않는다(가장 큰 limit 기준). 한 번 큰 limit 을 썼다면 forget() 으로 초기화한다.
"""
from __future__ import annotations

import bisect
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

__all__ = ["IncrementalKlines", "INTERVAL_MS", "request_weight", "parse_open_times"]

log = logging.getLogger(__name__)

INTERVAL_MS: dict[str, int] = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}
WEIGHT1_MAX_LIMIT = 100

Fetch = Callable[[str, str, int], Any]


def request_weight(limit: int) -> int:
    """/fapi/v1/klines 요청 무게 (limit 기준)."""
    if limit <= 100:
        return 1
    if limit <= 500:
        return 2
    if limit <= 1000:
        return 5
    return 10


def parse_open_times(rows: Any) -> list[int] | None:
    """형식 검증 겸 open_time 추출. 깨졌으면 None.
    깨짐 = rows 가 list 아님 · 행이 list 아님/빈 행 · open_time int 변환 실패(소수·bool·nan 포함) · 역순/중복."""
    if not isinstance(rows, list):
        return None
    out: list[int] = []
    for r in rows:
        if not isinstance(r, list) or not r:
            return None
        v = r[0]
        if isinstance(v, bool) or (isinstance(v, float) and not v.is_integer()):
            return None
        try:
            t = int(v)
        except (TypeError, ValueError, OverflowError):
            return None
        if out and t <= out[-1]:
            return None
        out.append(t)
    return out


@dataclass(slots=True)
class _Entry:
    rows: list[list]    # 내부 소유 복사본(호출자와 공유하지 않음), open_time 오름차순
    times: list[int]    # rows 의 open_time (병렬 배열)
    cap: int            # 보관 한도 = 지금까지 전체 조회에 쓴 가장 큰 limit
    contiguous: bool    # rows 전체가 interval 간격으로 이어지는가
    full_at: float      # 마지막 전체 조회 시각 (fetch 호출 직전 clock)
    fetched_at: float   # 마지막 실제 fetch(전체·증분) 시각 (fetch 호출 직전 clock)


class _Slot:
    """(symbol, interval) 별 락 + 캐시 항목. 항목 교체는 참조 하나를 바꾸는 원자적 대입이다."""
    __slots__ = ("lock", "entry")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.entry: _Entry | None = None


def _copy_tail(rows: list[list], limit: int) -> list[list]:
    return [list(r) for r in rows[-limit:]]


class IncrementalKlines:
    """fetch(symbol, interval, limit) 와 같은 결과를 더 적은 요청 무게로 돌려주는 캐시."""

    def __init__(self, fetch: Fetch, *, tail: int = 5, full_refresh_s: float = 6 * 3600,
                 clock: Callable[[], float] = time.time, reuse_window_s: float = 60.0) -> None:
        if not callable(fetch):
            raise TypeError("fetch must be callable")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if isinstance(tail, bool) or not isinstance(tail, int) or not 2 <= tail <= WEIGHT1_MAX_LIMIT:
            # tail=1 이면 새 봉이 하나만 생겨도 겹침이 깨진다 → 최소 2
            raise ValueError(f"tail must be an int in [2, {WEIGHT1_MAX_LIMIT}], got {tail!r}")
        for name, v in (("full_refresh_s", full_refresh_s), ("reuse_window_s", reuse_window_s)):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not v >= 0:  # nan 도 거부
                raise ValueError(f"{name} must be a number >= 0, got {v!r}")
        self._fetch = fetch
        self._tail = tail
        self._full_refresh_s = float(full_refresh_s)
        self._reuse_window_s = float(reuse_window_s)
        self._clock = clock
        self._slots: dict[tuple[str, str], _Slot] = {}
        self._slots_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._counts: dict[str, int] = dict.fromkeys(
            ("full", "incremental", "fallback", "reused", "passthrough", "closed_hit",
             "fetch_calls", "fetch_errors", "weight"), 0)
        self._reasons: dict[str, int] = {}
        self._last_reason: str | None = None

    # ------------------------------------------------------------------ 공개 API
    def get(self, symbol: str, interval: str, limit: int) -> list[list]:
        """fetch(symbol, interval, limit) 를 불렀을 때와 같은 리스트(행 값 그대로, 복사본).
        fetch 예외는 캐시를 바꾸지 않고 그대로 전파한다."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError(f"limit must be a positive int, got {limit!r}")
        iv = INTERVAL_MS.get(interval)
        if iv is None:                       # 모르는 interval → 캐시 없이 그대로
            self._add("passthrough")
            return self._call(symbol, interval, limit)
        slot = self._slot((symbol, interval))
        with slot.lock:                      # 같은 키는 직렬, 다른 키는 병렬
            return self._get_locked(slot, symbol, interval, iv, limit)

    def get_closed(self, symbol: str, interval: str, limit: int, now_ms: int | None = None) -> list[list]:
        """== [r for r in fetch(symbol, interval, limit) if open_time + interval <= now_ms] — **완료봉만**.

        가상매매처럼 완료봉만 쓰는 호출자용 (`chart_learning.compact(..., now_ms=)` 와 같은 기준).
        완료봉은 바뀌지 않으므로(A2), 캐시 마지막 행이 '지금 진행 중인 봉'이면 그 앞의 완료봉은 전부
        확정 뒤에 받은 값이다 → fetch 없이 응답한다. 이때 진짜 fetch(limit) 의 마지막 행은 그 진행 중 봉이므로
        완료봉은 마지막 limit-1 개다. 조건이 안 맞으면(새 봉이 닫힘·거래 정지·재조회 주기 등) get() 경로로 받는다.
        """
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError(f"limit must be a positive int, got {limit!r}")
        iv = INTERVAL_MS.get(interval)
        if now_ms is None:
            now_ms = int(self._clock() * 1000)
        if iv is not None:
            cur_open = now_ms // iv * iv                       # 지금 진행 중인 봉의 open_time
            slot = self._slot((symbol, interval))
            with slot.lock:
                e = slot.entry
                if (e is not None and limit <= e.cap and e.times[-1] == cur_open
                        and self._full_reason(e, limit, now_ms / 1000.0) is None):
                    self._add("closed_hit")
                    return _copy_tail(e.rows[:-1], limit - 1) if limit > 1 else []
        # 🚨 Fix 406 (Duel ext-bar-gate 테스트로 발견): get() 의 짧은 재사용 경로를 타면 「받을 때 진행 중이던 행」이
        #   지금 시각 기준으로는 완료봉으로 분류돼 미확정 봉이 섞인다 → 완료봉 경로는 재사용 없이 받는다.
        if iv is None:
            rows = self.get(symbol, interval, limit)
        else:
            slot = self._slot((symbol, interval))
            with slot.lock:
                rows = self._get_locked(slot, symbol, interval, iv, limit, allow_reuse=False)
        if not isinstance(rows, list) or iv is None:
            return rows
        out = []
        for r in rows:
            try:
                if int(r[0]) + iv <= now_ms:
                    out.append(r)
            except (TypeError, ValueError, IndexError):
                out.append(r)                                   # 깨진 행은 판정하지 않고 그대로 (get 과 같은 원칙)
        return out

    def stats(self) -> dict:
        with self._stats_lock:
            out: dict[str, Any] = dict(self._counts)
            out["full_reasons"] = dict(self._reasons)
            out["last_full_reason"] = self._last_reason
        with self._slots_lock:
            out["cached_keys"] = sum(1 for s in self._slots.values() if s.entry is not None)
        return out

    def forget(self, symbol: str | None = None) -> None:
        """symbol(없으면 전부)의 캐시를 비운다. 진행 중인 fetch 를 기다리지 않는다.
        진행 중이던 get 은 떼어낸 슬롯에 결과를 쓰므로 잊힌 캐시가 되살아나지 않는다."""
        with self._slots_lock:
            for key in [k for k in self._slots if symbol is None or k[0] == symbol]:
                self._slots.pop(key).entry = None

    # ------------------------------------------------------------------ 내부
    def _slot(self, key: tuple[str, str]) -> _Slot:
        with self._slots_lock:
            slot = self._slots.get(key)
            if slot is None:
                slot = self._slots[key] = _Slot()
            return slot

    def _add(self, key: str, n: int = 1) -> None:
        with self._stats_lock:
            self._counts[key] += n

    def _call(self, symbol: str, interval: str, limit: int) -> Any:
        with self._stats_lock:
            self._counts["fetch_calls"] += 1
            self._counts["weight"] += request_weight(limit)
        try:
            return self._fetch(symbol, interval, limit)
        except BaseException:
            self._add("fetch_errors")
            raise                            # 삼키지 않는다 — 종류도 그대로

    def _full_reason(self, e: _Entry | None, limit: int, now: float) -> str | None:
        if e is None:
            return "no_cache"
        if limit > e.cap:
            return "limit_grew"
        if not e.contiguous:
            return "noncontiguous"
        if now < e.fetched_at:
            return "clock_backwards"
        if now - e.full_at >= self._full_refresh_s:
            return "refresh_due"
        return None

    def _get_locked(self, slot: _Slot, symbol: str, interval: str, iv: int, limit: int,
                    allow_reuse: bool = True) -> list[list]:
        now = self._clock()
        e = slot.entry
        # 규칙 4: 직전 실제 fetch 뒤 아주 짧은 시간이면 fetch 없이 응답
        window = min(iv / 1000.0, self._reuse_window_s, 60.0)   # 명세 상한 60초 (GPT 감사 수용)
        if allow_reuse and e is not None and limit <= e.cap and window > 0 and 0 <= now - e.fetched_at <= window:
            self._add("reused")
            return _copy_tail(e.rows, limit)

        reason = self._full_reason(e, limit, now)
        if reason is None:
            assert e is not None
            gap = max(0, (int(now * 1000) - e.times[-1]) // iv)   # 캐시 마지막 봉 뒤 새로 열린 봉 수(추정)
            need = gap + 2                                       # 캐시 마지막 봉 + 새 봉들 + 시계 오차 여유 1
            if need > min(WEIGHT1_MAX_LIMIT, e.cap):
                reason = "stale_too_long" if need > WEIGHT1_MAX_LIMIT else "exceeds_cap"
            else:
                req = min(max(self._tail, need), WEIGHT1_MAX_LIMIT, e.cap)
                new = self._call(symbol, interval, req)          # 예외 → 캐시 그대로 전파
                merged = self._merge(e, new, iv, req)
                if isinstance(merged, str):
                    reason = "fallback:" + merged
                    self._add("fallback")
                    log.debug("klines %s %s incremental rejected (%s) → full fetch", symbol, interval, merged)
                elif merged[1][-1] < e.times[-1] + gap * iv:
                    # 리드 수정(테스트로 발견): 낡은 꼬리(캐시 계층·지연 응답)가 캐시 마지막 봉에서 딱 끝나면
                    # 겹침·연속성 검증을 다 통과하고 최신 봉이 조용히 빠진다. 시계상 열렸어야 할 봉까지 안 오면 전체 조회.
                    # 거래 정지·시계 오차도 이쪽(전체 조회 = 정확)으로 간다.
                    reason = "fallback:stale_tail"
                    self._add("fallback")
                else:
                    rows, times = merged
                    slot.entry = _Entry(rows, times, e.cap, True, e.full_at, now)   # 원자적 교체
                    self._add("incremental")
                    return _copy_tail(rows, limit)
        return self._full(slot, symbol, interval, iv, limit, reason, now)

    def _full(self, slot: _Slot, symbol: str, interval: str, iv: int, limit: int,
              reason: str, now: float) -> list[list]:
        e = slot.entry
        n = limit if e is None else max(limit, e.cap)
        rows = self._call(symbol, interval, n)                   # 예외 → 캐시 그대로 전파
        with self._stats_lock:
            self._counts["full"] += 1
            self._reasons[reason] = self._reasons.get(reason, 0) + 1
            self._last_reason = reason
        times = parse_open_times(rows)
        if times is None or len(rows) > n or not rows:
            # 깨졌거나(계약 위반) 비었으면(상장 전·상폐 등) 그대로 돌려주되 캐시하지 않는다
            if times is None or len(rows) > n:
                log.warning("klines %s %s: malformed full result, not cached", symbol, interval)
            slot.entry = None
            if not isinstance(rows, list):
                return rows
            out = rows if n == limit else rows[-limit:]
            return [list(r) if isinstance(r, list) else r for r in out]
        contiguous = all(b - a == iv for a, b in zip(times, times[1:]))
        if not contiguous:
            log.info("klines %s %s: gap in exchange data (halt?) — incremental paused", symbol, interval)
        stored = [list(r) for r in rows]                         # fetch 가 준 원본과도 분리
        slot.entry = _Entry(stored, times, n, contiguous, now, now)
        return _copy_tail(stored, limit)

    def _merge(self, e: _Entry, new: Any, iv: int, req: int) -> tuple[list[list], list[int]] | str:
        """성공하면 (rows, times), 실패하면 거부 사유 문자열."""
        nt = parse_open_times(new)
        if nt is None or len(nt) > req:
            return "malformed"
        if not nt:
            return "empty"
        ct = e.times
        if nt[0] > ct[-1]:
            return "no_overlap"              # 사이에 빠진 봉이 있을 수 있다
        if nt[0] < ct[0] or nt[-1] < ct[-1]:
            return "went_backwards"          # 거래소 데이터가 과거로 되돌아감
        k = bisect.bisect_left(ct, nt[0])
        pos = {t: j for j, t in enumerate(nt)}
        for i in range(k, len(ct) - 1):      # 겹친 구간의 '확정' 봉(캐시 마지막 행 제외)
            j = pos.get(ct[i])
            if j is None:
                return "gap"                 # 있던 봉이 사라짐
            if new[j] != e.rows[i]:
                return "revised"             # 확정 봉이 바뀜(A2 위반) → 캐시 앞부분도 못 믿는다
        times = ct[:k] + nt
        if len(times) < len(ct):
            return "shrank"
        if any(b - a != iv for a, b in zip(times, times[1:])):
            return "gap"                     # 연속성 검증 (거래 정지로 인한 누락 포함)
        rows = e.rows[:k] + [list(r) for r in new]
        drop = len(rows) - e.cap
        if drop > 0:
            del rows[:drop]
            del times[:drop]
        return rows, times
