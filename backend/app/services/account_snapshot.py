"""💰 Fix 479 (2026-10-22 사장님 「거래소잔액이 300USDT가 줄었는데 이유를 찾아줘」 뒤속) — 거래소 잔액 시간별 기록 + 두 시점 변화 설명.

읽기·기록 전용(주문·DB 쓰기·설정 변경 없음):
  take()    매시간(scheduler · 분 7) 계정 숫자 4개(지갑·미실현·마진·쓸 수 있는) + 열린 포지션 수 + 미실현 큰 5개 → Redis acct:snap:<YYYYmmddHH>(UTC, 120일)
            + 정렬 인덱스 acct:snap:index(점수 = epoch 초)
  explain() 두 시점에 가장 가까운 기록(±90분)으로 지갑·미실현·마진 변화 + 같은 구간 거래소 소득 기록(실현·펀딩·수수료·이체) 합
            · 「설명 안 되는 몫」 = 지갑 변화 − 소득 합 · 실현·펀딩 큰 심볼 5개
  report_text() 한국어 표 · CLI: docker compose exec -T api python -m app.services.account_snapshot explain --hours 24
무게: get_account 5 · 시간당 1번. 숫자 「Claude가 정함」(120일 · ±90분 · 분 7).
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

FIX = "Fix479"
KEY = "acct:snap:{hour}"
INDEX = "acct:snap:index"
TTL_DAYS = 120
NEAR = timedelta(minutes=90)
FIELDS = (("wallet", "totalWalletBalance"), ("unrealized", "totalUnrealizedProfit"),
          ("margin", "totalMarginBalance"), ("available", "availableBalance"))
KST = timezone(timedelta(hours=9))


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _hour_key(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%d%H")


def take(redis, get_account: Callable[[], dict], now: datetime | None = None) -> dict:
    try:
        a = get_account() or {}
    except Exception as e:  # noqa: BLE001 — 실패 = 저장 안 함
        return {"ok": False, "why": f"계정 조회 실패: {type(e).__name__}"}
    now = now or datetime.now(timezone.utc)           # 시각은 응답 **뒤** (교차 감사: 조회 전 시각이면 정산 펀딩이 앞뒤 구간에 어긋남)
    snap: dict[str, Any] = {"at": now.astimezone(timezone.utc).isoformat()}
    for k, src in FIELDS:
        snap[k] = _num(a.get(src))
    if all(snap[k] is None for k, _ in FIELDS) or not isinstance(a.get("positions", []), list):
        return {"ok": False, "why": "계정 응답 이상(숫자 없음) — 저장 안 함"}   # 오류 dict({"code","msg"}) 로 정상 기록을 덮지 않게
    pos = []
    for p in a.get("positions") or []:
        amt = _num(p.get("positionAmt"))
        if not amt:
            continue
        pos.append({"symbol": str(p.get("symbol")), "side": str(p.get("positionSide") or ("LONG" if amt > 0 else "SHORT")),
                    "upl": _num(p.get("unrealizedProfit"))})
    snap["positions"] = len(pos)
    snap["top_upl"] = sorted((x for x in pos if x["upl"] is not None), key=lambda x: -abs(x["upl"]))[:5]   # 크기(절댓값) 순 — 손실·이익 모두(Gemini 심판)
    hk = _hour_key(now)
    redis.setex(KEY.format(hour=hk), TTL_DAYS * 86400, json.dumps(snap, ensure_ascii=False))
    ts = now.timestamp()
    redis.zadd(INDEX, {hk: ts})
    redis.zremrangebyscore(INDEX, 0, ts - TTL_DAYS * 86400)
    return {"ok": True, **snap}


def _nearest(redis, dt: datetime) -> dict | None:
    lo, hi = (dt - NEAR).timestamp(), (dt + NEAR).timestamp()
    best, best_d = None, None
    for m in redis.zrangebyscore(INDEX, lo, hi, withscores=True) or []:
        member, score = m
        d = abs(float(score) - dt.timestamp())
        if best_d is None or d < best_d:
            best, best_d = member, d
    if best is None:
        return None
    raw = redis.get(KEY.format(hour=best.decode() if isinstance(best, bytes) else best))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _delta(a: dict | None, b: dict | None, k: str) -> float | None:
    if not a or not b or a.get(k) is None or b.get(k) is None:
        return None
    return b[k] - a[k]


def explain(redis, get_income: Callable[[int, int], list], start: datetime, end: datetime) -> dict:
    s0, s1 = _nearest(redis, start), _nearest(redis, end)
    out: dict[str, Any] = {"start": start.isoformat(), "end": end.isoformat(), "snap_start": s0, "snap_end": s1, "warnings": []}
    if s0 and s1 and s0.get("at") == s1.get("at"):
        out["warnings"].append("시작·끝이 같은 기록 하나 — 그 사이 기록이 빠짐(변화 0 이 아님)")
        s1 = out["snap_end"] = None
    for k, _ in FIELDS:
        out[f"d_{k}"] = _delta(s0, s1, k)
    # 소득 구간 = 실제 스냅샷 시각(있으면) — 지갑 변화와 같은 구간을 비교해야 「설명 안 되는 몫」 이 맞다
    a = datetime.fromisoformat(s0["at"]) if s0 else start
    b = datetime.fromisoformat(s1["at"]) if s1 else end
    try:
        rows = get_income(int(a.timestamp() * 1000), int(b.timestamp() * 1000)) or []
        out["income_ok"] = True
    except Exception as e:  # noqa: BLE001
        rows, out["income_ok"] = [], False
        out["income_why"] = type(e).__name__
    by = defaultdict(float)
    realized, funding, other = defaultdict(float), defaultdict(float), defaultdict(float)
    for x in rows:
        v = _num(x.get("income"))
        if v is None:
            continue
        t = str(x.get("incomeType") or "OTHER")
        asset = str(x.get("asset") or "USDT").upper()
        if asset != "USDT":                                   # BNB 수수료 등 — 지갑(USDT) 변화와 단위가 달라 합에서 뺀다(교차 감사)
            other[asset] += v
            continue
        key = {"REALIZED_PNL": "실현", "FUNDING_FEE": "펀딩", "COMMISSION": "수수료"}.get(t)
        if key is None:
            key = "이체" if "TRANSFER" in t or t.startswith("COIN_SWAP") else "그 밖"
        by[key] += v
        if t == "REALIZED_PNL":
            realized[str(x.get("symbol"))] += v
        elif t == "FUNDING_FEE":
            funding[str(x.get("symbol"))] += v
    out["income"] = {k: round(v, 4) for k, v in by.items()}
    out["income_total"] = round(sum(by.values()), 4)
    if other:
        out["other_assets"] = {k: round(v, 6) for k, v in other.items()}
        out["warnings"].append("USDT 아닌 소득 기록 있음(합에서 뺌): " + ", ".join(f"{k} {v:+g}" for k, v in other.items()))
    out["unexplained"] = None if out["d_wallet"] is None or not out["income_ok"] else round(out["d_wallet"] - out["income_total"], 4)
    out["top_realized"] = sorted(realized.items(), key=lambda kv: -abs(kv[1]))[:5]     # 크기 순
    out["top_funding"] = sorted(funding.items(), key=lambda kv: -abs(kv[1]))[:5]
    return out


def _f(v) -> str:
    return "—" if v is None else f"{v:+,.2f}"


def report_text(r: dict) -> str:
    def when(s):
        return "기록 없음" if not s else datetime.fromisoformat(s["at"]).astimezone(KST).strftime("%m-%d %H:%M KST")
    lines = [f"# 💰 거래소 잔액 변화 — {when(r.get('snap_start'))} → {when(r.get('snap_end'))}", "",
             "| 항목 | 처음 | 끝 | 변화 |", "|---|---|---|---|"]
    for k, label in (("wallet", "지갑 잔액"), ("unrealized", "미실현(평가손익)"), ("margin", "마진 잔액"), ("available", "쓸 수 있는")):
        a = (r.get("snap_start") or {}).get(k)
        b = (r.get("snap_end") or {}).get(k)
        lines.append(f"| {label} | {'—' if a is None else f'{a:,.2f}'} | {'—' if b is None else f'{b:,.2f}'} | {_f(r.get('d_' + k))} |")
    lines += ["", "지갑 변화 나누기 (거래소 소득 기록):"]
    for k in ("실현", "펀딩", "수수료", "이체", "그 밖"):
        if k in (r.get("income") or {}):
            lines.append(f"- {k} {_f(r['income'][k])}")
    lines.append(f"- 소득 합 {_f(r.get('income_total'))} · 설명 안 되는 몫 {_f(r.get('unexplained'))}"
                 + ("" if r.get("income_ok", True) else " (소득 조회 실패)"))
    if r.get("top_realized"):
        lines.append("- 실현 큰 것: " + " · ".join(f"{s} {v:+.2f}" for s, v in r["top_realized"]))
    if r.get("top_funding"):
        lines.append("- 펀딩 큰 것: " + " · ".join(f"{s} {v:+.2f}" for s, v in r["top_funding"]))
    for w in r.get("warnings") or []:
        lines.append(f"- ⚠️ {w}")
    return "\n".join(lines)


# ───────── 운영 연결 ─────────
def _client():
    from app.core.crypto import decrypt_text
    from app.core.database import SessionLocal
    from app.integrations.binance.client import BinanceClient
    from app.models.exchange_account import ExchangeAccount
    db = SessionLocal()
    try:
        acc = db.get(ExchangeAccount, 1)
        if acc is None:
            raise RuntimeError("거래소 계정 #1 없음")
        return BinanceClient(api_key=decrypt_text(acc.api_key_enc), api_secret=decrypt_text(acc.api_secret_enc), is_testnet=acc.is_testnet)
    finally:
        db.close()


def income_fetcher(bc) -> Callable[[int, int], list]:
    def get(start_ms: int, end_ms: int) -> list:
        out, t = [], start_ms
        for _ in range(50):
            r = bc._request("GET", "/fapi/v1/income", signed=True, params={"startTime": t, "endTime": end_ms, "limit": 1000}) or []
            out += r
            if len(r) < 1000:
                break
            t = int(r[-1]["time"]) + 1
        return out
    return get


def run_take_once() -> dict:
    from app.core.redis_client import get_redis_client
    bc = _client()
    return take(get_redis_client(), bc.get_account)


def main(argv: list[str]) -> int:
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")
    if not argv or argv[0] not in ("explain", "take"):
        print(__doc__)
        return 1
    from app.core.redis_client import get_redis_client
    if argv[0] == "take":
        print(json.dumps(run_take_once(), ensure_ascii=False))
        return 0
    now = datetime.now(timezone.utc)
    start, end = now - timedelta(hours=24), now
    if "--hours" in argv:
        start = now - timedelta(hours=float(argv[argv.index("--hours") + 1]))
    if "--from" in argv:
        start = datetime.fromisoformat(argv[argv.index("--from") + 1])
    if "--to" in argv:
        end = datetime.fromisoformat(argv[argv.index("--to") + 1])
    for d in (start, end):
        if d.tzinfo is None:
            raise SystemExit("시각에 시간대를 넣으세요(예 2026-10-22T09:00+09:00)")
    print(report_text(explain(get_redis_client(), income_fetcher(_client()), start, end)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
