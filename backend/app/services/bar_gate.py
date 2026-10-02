"""봉 마감 게이트 — 순수 함수 (표준 라이브러리만, 네트워크·Redis·시계 없음). Fix 406.

「완성봉 하나에 한 번 판정」하는 워커가 **판정할 새 봉이 없으면 캔들을 받지 않게** 하고,
받은 캔들이 확정됐는지(거래소가 다음 봉을 열었는지) 확인한다.
Duel_Lab ext-bar-gate 병합: GPT 초안(시간 안전 검사) + Claude 초안(응답 마지막 행 검사 BarNotSettled)
+ Claude 감사(단조 비교 — 배포 전환·정착 지연 변경 때 옛 봉 재판정 차단).
"""
from __future__ import annotations

SETTLE_DEFAULT_MS = 5_000
SETTLE_MAX_MS = 60_000


class BarNotSettled(Exception):
    """응답 마지막 행이 판정 시각에 이미 닫힘 = 거래소가 다음 봉을 아직 안 열었다 → 이번 사이클은 판정·캐시하지 않는다."""


def _int(name: str, v: object) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise TypeError(f"{name}: int 필요 ({type(v).__name__})")
    return v


def _iv(interval_ms: object) -> int:
    if _int("interval_ms", interval_ms) <= 0:
        raise ValueError(f"interval_ms 는 양수: {interval_ms}")
    return interval_ms


def last_closed_open(now_ms: int, interval_ms: int, settle_ms: int = 0) -> int:
    """t = now_ms − settle_ms 에 닫혀 있는(open + interval ≤ t) 마지막 봉의 open_time."""
    _int("now_ms", now_ms)
    _iv(interval_ms)
    if _int("settle_ms", settle_ms) < 0:
        raise ValueError(f"settle_ms 는 0 이상: {settle_ms}")
    return ((now_ms - settle_ms) // interval_ms - 1) * interval_ms


def parse_open(v: object) -> int | None:
    """Redis 기록값 → open_time. bytes 도 받는다. 정수 문자열이 아니면 None(= 기록 없음 취급)."""
    if isinstance(v, bytes):
        try:
            v = v.decode()
        except UnicodeDecodeError:
            return None
    if not isinstance(v, str):
        return None
    s = v.strip()
    digits = s[1:] if s[:1] == "-" else s
    if not (digits.isascii() and digits.isdigit()) or len(digits) > 20:   # 4,300자리 넘는 값의 int 변환 오류 차단 (GPT 감사)
        return None
    return int(s)


def should_fetch(last_judged: object, now_ms: int, interval_ms: int, settle_ms: int) -> bool:
    """이미 판정한 봉이 지금 기대하는 마지막 완성봉 **이상**이면 False(조회 생략). 기록 없음·깨짐 = True.
    단조 비교: 옛 코드가 더 새 봉을 이미 판정했거나 정착 지연을 늘린 직후에도 옛 봉을 다시 받지 않는다."""
    expected = last_closed_open(now_ms, interval_ms, settle_ms)       # 입력 검증이 먼저
    seen = parse_open(last_judged)
    return seen is None or seen < expected


def already_judged(last_judged: object, ts: int) -> bool:
    """고른 완성봉 ts 가 이미 판정한 봉과 같거나 과거면 True → 재판정 금지 (기존 `== str(ts)` 의 단조 버전)."""
    _int("ts", ts)
    seen = parse_open(last_judged)
    return seen is not None and ts <= seen


def check_rows(rows: object, interval_ms: int, judge_ms: int) -> list:
    """형식 오류 → TypeError/ValueError. 마지막 행이 judge_ms 에 이미 닫힘(다음 봉 미개시) → BarNotSettled.
    빈 리스트는 그대로 통과(상장 전 — 호출 측 봉 부족 처리)."""
    _iv(interval_ms)
    _int("judge_ms", judge_ms)
    if not isinstance(rows, list):
        raise TypeError(f"klines 응답이 list 가 아님: {type(rows).__name__}")
    prev = None
    for row in rows:
        if not isinstance(row, (list, tuple)) or not row or isinstance(row[0], bool) or not isinstance(row[0], int):
            raise ValueError(f"klines 행 형식 오류: {row!r:.80}")
        if prev is not None and row[0] <= prev:
            raise ValueError(f"klines open_time 오름차순 아님: {prev} → {row[0]}")
        prev = row[0]
    if prev is not None and prev + interval_ms <= judge_ms:
        raise BarNotSettled(f"마지막 행 {prev} 가 {judge_ms} 에 이미 닫힘(다음 봉 미개시)")
    return rows


def kline_weight(limit: int) -> int:
    """바이낸스 klines 요청 무게 (client.estimate_weight 와 같은 표): ≤100→1, ≤500→2, ≤1000→5, 그 위→10."""
    if _int("limit", limit) < 1:
        raise ValueError(f"limit 은 1 이상: {limit}")
    return 1 if limit <= 100 else 2 if limit <= 500 else 5 if limit <= 1000 else 10


def parse_settle_ms(v: object, default: int = SETTLE_DEFAULT_MS) -> int:
    """설정값 → settle_ms. 0~60000 정수가 아니면 default."""
    s = str(v).strip() if v is not None else ""
    if not (s.isascii() and s.isdigit()):
        return default
    n = int(s)
    return n if 0 <= n <= SETTLE_MAX_MS else default


def parse_flag(v: object, default: bool = True) -> bool:
    """'1/true/on/yes' → True, '0/false/off/no' → False, 그 외 → default."""
    s = str(v).strip().lower() if v is not None else ""
    return True if s in ("1", "true", "on", "yes") else False if s in ("0", "false", "off", "no") else default
