"""🧾 Fix 441 (2026-10-11 사장님 「1번 진행해줘」) — 10/23~25 통합 판정 보고서 (읽기 전용, 판정 기준을 미리 고정).

운영 서버에서:  docker compose exec -T api python - < scripts/entry_condition_study/verdict_2026_10_25.py
            (판정 날짜를 바꾸려면 환경변수 VERDICT_NOW=2026-10-25T00:00:00+00:00)

## 사전 등록 판정 기준 (2026-10-11 고정 — 결과를 보고 바꾸지 않는다. 숫자는 「Claude가 정함」)
  가상 규칙: 마감 n ≥ 30 · 진입일 ≥ 7일 · 평균 roi > 0 · 같은 날·같은 방향 무작위 대비 > 0 · 앞 절반 > 0 · 뒤 절반 > 0
            · 하루 1건 제한(종목당 하루 1번, 봉 순서) 합 > 0 · 이긴 날 ≥ 50%   →  모두 = ✅ 통과 / n·일수 미달 = ⏳ 보류 / 그 밖 = ❌ 기각
  실주문 가족: 시스템 몫(Fix 434) 합 > 0 · 끝난 n ≥ 5 → 통과 / n < 5 → 보류 / 그 밖 → 기각   (사람 💉 추가 몫은 따로 표시)
  운영팀 게이트: 칸 안 평균 − 칸 밖 평균 > 0 (가상 roi, 각 n ≥ 30) → 「막기」 후보
  각 대상은 **자기 배포 시각 이후** 행만 센다 (아래 CUTOFFS).
  📈 청산 방식(G, Fix 447 — 2026-10-12 추가 등록): 같은 거래 짝(지금 청산 live 대비) 평균 차 > 0 · 앞·뒤 절반 차 > 0 · 짝 n ≥ 30
            → 「청산 후보」 / 짝 n < 30 → 보류. 최악의 날 합은 위험 참고(24h 정체 청산은 이 값으로 본다). 새 변형 키가 있는 행만.

## 대상
  A 실주문 가족(장세 필터 뒤) · B 새 가상 규칙(합의 LONG · 급등 정점 SHORT 2) · C 외부 전략 가상 규칙(장세 필터 안/밖)
  D 규칙 가족 가상 규칙(장세 필터 안/밖) · E 운영팀 게이트(칸 안/밖) · G 청산 방식 비교(같은 거래 짝)
  H 통과 전략의 단계 1 설정표 (Fix 448 — 자본 계획서 4절 값 vs 지금 값, 보여 주기만)
  💸 순수익 열(Fix 452, 2026-10-14 추가 — 참고용, 판정 기준은 위 그대로): 수수료·슬리피지 뺀 평균. 행에 roi_net 이 없으면 roi − 0.4.
  I 가설(Fix 454, 2026-10-14 사전 등록 — 전략 손실 진단 감사관 제안): 장세 필터 안 SHORT(24h ≥ +10%) 중 시장폭 > 0.6 을 빼면 낫다.
     이 시각(CUTOFFS["short_high"]) 뒤 진입만 센다(가설을 만든 30일 데이터는 쓰지 않는다).
     「✅ 제외 후보」 = 시장폭 > 0.6 칸: n ≥ 30 · 7일 이상 · 평균 < 0 · 앞·뒤 절반 모두 < 0 · 그리고 ≤ 0.6 칸 평균보다 낮음.
     n·일수 미달 = ⏳ 보류 · 그 밖 = ❌ 기각(지금 그대로). 숫자는 Claude가 정함.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

sys.path.insert(0, "/app")

# ── 배포 시각 (UTC) — 이 뒤 진입만 센다 ──
CUTOFFS = {
    "emapb": "2026-10-09T10:02:00+00:00",            # Fix 423·424 EMA 추세 눌림 (아담쿠식)
    "fujimoto": "2026-10-09T18:12:00+00:00",          # Fix 427 일봉
    "mach7": "2026-10-09T18:12:00+00:00",
    "bbema": "2026-10-09T23:51:00+00:00",             # Fix 429
    "bbwave": "2026-10-10T01:10:00+00:00",            # Fix 431
    "trima": "2026-10-10T01:10:00+00:00",             # Fix 432
    "consensus": "2026-10-10T22:45:00+00:00",         # Fix 437
    "pumptop": "2026-10-11T03:05:00+00:00",           # Fix 438
    "regime": "2026-10-11T03:05:00+00:00",            # Fix 439 장세 필터 (규칙 가족)
    "ext_regime": "2026-10-11T10:08:00+00:00",        # Fix 440 장세 필터 (외부 전략)
    "short_high": "2026-10-14T04:00:00+00:00",        # Fix 454 가설 I 사전 등록 (이 뒤 진입만)
}
CRIT = {"min_n": 30, "min_days": 7, "win_days": 0.5, "live_min_n": 5, "gate_min_n": 30}
CUTOFFS["mass_rebound"] = "2026-10-10T22:45:00+00:00"        # 📣 Fix 442 — 판정 재료는 가상 행이라 합의 LONG 배포 시각부터 같게
EXT_PREFIX = {"emapb_": "emapb", "fujimoto_": "fujimoto", "mach7_": "mach7", "bbema_": "bbema", "bbwave_": "bbwave", "trima_": "trima"}
NEW_RULES = {"consensus_long": "consensus", "pumptop_short_30": "pumptop", "pumptop_short_mid": "pumptop"}


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _f(x: Any) -> float | None:
    if isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def regime_ok(side: str, breadth: Any, chg24: Any, lo_breadth: float = 0.4, short_chg: float = 10.0) -> bool | None:
    """두 줄 법칙 (Fix 439 와 같은 정의). 모르면 None."""
    if side == "LONG":
        b = _f(breadth)
        return None if b is None or not 0.0 <= b <= 1.0 else b < lo_breadth
    c = _f(chg24)
    return None if c is None else c >= short_chg


def evaluate(rows: list[dict], base_mean: dict) -> dict:
    """rows = [{"d": date, "side", "symbol", "ts": entry_bar_ts, "roi"}] → 판정 지표 + 사전 등록 판정."""
    n = len(rows)
    if n == 0:
        return {"n": 0, "days": 0, "verdict": "⏳ 보류", "why": "표본 없음"}
    days = sorted({r["d"] for r in rows})
    mid = days[len(days) // 2]
    roi = sum(r["roi"] for r in rows) / n
    e = [r["roi"] - base_mean[(r["side"], r["d"])] for r in rows if (r["side"], r["d"]) in base_mean]
    edge = sum(e) / len(e) if e else None
    h1 = [r["roi"] for r in rows if r["d"] < mid]
    h2 = [r["roi"] for r in rows if r["d"] >= mid]
    a1 = sum(h1) / len(h1) if h1 else None
    a2 = sum(h2) / len(h2) if h2 else None
    first: dict = {}
    seen: set = set()
    for r in sorted(rows, key=lambda r: (r["d"], r["ts"])):
        if r["d"] in first or (r["d"], r["symbol"]) in seen:
            continue
        first[r["d"]] = r["roi"]
        seen.add((r["d"], r["symbol"]))
    cap_sum = sum(first.values()) * 10 / 100                    # 10 USDT 증거금 기준 USDT
    win_days = sum(1 for v in first.values() if v > 0) / len(first) if first else 0.0
    nets = [v for v in (net_of(r) for r in rows) if v is not None]
    out = {"n": n, "days": len(days), "roi": roi, "edge": edge, "first_half": a1, "second_half": a2,
           "cap1_usdt": cap_sum, "win_days": win_days, "net": (sum(nets) / len(nets)) if nets else None}
    if n < CRIT["min_n"] or len(days) < CRIT["min_days"]:
        out.update(verdict="⏳ 보류", why=f"표본 n {n}/{CRIT['min_n']} · 일 {len(days)}/{CRIT['min_days']}")
        return out
    fails = []
    if not roi > 0:
        fails.append("평균 ≤ 0")
    if edge is None or not edge > 0:
        fails.append("무작위 대비 ≤ 0")
    if a1 is None or not a1 > 0:
        fails.append("앞 절반 ≤ 0")
    if a2 is None or not a2 > 0:
        fails.append("뒤 절반 ≤ 0")
    if not cap_sum > 0:
        fails.append("하루 1건 합 ≤ 0")
    if win_days < CRIT["win_days"]:
        fails.append(f"이긴 날 {win_days:.0%} < {CRIT['win_days']:.0%}")
    out.update(verdict="✅ 통과" if not fails else "❌ 기각", why=" · ".join(fails) or "기준 모두 충족")
    return out


EXIT_ENGINES = ("live_stale24", "live_trend", "live_trend0", "live_trail3", "live_trail8")   # 📈 Fix 447 · 📏 Fix 453 트레일링 폭


def exit_compare(rows: list[dict], engine: str) -> dict:
    """rows = [{"d", "eng": {엔진: roi}}] → 엔진 vs live 같은 거래 짝 비교 + 사전 등록 판정 (Fix 447)."""
    pairs = [(r["d"], r["eng"]["live"], r["eng"][engine]) for r in rows
             if _f((r.get("eng") or {}).get("live")) is not None and _f((r.get("eng") or {}).get(engine)) is not None]
    n = len(pairs)
    if n == 0:
        return {"n": 0, "verdict": "⏳ 보류", "why": "짝 없음"}
    days = sorted({d for d, _a, _b in pairs})
    mid = days[len(days) // 2]
    diff = [b - a for _d, a, b in pairs]
    h1 = [b - a for d, a, b in pairs if d < mid]
    h2 = [b - a for d, a, b in pairs if d >= mid]
    by_day_live: dict = defaultdict(float)
    by_day_eng: dict = defaultdict(float)
    for d, a, b in pairs:
        by_day_live[d] += a
        by_day_eng[d] += b
    out = {"n": n, "days": len(days), "live": sum(a for _d, a, _b in pairs) / n, "eng": sum(b for _d, _a, b in pairs) / n,
           "diff": sum(diff) / n, "first_half": (sum(h1) / len(h1)) if h1 else None,
           "second_half": (sum(h2) / len(h2)) if h2 else None,
           "worst_live": min(by_day_live.values()), "worst_eng": min(by_day_eng.values())}
    if n < CRIT["min_n"]:
        out.update(verdict="⏳ 보류", why=f"짝 n {n}/{CRIT['min_n']}")
        return out
    fails = []
    if not out["diff"] > 0:
        fails.append("평균 차 ≤ 0")
    if out["first_half"] is None or not out["first_half"] > 0:
        fails.append("앞 절반 차 ≤ 0")
    if out["second_half"] is None or not out["second_half"] > 0:
        fails.append("뒤 절반 차 ≤ 0")
    out.update(verdict="✅ 청산 후보" if not fails else "❌ 지금 청산 유지", why=" · ".join(fails) or "기준 모두 충족")
    return out


def exit_line(name: str, ev: dict) -> str:
    if not ev.get("n"):
        return f"| {name} | 0 | — | — | — | — | — | {ev['verdict']} {ev.get('why', '')} |"
    return (f"| {name} | {ev['n']} ({ev['days']}일) | {_fmt(ev['live'])} → {_fmt(ev['eng'])} | {_fmt(ev['diff'])} "
            f"| {_fmt(ev['first_half'])} → {_fmt(ev['second_half'])} | {_fmt(ev['worst_live'], '+.0f')} → {_fmt(ev['worst_eng'], '+.0f')} "
            f"| {ev['verdict']} | {ev['why']} |")


# 🪜 Fix 448 (2026-10-12 사장님 「1번 2번 진행해줘」): 통과 전략의 단계 1 설정표 — 자본 키우는 계획서(docs/spec/CAPITAL_SCALING_PLAN_2026-10-12.md) 4절
#   값은 계획서 그대로(Claude가 정함). 보고서는 **보여 주기만** 한다 — 바꾸는 건 사장님(관제실·system_settings).
FORCE_SHADOW = {"bbema": "전용 추세 보유 청산 미구현", "bbwave": "출처 청산이 실주문 경로에 없음",
                "trima": "출처 청산이 실주문 경로에 없음"}     # on 으로 바꿔도 shadow 로 돈다 (external_strategies_worker)
CAPITAL_KEY = {"fujimoto": "fujimoto_total_alloc_usdt"}            # 나머지는 <가족>_capital_usdt


def stage1_rows(fam: str, kind: str, cur: dict) -> list[tuple[str, str, str, str]]:
    """(설정 키, 지금 값, 단계 1, 메모). kind = "rf"(규칙 가족) | "ext"(외부 전략). cur = 키 → 지금 실효값(문자열|None)."""
    def now(k: str) -> str:
        v = cur.get(k)
        return "—" if v is None or str(v).strip() == "" else str(v)
    cap = CAPITAL_KEY.get(fam, f"{fam}_capital_usdt")
    rows = [(f"{fam}_mode", now(f"{fam}_mode"), "on",
             ("⚠️ on 이어도 shadow — " + FORCE_SHADOW[fam] + " (판정 G 추세 청산 결과 뒤 실주문 청산 개발 필요)") if fam in FORCE_SHADOW else ""),
            ((cap, now(cap), "유지", "⚠️ 총 배정액(단계 비율로 나눠 진입) — 계획서 진입당 10U 와 단위가 달라 사장님이 정함")
             if fam in CAPITAL_KEY else (cap, now(cap), "10", "진입당 증거금")),
            (f"daily_max_{fam}", now(f"daily_max_{fam}"), "1~3", "권장 1 → 2주 표본 뒤 3까지"),
            (f"{fam}_max_concurrent", now(f"{fam}_max_concurrent"), "2", ""),
            (f"{fam}_loss_breaker_usdt", now(f"{fam}_loss_breaker_usdt"), "0", "0 = 공통 family_loss_breaker_usdt(30)")]
    if kind == "rf":
        e = now(f"{fam}_entry")
        rows.append((f"{fam}_entry", e, "single", "" if e == "single" else "⚠️ 계획서 숫자는 단일 진입 기준 — 분할 유지면 자본 숫자 다시 정함"))
        rows.append(("rf_regime_filter", now("rf_regime_filter"), "on", "장세 필터 (계획서 원칙 4)"))
    else:
        rows.append(("ext_regime_filter", now("ext_regime_filter"), "on", "장세 필터 (계획서 원칙 4)"))
    return rows


def stage1_table(fam: str, label: str, kind: str, cur: dict) -> str:
    out = [f"### {label} (`{fam}`)", "| 설정 | 지금 | 단계 1 | 바꿈 | 메모 |", "|---|---|---|---|---|"]
    for k, n, t, m in stage1_rows(fam, kind, cur):
        same = n == t or t == "유지" or (t == "1~3" and n in ("1", "2", "3")) or (t == "0" and n in ("—", "0", "0.0"))
        out.append(f"| `{k}` | {n} | {t} | {'—' if same else '✏️'} | {m} |")
    return "\n".join(out)


HIGH_BREADTH = 0.6


def short_high_hypothesis(rows: list[dict]) -> dict:
    """I 가설 — rows = 장세 필터 안 SHORT 행(rule 이 baseline_ 아님) [{d, roi, mb}]. 시장폭 > 0.6 칸 vs 나머지."""
    hi = [r for r in rows if _f(r.get("mb")) is not None and _f(r["mb"]) > HIGH_BREADTH]
    lo = [r for r in rows if _f(r.get("mb")) is not None and _f(r["mb"]) <= HIGH_BREADTH]

    def st(xs):
        if not xs:
            return {"n": 0, "days": 0, "mean": None, "h1": None, "h2": None}
        days = sorted({r["d"] for r in xs})
        mid = days[len(days) // 2]
        a = [r["roi"] for r in xs if r["d"] < mid]
        b = [r["roi"] for r in xs if r["d"] >= mid]
        return {"n": len(xs), "days": len(days), "mean": sum(r["roi"] for r in xs) / len(xs),
                "h1": (sum(a) / len(a)) if a else None, "h2": (sum(b) / len(b)) if b else None}
    H, L = st(hi), st(lo)
    out = {"high": H, "rest": L}
    if H["n"] < CRIT["min_n"] or H["days"] < CRIT["min_days"]:
        out.update(verdict="⏳ 보류", why=f"시장폭>{HIGH_BREADTH} 칸 n {H['n']}/{CRIT['min_n']} · 일 {H['days']}/{CRIT['min_days']}")
        return out
    fails = []
    if not H["mean"] < 0:
        fails.append("평균 ≥ 0")
    if H["h1"] is None or not H["h1"] < 0:
        fails.append("앞 절반 ≥ 0")
    if H["h2"] is None or not H["h2"] < 0:
        fails.append("뒤 절반 ≥ 0")
    if L["mean"] is not None and not H["mean"] < L["mean"]:
        fails.append("나머지 칸보다 낮지 않음")
    out.update(verdict="✅ 제외 후보" if not fails else "❌ 기각(지금 그대로)", why=" · ".join(fails) or "기준 모두 충족")
    return out


def live_verdict(system_sum: float, n_closed: int) -> str:
    if n_closed < CRIT["live_min_n"]:
        return "⏳ 보류"
    return "✅ 통과" if system_sum > 0 else "❌ 기각"


NET_COST_FALLBACK = 0.4          # Fix 452 이전 행: 왕복 (0.05 + 0.05)% × 2 × 레버 2


def net_of(r: dict) -> float | None:
    n = _f(r.get("roi_net"))
    if n is not None:
        return n
    g = _f(r.get("roi"))
    return None if g is None else g - NET_COST_FALLBACK


def _fmt(x: Any, p: str = "+.2f") -> str:
    return "—" if x is None else format(x, p)


def line(name: str, ev: dict) -> str:
    if not ev.get("n"):
        return f"| {name} | 0 | — | — | — | — | — | — | {ev['verdict']} {ev.get('why', '')} | — |"
    return (f"| {name} | {ev['n']} ({ev['days']}일) | {_fmt(ev['roi'])} | {_fmt(ev['edge'])} | {_fmt(ev['first_half'])} → {_fmt(ev['second_half'])} "
            f"| {_fmt(ev['cap1_usdt'], '+.1f')}U | {ev['win_days']:.0%} | {ev['verdict']} | {ev['why']} | {_fmt(ev.get('net'))} |")


def main() -> None:  # pragma: no cover — 운영 DB 필요
    from sqlalchemy import select, text
    from app.core.database import SessionLocal
    from app.core.redis_client import get_redis_client
    from app.services import human_share as HS
    from app.services import rule_families as RF
    from app.models.strategy_instance import StrategyInstance as SI
    from app.models.strategy_template import StrategyTemplate as ST

    now = _dt(os.environ["VERDICT_NOW"]) if os.environ.get("VERDICT_NOW") else datetime.now(timezone.utc)
    earliest = min(_dt(v) for v in CUTOFFS.values())
    db = SessionLocal()
    try:
        q = text("""select rule, side, symbol, entry_bar_ts ts, opened_at, opened_at::date d, (engines->'live'->>'roi')::float roi,
                    (engines->'live'->>'roi_net')::float roi_net,
                    chg_24h, snapshot->>'market_breadth' mb, snapshot->'rules_fired' rf
                    from paper_trades where source='live' and status='CLOSED' and opened_at >= :since and opened_at <= :now
                    and engines->'live'->>'roi' is not null""")
        rows = [dict(r._mapping) for r in db.execute(q, {"since": earliest, "now": now})]
        passed: dict = {}                     # 🪜 Fix 448: 가족 키 → (이름, rf|ext, 통과 근거)
        fam_of_rule = {f.rule: f for f in RF.FAMILIES}
        base: dict = defaultdict(list)
        for r in rows:
            if r["rule"].startswith("baseline_"):
                base[(r["side"], r["d"])].append(r["roi"])
        bm = {k: sum(v) / len(v) for k, v in base.items()}
        print(f"# 통합 판정 보고서 — {now:%Y-%m-%d %H:%M} UTC (사전 등록 기준 2026-10-11 고정)\n")
        print("기준: n ≥ 30 · 7일 이상 · 평균 > 0 · 무작위 대비 > 0 · 앞·뒤 절반 > 0 · 하루 1건 합 > 0 · 이긴 날 ≥ 50%\n")
        hdr = "| 대상 | n | 평균 roi % | 무작위 대비 | 앞 → 뒤 | 하루 1건(10U) | 이긴 날 | 판정 | 사유 | 💸 순수익 |\n|---|---|---|---|---|---|---|---|---|---|"

        print("## B. 새 가상 규칙 (강화판)\n" + hdr)
        for rule, ck in NEW_RULES.items():
            xs = [r for r in rows if r["rule"] == rule and r["opened_at"] >= _dt(CUTOFFS[ck])]
            ev = evaluate(xs, bm)
            print(line(rule, ev))
            if ev["verdict"] == "✅ 통과" and rule in fam_of_rule:
                f_ = fam_of_rule[rule]
                passed.setdefault(f_.key, (f_.label, "rf", f"B {rule}"))

        print("\n## C. 외부 전략 가상 규칙 — 장세 필터 안 / 밖\n" + hdr)
        ext_rules = sorted({r["rule"] for r in rows if any(r["rule"].startswith(p) for p in EXT_PREFIX)})
        for rule in ext_rules:
            ck = next(v for p, v in EXT_PREFIX.items() if rule.startswith(p))
            xs = [r for r in rows if r["rule"] == rule and r["opened_at"] >= _dt(CUTOFFS[ck])]
            ins = [r for r in xs if regime_ok(r["side"], r["mb"], r["chg_24h"]) is True]
            outs = [r for r in xs if regime_ok(r["side"], r["mb"], r["chg_24h"]) is False]
            ev = evaluate(ins, bm)
            print(line(f"{rule} · 필터 안", ev))
            if ev["verdict"] == "✅ 통과":
                passed.setdefault(ck, (ck, "ext", f"C {rule} · 필터 안"))
            print(line(f"{rule} · 필터 밖", evaluate(outs, bm)))

        print("\n## D. 규칙 가족 가상 규칙 — 장세 필터 안 / 밖 (Fix 439 배포 뒤)\n" + hdr)
        for fam in RF.FAMILIES:
            if fam.rule in NEW_RULES:
                continue
            xs = [r for r in rows if r["rule"] == fam.rule and r["opened_at"] >= _dt(CUTOFFS["regime"])]
            ins = [r for r in xs if regime_ok(r["side"], r["mb"], r["chg_24h"]) is True]
            outs = [r for r in xs if regime_ok(r["side"], r["mb"], r["chg_24h"]) is False]
            ev = evaluate(ins, bm)
            print(line(f"{fam.key} · 필터 안", ev))
            if ev["verdict"] == "✅ 통과":
                passed.setdefault(fam.key, (fam.label, "rf", f"D {fam.rule} · 필터 안"))
            print(line(f"{fam.key} · 필터 밖", evaluate(outs, bm)))

        print("\n## A. 실주문 가족 — 장세 필터 뒤 실현 (시스템 몫 · 사람 💉 추가 몫 따로)\n")
        print("| 가족 | 모드 | 끝난 n | 시스템 몫 USDT | 사람 추가 몫 | 진행 중 | 판정 |\n|---|---|---|---|---|---|---|")
        from app.core.strategy_status import TERMINAL_STATUSES
        st_of = {f.stype: f for f in RF.FAMILIES}
        got = db.execute(select(SI.id, SI.side, SI.status, SI.realized_pnl, ST.strategy_type)
                         .join(ST, ST.id == SI.strategy_template_id)
                         .where(ST.strategy_type.in_(list(st_of)), SI.created_at >= _dt(CUTOFFS["regime"]), SI.created_at <= now)).all()
        closed = [(sid, side, rp, stype) for sid, side, status, rp, stype in got if status in TERMINAL_STATUSES]
        sp = HS.split_for(db, [(sid, side, rp) for sid, side, rp, _s in closed]) if closed else {}
        agg: dict = defaultdict(lambda: [0, 0.0, 0.0, 0])
        for sid, side, status, rp, stype in got:
            a = agg[st_of[stype].key]
            if status in TERMINAL_STATUSES:
                a[0] += 1
                a[1] += sp.get(sid, {}).get("system", float(rp or 0))
                a[2] += sp.get(sid, {}).get("human", 0.0)
            else:
                a[3] += 1
        for fam in RF.FAMILIES:
            mode = RF.mode_of(db, fam.key)
            if mode != "on" and fam.key not in agg:
                continue
            n, s, h, op = agg[fam.key]
            print(f"| {fam.label} | {mode} | {n} | {s:+.2f} | {h:+.2f} | {op} | {live_verdict(s, n)} |")
            if live_verdict(s, n) == "✅ 통과":
                passed.setdefault(fam.key, (fam.label, "rf", "A 실주문 시스템 몫"))

        print("\n## F. 📣 시장 전체 동시 반등 (Fix 442) — 같은 봉 LONG 규칙 4개+ 종목 16개+ 순간의 LONG 진입 (봉·종목당 1건)\n" + hdr)
        from app.services import mass_rebound as MR
        side_of = {}
        for r_ in rows:
            if not r_["rule"].startswith("baseline_"):
                side_of.setdefault(r_["rule"], r_["side"])
        mr_rows = [r_ for r_ in rows if r_["opened_at"] >= _dt(CUTOFFS["mass_rebound"])]
        bars = MR.retro_bars(mr_rows, side_of=side_of)
        one: dict = {}
        for r_ in mr_rows:
            if r_["ts"] in bars and r_["side"] == "LONG" and not r_["rule"].startswith("baseline_") and r_["rule"] not in NEW_RULES:
                one.setdefault((r_["ts"], r_["symbol"]), r_)
        print(line(f"동시 반등 봉 {len(bars)}개", evaluate(list(one.values()), bm)))

        print("\n## E. 운영팀 게이트 (Fix 433) — 칸 안 / 밖 (가상 roi, 그림자 기록)\n")
        r = get_redis_client()
        recs = []
        for k in r.scan_iter("council:gate:*", count=500):
            try:
                recs.append(json.loads(r.get(k)))
            except Exception:  # noqa: BLE001
                pass
        pids = [x["paper_trade_id"] for x in recs if x.get("paper_trade_id")]
        roi_of = {}
        if pids:
            for pid, eng in db.execute(text("select id, engines from paper_trades where id = any(:ids) and status='CLOSED'"),
                                       {"ids": pids}).all():
                if isinstance(eng, dict) and isinstance(eng.get("live"), dict) and _f(eng["live"].get("roi")) is not None:
                    roi_of[pid] = float(eng["live"]["roi"])
        g = {"안": [], "밖": []}
        for x in recs:
            v = roi_of.get(x.get("paper_trade_id"))
            if v is not None and x.get("in_cells") is not None:
                g["안" if x["in_cells"] else "밖"].append(v)
        mi = sum(g["안"]) / len(g["안"]) if g["안"] else None
        mo = sum(g["밖"]) / len(g["밖"]) if g["밖"] else None
        print(f"칸 안 n {len(g['안'])} 평균 {_fmt(mi)} · 칸 밖 n {len(g['밖'])} 평균 {_fmt(mo)}")
        if len(g["안"]) >= CRIT["gate_min_n"] and len(g["밖"]) >= CRIT["gate_min_n"] and mi is not None and mo is not None:
            print("→ " + ("✅ 「칸 밖 막기」 후보 (안 > 밖)" if mi > mo else "❌ 막지 않는다 (안 ≤ 밖)"))
        else:
            print(f"→ ⏳ 보류 (각 n ≥ {CRIT['gate_min_n']} 필요)")

        print("\n## G. 📈 청산 방식 비교 (Fix 447) — 같은 거래 짝: 지금 청산(live) 대비 · 24h 정체 · 추세 보유(TP1 뒤) · 추세 보유(처음부터)\n")
        print("| 대상 · 엔진 | 짝 n | 평균 live → 변형 | 평균 차 | 앞 → 뒤 차 | 최악의 날 합 live → 변형 | 판정 | 사유 |\n|---|---|---|---|---|---|---|---|")
        qe = text("""select rule, side, opened_at::date d, engines->'live'->>'roi' live,
                     engines->'live_stale24'->>'roi' live_stale24, engines->'live_trend'->>'roi' live_trend,
                     engines->'live_trend0'->>'roi' live_trend0,
                     engines->'live_trail3'->>'roi' live_trail3, engines->'live_trail8'->>'roi' live_trail8
                     from paper_trades where source='live' and status='CLOSED' and opened_at >= :since and opened_at <= :now
                     and engines->'live_trend' is not null""")
        er = [{"rule": x.rule, "side": x.side, "d": x.d,
               "eng": {k: _f(getattr(x, k)) for k in ("live",) + EXIT_ENGINES}}
              for x in db.execute(qe, {"since": earliest, "now": now})]
        on_rules = {f.rule: f.label for f in RF.FAMILIES if RF.mode_of(db, f.key) == "on"}
        groups = [("🤝 합의 LONG", [r for r in er if r["rule"] == "consensus_long"])]
        groups += [(f"실주문 {lab}", [r for r in er if r["rule"] == rule]) for rule, lab in on_rules.items()]
        groups += [(f"전체 {sd}", [r for r in er if r["side"] == sd and not r["rule"].startswith("baseline_")]) for sd in ("LONG", "SHORT")]
        for gname, grows in groups:
            for eng in EXIT_ENGINES:
                print(exit_line(f"{gname} · {eng}", exit_compare(grows, eng)))

        print(f"\n## I. 🧪 가설(Fix 454) — 장세 필터 안 SHORT 중 시장폭 > {HIGH_BREADTH} 빼기 (10/14 사전 등록, 그 뒤 진입만)\n")
        sh = [r for r in rows if r["side"] == "SHORT" and not r["rule"].startswith("baseline_")
              and r["opened_at"] >= _dt(CUTOFFS["short_high"]) and regime_ok("SHORT", r["mb"], r["chg_24h"]) is True]
        hv = short_high_hypothesis(sh)
        for k, lab in (("high", f"시장폭 > {HIGH_BREADTH}"), ("rest", f"시장폭 ≤ {HIGH_BREADTH}")):
            g = hv[k]
            print(f"- {lab}: n {g['n']} ({g['days']}일) · 평균 {_fmt(g['mean'])} · 앞 {_fmt(g['h1'])} → 뒤 {_fmt(g['h2'])}")
        print(f"→ {hv['verdict']} — {hv['why']}  (제외 후보여도 실주문 반영은 사장님 승인 뒤)")

        print("\n## H. 🪜 단계 1 설정표 (Fix 448) — 위에서 ✅ 통과한 전략만 · 계획서 4절 값 vs 지금 값 · 바꾸는 건 사장님\n")
        # 미리 보기(판정 아님): VERDICT_PREVIEW_H=rf_consensus_long,trima — 표가 맞게 나오는지 판정 전에 확인용
        rf_keys = {f.key: f.label for f in RF.FAMILIES}
        for fk in [x.strip() for x in os.environ.get("VERDICT_PREVIEW_H", "").split(",") if x.strip()]:
            if fk in rf_keys or fk in set(EXT_PREFIX.values()):
                passed.setdefault(fk, (rf_keys.get(fk, fk), "rf" if fk in rf_keys else "ext", "🔎 미리 보기 — 판정 아님"))
        if not passed:
            print("통과한 전략 없음 → 단계 0 유지 (설정 변경 없음)")
        else:
            from app.models.system_setting import SystemSetting
            from app.services import ext_regime as ER
            from app.services import external_strategies as ES
            defaults = {**{k: v[0] for k, v in RF.SETTINGS.items()}, **{k: v[0] for k, v in ES.SETTINGS.items()},
                        **{k: v[0] for k, v in ER.SETTINGS.items()}}
            for fk, (label, kind, why) in passed.items():
                keys = [k for k, _n, _t, _m in stage1_rows(fk, kind, {})]
                cur = {}
                for k in keys:
                    row = db.get(SystemSetting, k)
                    raw = None if row is None or row.value is None or not str(row.value).strip() else str(row.value).strip()
                    cur[k] = raw if raw is not None else defaults.get(k, "1" if k.startswith("daily_max_") else None)
                print(stage1_table(fk, label, kind, cur))
                print(f"근거: {why}\n")
    finally:
        db.close()


if __name__ == "__main__":
    main()
