"""📣 Fix 442 (2026-10-11 사장님 「1」) — 「시장 전체 동시 반등」 감지 (알림·기록 전용, 주문 없음).

근거 [[큰 수익 후보 — 합의 LONG 2026-10-10]]: 같은 15분봉에 LONG 규칙 4개+ 가 켜진 종목이 16개 이상인 순간의 LONG 진입
  = 건당 +3.99% · 승률 64% · 앞 +8.67 / 뒤 +1.66 — 30일 19번(9일)뿐이라 표본을 모은다.
동작: 가상매매 워커가 사이클 끝에 「LONG 규칙 4개+ 종목」 수를 넘긴다 → 16개 이상이면 Redis 기록(30일) + 텔레그램 1통(봉당 한 번).
판정: 10/25 통합 판정 보고서(Fix 441) F 구역이 가상 행에서 같은 순간을 다시 찾아 성적을 낸다 (retro_bars).
설정(「Claude가 정함」 — 측정 경계): mass_rebound_min_symbols 16 · mass_rebound_min_rules 4 · mass_rebound_alert 1.
"""
from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from typing import Any, Iterable

logger = logging.getLogger(__name__)
FIX = "Fix442"
SETTINGS: dict[str, tuple[str, str, str]] = {
    "mass_rebound_min_symbols": ("16", "같은 봉에 LONG 규칙 4개+ 종목이 이 수 이상 = 시장 전체 동시 반등", "Claude가 정함 — 가상 30일 16+ 칸"),
    "mass_rebound_min_rules": ("4", "종목마다 같은 봉에 켜진 LONG 규칙 수 하한", "Claude가 정함 — 합의 LONG 과 같은 4"),
    "mass_rebound_alert": ("1", "텔레그램 알림 (1 켬 · 0 끔)", "Claude가 정함"),
}
EVENT_TTL = 30 * 86400
DEFAULTS = {"min_symbols": 16, "min_rules": 4, "alert": True}


def params_from(get) -> dict:
    def v(k):
        try:
            return get(k)
        except Exception:  # noqa: BLE001
            return None
    p = dict(DEFAULTS)
    for key, name, lo, hi in (("mass_rebound_min_symbols", "min_symbols", 2, 500), ("mass_rebound_min_rules", "min_rules", 2, 20)):
        raw = v(key)
        try:
            x = float(str(raw).strip()) if raw is not None and not isinstance(raw, bool) else None
        except (TypeError, ValueError, OverflowError):
            x = None
        if x is not None and math.isfinite(x) and x == int(x) and lo <= x <= hi:
            p[name] = int(x)
    p["alert"] = str(v("mass_rebound_alert") or "1").strip() != "0"
    return p


def detect(per_symbol_long_rules: dict[str, int | None], p: dict) -> list[str]:
    """{종목: 이 봉 LONG 규칙 수} → 하한 이상 종목 목록(많은 순). 시장 전체 반등이 아니면 []."""
    hits = sorted((s for s, n in per_symbol_long_rules.items() if isinstance(n, int) and n >= p["min_rules"]),
                  key=lambda s: (-per_symbol_long_rules[s], s))
    return hits if len(hits) >= p["min_symbols"] else []


def record_and_alert(db: Any, r: Any, *, bar_ts: int, symbols: list[str], breadth: Any, p: dict) -> bool:
    """Redis 기록(30일) + 텔레그램(봉당 한 번). 실패해도 예외를 내지 않는다. 처음 기록이면 True."""
    payload = {"bar_ts": bar_ts, "n": len(symbols), "symbols": symbols[:40], "breadth": breadth}
    try:
        first = bool(r.set(f"mass_rebound:{bar_ts}", json.dumps(payload), nx=True, ex=EVENT_TTL))
        r.setex("mass_rebound:last", EVENT_TTL, json.dumps(payload))
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] 기록 실패: %s", FIX, e)
        return False
    if first and p.get("alert", True):
        try:
            from app.services.notification_service import NotificationService
            b = f"{float(breadth):.2f}" if isinstance(breadth, (int, float)) and not isinstance(breadth, bool) else "모름"
            NotificationService(db).send_system_alert(
                title=f"📣 시장 전체 동시 반등 — {len(symbols)}종목 (LONG 규칙 {p['min_rules']}개+)",
                body=(f"시장폭 {b} · 종목: {', '.join(s.replace('USDT', '') for s in symbols[:20])}"
                      f"{' …' if len(symbols) > 20 else ''}\n"
                      "가상 30일: 이런 순간의 LONG 건당 +3.99% · 승률 64% (19번뿐 — 표본 모으는 중)\n"
                      "※ 알림·기록 전용 — 주문은 내지 않습니다. 판정은 10/25 통합 판정."))
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s] 알림 실패: %s", FIX, e)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
    return first


def retro_bars(rows: Iterable[dict], *, side_of: dict[str, str], min_rules: int = 4, min_symbols: int = 16) -> set[int]:
    """판정용 — 가상 행[{rule, side, symbol, ts, rf}] 에서 「시장 전체 동시 반등」 봉 시각을 다시 찾는다."""
    k: dict[tuple, int] = {}
    for x in rows:
        if x.get("side") != "LONG" or str(x.get("rule", "")).startswith("baseline_"):
            continue
        names = {x["rule"]} | {n for n in (x.get("rf") or []) if isinstance(n, str) and side_of.get(n) == "LONG"
                                and not n.startswith("baseline_") and n not in ("consensus_long",)}
        key = (x["ts"], x["symbol"])
        k[key] = max(k.get(key, 0), len(names))
    per_bar: dict[int, int] = defaultdict(int)
    for (ts, _sym), n in k.items():
        if n >= min_rules:
            per_bar[ts] += 1
    return {ts for ts, c in per_bar.items() if c >= min_symbols}
