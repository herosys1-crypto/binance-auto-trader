"""🏷 Fix 476 (2026-10-21 사장님) — 종목 「세력 그림」 표시 (새 전략 화면 · 전략 인스턴스 목록) — 표시 전용, 주문·판정 무변경.

사장님: 「이런 코인(심볼) 새전략시 구분되게 해줘 그리고 전략인스턴스에서도 한눈에 구분되게 표시해줘 집중관리와 진입시 알아야 할것 같아」
근거 = [[일봉 세 그림 연구 2026-10-21]] (공개 일봉 517종목 · scripts/entry_condition_study/daily_*_2026_10_21.py):
  ③ 펌프·덤프 위험  최근 3일 안 일봉 종가가 3일 최저가 대비 +30%↑ — 다음 날 음봉이면 44% 가 열흘 안 급등분 반납(양봉 8%)
  ② 펌프·회귀 위험  30일 안 랠리 +100%↑ · 가파름(하루 ≥3%) · 거래대금 ×10↑ (연구: +100%↑·하루 3%↑·×30↑ 쪽이 회귀 많음) — 고점 −25%↓·중단 아래 마감이면 원점 회귀 쪽
  ① 정상 추세       랠리 +30%↑ · 완만(하루 <1%) · 중단 위 — 코인 자체 상승
  🐋 소형·큰손      시총 < 2억$ · 유통 비율 < 60% (CoinGecko, 받은 날 값)
판정은 **마감한 일봉만** (오늘 진행 중 봉 안 씀). 숫자는 연구 값 그대로(「Claude가 정함」).
저장: Redis pump:profile:v1 = {symbol: profile} (2일) · pump:profile:at · 매일 KST 09:15 + 시작 2분 뒤 (scheduler_runner).
일봉 = 공개 klines limit 99(무게 1) × COIN 무기한 전부 — 하루 ≈500 무게.
"""
from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)

FIX = "Fix476"
KEY = "pump:profile:v1"
AT_KEY = "pump:profile:at"
TTL = 2 * 86400
LIMIT = 99
N, K = 20, 2.0

TAGS = {   # 태그 → (짧은 이름, 색, 설명)
    "p3": ("③ 펌프·덤프", "red", "3일 안 +30% 급등 — 다음 날 음봉이면 44% 가 열흘 안 급등분 반납"),
    "p2": ("② 펌프·회귀", "orange", "가파른 랠리·거래대금 폭증 — 깊은 눌림·중단 아래 마감이면 원점 회귀 쪽"),
    "p1": ("① 정상 추세", "green", "완만한 랠리 · 중단 위 — 코인 자체 상승"),
    "whale": ("🐋 소형·큰손", "purple", "시총 < 2억$ · 유통 < 60% — 큰손 몇이 물량을 쥠"),
}


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def classify(kl: list, mcap: float | None = None, flt: float | None = None) -> dict:
    """kl = 마감 일봉 [[open_ms, o, h, l, c, v, close_ms, qv, ...], ...] (오래된 → 최근). 순수 함수.
    → {"tags": [..], "reasons": [..], "gain", "speed", "dd", "vspike", "mcap", "float"} — 판정 못 하면 tags 비움."""
    out: dict[str, Any] = {"tags": [], "reasons": [], "mcap": mcap, "float": flt}
    try:
        h = [float(k[2]) for k in kl]
        lw = [float(k[3]) for k in kl]
        c = [float(k[4]) for k in kl]
        qv = [float(k[7]) if len(k) > 7 else float(k[5]) * float(k[4]) for k in kl]
    except (TypeError, ValueError, IndexError):
        out["reasons"].append("일봉 형식 이상")
        return out
    if mcap is not None and flt is not None and mcap < 2e8 and flt < 0.6:
        out["tags"].append("whale")
        out["reasons"].append(f"시총 {mcap / 1e6:.0f}M$ · 유통 {flt:.0%}")
    t = len(c) - 1
    if t < 95 or any(not math.isfinite(x) or x <= 0 for x in (c[-95:] + lw[-95:])):
        out["reasons"].append("일봉 부족")
        return out
    # ③ 최근 3일 안 급등 날
    for d in range(t - 2, t + 1):
        base = min(lw[d - 3:d + 1])
        if c[d] / base - 1 >= 0.30:
            out["tags"].append("p3")
            rest = "다음 날 음봉" if d < t and c[d + 1] < c[d] else ("다음 날 양봉" if d < t else "오늘 마감이 급등 날")
            out["reasons"].append(f"{t - d}일 전 +{(c[d] / base - 1) * 100:.0f}% 급등 · {rest}")
            break
    # 랠리 (직전 30일 고점 · 그 전 60일 최저)
    pk = max(range(t - 30, t + 1), key=lambda j: h[j])
    org = min(range(max(0, pk - 60), pk + 1), key=lambda j: lw[j])
    gain = h[pk] / lw[org] - 1
    speed = gain / max(1, pk - org)
    pre = sorted(qv[max(0, org - 60):org]) or [0.0]
    med = pre[len(pre) // 2]
    vsp = (max(qv[org:pk + 1]) / med) if med > 0 else None
    w = c[t - N + 1:t + 1]
    mid = sum(w) / N
    dd = 1 - c[t] / h[pk]
    out.update(gain=round(gain, 4), speed=round(speed, 4), dd=round(dd, 4), vspike=round(vsp, 1) if vsp else None,
               above_mid=c[t] >= mid)
    if gain >= 0.30 and "p3" not in out["tags"]:
        if gain >= 1.0 and speed >= 0.03 and vsp is not None and vsp >= 10:   # 표시는 「확실한 세력 랠리」만 — +30%·하루 3%·×30 중 하나로는 517종목 중 245개가 걸렸다(10/21 실측)
            out["tags"].append("p2")
            bits = [f"랠리 +{gain * 100:.0f}% · 하루 {speed * 100:.1f}%"] + ([f"거래대금 ×{vsp:.0f}"] if vsp and vsp >= 30 else [])
            if dd >= 0.25:
                bits.append(f"고점 −{dd * 100:.0f}% (원점 회귀 쪽)")
            if c[t] < mid:
                bits.append("중단 아래 마감")
            out["reasons"].append(" · ".join(bits))
        elif speed < 0.01 and c[t] >= mid:
            out["tags"].append("p1")
            out["reasons"].append(f"완만 랠리 +{gain * 100:.0f}% · 하루 {speed * 100:.1f}% · 중단 위 · 고점 −{dd * 100:.0f}%")
    return out


def badge(profile: dict | None) -> dict | None:
    """화면용 — 가장 중요한 태그 하나 + 전체 목록. 없으면 None."""
    if not profile or not profile.get("tags"):
        return None
    order = ("p3", "p2", "whale", "p1")
    tags = [t for t in order if t in profile["tags"]]
    main = tags[0]
    return {"main": main, "label": TAGS[main][0], "color": TAGS[main][1],
            "tags": [{"tag": t, "label": TAGS[t][0], "color": TAGS[t][1], "desc": TAGS[t][2]} for t in tags],
            "reasons": profile.get("reasons") or []}


def build(symbols: Iterable[str], fetch: Callable[[str], list | None], mcap_of: Callable[[str], dict | None],
          *, sleep: float = 0.15) -> dict[str, dict]:
    """심볼마다 일봉을 받아 분류. fetch(sym) → 마감 봉 포함 리스트(마지막 진행 중 봉은 여기서 뺀다)."""
    out: dict[str, dict] = {}
    now_ms = int(time.time() * 1000)
    for sym in symbols:
        try:
            kl = fetch(sym) or []
            kl = [k for k in kl if int(k[6]) < now_ms]            # 마감 봉만
            mi = mcap_of(sym) or {}
            prof = classify(kl, _num(mi.get("mcap")), _num(mi.get("float")))
            if prof.get("tags"):
                out[sym] = prof
        except Exception as e:  # noqa: BLE001
            logger.debug("[%s] %s 분류 실패: %s", FIX, sym, e)
        if sleep:
            time.sleep(sleep)
    return out


def refresh(redis, bc, symbols: Iterable[str]) -> dict:
    """스케줄러 잡. 결과 저장(태그 있는 심볼만). 반환 stat."""
    from app.services import coin_mcap as CM

    def fetch(sym):
        return bc.get_klines(symbol=sym, interval="1d", limit=LIMIT)

    def mcap_of(sym):
        return CM.info(sym, redis=redis)

    syms = list(symbols)
    prof = build(syms, fetch, mcap_of)
    redis.setex(KEY, TTL, json.dumps(prof, ensure_ascii=False))
    redis.setex(AT_KEY, TTL, datetime.now(timezone.utc).isoformat())
    stat = {"symbols": len(syms), "tagged": len(prof),
            **{t: sum(1 for p in prof.values() if t in p["tags"]) for t in TAGS}}
    logger.info("[%s] 세력 그림 표시 갱신: %s", FIX, stat)
    return stat


_MEM: dict[str, Any] = {"at": 0.0, "data": {}}


def profiles(redis=None) -> dict[str, dict]:
    """프로세스 안 60초 캐시 + Redis. 실패 = 빈 표(예외 없음)."""
    if time.time() - _MEM["at"] < 60:
        return _MEM["data"]
    try:
        if redis is None:
            from app.core.redis_client import get_redis_client
            redis = get_redis_client()
        raw = redis.get(KEY)
        data = json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001
        data = {}
    _MEM.update(at=time.time(), data=data)
    return data


def badges_for(symbols: Iterable[str], redis=None) -> dict[str, dict]:
    p = profiles(redis)
    out = {}
    for s in symbols:
        b = badge(p.get(str(s).upper()))
        if b:
            out[str(s).upper()] = b
    return out
