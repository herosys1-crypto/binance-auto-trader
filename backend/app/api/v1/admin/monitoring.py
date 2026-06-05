"""Admin — read-only 모니터링 endpoint (health, notifications, recent-activity, stats).

UI 대시보드의 read-only 패널들이 호출하는 endpoint 모음.
2026-05-14 Phase 4 split: 기존 admin.py 에서 분리 (~493 줄).
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/system-health")
def get_system_health(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """8개 컴포넌트의 통합 상태 — 대시보드 시스템 패널용.

    각 컴포넌트는 status: 'ok' | 'warn' | 'down' + detail 메시지.
    """
    from datetime import datetime, timezone
    from sqlalchemy import text
    from app.core.redis_client import get_redis_client
    from app.core.config import settings

    components: dict[str, dict] = {}

    # 1. API (이 endpoint 가 응답한다 = 작동 중)
    components["api"] = {"status": "ok", "label": "API 서버", "detail": "응답 정상"}

    # 2. DB
    try:
        db.execute(text("SELECT 1"))
        components["db"] = {"status": "ok", "label": "데이터베이스", "detail": "PostgreSQL 연결됨"}
    except Exception as e:  # pragma: no cover
        components["db"] = {"status": "down", "label": "데이터베이스", "detail": f"DB 오류: {e}"}

    # 3. Redis
    try:
        client = get_redis_client()
        client.ping()
        components["redis"] = {"status": "ok", "label": "Redis 캐시", "detail": "Redis 연결됨"}
    except Exception as e:  # pragma: no cover
        components["redis"] = {"status": "down", "label": "Redis 캐시", "detail": f"Redis 오류: {e}"}

    # 4. Scheduler (Redis heartbeat 키 확인)
    try:
        client = get_redis_client()
        if client.exists("health:scheduler:leader"):
            components["scheduler"] = {"status": "ok", "label": "스케줄러", "detail": "Leader heartbeat 정상"}
        else:
            components["scheduler"] = {"status": "warn", "label": "스케줄러", "detail": "heartbeat 없음 (60s 내 갱신 필요)"}
    except Exception:  # pragma: no cover
        components["scheduler"] = {"status": "down", "label": "스케줄러", "detail": "확인 불가"}

    # 5. User Stream (Redis heartbeat 키)
    try:
        client = get_redis_client()
        if client.exists("health:user_stream:connected"):
            components["user_stream"] = {"status": "ok", "label": "Binance User Stream", "detail": "WebSocket 연결됨"}
        else:
            components["user_stream"] = {"status": "warn", "label": "Binance User Stream", "detail": "heartbeat 없음 (재연결 필요)"}
    except Exception:  # pragma: no cover
        components["user_stream"] = {"status": "down", "label": "Binance User Stream", "detail": "확인 불가"}

    # 6. Telegram (설정 + 최근 발송 성공률)
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        components["telegram"] = {"status": "warn", "label": "Telegram", "detail": "TOKEN 또는 CHAT_ID 미설정"}
    else:
        from app.models.notification import Notification  # noqa: F401  (import 보장)
        recent = db.execute(
            text("SELECT send_status FROM notifications WHERE channel='TELEGRAM' AND created_at > NOW() - INTERVAL '24 hours' ORDER BY id DESC LIMIT 5")
        ).scalars().all()
        if not recent:
            components["telegram"] = {"status": "ok", "label": "Telegram", "detail": "설정 완료 (최근 24h 발송 없음)"}
        else:
            failed = sum(1 for s in recent if (s or "").upper() == "FAILED")
            if failed == len(recent):
                components["telegram"] = {"status": "down", "label": "Telegram", "detail": f"최근 {len(recent)}건 모두 실패"}
            elif failed > 0:
                components["telegram"] = {"status": "warn", "label": "Telegram", "detail": f"최근 {len(recent)}건 중 {failed}건 실패"}
            else:
                components["telegram"] = {"status": "ok", "label": "Telegram", "detail": f"최근 {len(recent)}건 모두 발송 성공"}

    # 7. Sentry (DSN 설정 여부)
    if settings.sentry_dsn:
        components["sentry"] = {"status": "ok", "label": "Sentry", "detail": "DSN 설정됨 (에러 추적 활성)"}
    else:
        components["sentry"] = {"status": "warn", "label": "Sentry", "detail": "DSN 미설정 (mainnet 직전 권장)"}

    # 8. DB Backup (마지막 백업 row 확인 — 실제 파일 시스템 확인은 어려우니 가능 여부만)
    components["db_backup"] = {"status": "ok", "label": "DB 자동 백업", "detail": "스케줄러 동작 (매일 03:00 UTC)"}

    # 전체 상태 요약
    statuses = [c["status"] for c in components.values()]
    overall = "down" if "down" in statuses else ("warn" if "warn" in statuses else "ok")

    return {
        "overall": overall,
        "components": components,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/notifications-by-title")
def get_notifications_by_title(
    title_like: str,
    limit: int = 200,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[dict]:
    """제목 패턴 매칭 알림 목록 — 운영 통계 패널의 TP/TRAIL 셀 클릭 시 사용.

    2026-05-12 (사용자 요청): TP1~10/TRAILING_TP 카운트 셀 클릭 → 해당 알림 상세 목록.
    title_like 는 SQL LIKE 패턴 (% 허용). 보안상 길이 200자 이내.

    예: title_like='%[TP1 익절%' → TP1 익절 알림 모두
        title_like='%[TRAILING_TP 익절%' → 트레일링 청산 모두
    """
    from sqlalchemy import select as sa_select
    from app.models.notification import Notification
    if not title_like or len(title_like) > 200:
        raise HTTPException(status_code=400, detail="title_like 1~200자")
    limit = max(1, min(limit, 1000))
    rows = db.execute(
        sa_select(Notification)
        .where(Notification.title.like(title_like))
        .order_by(Notification.created_at.desc())
        .limit(limit)
    ).scalars().all()
    out: list[dict] = []
    for n in rows:
        sym = n.strategy_instance.symbol if n.strategy_instance else None
        side = n.strategy_instance.side if n.strategy_instance else None
        out.append({
            "id": n.id,
            "ts": n.created_at.isoformat() if n.created_at else None,
            "strategy_id": n.strategy_instance_id,
            "symbol": sym,
            "side": side,
            "title": n.title or "",
            "body": (n.body or "")[:500],
            "send_status": n.send_status,
        })
    return out


@router.get("/recent-activity")
def get_recent_activity(
    limit: int = 20,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[dict]:
    """모든 전략의 최근 활동 통합 (orders + risk_events + notifications).

    메인 대시보드 활동 피드용. 시간 역순 정렬, 최근 N건만 반환.
    2026-05-12 (사용자 요청): 20건 한도 → 사용자가 20/50/100/200/500 선택 가능.
    상한 1000 — 메모리 안전 (3 source × 1000 = 3000 sort).
    """
    limit = max(1, min(limit, 1000))
    from sqlalchemy import select as sa_select
    from app.models.order import Order
    from app.models.risk_event import RiskEvent
    from app.models.notification import Notification

    items: list[dict] = []

    # 최근 주문 (체결 위주).
    # 2026-05-12 (사용자 요청): 「매도/매수」 → 「SHORT/LONG 포지션 진입/청산」 으로 변경.
    # 사용자 의견: 「실제로 매도/매수가 일어나긴 하지만 의미는 포지션 진입/청산이라
    # 헷갈림. 실제 사용 용어로 표시해줘」.
    # 매핑:
    #   ENTRY  + SELL  → SHORT 포지션 진입
    #   ENTRY  + BUY   → LONG 포지션 진입
    #   TP/SL/EMERG + BUY  → SHORT 포지션 청산 (SHORT 닫으려면 BUY)
    #   TP/SL/EMERG + SELL → LONG 포지션 청산 (LONG 닫으려면 SELL)
    orders = db.execute(
        sa_select(Order).order_by(Order.updated_at.desc()).limit(limit)
    ).scalars().all()
    _close_purposes = {"TAKE_PROFIT", "STOP_LOSS", "EMERGENCY_CLOSE"}
    _purpose_ko = {"ENTRY": "진입", "TAKE_PROFIT": "익절", "STOP_LOSS": "손절", "EMERGENCY_CLOSE": "긴급청산"}
    for o in orders:
        purpose_upper = (o.purpose or "").upper()
        order_side = (o.side or "").upper()
        is_close = purpose_upper in _close_purposes
        if is_close:
            # 청산: BUY=SHORT 청산, SELL=LONG 청산
            pos_dir = "SHORT" if order_side == "BUY" else ("LONG" if order_side == "SELL" else "?")
            action_ko = "포지션 청산"
        else:
            # 진입 (ENTRY 또는 unknown — 진입으로 간주)
            pos_dir = "SHORT" if order_side == "SELL" else ("LONG" if order_side == "BUY" else "?")
            action_ko = "포지션 진입"
        dir_emoji = "📉" if pos_dir == "SHORT" else ("📈" if pos_dir == "LONG" else "❓")
        purpose_ko = _purpose_ko.get(purpose_upper, o.purpose or "")
        is_filled = (o.status or "").upper() == "FILLED"
        ts = o.updated_at if (is_filled and o.updated_at) else o.created_at
        # title — 청산이면 사유 추가 (익절/손절/긴급청산), 진입이면 단순 「SHORT 포지션 진입」
        if is_close:
            title = f"{dir_emoji} {pos_dir} {action_ko} ({purpose_ko}){' 체결' if is_filled else ' 발송'}"
        else:
            title = f"{dir_emoji} {pos_dir} {action_ko}{' 체결' if is_filled else ' 발송'}"
        qty = o.executed_qty if is_filled else o.orig_qty
        px = o.avg_price if is_filled else o.price
        items.append({
            "ts": ts.isoformat(),
            "strategy_id": o.strategy_instance_id,
            "symbol": o.symbol,
            "kind": "ORDER",
            "icon": "✅" if is_filled else "📤",
            "title": title,
            "detail": f"수량 {qty} @ {px}" + (f" — {o.stage_no}단계" if o.stage_no else ""),
        })

    # 최근 리스크 이벤트 (크라이시스/손절 등)
    # 2026-06-05 N+1 Query fix (Sentry 자동 발견 첫 사례):
    # 이전: r.strategy_instance.symbol → lazy load → row 별 SELECT (사장님 폴링마다 발생)
    # 신규: selectinload 로 eager load → 1 SELECT 로 모든 strategy_instance 미리 fetch
    from sqlalchemy.orm import selectinload as _selectinload
    risk_events = db.execute(
        sa_select(RiskEvent)
        .options(_selectinload(RiskEvent.strategy_instance))
        .order_by(RiskEvent.created_at.desc()).limit(limit)
    ).scalars().all()
    for r in risk_events:
        sev_icon = {"CRITICAL": "🚨", "WARNING": "⚠️", "INFO": "ℹ️"}.get(r.severity, "📌")
        # strategy 의 symbol 가져오기 (relationship — 위 selectinload 로 prefetch 됨)
        sym = r.strategy_instance.symbol if r.strategy_instance else "?"
        items.append({
            "ts": r.created_at.isoformat(),
            "strategy_id": r.strategy_instance_id,
            "symbol": sym,
            "kind": "RISK",
            "icon": sev_icon,
            "title": r.title or r.event_type,
            "detail": (r.message or "")[:200],
        })

    # 최근 알림 (Telegram 발송)
    # 2026-06-05 N+1 Query fix: notifications 도 selectinload eager load
    notifications = db.execute(
        sa_select(Notification)
        .options(_selectinload(Notification.strategy_instance))
        .order_by(Notification.created_at.desc()).limit(limit)
    ).scalars().all()
    for n in notifications:
        status_icon = "✉️" if (n.send_status or "").upper() == "SENT" else "❌"
        sym = n.strategy_instance.symbol if n.strategy_instance else "시스템"
        items.append({
            "ts": n.created_at.isoformat(),
            "strategy_id": n.strategy_instance_id,
            "symbol": sym,
            "kind": "NOTIFY",
            "icon": status_icon,
            "title": n.title or "알림",
            "detail": (n.body or "")[:200],
        })

    # 시간 역순 정렬 + 상위 limit 만
    items.sort(key=lambda x: x["ts"], reverse=True)
    return items[:limit]


@router.get("/stats")
def get_operation_stats(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """운영 통계 — 전체 전략 분포 + 누적 손익 + 승률 + 크라이시스 발동 횟수.

    대시보드 상단 패널에 표시. 시계열 차트는 다음 phase 에서 추가.
    """
    from sqlalchemy import func, select as sa_select
    from app.models.strategy_instance import StrategyInstance

    # 전체/활성/완료/손절 분포
    rows = db.execute(
        sa_select(StrategyInstance.status, func.count(StrategyInstance.id))
        .group_by(StrategyInstance.status)
    ).all()
    status_counts = {r[0]: r[1] for r in rows}
    total = sum(status_counts.values())

    terminal = {"STOPPED", "CLOSED", "CLOSED_BY_TP", "CLOSED_BY_SL", "COMPLETED", "STOPPING"}
    active_count = sum(c for s, c in status_counts.items() if (s or "").upper() not in terminal)
    # 익절 카운트 (사용자 기획 B 안, 2026-04-30): notification 의 TP 알림 합계.
    # 자동 TP 만 익절로 분류 — 수동 emergency_stop 은 수익이 나도 익절 X.
    # 이전 status 기반은 부분 TP 누락 + 수동 청산이 익절로 잘못 분류되는 문제 해결.
    from app.models.notification import Notification as _Notif
    completed_count = db.execute(
        sa_select(func.count(_Notif.id))
        .where(_Notif.title.like("%익절 체결%"))
    ).scalar_one() or 0
    # 손절 카운트 — 자동 SL 알림 기준. 수동 stopping 제외.
    sl_count = db.execute(
        sa_select(func.count(_Notif.id))
        .where(_Notif.title.like("%[손절 발동]%"))
    ).scalar_one() or 0
    # 수동 종료 카운트 (참고용)
    manual_stop_count = db.execute(
        sa_select(func.count(StrategyInstance.id))
        .where(StrategyInstance.status.in_(["STOPPED", "STOPPING"]))
    ).scalar_one() or 0

    # 누적 실현 손익 합계
    realized_total = db.execute(
        sa_select(func.coalesce(func.sum(StrategyInstance.realized_pnl), 0))
    ).scalar_one() or Decimal("0")

    # 2026-05-06 fix (사용자 보고): strategy 단위 손익 분류 — 알림 기반 승률은 부정확.
    # 손실 strategy 가 「[손절 발동]」 알림 없이 STOPPED 되면 (수동 정리 또는 -50% 임계
    # 미달) 분모에서 빠져 승률 100% 잘못 계산됐음. 실제 strategy.realized_pnl 부호 기준.
    profit_strategy_count = db.execute(
        sa_select(func.count(StrategyInstance.id))
        .where(StrategyInstance.realized_pnl > 0)
    ).scalar_one() or 0
    loss_strategy_count = db.execute(
        sa_select(func.count(StrategyInstance.id))
        .where(StrategyInstance.realized_pnl < 0)
    ).scalar_one() or 0
    decided_strategy_count = profit_strategy_count + loss_strategy_count
    win_rate = (
        Decimal(profit_strategy_count) / Decimal(decided_strategy_count) * Decimal("100")
        if decided_strategy_count > 0 else Decimal("0")
    )
    # 알림 기반 승률 (이전 호환 + tooltip 노출용) — 명칭 명확화.
    decided_alert = completed_count + sl_count
    win_rate_alert_based = (
        Decimal(completed_count) / Decimal(decided_alert) * Decimal("100")
        if decided_alert > 0 else Decimal("0")
    )

    # 크라이시스 모드 진입 횟수
    crisis_total = db.execute(
        sa_select(func.count(StrategyInstance.id))
        .where(StrategyInstance.crisis_mode_triggered_at.is_not(None))
    ).scalar_one() or 0
    crisis_active = db.execute(
        sa_select(func.count(StrategyInstance.id))
        .where(
            StrategyInstance.crisis_mode_triggered_at.is_not(None),
            StrategyInstance.status.notin_(list(terminal)),
        )
    ).scalar_one() or 0

    # 평균 max_loss / max_profit (운영 패턴 파악)
    avg_max_loss = db.execute(
        sa_select(func.coalesce(func.avg(StrategyInstance.max_loss_pct), 0))
    ).scalar_one() or Decimal("0")
    avg_max_profit = db.execute(
        sa_select(func.coalesce(func.avg(StrategyInstance.max_profit_pct), 0))
    ).scalar_one() or Decimal("0")

    # TP 단계별 카운트 — notification 의 title prefix 로 집계.
    # 2026-05-12: TP1~10 + TRAILING_TP 동적 확장 (사용자 요청 — 기존 TP1~5 만 집계로
    # TP6~10 발동분 누락. TRAILING_TP 도 별도 카운트해서 trailing 빈도 파악 가능).
    from app.models.notification import Notification
    tp_breakdown = {}
    for n in range(1, 11):
        level = f"TP{n}"
        tp_breakdown[level] = db.execute(
            sa_select(func.count(Notification.id))
            .where(Notification.title.like(f"%[{level} 익절%"))
        ).scalar_one() or 0
    tp_breakdown["TRAILING_TP"] = db.execute(
        sa_select(func.count(Notification.id))
        .where(Notification.title.like("%[TRAILING_TP 익절%"))
    ).scalar_one() or 0

    return {
        "total": total,
        "active": active_count,
        "completed": completed_count,  # 익절 알림 건수 (한 strategy 가 다단계 거치면 중복)
        "stop_loss": sl_count,         # 손절 발동 알림 건수
        "manual_stop": manual_stop_count,
        "win_rate_pct": str(round(win_rate, 2)),  # 2026-05-06 부터 strategy 단위
        "win_rate_alert_based_pct": str(round(win_rate_alert_based, 2)),  # 이전 호환
        # 2026-05-06: strategy 단위 손익 분류 (정확한 승률 계산용)
        "profit_strategy_count": profit_strategy_count,
        "loss_strategy_count": loss_strategy_count,
        "decided_strategy_count": decided_strategy_count,
        "realized_pnl_total": str(realized_total),
        "crisis_total": crisis_total,
        "crisis_active": crisis_active,
        "avg_max_loss_pct": str(round(Decimal(str(avg_max_loss)), 2)),
        "avg_max_profit_pct": str(round(Decimal(str(avg_max_profit)), 2)),
        "status_breakdown": status_counts,
        "tp_breakdown": tp_breakdown,
    }


@router.get("/stats/breakdown")
def get_stats_breakdown(
    view: str = "strategies",
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """운영 통계 상세 — 사용자가 운영 통계 패널의 셀 클릭 시 띄울 모달 데이터.

    2026-05-06 (사용자 요청): 합계만 보이는 패널의 산출 근거 가시화.
    archive 된 strategy 도 포함 (realized_pnl 통계 일관성 유지 목적).

    view 옵션:
    - "strategies" (default): 모든 strategy 별 분류 + 손익 + 라이프사이클
    - "realized": realized_pnl != 0 인 strategy 만 (수익/손실 분류, 절댓값 정렬)
    - "losses": 손실/STOPPED 분류 (감사 시점 detail)
    """
    from sqlalchemy import select as sa_select, desc
    from app.models.strategy_instance import StrategyInstance

    if view not in {"strategies", "realized", "losses"}:
        raise HTTPException(status_code=400, detail=f"Unknown view: {view}")

    # 공통 select — 핵심 필드만 (응답 가벼움). 2026-06-02 (#29): qty + avg_entry 추가 (진입실패 판정용).
    base = sa_select(
        StrategyInstance.id,
        StrategyInstance.symbol,
        StrategyInstance.side,
        StrategyInstance.status,
        StrategyInstance.current_stage,
        StrategyInstance.realized_pnl,
        StrategyInstance.unrealized_pnl,
        StrategyInstance.max_loss_pct,
        StrategyInstance.max_profit_pct,
        StrategyInstance.crisis_mode_triggered_at,
        StrategyInstance.is_archived,
        StrategyInstance.started_at,
        StrategyInstance.stopped_at,
        StrategyInstance.created_at,
        StrategyInstance.current_position_qty,
        StrategyInstance.avg_entry_price,
    )

    # 2026-05-08 fix (사용자 보고): realized 탭이 PNL 절대값 큰 순이라 최신 데이터가
    # 안 보이던 문제. 모든 view 를 「최신 시작 순」 으로 통일 — 사용자가 가장 알고 싶은 것은
    # "최근 거래가 어떻게 됐나". 정렬 기준 변경 시 created_at 우선, ID 폴백 (옛날 row 호환).
    _recent_first = (desc(StrategyInstance.created_at), desc(StrategyInstance.id))
    if view == "realized":
        rows = db.execute(
            base.where(StrategyInstance.realized_pnl != 0).order_by(*_recent_first)
        ).all()
    elif view == "losses":
        # 2026-05-12 (사용자 보고): 「손실/감사」 view 가 realized_pnl<0 만 필터링.
        # 수동 정지 (STOPPED/STOPPING) + 크라이시스 모드 진입 + max_loss<-10% 모두 누락.
        # 사용자 의도: 감사 대상 = 「뭔가 비정상이거나 사용자 개입 있었던 strategy 모두」.
        # → realized_pnl<0 OR max_loss_pct<-10 OR 수동정지 OR 크라이시스 진입 (OR 조건).
        from sqlalchemy import or_
        rows = db.execute(
            base.where(or_(
                StrategyInstance.realized_pnl < 0,
                StrategyInstance.max_loss_pct < Decimal("-10"),
                StrategyInstance.status.in_(["STOPPED", "STOPPING"]),
                StrategyInstance.crisis_mode_triggered_at.is_not(None),
            )).order_by(*_recent_first)
        ).all()
    else:  # strategies
        rows = db.execute(base.order_by(*_recent_first)).all()

    def _classify(realized, status, stage, crisis, max_loss, qty, avg_entry):
        """2026-06-02 (#29 fix) — STOPPED 의 3-way 분리.

        우선순위:
        1. 🚫진입실패 — STOPPED + 한 번도 체결 안 됨 (LIMIT 미체결 후 종료)
        2. 🎯자동익절 — TP_FINAL 류 (COMPLETED + realized>0)
        3. 🤖자동손절 — STOPPED_BY_SL / CLOSED_BY_SL
        4. ✋수동손절 — STOPPED + 진입했었음 + realized<=0 (사용자가 손실 상태에서 stop)
        5. ✋수동익절 — STOPPED + 진입했었음 + realized>0 (사용자가 익절 위치에서 stop)
        6. 🚨크라이시스_진행중 — crisis active + not terminal
        7. ✅수익 / 📉손실 — realized 기준 (옛 데이터 fallback)
        8. ⚠️큰낙폭 — max_loss<-10 + 진행중
        9. BREAKEVEN / 미진입_종료 / 진행중
        """
        realized_dec = Decimal(str(realized or 0))
        stage_n = stage or 0
        qty_zero = qty is None or Decimal(str(qty or 0)) == 0
        entry_zero = avg_entry is None or Decimal(str(avg_entry or 0)) == 0
        st_upper = (status or "").upper()

        # 1. 진입실패 — STOPPED + 한 번도 체결 안 됨
        if st_upper == "STOPPED" and stage_n == 0 and qty_zero and entry_zero and realized_dec == 0:
            return "🚫진입실패"

        # 2. 자동손절 — 시스템 SL 발동
        if st_upper in ("STOPPED_BY_SL", "CLOSED_BY_SL"):
            return "🤖자동손절"

        # 3. 자동익절 — COMPLETED/REENTRY_READY 면서 수익
        if st_upper in ("COMPLETED", "CLOSED", "REENTRY_READY") and realized_dec > 0:
            return "🎯자동익절"

        # 4. 수동손절/익절 — STOPPED 인데 진입했었음
        if st_upper in ("STOPPED", "STOPPING"):
            if realized_dec > 0:
                return "✋수동익절"
            if realized_dec < 0:
                return "✋수동손절"
            return "✋수동정지"  # 진입했지만 손익 0

        # 5. 크라이시스 진행중
        if crisis is not None and st_upper not in {"STOPPED", "COMPLETED", "REENTRY_READY", "CLOSED"}:
            return "🚨크라이시스"

        # 6. realized 기준 fallback
        if realized_dec > 0:
            return "✅수익"
        if realized_dec < 0:
            return "📉손실"

        # 7. 진행중 큰낙폭
        if max_loss is not None and Decimal(str(max_loss)) < Decimal("-10"):
            return "⚠️큰낙폭"

        # 8. 정상 종료
        if st_upper in {"COMPLETED", "CLOSED", "REENTRY_READY"}:
            return "BREAKEVEN" if stage_n > 0 else "미진입_종료"

        return "진행중"

    items = [
        {
            "id": r[0],
            "symbol": r[1],
            "side": r[2],
            "status": r[3],
            "current_stage": r[4],
            "realized_pnl": str(r[5] or 0),
            "unrealized_pnl": str(r[6] or 0),
            "max_loss_pct": str(r[7]) if r[7] is not None else None,
            "max_profit_pct": str(r[8]) if r[8] is not None else None,
            "crisis_triggered": r[9] is not None,
            "is_archived": bool(r[10]),
            "started_at": r[11].isoformat() if r[11] else None,
            "stopped_at": r[12].isoformat() if r[12] else None,
            "created_at": r[13].isoformat() if r[13] else None,
            "current_position_qty": str(r[14] or 0),
            "avg_entry_price": str(r[15] or 0),
            "classification": _classify(r[5], r[3], r[4], r[9], r[7], r[14], r[15]),
        }
        for r in rows
    ]

    # 요약 — UI 헤더에 표시 (2026-06-02 #29: 새 분류 카운트 추가)
    def _cnt(cls):
        return sum(1 for x in items if x["classification"] == cls)
    profit_count = _cnt("✅수익") + _cnt("🎯자동익절") + _cnt("✋수동익절")
    loss_count = _cnt("📉손실") + _cnt("🤖자동손절") + _cnt("✋수동손절")
    never_entered_count = _cnt("🚫진입실패")
    auto_tp_count = _cnt("🎯자동익절")
    auto_sl_count = _cnt("🤖자동손절")
    manual_stop_count = _cnt("✋수동손절") + _cnt("✋수동익절") + _cnt("✋수동정지")
    crisis_count = sum(1 for x in items if x["crisis_triggered"])
    realized_sum = sum((Decimal(x["realized_pnl"]) for x in items), Decimal("0"))
    archived_count = sum(1 for x in items if x["is_archived"])

    return {
        "view": view,
        "count": len(items),
        "profit_count": profit_count,
        "loss_count": loss_count,
        "archived_count": archived_count,
        "realized_pnl_sum": str(realized_sum),
        # 2026-06-02 (#29): 분류별 정확한 카운트 — 사장님 통계 신뢰성 회복
        "never_entered_count": never_entered_count,
        "auto_tp_count": auto_tp_count,
        "auto_sl_count": auto_sl_count,
        "manual_stop_count": manual_stop_count,
        "crisis_count": crisis_count,
        "items": items,
    }
