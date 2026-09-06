"""📚 실매매 × 차트 학습 일지 라벨 조인 — 「진입이 정점/저점 대비 어디였나」 (Fix 355, 2026-09-07).

## 사장님 지시 (2026-09-07)

  "분석하지 않은 포지션 실패와 성공을 분석해서 우리 시스템로직에서 반영할수 있는
   데이터로 만들어줘"

## 왜 이 모듈이 필요한가

`chart_learning_days`(Fix 353, app/services/chart_learning.py)는 상승50·하락50 심볼의
「그날 정점·저점이 어디였는지」를 매일 라벨로 쌓는다. 하지만 그 라벨은 지금까지 실매매
(strategy_instances/orders/risk_events)와 한 번도 조인된 적이 없다 — 우리가 「좋은 자리」로
정의한 값과 「실제로 우리가 들어간 자리」를 비교할 방법이 없었다. 이 모듈이 그 조인이다.

조인 규칙은 scratchpad 로 먼저 실데이터(14일·504행)에 대해 검증한 스크립트
(wf/build_real_trades.py, wf/extra_agg.py)를 그대로 옮긴 것이다 — 새로 설계하지 않았다.

## 데이터 함정 6가지 (조인 로직에 반영함)

  1. `strategy_instances` 1행 ≠ 1매매. 수동(`_quick_`) 인스턴스는 한 행 안에서 ENTRY/EXIT 를
     여러 사이클 돈다. **재사용 인스턴스**는 `started_at` 이 재시작 시각으로 덮여 옛 체결이
     조회 창 안에 들어온다 → 「에피소드」= `started_at − 10분` 이전의 마지막 EXIT 체결
     이후의 ENTRY 체결만 쓴다(`episode_entry_fills`). 에피소드에 ENTRY 체결이 없으면 무효.
  2. 진입 시각은 `started_at` 이 아니라 **첫 ENTRY 체결**(`updated_at`). `started_at` 은
     체결 뒤에 찍히고, 「💉 포지션 추가(reset 모드)」는 `started_at` 을 다시 찍기도 한다.
  3. `stopped_at` 은 COMPLETED 여도 자주 NULL — 종료 시각은 마지막 EXIT 체결 `updated_at`
     으로 대체한다.
  4. 종료 사유를 직접 말하는 컬럼이 없다 — `risk_events` 로 유도해야 하고(`derive_close_reason`),
     정지 개시자가 기록되지 않는 경로(`STOP_UNLOGGED`)가 실재한다.
  5. `chart_learning_days` 의 `peak/trough.hours` 는 스냅샷을 15분 단위로 내림한 시각
     (`fwd_start`) 기준 봉 종가 시각이고, 라벨링은 스냅샷 36시간 뒤에야 된다 → 최근 진입은
     `ROW_PENDING_OR_EXPIRED` 로 남는 것이 정상이다.
  6. 「정점 전/후」(`timing_vs_extreme`)는 **사후에만** 알 수 있는 값이다. 진입이 늦을수록
     기계적으로 「후」가 되기 쉬우므로 `entry_bucket`(진입이 스냅샷 뒤 몇 시간째인지)과
     `hours_to_extreme`(극값까지 남은 시간)을 항상 같이 읽어야 한다.

## 이 모듈이 하지 않는 것

읽기 전용 분석이다. 손절/익절/진입/차단 등 매매 판정을 계산하거나 바꾸지 않는다. 여기서 나온
숫자를 실행 로직에 반영하는 것은 사람이 규칙을 채택한 뒤 별도 작업으로 한다
(app/services/chart_learning.py 와 같은 원칙 — "규칙 채택은 사람이 한다").
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from math import floor
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.strategy_status import SPLIT_ENTRY_MODE
from app.models.chart_learning_day import ChartLearningDay
from app.models.order import Order
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_template import StrategyTemplate
from app.services import chart_learning as CL

FIX = "Fix355"

_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)
_S15 = 15 * 60  # 초 — snapshot_at 15분 내림용(라벨 klines 타임스탬프는 ms 지만 여긴 datetime 초 단위 계산)

# 가족
FAMILY_MANUAL = "MANUAL"
FAMILY_A_LADDER = "A_LADDER"
FAMILY_B_BBSPLIT = "B_BBSPLIT"
FAMILY_C_OTHER = "C_OTHER"

# 🚨 이 OPEN_STATUSES 는 실데이터(scratchpad wf/real_trades_summary.md §5-2)로 검증한 「이 분석에서
# 아직 안 끝난 것으로 볼 status」 목록이다. app/core/strategy_status.ACTIVE_LIKE(신규 진입 차단용)와
# 목적이 다르므로 값이 다를 수 있다 — 여기 값을 바꾸려면 새 실데이터로 다시 검증할 것.
OPEN_STATUSES: frozenset[str] = frozenset({
    "STAGE1_OPEN", "STAGE2_OPEN", "STAGE3_OPEN", "STAGE4_OPEN", "REENTRY_READY",
    "TP1_DONE_PARTIAL", "TP2_DONE_PARTIAL", "STOPPING",
})

# 사장님 잣대와 같은 것을 재는지 확인하려면 chart_learning.RULES 를 그대로 참조(복제 금지).
RULE_SIDE: dict[str, str] = {r.key: r.side for r in CL.RULES}

DUST_NOTIONAL_USDT = 25.0   # 이 밑이면서 EXIT 체결도 없고 손익도 미미하면 dust(잔재)
DUST_PNL_USDT = 1.0

HOURS_TO_EXTREME_BUCKETS: tuple[tuple[float, float], ...] = ((-24, -6), (-6, -1), (-1, 1), (1, 6), (6, 24))
ENTRY_BUCKETS: tuple[str, ...] = ("<0", "0-3h", "3-9h", "9-24h", ">=24h")


def _to_float(x: Any) -> float | None:
    return float(x) if x is not None else None


# ══════════════════════════════════════════════════════════════════════
# 순수 함수 — DB 없이 테스트 가능
# ══════════════════════════════════════════════════════════════════════

def episode_entry_fills(orders: Sequence[Any], started_at: datetime) -> list[Any]:
    """재사용 인스턴스의 옛 사이클을 제외한 이번 에피소드의 ENTRY 체결(시간순).

    함정 1: `started_at` 보다 10분 이상 전에 끝난 EXIT 체결이 있으면 그 이후 체결만
    이번 에피소드로 본다(그 전은 옛 사이클)."""
    prev_exit_ats = [
        o.created_at for o in orders
        if o.purpose == "EXIT" and o.status == "FILLED" and o.created_at < started_at - timedelta(minutes=10)
    ]
    ep_start = max(prev_exit_ats) if prev_exit_ats else _EPOCH
    fills = [o for o in orders if o.purpose == "ENTRY" and o.status == "FILLED" and o.created_at > ep_start]
    return sorted(fills, key=lambda o: o.created_at)


def weighted_entry_price(fills: Sequence[Any]) -> tuple[float | None, float]:
    """체결 가중평균 진입가와 진입 명목(Σ executed_qty×avg_price)."""
    notional = 0.0
    qty = 0.0
    for o in fills:
        q = float(o.executed_qty or 0)
        p = float(o.avg_price or 0)
        if q > 0 and p > 0:
            notional += q * p
            qty += q
    price = notional / qty if qty > 0 else None
    return price, notional


def derive_close_reason(*, status: str, orders: Sequence[Any], events: Sequence[Any],
                         entry_at: datetime, stopped_at: datetime | None,
                         now: datetime) -> tuple[str, datetime | None, Any | None, dict[str, Any]]:
    """종료 사유 유도(우선순위 순). 직접 말하는 컬럼이 없어(함정 4) risk_events 로 유도한다.

    반환: (사유, 종료시각, 마지막 EXIT 체결 주문, 근거 detail)."""
    exits = sorted(
        (o for o in orders if o.purpose == "EXIT" and o.status == "FILLED" and o.created_at >= entry_at),
        key=lambda o: o.created_at,
    )
    last_exit = exits[-1] if exits else None
    exit_at = stopped_at if (stopped_at and stopped_at >= entry_at) else (last_exit.updated_at if last_exit else None)
    t_end = (exit_at or now) + timedelta(minutes=10)
    window = [e for e in events if entry_at - timedelta(minutes=1) <= e.created_at <= t_end]

    sl_events = sorted((e for e in window if e.event_type == "FORCE_STOP_LOSS_TRIGGERED"), key=lambda e: e.created_at)
    tp_levels = [
        (e.event_payload or {}).get("level") for e in window
        if e.event_type == "TP_EXECUTION_AUDIT" and e.event_payload
    ]
    manual_tp_count = sum(1 for e in window if e.event_type == "MANUAL_TP")
    has_zombie = any(e.event_type in ("ZOMBIE_GUARDIAN_FORCE_STOP", "STOPPING_STUCK_DETECTED") for e in window)
    reconcile = sorted((e for e in window if e.event_type == "RECONCILE_FLAT_POSITION_CLEANUP"),
                       key=lambda e: e.created_at)
    reconcile_old_status = (reconcile[-1].event_payload or {}).get("old_status") if reconcile else None

    detail: dict[str, Any] = {
        "tp_levels": tp_levels, "manual_tp_count": manual_tp_count,
        "n_exit_fills": len(exits), "reconcile_old_status": reconcile_old_status,
    }
    if sl_events:
        first = sl_events[0]
        payload = first.event_payload or {}
        detail["force_sl_first_at"] = first.created_at.isoformat()
        roi = payload.get("unrealized_roi")
        detail["force_sl_roi"] = float(roi) if roi is not None else None
        detail["force_sl_count"] = len(sl_events)
        detail["force_sl_to_exit_min"] = (
            round((exit_at - first.created_at).total_seconds() / 60, 1) if exit_at else None
        )

    # 우선순위: OPEN > FORCE_SL > MANUAL_TP > TP_COMPLETE > ZOMBIE > (개시자 미기록) 정리 > 외부청산 > 미상
    if status in OPEN_STATUSES:
        reason = "OPEN"
    elif sl_events:
        delay = detail.get("force_sl_to_exit_min")
        reason = "FORCE_SL" if (delay is None or delay <= 30) else "FORCE_SL_DELAYED"
    elif manual_tp_count and status != "COMPLETED":
        reason = "MANUAL_TP"
    elif status == "COMPLETED":
        reason = "TP_COMPLETE"
    elif has_zombie or status == "MANUAL_CLEANUP_REQUIRED":
        reason = "ZOMBIE_MANUAL_CLEANUP"
    elif last_exit is None:
        reason = "EXTERNAL_CLOSE_NO_DB_EXIT" if reconcile else "NO_EXIT_FILL"
    elif reconcile and reconcile_old_status == "STOPPING":
        # 우리 EXIT 체결 + STOPPING 정리 = 정지 개시자(UI 정지/워커)가 risk_events 에 없음
        reason = "STOP_UNLOGGED_TP_PARTIAL" if tp_levels else "STOP_UNLOGGED"
    elif reconcile:
        reason = "EXTERNAL_CLOSE"
    elif tp_levels:
        reason = "TP_PARTIAL_THEN_STOP"
    else:
        reason = "STOP_UNLOGGED"
    return reason, exit_at, last_exit, detail


def classify_family(*, template_name: str | None, strategy_type: str | None,
                     capital_management_mode: str | None) -> str:
    name = template_name or ""
    st = strategy_type or ""
    cmm = capital_management_mode or ""
    if name.startswith("_quick_") or st.startswith("DYNAMIC_"):
        return FAMILY_MANUAL
    if cmm == "stage_ladder":
        return FAMILY_A_LADDER
    if cmm == SPLIT_ENTRY_MODE or st == "pump_split":
        return FAMILY_B_BBSPLIT
    return FAMILY_C_OTHER


def build_episode(instance: Any, orders: Sequence[Any], events: Sequence[Any], *,
                   template_name: str | None, strategy_type: str | None, now: datetime) -> dict[str, Any]:
    """strategy_instance 1행 → 에피소드 1행(가족/진입/종료/유효성). 학습 일지 조인은 별도(호출자)."""
    started_at = instance.started_at or now
    fills = episode_entry_fills(orders, started_at)
    valid = bool(fills)
    if fills:
        first = fills[0]
        entry_at = first.updated_at or first.created_at
        entry_price, notional = weighted_entry_price(fills)
        if entry_price is None:
            entry_price = _to_float(instance.avg_entry_price) or _to_float(instance.start_price)
        entry_src = f"order:{first.client_order_id or ''}"
    else:
        entry_at = started_at
        entry_price = _to_float(instance.avg_entry_price) or _to_float(instance.start_price)
        notional = 0.0
        entry_src = "INVALID:no_entry_fill_in_episode"

    reason, exit_at, last_exit, detail = derive_close_reason(
        status=instance.status, orders=orders, events=events,
        entry_at=entry_at, stopped_at=instance.stopped_at, now=now,
    )
    pnl = float(instance.realized_pnl or 0)
    if reason == "NO_EXIT_FILL" and notional < DUST_NOTIONAL_USDT and abs(pnl) < DUST_PNL_USDT:
        valid = False
        entry_src += "|INVALID:dust_no_exit"

    lev = int(instance.leverage or 1)
    exit_price = _to_float(last_exit.avg_price) if last_exit is not None else None
    win = (pnl > 0) if reason != "OPEN" else None
    price_roi_pct = round(pnl / notional * 100, 4) if notional else None
    margin_roi_pct = round(price_roi_pct * lev, 4) if price_roi_pct is not None else None

    return {
        "id": instance.id, "symbol": instance.symbol, "side": instance.side,
        "family": classify_family(template_name=template_name, strategy_type=strategy_type,
                                   capital_management_mode=instance.capital_management_mode),
        "template_name": template_name, "strategy_type": strategy_type,
        "capital_management_mode": instance.capital_management_mode,
        "status": instance.status, "leverage": lev, "valid_trade": valid,
        "started_at": started_at.isoformat() if started_at else None,
        "entry_at": entry_at.isoformat() if entry_at else None, "entry_price": entry_price,
        "entry_notional_usdt": round(notional, 4), "n_entry_fills": len(fills), "entry_src": entry_src,
        "exit_at": exit_at.isoformat() if exit_at else None, "exit_price": exit_price,
        "close_reason": reason, "close_detail": detail,
        "hold_hours": round((exit_at - entry_at).total_seconds() / 3600, 2) if exit_at else None,
        "realized_pnl": pnl, "win": win,
        "price_roi_pct": price_roi_pct, "margin_roi_pct": margin_roi_pct,
        "_entry_at_dt": entry_at,   # 내부용(학습 일지 조인 키) — 최종 반환 전 제거
    }


def classify_join(cld_row: Any | None, *, any_row_that_day: bool) -> str:
    """(symbol, snap_date) 키로 학습 일지 행을 못 찾았을 때 이유를 구분한다(문서 §2)."""
    if cld_row is None:
        return "NO_SNAPSHOT_THAT_DAY" if not any_row_that_day else "SYMBOL_NOT_IN_UNIVERSE"
    if cld_row.outcome_status != "DONE" or not cld_row.outcome or "peak" not in (cld_row.outcome or {}):
        return "ROW_PENDING_OR_EXPIRED"
    return "JOINED"


def compute_cld_metrics(*, side: str, entry_at: datetime, entry_price: float,
                         snapshot_at: datetime, outcome: Mapping[str, Any],
                         fwd_bars: Sequence[Sequence[float]] | None) -> dict[str, Any]:
    """문서 §3 열 전부 — 라벨(outcome) 대비 실제 진입가의 위치.

    `label_sim_from_entry` 는 app/services/chart_learning.sim 을 그대로 써서 라벨과 같은 잣대로 잰다
    (복제하면 잣대가 갈라져 비교가 무의미해진다)."""
    fwd_start = datetime.fromtimestamp((int(snapshot_at.timestamp()) // _S15) * _S15, tz=timezone.utc)
    entry_hour = (entry_at - fwd_start).total_seconds() / 3600
    k = floor(entry_hour * 4)

    snap_entry = float(outcome["entry_price"])
    peak, trough = outcome["peak"], outcome["trough"]
    peak_price = snap_entry * (1 + peak["pct"] / 100)
    trough_price = snap_entry * (1 + trough["pct"] / 100)
    ref = peak if side == "SHORT" else trough

    if entry_hour < 0:
        timing = "BEFORE_WINDOW"
    elif entry_hour >= 24:
        timing = "AFTER_WINDOW"
    elif k < ref["bar"]:
        timing = "BEFORE"
    elif k == ref["bar"]:
        timing = "AT"
    else:
        timing = "AFTER"

    rules_same = {key: v for key, v in (outcome.get("rules") or {}).items() if RULE_SIDE.get(key) == side}
    fired_before = {key: v["hours"] for key, v in rules_same.items() if v and v["hours"] <= entry_hour}
    fired_after = {key: v["hours"] for key, v in rules_same.items() if v and v["hours"] > entry_hour}

    bar_close = None
    label_sim = None
    if fwd_bars and 0 <= k < len(fwd_bars):
        bar_close = fwd_bars[k][4]
        label_sim = CL.sim(side, entry_price, fwd_bars[k + 1:])

    base = (outcome.get("baseline") or {}).get(side) or []
    slot = k // 12 if 0 <= k < 96 else None

    return {
        "fwd_start_utc": fwd_start.isoformat(),
        "entry_hour": round(entry_hour, 2), "entry_bar": k,
        "entry_bucket": ("<0" if entry_hour < 0 else "0-3h" if entry_hour < 3 else "3-9h" if entry_hour < 9
                         else "9-24h" if entry_hour < 24 else ">=24h"),
        "peak": peak, "trough": trough,
        "entry_vs_snap_pct": round((entry_price / snap_entry - 1) * 100, 4),
        "entry_vs_peak_pct": round((entry_price / peak_price - 1) * 100, 4),
        "entry_vs_trough_pct": round((entry_price / trough_price - 1) * 100, 4),
        "timing_vs_extreme": timing, "extreme_hours": ref["hours"],
        "hours_to_extreme": round(ref["hours"] - entry_hour, 2),
        "bar_close_at_entry": bar_close,
        "entry_vs_bar_close_pct": round((entry_price / bar_close - 1) * 100, 3) if bar_close else None,
        "label_sim_from_entry": label_sim,
        "at_snapshot_same_side": (outcome.get("at_snapshot") or {}).get(side),
        "baseline_same_side": base, "baseline_slot": slot,
        "baseline_slot_roi": base[slot] if slot is not None and slot < len(base) else None,
        "rules_same_side": rules_same, "rules_fired_before_entry": fired_before,
        "rules_fired_after_entry": fired_after, "any_rule_before": bool(fired_before),
    }


def _agg(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    closed = [r for r in rows if r.get("win") is not None]
    n = len(closed)
    w = sum(1 for r in closed if r["win"])
    pnl = [r["realized_pnl"] for r in closed]
    roi = [r["price_roi_pct"] for r in closed if r.get("price_roi_pct") is not None]
    return {
        "n": n, "win": w, "wr": round(100 * w / n, 1) if n else None,
        "pnl_sum": round(sum(pnl), 2) if pnl else 0.0,
        "pnl_avg": round(sum(pnl) / n, 2) if n else None,
        "price_roi_med": round(statistics.median(roi), 3) if roi else None,
    }


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """문서 §4 집계 그대로 — 가족×방향 / 정점·저점 전후 / hours_to_extreme 구간 / entry_bucket.

    다일 집계이므로 호출부에서 Redis 등에 캐시하지 말 것(하루만 지나도 낡는다 — 9/5 교훈)."""
    valid = [r for r in rows if r.get("valid_trade")]
    joined = [r for r in valid if r.get("join") == "JOINED"]
    sides = ("LONG", "SHORT")

    meta = {
        "n_instances": len(rows), "n_valid": len(valid), "n_invalid": len(rows) - len(valid),
        "n_joined": len(joined),
        "join_status": dict(Counter(r.get("join") for r in valid)),
        "close_reason": dict(Counter(r.get("close_reason") for r in valid)),
    }

    fam_side_keys = sorted({(r["family"], r["side"]) for r in valid})
    family_side = {
        f"{fam}/{side}": _agg([r for r in valid if (r["family"], r["side"]) == (fam, side)])
        for fam, side in fam_side_keys
    }

    timing_before_after = {
        side: {t: _agg([r for r in joined if r["side"] == side and r["cld"]["timing_vs_extreme"] == t])
               for t in ("BEFORE", "AFTER")}
        for side in sides
    }

    hours_to_extreme = {
        side: {
            f"[{lo},{hi})": _agg([r for r in joined if r["side"] == side
                                   and lo <= r["cld"]["hours_to_extreme"] < hi])
            for lo, hi in HOURS_TO_EXTREME_BUCKETS
        }
        for side in sides
    }

    entry_bucket = {
        side: {b: _agg([r for r in joined if r["side"] == side and r["cld"]["entry_bucket"] == b])
               for b in ENTRY_BUCKETS}
        for side in sides
    }

    return {
        "meta": meta, "family_side": family_side,
        "timing_before_after": timing_before_after,
        "hours_to_extreme": hours_to_extreme, "entry_bucket": entry_bucket,
    }


def _pct(x: Any) -> str:
    return "—" if x is None else f"{x:.1f}%"


def _num(x: Any) -> str:
    return "—" if x is None else f"{x:+.2f}"


def _cell(a: Mapping[str, Any]) -> str:
    return f"n{a.get('n', 0)} · {_pct(a.get('wr'))} · {_num(a.get('pnl_sum'))}"


def _bucket_table(title: str, data: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> list[str]:
    sides = list(data.keys())
    buckets = list(next(iter(data.values()), {}).keys())
    lines = [f"## {title}", "", "| 구간 | " + " | ".join(sides) + " |", "|---|" + "---|" * len(sides)]
    for b in buckets:
        lines.append(f"| {b} | " + " | ".join(_cell(data[s].get(b, {})) for s in sides) + " |")
    lines.append("")
    return lines


def render_markdown(summary: Mapping[str, Any]) -> str:
    meta = summary.get("meta", {})
    L: list[str] = [
        "# 실매매 × 차트 학습 일지 조인 보고서",
        "",
        f"인스턴스 {meta.get('n_instances')} · 유효 {meta.get('n_valid')} · 무효 {meta.get('n_invalid')} · "
        f"조인 {meta.get('n_joined')} ({meta.get('join_status')})",
        f"종료 사유: {meta.get('close_reason')}",
        "",
        "## 1. 가족×방향 실적 (유효·청산 완료, realized_pnl 기준)",
        "",
        "| 가족/방향 | n | 승 | 승률 | pnl 합 | 건당 |",
        "|---|---|---|---|---|---|",
    ]
    for key, a in summary.get("family_side", {}).items():
        L.append(f"| {key} | {a['n']} | {a['win']} | {_pct(a['wr'])} | {_num(a['pnl_sum'])} | {_num(a['pnl_avg'])} |")
    L.append("")
    L += _bucket_table("2. 정점(저점) 전/후 진입 (조인·유효·청산 완료)", summary.get("timing_before_after", {}))
    L += _bucket_table("3. 극값까지 남은 시간 hours_to_extreme (음수 = 극값이 이미 지남)",
                       summary.get("hours_to_extreme", {}))
    L += _bucket_table("4. 진입 시각 구간 entry_bucket (스냅샷 뒤 몇 시간째)", summary.get("entry_bucket", {}))
    return "\n".join(L)


# ══════════════════════════════════════════════════════════════════════
# DB 조회 — 순수 함수를 실제 데이터에 적용
# ══════════════════════════════════════════════════════════════════════

def build_trade_dataset(db: Session, days: int) -> list[dict[str, Any]]:
    """과거 `days`일 started 인스턴스 → 에피소드 → 학습 일지(chart_learning_days) 조인 행 목록.

    읽기 전용. 매매 실행/판정 코드를 호출하거나 바꾸지 않는다."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    inst_rows = db.execute(
        select(StrategyInstance, StrategyTemplate.name, StrategyTemplate.strategy_type)
        .outerjoin(StrategyTemplate, StrategyTemplate.id == StrategyInstance.strategy_template_id)
        .where(StrategyInstance.started_at >= cutoff)
    ).all()
    if not inst_rows:
        return []
    ids = [inst.id for inst, _, _ in inst_rows]

    orders_by: dict[int, list[Order]] = defaultdict(list)
    for o in db.execute(select(Order).where(Order.strategy_instance_id.in_(ids))).scalars():
        orders_by[o.strategy_instance_id].append(o)

    events_by: dict[int, list[RiskEvent]] = defaultdict(list)
    for e in db.execute(select(RiskEvent).where(RiskEvent.strategy_instance_id.in_(ids))).scalars():
        events_by[e.strategy_instance_id].append(e)

    episodes = [
        build_episode(inst, orders_by.get(inst.id, []), events_by.get(inst.id, []),
                      template_name=tname, strategy_type=stype, now=now)
        for inst, tname, stype in inst_rows
    ]

    snap_dates: set[date] = {
        r["_entry_at_dt"].astimezone(timezone.utc).date() for r in episodes if r["_entry_at_dt"] is not None
    }
    cld_by: dict[tuple[str, str], ChartLearningDay] = {}
    dates_with_rows: Counter[str] = Counter()
    if snap_dates:
        for row in db.execute(
            select(ChartLearningDay).where(ChartLearningDay.snap_date.in_(sorted(snap_dates)))
        ).scalars():
            sd = row.snap_date.isoformat()
            dates_with_rows[sd] += 1
            cld_by[(row.symbol, sd)] = row

    for r in episodes:
        entry_dt = r.pop("_entry_at_dt")
        if entry_dt is None:
            r["join"] = "NO_ENTRY_TIME"
            r["cld"] = None
            continue
        sd = entry_dt.astimezone(timezone.utc).date().isoformat()
        cld_row = cld_by.get((r["symbol"], sd))
        status = classify_join(cld_row, any_row_that_day=dates_with_rows.get(sd, 0) > 0)
        r["join"] = status
        if status in ("NO_SNAPSHOT_THAT_DAY", "SYMBOL_NOT_IN_UNIVERSE"):
            r["cld"] = None
        elif status == "ROW_PENDING_OR_EXPIRED":
            r["cld"] = {"snap_date": sd, "tags": list(cld_row.tags or []), "outcome_status": cld_row.outcome_status}
        elif r["entry_price"] is None or r["entry_price"] <= 0:
            # fail-open: 진입가를 못 구하면 그냥 조인만 안 한다(집계에서 자연히 빠짐) — 알 수 없다고 매매를 막는 게 아니라 분석 행 하나를 건너뛸 뿐이다.
            r["join"] = "ENTRY_PRICE_MISSING"
            r["cld"] = None
        else:
            fwd = (cld_row.klines or {}).get("15m_fwd") if cld_row.klines else None
            metrics = compute_cld_metrics(side=r["side"], entry_at=entry_dt, entry_price=r["entry_price"],
                                          snapshot_at=cld_row.snapshot_at, outcome=cld_row.outcome, fwd_bars=fwd)
            r["cld"] = {
                "snap_date": sd, "source": cld_row.source, "tags": list(cld_row.tags or []),
                "snapshot_at": cld_row.snapshot_at.isoformat(),
                "chg_24h": _to_float(cld_row.chg_24h), "chg_3d": _to_float(cld_row.chg_3d),
                "chg_5d": _to_float(cld_row.chg_5d), "snap_entry_price": cld_row.outcome.get("entry_price"),
                **metrics,
            }
    return episodes
