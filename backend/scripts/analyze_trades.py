"""📊 매매 전수 분석 — 롱/숏 성공·실패를 숫자로 갈라본다 (Fix 239).

사장님 지시 (2026-08-31):
  "자동매매를 분석하고 **롱과숏 실패와 성공을 세밀하게 분석**해서 변경해야 할부분을
   수정해서 학습하고 우리로직에 반영해줘. 그리고 **익절과 손절에서 우리 로직이
   효율적으로 잘 작동하는지 검증**하고 **실패보다는 익절을 많이 할수 있는 로직**을
   만들수 있게 데이터를 수집해줘"

## 실행

    docker compose exec -T api python scripts/analyze_trades.py
    docker compose exec -T api python scripts/analyze_trades.py --days 14
    docker compose exec -T api python scripts/analyze_trades.py --csv /tmp/trades.csv

## 이 도구가 답하는 질문

  1. 롱과 숏 중 무엇이 되고 무엇이 안 되나 (승률·손익비·총액)
  2. 어느 전략(워커)이 돈을 벌고 어느 것이 잃나
  3. **익절을 놓치고 있나** — 이익 구간까지 갔다가 손실로 끝난 건수
     = 사장님이 물은 "익절 로직이 효율적인가" 의 직접 답
  4. **손절이 제때 걸리나** — 최대 손실 대비 어디서 잘렸나
  5. 청산 사유별 성적 (TP / 손절 / 강제청산 / 수동)
  6. 승/패 그룹의 **진입 지표 차이** = 무엇을 게이트로 써야 하는가
  7. 학습 데이터가 얼마나 비어 있나 (분석 자체의 신뢰도)

⚠️ 이 스크립트는 **읽기 전용**이다. 어떤 주문도 내지 않고 DB 도 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

sys.path.insert(0, "/app")

from app.core.database import SessionLocal                      # noqa: E402
from app.models.strategy_instance import StrategyInstance       # noqa: E402
from app.models.strategy_template import StrategyTemplate       # noqa: E402
from app.models.trade_learning_record import TradeLearningRecord  # noqa: E402

TERMINAL = ("STOPPED", "COMPLETED", "CLOSED", "LIQUIDATED", "FAILED")


# ───────────────────────────────────────────────── 유틸

def _d(x: Any) -> Decimal | None:
    if x is None:
        return None
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _f(x: Any) -> float | None:
    v = _d(x)
    return float(v) if v is not None else None


def _pct(n: int, d: int) -> str:
    return f"{(n / d * 100):5.1f}%" if d else "  n/a"


def _hr(title: str) -> None:
    print()
    print("=" * 78)
    print(f"  {title}")
    print("=" * 78)


def _row(*cells: Any, w: tuple[int, ...] = ()) -> str:
    out = []
    for i, c in enumerate(cells):
        width = w[i] if i < len(w) else 12
        out.append(str(c).ljust(width) if i == 0 else str(c).rjust(width))
    return "".join(out)


def _normalize_source(name: str) -> str:
    """템플릿 이름 -> **워커 이름**.

    🚨 옛 코드는 앞 두 토큰만 잘라서 `PUMPSPLIT_BTRUSDT` 처럼 **심볼이 섞였다**.
    그래서 같은 워커가 심볼 수만큼 쪼개져 「건수 2건」짜리 그룹이 줄줄이 나왔고,
    워커별 성적을 볼 수 없었다. 심볼 토큰을 걷어내고 합친다.
    """
    if not name:
        return "미상"
    if name.startswith("_quick_"):
        return "수동(직접입력)"
    parts = []
    for tok in name.upper().replace("-", "_").split("_"):
        if not tok:
            continue
        if tok.endswith("USDT") or tok.endswith("BUSD"):
            break                      # 심볼부터는 이름이 아니다
        if tok.isdigit() or len(tok) > 14:
            break                      # 타임스탬프
        parts.append(tok)
        if len(parts) >= 3:
            break
    return "_".join(parts) or "미상"


class Stat:
    """한 그룹의 성적."""

    def __init__(self) -> None:
        self.wins: list[float] = []
        self.losses: list[float] = []
        self.flat = 0

    def add(self, pnl: float) -> None:
        if pnl > 0:
            self.wins.append(pnl)
        elif pnl < 0:
            self.losses.append(pnl)
        else:
            self.flat += 1

    @property
    def n(self) -> int:
        return len(self.wins) + len(self.losses) + self.flat

    @property
    def total(self) -> float:
        return sum(self.wins) + sum(self.losses)

    @property
    def win_rate(self) -> float:
        d = len(self.wins) + len(self.losses)
        return len(self.wins) / d * 100 if d else 0.0

    @property
    def avg_win(self) -> float:
        return sum(self.wins) / len(self.wins) if self.wins else 0.0

    @property
    def avg_loss(self) -> float:
        return sum(self.losses) / len(self.losses) if self.losses else 0.0

    @property
    def rr(self) -> float:
        """손익비 = 평균이익 / |평균손실|. 클수록 좋다."""
        return self.avg_win / abs(self.avg_loss) if self.losses and self.avg_loss else 0.0

    @property
    def expectancy(self) -> float:
        """1건당 기대값 = 승률×평균익 + 패률×평균손. **음수면 하면 할수록 잃는다.**"""
        d = len(self.wins) + len(self.losses)
        if not d:
            return 0.0
        p = len(self.wins) / d
        return p * self.avg_win + (1 - p) * self.avg_loss

    def line(self, label: str) -> str:
        return _row(
            label, self.n, f"{self.win_rate:.1f}%", f"{self.avg_win:+.2f}",
            f"{self.avg_loss:+.2f}", f"{self.rr:.2f}", f"{self.expectancy:+.2f}",
            f"{self.total:+.2f}",
            w=(26, 6, 8, 10, 10, 7, 11, 12),
        )


HEADER = _row("그룹", "건수", "승률", "평균익", "평균손", "손익비", "기대값/건", "합계",
              w=(26, 6, 8, 10, 10, 7, 11, 12))


# ───────────────────────────────────────────────── 수집

def collect(db, days: int) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = (
        db.query(StrategyInstance, StrategyTemplate)
        .outerjoin(StrategyTemplate,
                   StrategyInstance.strategy_template_id == StrategyTemplate.id)
        .filter(StrategyInstance.status.in_(TERMINAL))
        .filter(StrategyInstance.created_at >= since)
    )
    learn = {
        r.strategy_instance_id: r
        for r in db.query(TradeLearningRecord).filter(
            TradeLearningRecord.created_at >= since
        )
    }
    out = []
    for si, tpl in q:
        pnl = _f(si.realized_pnl) or 0.0
        lr = learn.get(si.id)
        name = (tpl.name if tpl else "") or ""
        is_manual = name.startswith("_quick_")
        source = _normalize_source(name)
        out.append({
            "id": si.id,
            "symbol": si.symbol,
            "side": (si.side or "").upper(),
            "status": si.status,
            "source": source[:26],
            "is_manual": is_manual,
            "tpl_name": name,
            "pnl": pnl,
            "capital": _f(si.total_capital) or 0.0,
            "stage": si.current_stage or 0,
            "max_profit_pct": _f(si.max_profit_pct),
            "max_loss_pct": _f(si.max_loss_pct),
            "peak_after_tp1": _f(si.peak_pnl_pct_after_first_tp),
            "close_reason": (lr.close_reason if lr else None),
            "pnl_pct": (_f(lr.pnl_pct) if lr else None),
            "entry_ctx": (lr.entry_context if lr else None) or {},
            "created_at": si.created_at,
        })
    return out


# ───────────────────────────────────────────────── 섹션

def sec_overview(rows: list[dict], days: int) -> None:
    _hr(f"1. 전체 — 최근 {days}일 / 종료된 전략 {len(rows)}건")
    if not rows:
        print("  분석할 종료 전략이 없습니다.")
        return
    by_side: dict[str, Stat] = defaultdict(Stat)
    allst = Stat()
    for r in rows:
        by_side[r["side"] or "?"].add(r["pnl"])
        allst.add(r["pnl"])
    print(HEADER)
    print("-" * 78)
    for side in ("LONG", "SHORT"):
        if by_side.get(side):
            print(by_side[side].line(side))
    print("-" * 78)
    print(allst.line("전체"))
    print()
    print("  ※ 기대값/건 이 **음수면 그 그룹은 거래할수록 잃는다**.")
    print("     손익비 1.0 = 이익과 손실 크기가 같다. 승률 50% 미만이면 1.0 초과 필수.")


def sec_by_source(rows: list[dict]) -> None:
    _hr("2. 전략(워커)별 성적 — 어디서 벌고 어디서 잃나")
    g: dict[str, Stat] = defaultdict(Stat)
    for r in rows:
        g[f"{r['source']} {r['side'][:1]}"].add(r["pnl"])
    print(HEADER)
    print("-" * 78)
    for k, st in sorted(g.items(), key=lambda kv: kv[1].total):
        if st.n >= 2:
            print(st.line(k))
    print()
    print("  ※ 합계 오름차순 — 맨 위가 **가장 많이 잃은 전략**이다.")


def sec_profit_efficiency(rows: list[dict]) -> None:
    """🚨 사장님 질문의 핵심: 익절을 놓치고 있나."""
    _hr("3. 🚨 익절 효율 — 이익 구간까지 갔다가 손실로 끝난 건")
    have = [r for r in rows if r["max_profit_pct"] is not None]
    if not have:
        print("  max_profit_pct 데이터가 없습니다 (학습 기록 결손 — 8번 항목 참조).")
        return
    print(f"  최대이익률이 기록된 건: {len(have)} / {len(rows)}")
    print()
    print(_row("최대이익 도달", "건수", "그중 손실마감", "비율", "놓친 이익합",
               w=(20, 8, 14, 10, 14)))
    print("-" * 70)
    for lo, hi, label in [(1, 3, "+1~3%"), (3, 5, "+3~5%"), (5, 10, "+5~10%"),
                          (10, 20, "+10~20%"), (20, 10**9, "+20% 이상")]:
        grp = [r for r in have if lo <= (r["max_profit_pct"] or 0) < hi]
        lost = [r for r in grp if r["pnl"] < 0]
        missed = sum(abs(r["pnl"]) for r in lost)
        print(_row(label, len(grp), len(lost), _pct(len(lost), len(grp)),
                   f"{missed:,.0f}", w=(20, 8, 14, 10, 14)))
    print()
    reversed_ = [r for r in have if (r["max_profit_pct"] or 0) >= 5 and r["pnl"] < 0]
    if reversed_:
        tot = sum(abs(r["pnl"]) for r in reversed_)
        print(f"  🚨 **+5% 이상 이익이었는데 손실로 끝난 건: {len(reversed_)}건 / "
              f"합계 -{tot:,.2f} USDT**")
        print("     = 익절 지점이 너무 멀거나 트레일링이 늦다는 직접 증거.")
        print()
        print("     최악 10건:")
        for r in sorted(reversed_, key=lambda x: x["pnl"])[:10]:
            print(f"       #{r['id']:<6} {r['symbol']:<12} {r['side']:<5} "
                  f"최대 +{r['max_profit_pct']:.1f}% -> 마감 {r['pnl']:+.2f} "
                  f"({r['close_reason'] or '사유없음'})")
    else:
        print("  ✅ +5% 이상 갔다가 손실로 끝난 건이 없습니다.")


def sec_loss_efficiency(rows: list[dict]) -> None:
    _hr("4. 손절 효율 — 최대 손실이 어디까지 갔나")
    have = [r for r in rows if r["max_loss_pct"] is not None]
    if not have:
        print("  max_loss_pct 데이터가 없습니다.")
        return
    print(_row("최대손실 구간", "건수", "비율", "평균 마감손익", w=(20, 8, 10, 16)))
    print("-" * 60)
    for lo, hi, label in [(0, 5, "0~-5%"), (5, 10, "-5~-10%"), (10, 20, "-10~-20%"),
                          (20, 50, "-20~-50%"), (50, 10**9, "-50% 이상")]:
        grp = [r for r in have if lo <= abs(r["max_loss_pct"] or 0) < hi]
        avg = sum(x["pnl"] for x in grp) / len(grp) if grp else 0
        print(_row(label, len(grp), _pct(len(grp), len(have)), f"{avg:+.2f}",
                   w=(20, 8, 10, 16)))
    deep = [r for r in have if abs(r["max_loss_pct"] or 0) >= 50]
    if deep:
        print()
        print(f"  🚨 **-50% 를 넘긴 건: {len(deep)}건** — 손절이 제때 안 걸렸다는 뜻이다.")
        for r in sorted(deep, key=lambda x: x["pnl"])[:10]:
            print(f"       #{r['id']:<6} {r['symbol']:<12} {r['side']:<5} "
                  f"최저 {r['max_loss_pct']:.1f}% -> 마감 {r['pnl']:+.2f} "
                  f"(단계 {r['stage']}, {r['close_reason'] or '사유없음'})")


def sec_close_reason(rows: list[dict]) -> None:
    _hr("5. 청산 사유별 성적")
    g: dict[str, Stat] = defaultdict(Stat)
    for r in rows:
        g[(r["close_reason"] or "(기록없음)")[:26]].add(r["pnl"])
    print(HEADER)
    print("-" * 78)
    for k, st in sorted(g.items(), key=lambda kv: -kv[1].n):
        print(st.line(k))
    unknown = g.get("(기록없음)")
    if unknown and unknown.n > len(rows) * 0.3:
        print()
        print(f"  ⚠️ 청산 사유가 없는 건이 {_pct(unknown.n, len(rows))} 다.")
        print("     사유 없이는 「어떤 청산 로직이 좋았나」를 가릴 수 없다.")


def _flatten(obj, prefix: str = "", out: dict | None = None, depth: int = 0) -> dict:
    """중첩 dict 를 `부모.자식` 평탄 키로. 숫자 잎만 남긴다.

    🚨 Fix 246: 옛 코드는 `rsi_15m` 같은 **평탄 키를 가정**했는데,
    실제 entry_context 는 ema_vcp / bb_top / pump_dump / bb_4h ... 7개
    하위 dict 로 중첩돼 있다. 그래서 데이터가 71% 차 있는데도
    「진입 스냅샷이 비어 있습니다」가 나왔다.
    키 이름을 추측하지 말고 **있는 것을 전부 펼쳐서** 판별력으로 고른다.
    """
    if out is None:
        out = {}
    if depth > 4 or not isinstance(obj, dict):
        return out
    for k, v in obj.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            _flatten(v, key, out, depth + 1)
        elif isinstance(v, bool):
            out[key] = 1.0 if v else 0.0
        elif isinstance(v, (int, float)):
            fv = float(v)
            if fv == fv and abs(fv) < 1e12:      # NaN / 무계값 제외
                out[key] = fv
    return out


def _median(vals: list[float]) -> float:
    v = sorted(vals)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def _stdev(vals: list[float]) -> float:
    n = len(vals)
    if n < 2:
        return 0.0
    m = sum(vals) / n
    return (sum((x - m) ** 2 for x in vals) / (n - 1)) ** 0.5


def sec_entry_indicators(rows: list[dict]) -> None:
    _hr("6. 진입 지표 — 이긴 진입과 진 진입의 차이 (자동 탐색)")
    win = [_flatten(r["entry_ctx"]) for r in rows if r["pnl"] > 0 and r["entry_ctx"]]
    los = [_flatten(r["entry_ctx"]) for r in rows if r["pnl"] < 0 and r["entry_ctx"]]
    if not win or not los:
        print("  진입 스냅샷이 한쪽에 없습니다 — 8번 결손 리포트를 보십시오.")
        return
    print(f"  스냅샷이 있는 건: 승 {len(win)} / 패 {len(los)}")
    print()
    keys = set()
    for d in win + los:
        keys |= set(d)
    ranked = []
    for k in sorted(keys):
        wv = [d[k] for d in win if k in d]
        lv = [d[k] for d in los if k in d]
        if len(wv) < 5 or len(lv) < 5:
            continue
        wm, lm = _median(wv), _median(lv)
        sd = _stdev(wv + lv)
        if sd <= 0:
            continue                       # 값이 하나뿐 = 변별 불가
        effect = (wm - lm) / sd            # 척도 무관 효과크기
        ranked.append((abs(effect), k, len(wv), wm, len(lv), lm, effect))
    if not ranked:
        print("  비교 가능한 숫자 필드가 없습니다 (표본 5건 미만 또는 상수).")
        return
    print(f"{'지표':<38}{'승n':>5}{'승중앙':>10}{'패n':>5}{'패중앙':>10}{'효과크기':>10}")
    print("-" * 78)
    for _a, k, nw, wm, nl, lm, eff in sorted(ranked, reverse=True)[:20]:
        print(f"{k[:38]:<38}{nw:>5}{wm:>10.3f}{nl:>5}{lm:>10.3f}{eff:>+10.2f}")
    print()
    print("  ※ **효과크기**로 정렬했다 (중앙값 차이 / 표준편차) — 척도가 달라도 비교된다.")
    print("     |효과크기| 0.5 이상이면 게이트 후보, 0.2 미만이면 써도 소용없다.")
    print(f"     상위 20개만 표시 (전체 {len(ranked)}개 필드 비교).")


def sec_stage(rows: list[dict]) -> None:
    _hr("7. 단계별 — 몇 단계까지 갔을 때 결과가 어땠나")
    g: dict[str, Stat] = defaultdict(Stat)
    for r in rows:
        g[f"{r['stage']}단계"].add(r["pnl"])
    print(HEADER)
    print("-" * 78)
    for k in sorted(g, key=lambda x: int(x[0]) if x[0].isdigit() else 99):
        print(g[k].line(k))
    print()
    print("  ※ 단계가 올라갈수록 기대값이 나빠지면 **물타기가 손실을 키우고 있다**는 뜻.")


def sec_gaps(rows: list[dict]) -> None:
    _hr("8. 데이터 결손 — 이 분석을 얼마나 믿을 수 있나")
    n = len(rows) or 1
    checks = [
        ("close_reason", lambda r: r["close_reason"]),
        ("max_profit_pct", lambda r: r["max_profit_pct"] is not None),
        ("max_loss_pct", lambda r: r["max_loss_pct"] is not None),
        ("entry_context", lambda r: bool(r["entry_ctx"])),
        ("pnl_pct(학습)", lambda r: r["pnl_pct"] is not None),
    ]
    print(_row("필드", "채워진 건", "비율", w=(24, 12, 10)))
    print("-" * 48)
    for name, fn in checks:
        ok = sum(1 for r in rows if fn(r))
        mark = " ⚠️" if ok < n * 0.7 else ""
        print(_row(name, ok, _pct(ok, n) + mark, w=(24, 12, 10)))
    print()
    print("  ※ 70% 미만이면 그 항목의 결론은 **표본 편향**을 의심해야 한다.")


def write_csv(rows: list[dict], path: str) -> None:
    cols = ["id", "symbol", "side", "status", "source", "pnl", "capital", "stage",
            "max_profit_pct", "max_loss_pct", "close_reason", "pnl_pct", "created_at"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\n  📁 CSV 저장: {path} ({len(rows)}행)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--csv", type=str, default=None)
    ap.add_argument("--auto-only", action="store_true",
                    help="수동(직접입력) 전략을 빼고 **자동매매만** 분석")
    ap.add_argument("--manual-only", action="store_true",
                    help="수동 전략만 분석 (대조용)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        rows = collect(db, args.days)
        _all_n = len(rows)
        if args.auto_only:
            rows = [r for r in rows if not r["is_manual"]]
            print()
            print(f"  🤖 **자동매매만** 분석 — 수동 {_all_n - len(rows)}건 제외")
        elif args.manual_only:
            rows = [r for r in rows if r["is_manual"]]
            print()
            print(f"  ✋ **수동만** 분석 — 자동 {_all_n - len(rows)}건 제외")
        sec_overview(rows, args.days)
        if rows:
            sec_by_source(rows)
            sec_profit_efficiency(rows)
            sec_loss_efficiency(rows)
            sec_close_reason(rows)
            sec_entry_indicators(rows)
            sec_stage(rows)
            sec_gaps(rows)
            if args.csv:
                write_csv(rows, args.csv)
        print()
    finally:
        db.close()


if __name__ == "__main__":
    main()
