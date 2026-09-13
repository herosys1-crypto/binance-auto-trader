"""📉 Fix 371b (2026-09-14 사장님) — 손실 원인 학습 기록.

사장님 verbatim: "…가상으로만 매매하고 학습하고 손실이 발행하는 원일을 학습해서 수정할수 있게 기록해서 우리 자동매매에 적용할수 있게 자료를 만들어줘"

청산된 실거래 중 손실마다 **DB 사실만으로** 원인 태그를 붙여 `trade_learning_records.insights["loss_causes"]` 에 남기고(마이그레이션 없음),
기간 집계를 `system_settings.loss_cause_report_last` 와 `GET /trade-learning/loss-causes` 로 낸다. 매매 판정은 하지 않는다.

손익 배분 = **체결 재생** (반박 검증 C 반영 — trade_learning_records.exit_price 는 운영에서 항상 NULL 이고, 부분 익절·10 USDT 잔량 손절이 있어
「수량×(청산가−추가가)」 는 최대 3배 틀린다):
  진입 체결(orders purpose=ENTRY) 을 lot 으로 쌓고, 청산 체결(purpose=EXIT) 마다 열린 lot 을 **보유 비중대로** 줄이며 손익을 lot 에 배분한다
  (선물 평균원가 = 부분 청산해도 평단 불변 → 비례 배분이 맞다). 수수료 제외 · 청산 체결이 모자라면 approx.
  체결 시각 = 주문 updated_at (스트림이 체결을 반영한 시각. LIMIT 은 created_at 이 주문 시각이라 쓰지 않는다).

계획 밖 추가(ENTRY stage_no NULL)의 출처:
  1) client_order_id 접미사 `_ADHOC_AM_`/`_ADHOC_AL_` = 자동 (Fix 371 이후 add_position_now origin=auto)
  2) 그 밖(`_ADHOC_M_`/`_ADHOC_L_` — Fix 371 이전엔 자동·수동 공용) 시장가는 자동 수익 추가 기록(strategy_suggestions pyramid=true)
     시각과 **1대1 최근접** 매칭(창 add_match_sec)
  3) 남은 것: 사람이 모달로 만든 전략(entry_origin manual_modal · legacy_manual · obv_auto 가족)이면 수동, 아니면 **출처 미상**
     (외부 전략·급등 사다리 추가는 추천 기록을 남기지 않는다)
숫자는 THRESHOLDS(「Claude가 정함」), 설정 `loss_cause_thresholds`(JSON) 로 덮는다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

FIX = "Fix371b"
VERSION = 1
S_THRESH = "loss_cause_thresholds"
REPORT_KEY = "loss_cause_report_last"
REPORT_MAX_DAYS = 90

THRESHOLDS: dict[str, float] = {
    "gave_back_roi": 10.0,        # 최고 ROI(레버리지·평단 기준)가 이 이상이었는데 손실 = 이익 반납
    "never_profit_roi": 2.0,      # 최고 ROI 가 이 미만 = 진입 뒤 한 번도 의미 있게 못 감
    "deep_drawdown_roi": -50.0,   # 최저 ROI 가 이 이하 + 강제손절 꺼짐(실효) = 손절 없는 깊은 역행
    "add_match_sec": 600.0,       # 자동 추가 기록 ↔ 계획 밖 시장가 체결 매칭 창(초) — 사이클 트랜잭션 지연 감안
    "surge_chase_pct": 15.0,      # 진입 당시 급등락 변동률(절대값) 같은 방향 진입 = 추격
    "add_primary_share": 0.5,     # 추가분 손실이 전체 손실의 이 비율 이상이면 주원인 = 추가
    "min_loss_usdt": 1.0,         # 이보다 작은 손실(수수료성 본전)은 태깅하지 않는다
}

CAUSES: dict[str, dict[str, str]] = {
    "AUTO_ADD_LOSS": {"label": "자동 수익 추가분이 손실로 뒤집힘",
                      "apply": "자동 수익 추가 재개 전: 가상 추가 lot(paper adds) 결과 확인 · 재개 시 pyramid_after_add_sl_scope=all(추가 뒤 손절 −5) 검토"},
    "UNKNOWN_ADD_LOSS": {"label": "계획 밖 추가분이 손실 (출처 미상 — 자동 워커 추정)",
                         "apply": "외부 전략·급등 사다리 추가 경로 확인 (Fix 371 이후 주문 접미사 ADHOC_AM 으로 구분됨)"},
    "MANUAL_ADD_PROFIT_ZONE_LOSS": {"label": "수동 💉 이익 구간 추가분이 손실",
                                    "apply": "manual_add_after_sl_enabled=1 (대기열 2① — 시장가·이익 구간 추가 뒤 손절)"},
    "MANUAL_AVG_DOWN_LOSS": {"label": "수동 💉 물타기(손실 구간 추가)분이 손실",
                             "apply": "사람 규율 — 손실 구간 추가 금액·횟수 한도를 정해 두기"},
    "ADD_UNATTRIBUTED": {"label": "계획 밖 추가가 있었으나 청산 체결 기록이 없어 금액 미계산",
                         "apply": "청산 체결 누락 확인 (user-stream 놓침 · reconcile 정리)"},
    "LADDER_AVERAGING_LOSS": {"label": "계획 단계 2개 이상 체결 뒤 손실 (물타기 사다리)",
                              "apply": "stage_trim_before_next_enabled(단계 전 정리) · 단계 간격 재검토"},
    "GAVE_BACK_PROFIT": {"label": "최고 ROI 가 크게 갔다가 손실로 끝남 (이익 반납)",
                         "apply": "가상 엔진 청산 변형(이익 보호 · Fix 370) 결과로 TP1 전 보호선 검토"},
    "NEVER_IN_PROFIT": {"label": "진입 뒤 의미 있는 이익 구간이 없었음 (진입 자리 문제)",
                        "apply": "진입 규칙 — 가상매매 보고서 규칙별 Δ·CV 4조각으로 자리 재검증"},
    "DEEP_DRAWDOWN_NO_STOP": {"label": "강제손절 없이 ROI −50 이하까지 역행",
                              "apply": "legacy_ladder_force_sl_enabled (기존 방식 손절) 여부 결정"},
    "STOP_LOSS_HIT": {"label": "손절 발동으로 종료", "apply": "손절 깊이 — 가상 손절 변형 비교"},
    "EXTERNAL_CLOSE": {"label": "시스템 밖에서 닫힘 (거래소 강제청산·사람 거래소 앱 청산 가능)",
                       "apply": "증거금·레버리지·130% 가드 · 거래소 거래 내역 대조"},
    "SURGE_CHASE_ENTRY": {"label": "급등락 이벤트 같은 방향으로 추격 진입",
                          "apply": "급등 막바지 판정 — chg24 진입 게이트(Fix 310) · 정점 판정 재검증"},
    "ROI_RECORD_MISSING": {"label": "최고·최저 ROI 기록 없음 (평가 결손)", "apply": "risk_service 평가 누락 확인"},
    "CLOSE_REASON_UNKNOWN": {"label": "청산 사유가 정리 이벤트뿐 (체결 놓침 흔적)", "apply": "user-stream 체결 누락 확인"},
    "UNCLASSIFIED": {"label": "태그 없음 (자료 부족)", "apply": "기록 결손 확인 — entry_context · max_profit_pct · 체결"},
}
ADD_CODES = ("AUTO_ADD_LOSS", "UNKNOWN_ADD_LOSS", "MANUAL_ADD_PROFIT_ZONE_LOSS", "MANUAL_AVG_DOWN_LOSS")
PRIORITY = ("DEEP_DRAWDOWN_NO_STOP", "GAVE_BACK_PROFIT", "LADDER_AVERAGING_LOSS", "SURGE_CHASE_ENTRY",
            "NEVER_IN_PROFIT", "STOP_LOSS_HIT", "EXTERNAL_CLOSE")
SL_REASONS = frozenset({"FORCE_SL", "SL"})
CLEANUP_REASONS = frozenset({"FLAT_CLEANUP", "STOPPING_CLEANUP", "ZOMBIE_FORCE_STOP", "CLOSED_UNKNOWN", "UNKNOWN"})
AUTO_SUFFIXES = ("_ADHOC_AM_", "_ADHOC_AL_")
MANUAL_FAMILIES = frozenset({"legacy_manual", "obv_auto"})


def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _dir(side: Any) -> int:
    return -1 if str(side or "").upper() == "SHORT" else 1


def thresholds(db: Any = None) -> dict[str, float]:
    th = dict(THRESHOLDS)
    if db is None:
        return th
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, S_THRESH)
        raw = json.loads(str(row.value)) if row is not None and row.value not in (None, "") else {}
        for k, v in (raw or {}).items():
            if k in th and _f(v) is not None:
                th[k] = float(v)
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] %s 읽기 실패 → 기본값: %s", FIX, S_THRESH, e)
    return th


def mark_entry_origins(entries: Sequence[Mapping[str, Any]], auto_add_times: Sequence[datetime], *,
                       match_sec: float, manual_strategy: bool) -> list[dict[str, Any]]:
    """진입 체결마다 origin = plan | auto_add | manual_add | unknown_add. 자동 추가 기록은 체결 하나에만 1대1 로 쓴다."""
    out = [dict(e) for e in sorted(entries, key=lambda x: x["t"])]
    free: list[datetime] = sorted(auto_add_times)

    def _take_nearest(t: datetime) -> bool:
        if not free:
            return False
        j = min(range(len(free)), key=lambda k: abs((free[k] - t).total_seconds()))
        if abs((free[j] - t).total_seconds()) > match_sec:
            return False
        free.pop(j)
        return True

    pending = []
    for e in out:
        cid = str(e.get("client_order_id") or "")
        if e.get("stage_no") is not None:
            e["origin"] = "plan"
        elif any(s in cid for s in AUTO_SUFFIXES):
            e["origin"] = "auto_add"
            _take_nearest(e["t"])                      # 접미사로 확정된 자동 추가가 기록을 먼저 소비한다
        else:
            pending.append(e)
    for e in pending:
        if str(e.get("order_type") or "").upper() == "MARKET" and _take_nearest(e["t"]):
            e["origin"] = "auto_add"
        else:
            e["origin"] = "manual_add" if manual_strategy else "unknown_add"
    return out


def replay(side: Any, entries: Sequence[Mapping[str, Any]], exits: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """체결 재생 — lot 별 실현손익(수수료 제외). 같은 시각이면 진입 먼저."""
    d = _dir(side)
    ev = [(e["t"], 0, e) for e in entries] + [(x["t"], 1, x) for x in exits]
    ev.sort(key=lambda z: (z[0], z[1]))
    lots: list[dict[str, Any]] = []
    exit_n = 0
    for _t, kind, e in ev:
        q, px = _f(e.get("qty")), _f(e.get("price"))
        if not q or not px or q <= 0 or px <= 0:
            continue
        open_qty = sum(l["open"] for l in lots)
        if kind == 0:
            avg = sum(l["open"] * l["px"] for l in lots) / open_qty if open_qty > 0 else None
            move = (px - avg) / avg * 100 * d if avg else None
            lots.append({"origin": e.get("origin", "plan"), "px": px, "qty": q, "open": q, "pnl": 0.0,
                         "move_pct": move, "approx": bool(e.get("approx_price"))})
        else:
            exit_n += 1
            if open_qty <= 0:
                continue
            ratio = min(q, open_qty) / open_qty
            for l in lots:
                r = l["open"] * ratio
                l["pnl"] += r * (px - l["px"]) * d
                l["open"] -= r
    total_qty = sum(l["qty"] for l in lots)
    left = sum(l["open"] for l in lots)
    return {"lots": lots, "exit_n": exit_n, "open_left_qty": left,
            "closed_ratio": (1 - left / total_qty) if total_qty > 0 else 0.0,
            "pnl_gross": sum(l["pnl"] for l in lots)}


def _tag(code: str, usdt: float | None, detail: str) -> dict[str, Any]:
    return {"code": code, "label": CAUSES[code]["label"], "usdt": None if usdt is None else round(usdt, 4), "detail": detail}


def classify(facts: Mapping[str, Any], th: Mapping[str, float] | None = None) -> dict[str, Any]:
    """순수 함수 — 손실 거래 한 건의 원인 태그. 손실이 min_loss_usdt 미만이면 tags=[]."""
    th = {**THRESHOLDS, **(th or {})}
    pnl = _f(facts.get("pnl_usdt"))
    out: dict[str, Any] = {"v": VERSION, "pnl_usdt": pnl, "tags": [], "primary": None, "add_loss_usdt": None,
                           "pnl_gross_replay": None, "closed_ratio": None, "family": facts.get("family"),
                           "entry_origin": facts.get("entry_origin"), "approx": True}
    if pnl is None or pnl > -th["min_loss_usdt"]:
        return out
    side = facts.get("side")
    rp = replay(side, facts.get("entries") or [], facts.get("exits") or [])
    out["pnl_gross_replay"] = round(rp["pnl_gross"], 4)
    out["closed_ratio"] = round(rp["closed_ratio"], 4)
    tags: list[dict[str, Any]] = []

    add_lots = [l for l in rp["lots"] if l["origin"] != "plan"]
    attributable = rp["exit_n"] > 0
    add_sum: dict[str, float] = {}
    add_det: dict[str, list[str]] = {}
    for l in add_lots:
        if l["origin"] == "auto_add":
            code = "AUTO_ADD_LOSS"
        elif l["origin"] == "unknown_add":
            code = "UNKNOWN_ADD_LOSS"
        else:
            code = "MANUAL_ADD_PROFIT_ZONE_LOSS" if (l["move_pct"] or 0.0) >= 0 else "MANUAL_AVG_DOWN_LOSS"
        add_sum[code] = add_sum.get(code, 0.0) + l["pnl"]
        add_det.setdefault(code, []).append(f"{l['px']:g}" + (f"({l['move_pct']:+.1f}%)" if l["move_pct"] is not None else ""))
    total_add = None
    if add_lots and attributable:
        total_add = sum(add_sum.values())
        for code in ADD_CODES:
            if code in add_sum and add_sum[code] < 0:
                tags.append(_tag(code, add_sum[code], f"추가 @ {', '.join(add_det[code])} → 청산 체결 재생 배분 {add_sum[code]:+.2f} USDT"
                                 + ("" if rp["closed_ratio"] > 0.999 else f" (청산 체결 {rp['closed_ratio']*100:.0f}%만 기록)")))
    elif add_lots:
        tags.append(_tag("ADD_UNATTRIBUTED", None, f"계획 밖 추가 {len(add_lots)}건 · 청산 체결 기록 없음"))
    out["add_loss_usdt"] = None if total_add is None else round(total_add, 4)

    plan_n = sum(1 for l in rp["lots"] if l["origin"] == "plan")
    if plan_n >= 2:
        tags.append(_tag("LADDER_AVERAGING_LOSS", None, f"계획 단계 체결 {plan_n}건"))
    mp, ml = _f(facts.get("max_profit_roi")), _f(facts.get("max_loss_roi"))
    if mp is None and ml is None:
        tags.append(_tag("ROI_RECORD_MISSING", None, "max_profit_pct·max_loss_pct 둘 다 없음"))
    elif mp is not None and mp >= th["gave_back_roi"]:
        tags.append(_tag("GAVE_BACK_PROFIT", None, f"최고 ROI +{mp:.1f}% 뒤 손실"))
    elif (mp is None or mp < th["never_profit_roi"]) and not add_lots:
        # 추가(reset) 는 max_profit_pct 를 지우므로 추가가 있던 거래엔 붙이지 않는다
        tags.append(_tag("NEVER_IN_PROFIT", None, "이익 구간 기록 없음" if mp is None else f"최고 ROI +{mp:.1f}%"))
    if ml is not None and ml <= th["deep_drawdown_roi"] and facts.get("force_sl_enabled") is False:
        tags.append(_tag("DEEP_DRAWDOWN_NO_STOP", None, f"최저 ROI {ml:.1f}% · 강제손절 꺼짐(태깅 시점 실효값)"))
    reason = str(facts.get("close_reason") or "").upper()
    if reason in SL_REASONS:
        tags.append(_tag("STOP_LOSS_HIT", None, f"청산 사유 {reason}"))
    elif reason == "EXTERNAL_CLOSE":
        tags.append(_tag("EXTERNAL_CLOSE", None, "reconcile 고아 정리 (시스템 밖 청산)"))
    elif reason in CLEANUP_REASONS:
        tags.append(_tag("CLOSE_REASON_UNKNOWN", None, f"청산 사유 {reason}"))
    ctx = facts.get("entry_ctx") if isinstance(facts.get("entry_ctx"), Mapping) else {}
    pd = ctx.get("pump_dump") if isinstance(ctx.get("pump_dump"), Mapping) else {}
    ch = _f(pd.get("change_pct"))
    if ch is not None and abs(ch) >= th["surge_chase_pct"] and ch * _dir(side) > 0:
        tags.append(_tag("SURGE_CHASE_ENTRY", None, f"진입 당시 급등락 {ch:+.1f}% ({pd.get('tf')}·{pd.get('window')}) 같은 방향"))

    present = {t["code"] for t in tags}
    add_tags = sorted((t for t in tags if t["code"] in ADD_CODES), key=lambda t: t["usdt"] or 0.0)
    if add_tags and total_add is not None and total_add <= th["add_primary_share"] * pnl:
        out["primary"] = add_tags[0]["code"]
    elif "ADD_UNATTRIBUTED" in present:
        out["primary"] = "ADD_UNATTRIBUTED"
    else:
        out["primary"] = next((c for c in PRIORITY if c in present), add_tags[0]["code"] if add_tags else None)
    if out["primary"] is None:
        tags.append(_tag("UNCLASSIFIED", None, "주원인으로 쓸 사실이 없음"))
        out["primary"] = "UNCLASSIFIED"
    out["tags"] = tags
    out["approx"] = bool(rp["closed_ratio"] < 0.999 or any(l["approx"] for l in rp["lots"]))
    return out


# ── DB ──────────────────────────────────────────────────────────────────
def scan_stmt(*, version: int, min_loss: float, limit: int):
    """아직 이 버전으로 태깅되지 않은 손실 기록 — 필요한 컬럼만 (progression 등 큰 JSONB 제외)."""
    from sqlalchemy import func, or_, select
    from app.models.trade_learning_record import TradeLearningRecord as TLR
    return (
        select(TLR.id, TLR.strategy_instance_id, TLR.pnl_usdt, TLR.max_profit_pct, TLR.max_loss_pct, TLR.close_reason,
               TLR.entry_context["pump_dump"].label("pump_dump"))
        .where(TLR.status == "CLOSED", TLR.pnl_usdt < -min_loss,
               or_(TLR.insights.is_(None), func.coalesce(TLR.insights["loss_causes"]["v"].astext, "") != str(version)))
        .order_by(TLR.id.desc()).limit(limit)
    )


def save_stmt(record_id: int, result: Mapping[str, Any]):
    """insights 의 loss_causes 키만 바꾼다 (다른 키를 읽어 오지 않는다)."""
    from sqlalchemy import cast, func, literal, literal_column, update
    from sqlalchemy.dialects.postgresql import JSONB
    from app.models.trade_learning_record import TradeLearningRecord as TLR
    payload = json.dumps(result, ensure_ascii=False, default=str)
    return (
        update(TLR).where(TLR.id == record_id)
        .values(insights=func.jsonb_set(func.coalesce(TLR.insights, cast(literal("{}"), JSONB)),
                                        literal_column("'{loss_causes}'"), cast(literal(payload), JSONB)))
    )


def report_stmt(*, version: int, cutoff: datetime):
    from sqlalchemy import select
    from app.models.trade_learning_record import TradeLearningRecord as TLR
    return (
        select(TLR.strategy_instance_id, TLR.symbol, TLR.side, TLR.exit_time, TLR.insights["loss_causes"].label("lc"))
        .where(TLR.status == "CLOSED", TLR.pnl_usdt < 0, TLR.exit_time >= cutoff,
               TLR.insights["loss_causes"]["v"].astext == str(version))
    )


def gather_facts(db: Any, si: Any, rec: Mapping[str, Any], th: Mapping[str, float] | None = None) -> dict[str, Any]:
    """rec = scan_stmt 한 행(dict). 체결·추천 기록·가족·강제손절 실효값을 모은다."""
    from sqlalchemy import select
    from app.models.order import Order
    from app.models.strategy_suggestion import StrategySuggestion
    from app.services.strategy_family import family_of
    th = {**THRESHOLDS, **(th or {})}
    rows = db.execute(
        select(Order.purpose, Order.stage_no, Order.order_type, Order.client_order_id, Order.executed_qty,
               Order.avg_price, Order.price, Order.created_at, Order.updated_at)
        .where(Order.strategy_instance_id == si.id, Order.executed_qty > 0, Order.purpose.in_(("ENTRY", "EXIT")))
    ).all()
    entries, exits = [], []
    for purpose, stage_no, otype, cid, qty, avg_px, px, created, updated in rows:
        ev = {"t": updated or created, "qty": qty, "price": avg_px if _f(avg_px) else px, "approx_price": not _f(avg_px),
              "stage_no": stage_no, "order_type": otype, "client_order_id": cid}
        (entries if purpose == "ENTRY" else exits).append(ev)
    sugg = db.execute(
        select(StrategySuggestion.executed_at, StrategySuggestion.strategy_config)
        .where(StrategySuggestion.executed_strategy_id == si.id)
    ).all()
    auto_times = [at for at, cfg in sugg if at is not None and isinstance(cfg, dict) and cfg.get("pyramid") is True]
    family = family_of(si)
    manual = str(getattr(si, "entry_origin", None) or "") == "manual_modal" or family in MANUAL_FAMILIES
    force_sl = getattr(si, "force_sl_enabled_override", None)
    if force_sl is None:
        try:
            from app.services.system_settings_service import SystemSettingsService
            force_sl = bool(SystemSettingsService(db).get_force_sl(str(si.side or "").upper())[0])
        except Exception as e:  # noqa: BLE001
            logger.debug("[%s] #%s 전역 강제손절 조회 실패: %s", FIX, si.id, e)
    return {
        "id": si.id, "symbol": si.symbol, "side": si.side, "family": family, "entry_origin": getattr(si, "entry_origin", None),
        "force_sl_enabled": force_sl, "pnl_usdt": rec.get("pnl_usdt"), "close_reason": rec.get("close_reason"),
        "max_profit_roi": rec.get("max_profit_pct"), "max_loss_roi": rec.get("max_loss_pct"),
        "entry_ctx": {"pump_dump": rec.get("pump_dump") or {}},
        "entries": mark_entry_origins(entries, auto_times, match_sec=th["add_match_sec"], manual_strategy=manual),
        "exits": exits,
    }


def aggregate(items: Iterable[Mapping[str, Any]], *, days: int) -> dict[str, Any]:
    """items = {"id","symbol","side","exit_time"(iso|None),"result"(classify 결과)}."""
    by_code: dict[str, dict[str, Any]] = {}
    by_family: dict[str, dict[str, Any]] = {}
    rows = [it for it in items if (it.get("result") or {}).get("tags")]
    total = 0.0
    for it in rows:
        r = it["result"]
        pnl = float(r.get("pnl_usdt") or 0.0)
        total += pnl
        bf = by_family.setdefault(str(r.get("family") or "unknown"), {"n": 0, "pnl_usdt": 0.0})
        bf["n"] += 1
        bf["pnl_usdt"] += pnl
        for t in r["tags"]:
            c = t["code"]
            b = by_code.setdefault(c, {"label": CAUSES.get(c, {}).get("label", c), "apply": CAUSES.get(c, {}).get("apply", ""),
                                       "n": 0, "pnl_usdt": 0.0, "attributed_usdt": 0.0, "primary_n": 0, "primary_pnl_usdt": 0.0})
            b["n"] += 1
            b["pnl_usdt"] += pnl
            b["attributed_usdt"] += float(t.get("usdt") or 0.0)
            if r.get("primary") == c:
                b["primary_n"] += 1
                b["primary_pnl_usdt"] += pnl
    for b in list(by_code.values()) + list(by_family.values()):
        for k in ("pnl_usdt", "attributed_usdt", "primary_pnl_usdt"):
            if k in b:
                b[k] = round(b[k], 2)
    worst = sorted(rows, key=lambda it: float(it["result"].get("pnl_usdt") or 0.0))[:10]
    return {
        "fix": FIX, "v": VERSION, "generated_at": datetime.now(timezone.utc).isoformat(), "days": days,
        "n_loss": len(rows), "loss_usdt": round(total, 2), "approx": True,
        "by_code": by_code, "by_family": by_family,
        "actions": sorted(({"code": c, **b} for c, b in by_code.items()), key=lambda b: b["primary_pnl_usdt"]),
        "worst": [{"id": it["id"], "symbol": it["symbol"], "side": it["side"], "exit_time": it.get("exit_time"),
                   "pnl_usdt": it["result"].get("pnl_usdt"), "primary": it["result"].get("primary"),
                   "add_loss_usdt": it["result"].get("add_loss_usdt"),
                   "tags": [t["code"] for t in it["result"]["tags"]]} for it in worst],
    }


def build_report(db: Any, *, days: int = 30) -> dict[str, Any]:
    days = max(1, min(int(days or 30), REPORT_MAX_DAYS))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    items = [{"id": sid, "symbol": sym, "side": side, "exit_time": et.isoformat() if et else None, "result": lc}
             for sid, sym, side, et, lc in db.execute(report_stmt(version=VERSION, cutoff=cutoff)).all()
             if isinstance(lc, dict)]
    return aggregate(items, days=days)


def render_markdown(rep: Mapping[str, Any]) -> str:
    lines = [f"# 📉 손실 원인 보고서 (최근 {rep.get('days')}일 · {str(rep.get('generated_at', ''))[:16]} UTC)", "",
             f"- 손실 거래 {rep.get('n_loss')}건 · 합계 {rep.get('loss_usdt')} USDT",
             "- 추가분 금액 = 진입·청산 체결 재생 배분 (수수료 제외 근사)", "",
             "## 주원인별 (손실 큰 순) → 먼저 검증할 것", "",
             "| 원인 | 주원인 건수 | 주원인 손실 | 태그 건수 | 추가분 배분 | 먼저 검증할 것 |", "|---|---:|---:|---:|---:|---|"]
    for a in rep.get("actions") or []:
        lines.append(f"| {a['label']} (`{a['code']}`) | {a['primary_n']} | {a['primary_pnl_usdt']} | {a['n']} | "
                     f"{a['attributed_usdt'] if a['attributed_usdt'] else ''} | {a['apply']} |")
    lines += ["", "## 가족별", "", "| 가족 | 건수 | 손실 |", "|---|---:|---:|"]
    for fam, b in sorted((rep.get("by_family") or {}).items(), key=lambda kv: kv[1]["pnl_usdt"]):
        lines.append(f"| {fam} | {b['n']} | {b['pnl_usdt']} |")
    lines += ["", "## 손실 큰 거래", "", "| # | 심볼 | 방향 | 손실 | 추가분 | 주원인 | 태그 |", "|---|---|---|---:|---:|---|---|"]
    for w in rep.get("worst") or []:
        lines.append(f"| {w['id']} | {w['symbol']} | {w['side']} | {w['pnl_usdt']} | {w['add_loss_usdt']} | {w['primary']} | {', '.join(w['tags'])} |")
    return "\n".join(lines) + "\n"
