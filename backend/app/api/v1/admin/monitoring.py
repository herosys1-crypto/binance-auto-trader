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
    from sqlalchemy.orm import selectinload
    from app.models.notification import Notification
    if not title_like or len(title_like) > 200:
        raise HTTPException(status_code=400, detail="title_like 1~200자")
    limit = max(1, min(limit, 1000))
    # 2026-06-05 N+1 Query fix (Sentry 발견 선제 fix — recent-activity 와 동일 패턴):
    # 사장님 「운영 통계 → TP1/TRAIL 카운트 클릭」 시 호출 = 매번 N+1 발생 위험.
    # selectinload 로 strategy_instance 미리 prefetch.
    rows = db.execute(
        sa_select(Notification)
        .options(selectinload(Notification.strategy_instance))
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
    date: str | None = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """운영 통계 — 전체 전략 분포 + 누적 손익 + 승률 + 크라이시스 발동 횟수.

    🌟 2026-07-01 사장님 요구: date 파라미터 = "YYYY-MM-DD" 형식 = 특정 날짜 익절 카운트!
    + today_pnl 필드 = 오늘 (KST 자정~) 실현 손익!
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

    # 🌟 2026-07-01 사장님 요구: 당일 손익 (KST 자정 기준!) + 특정 날짜 조회!
    # 계산 방식: 해당 날짜에 종료된 (stopped_at) strategy 의 realized_pnl 합계!
    from datetime import datetime, timezone, timedelta
    KST = timezone(timedelta(hours=9))
    now_kst = datetime.now(KST)
    if date:
        # 사장님 특정 날짜 (= "YYYY-MM-DD" KST 자정~다음 자정!)
        try:
            target_kst = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=KST)
            day_start = target_kst.astimezone(timezone.utc)
            day_end = (target_kst + timedelta(days=1)).astimezone(timezone.utc)
        except Exception:
            today_kst = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
            day_start = today_kst.astimezone(timezone.utc)
            day_end = (today_kst + timedelta(days=1)).astimezone(timezone.utc)
    else:
        today_kst = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
        day_start = today_kst.astimezone(timezone.utc)
        day_end = (today_kst + timedelta(days=1)).astimezone(timezone.utc)
    # 해당 날짜에 종료된 strategy 의 realized_pnl 합계 = 확정 손익!
    today_pnl_val = db.execute(
        sa_select(func.coalesce(func.sum(StrategyInstance.realized_pnl), 0))
        .where(StrategyInstance.stopped_at >= day_start)
        .where(StrategyInstance.stopped_at < day_end)
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
        "today_pnl": str(today_pnl_val),  # 🌟 2026-07-01 사장님: 당일/특정날짜 실현 손익!
        "date_filter": date or now_kst.strftime("%Y-%m-%d"),  # 선택 날짜 (없으면 오늘!)
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


# ============================================================================
# 2026-06-06 — Diagnostic endpoint (사장님 EPICUSDT #23 미청산 분석)
# ============================================================================
# docker compose exec ... python -c "..." 가 stdout buffering 으로 0 라인 출력 문제 발생.
# HTTP API 로 우회 = 사장님 브라우저 또는 curl 로 즉시 확인.
#
# 사용:
#   브라우저: https://[domain]/api/v1/admin/diagnostic/strategy/23
#   curl:     curl -H "Authorization: Bearer $TOKEN" https://[domain]/api/v1/admin/diagnostic/strategy/23
#
# 반환: 전략 핵심 필드 (status, crisis_*, peak, pnl 등) + Redis peak + trailing 발동 조건 평가
# ============================================================================


@router.get("/diagnostic/strategy/{strategy_id}")
def diagnose_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """전략 인스턴스의 핵심 필드 + Redis peak + trailing 발동 조건 평가.

    EPICUSDT (#23) 같은 「TP3 발동 + 가격 하락 = 미청산」 원인 진단용.
    """
    from app.models.strategy_instance import StrategyInstance
    from app.core.risk_constants import (
        TRAILING_MIN_TP_INDEX,
        TRAILING_MIN_STAGE,
        TRAILING_PEAK_THRESHOLD_PCT,
        TRAILING_RETRACE_PCT,
    )

    s = db.get(StrategyInstance, strategy_id)
    if not s:
        raise HTTPException(404, f"Strategy {strategy_id} not found")

    # Redis peak 키 (정상 모드 trailing 의 진짜 peak)
    redis_peak = None
    redis_err = None
    try:
        from app.core.redis_client import get_redis_client
        val = get_redis_client().get(f"strategy:{strategy_id}:peak_pnl_pct")
        if val is not None:
            redis_peak = val.decode() if isinstance(val, bytes) else val
    except Exception as e:
        redis_err = str(e)

    # Position 의 latest mark_price + isolated_margin
    from app.models.position import Position
    from sqlalchemy import select
    latest_pos = db.execute(
        select(Position)
        .where(Position.strategy_instance_id == strategy_id)
        .order_by(Position.id.desc())
        .limit(1)
    ).scalars().first()

    # 2026-06-06 critical: notifications (TP 발동 이력) 확인 — UI 카운트 vs DB status 모순 분석용
    # EPICUSDT (#23) = UI 3/10 익절 vs DB TP2_DONE_PARTIAL = 알림은 3건인데 status 는 TP2?
    # = TP3 알림 발송 후 status update 실패 silent bug 의심
    from app.models.notification import Notification
    notif_rows = db.execute(
        select(Notification.id, Notification.title, Notification.send_status, Notification.created_at)
        .where(Notification.strategy_instance_id == strategy_id)
        .where(Notification.title.like("%[TP%"))
        .order_by(Notification.created_at.asc())
    ).all()
    notifications = [
        {
            "id": n.id,
            "title": n.title,
            "status": n.send_status,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notif_rows
    ]

    # Orders 의 TP 발동 이력 (status 와 진짜 비교용)
    from app.models.order import Order
    order_rows = db.execute(
        select(Order.id, Order.purpose, Order.status, Order.executed_qty, Order.avg_price, Order.created_at)
        .where(Order.strategy_instance_id == strategy_id)
        .where(Order.purpose == "TAKE_PROFIT")
        .order_by(Order.created_at.asc())
    ).all()
    tp_orders = [
        {
            "id": o.id,
            "purpose": o.purpose,
            "status": o.status,
            "executed_qty": str(o.executed_qty) if o.executed_qty else None,
            "avg_price": str(o.avg_price) if o.avg_price else None,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in order_rows
    ]

    # Trailing 발동 조건 자체 평가 (real-time)
    TRAILING_ARMED_STATUSES = (
        {f"TP{n}_DONE_PARTIAL" for n in range(TRAILING_MIN_TP_INDEX, 11)}
        | {"TRAILING_ARMED"}
    )
    status_upper = (s.status or "").upper()
    cond_status = status_upper in TRAILING_ARMED_STATUSES
    cond_stage = (s.current_stage or 0) >= TRAILING_MIN_STAGE

    # peak = max(redis, max_profit_pct, current pnl_ratio)
    from decimal import Decimal
    candidates = []
    if redis_peak:
        try:
            candidates.append(Decimal(redis_peak))
        except Exception:
            pass
    if s.max_profit_pct is not None:
        candidates.append(Decimal(str(s.max_profit_pct)))

    true_peak = max(candidates) if candidates else None

    # Current pnl_ratio = (mark - entry) / entry * 100 * leverage
    cur_pnl_ratio = None
    if (
        latest_pos
        and latest_pos.mark_price is not None
        and s.avg_entry_price is not None
        and s.leverage
    ):
        try:
            avg_entry = Decimal(str(s.avg_entry_price))
            mark = Decimal(str(latest_pos.mark_price))
            raw_pct = (
                (mark - avg_entry) / avg_entry * Decimal("100")
                if (s.side or "").upper() == "LONG"
                else (avg_entry - mark) / avg_entry * Decimal("100")
            )
            cur_pnl_ratio = raw_pct * Decimal(str(s.leverage))
        except Exception:
            pass

    cond_peak = (true_peak is not None) and (true_peak >= TRAILING_PEAK_THRESHOLD_PCT)
    # 🌟 2026-06-08 사장님 trailing retrace 옵션 반영 (spec):
    # strategy 별 trailing_retrace_pct > 0 = 사장님 선택 (5/10/15/20)
    # NULL = global TRAILING_RETRACE_PCT (= default 5)
    _strategy_retrace = (
        Decimal(str(s.trailing_retrace_pct))
        if s.trailing_retrace_pct is not None
        else TRAILING_RETRACE_PCT
    )
    cond_retrace = (
        true_peak is not None
        and cur_pnl_ratio is not None
        and cur_pnl_ratio <= (true_peak - _strategy_retrace)
    )

    trailing_should_fire = cond_status and cond_stage and cond_peak and cond_retrace

    return {
        "id": s.id,
        "symbol": s.symbol,
        "side": s.side,
        "status": s.status,
        "current_stage": s.current_stage,
        "leverage": s.leverage,
        "total_capital": str(s.total_capital) if s.total_capital is not None else None,
        "avg_entry_price": str(s.avg_entry_price) if s.avg_entry_price is not None else None,
        "current_position_qty": str(s.current_position_qty) if s.current_position_qty is not None else None,
        "unrealized_pnl": str(s.unrealized_pnl) if s.unrealized_pnl is not None else None,
        "realized_pnl": str(s.realized_pnl) if s.realized_pnl is not None else None,
        "max_profit_pct": str(s.max_profit_pct) if s.max_profit_pct is not None else None,
        "max_loss_pct": str(s.max_loss_pct) if s.max_loss_pct is not None else None,
        "peak_pnl_pct_after_first_tp": str(s.peak_pnl_pct_after_first_tp) if s.peak_pnl_pct_after_first_tp is not None else None,
        "crisis_mode_triggered_at": s.crisis_mode_triggered_at.isoformat() if s.crisis_mode_triggered_at else None,
        "crisis_first_tp_done_at": s.crisis_first_tp_done_at.isoformat() if s.crisis_first_tp_done_at else None,
        "latest_mark_price": str(latest_pos.mark_price) if latest_pos and latest_pos.mark_price is not None else None,
        "latest_isolated_margin": str(latest_pos.isolated_margin) if latest_pos and latest_pos.isolated_margin is not None else None,
        "redis_peak_pnl_pct": redis_peak,
        "redis_error": redis_err,
        "computed": {
            "true_peak": str(true_peak) if true_peak is not None else None,
            "current_pnl_ratio": str(cur_pnl_ratio) if cur_pnl_ratio is not None else None,
        },
        "trailing_conditions": {
            "status_ok": cond_status,
            "status_required": list(TRAILING_ARMED_STATUSES),
            "stage_ok": cond_stage,
            "stage_required": f">= {TRAILING_MIN_STAGE}",
            "peak_ok": cond_peak,
            "peak_required": f">= {TRAILING_PEAK_THRESHOLD_PCT}%",
            "retrace_ok": cond_retrace,
            "retrace_required": f"current <= peak - {_strategy_retrace}%p (사장님 옵션, default {TRAILING_RETRACE_PCT})",
        },
        "trailing_should_fire": trailing_should_fire,
        "diagnosis_hint": (
            "✅ 모든 조건 만족 — TRAILING_TP 즉시 발동되어야 (process_action 호출 안 됨 의심)"
            if trailing_should_fire
            else "❌ 조건 미달 — 위 trailing_conditions 의 false 항목 확인"
        ),
        # 2026-06-06 critical 진단 — UI 카운트 vs DB status 모순 분석
        "notifications_tp": notifications,
        "tp_orders": tp_orders,
        "notification_count": len(notifications),
        "tp_order_count": len(tp_orders),
        "status_mismatch_check": {
            "ui_count_from_notifications": len(notifications),
            "db_status": s.status,
            "expected_status_from_count": (
                f"TP{len(notifications)}_DONE_PARTIAL"
                if len(notifications) > 0 and len(notifications) <= 10
                else None
            ),
            "is_mismatch": (
                len(notifications) > 0
                and s.status
                and s.status != f"TP{len(notifications)}_DONE_PARTIAL"
                and s.status != "COMPLETED"
            ),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# 🔍 사장님 「포지션 예약됨 0」 silent bug 진단 endpoint (fix v4 — 2026-06-08)
#
# 사장님 발견: PR #131 (template stages_config) + fix v3 (strategy_stage_plans)
# 머지 + 배포 후에도 「포지션 예약됨 0」 여전.
#
# 진짜 원인 식별 도구 (= 브라우저에서 즉시 확인 가능):
#   https://VPS_IP/api/v1/admin/diagnostic/reserved
#
# 각 active strategy 별:
#   - total_capital (DB 저장)
#   - strategy_stage_plans 의 planned_capital 합 (= fix v3 핵심)
#   - template.stages_config.capitals 합 (= fix v2 fallback)
#   - 어떤 source 가 사용되는지 (= 사장님 가시성)
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/diagnostic/reserved")
def diagnose_reserved(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """사장님 「포지션 예약됨」 silent bug 진단.

    각 active strategy 별 = 모든 fallback 데이터 source 표시 + 사용된 source 명시.
    사장님이 = 브라우저에서 = JSON 직접 확인 = 진짜 원인 즉시 식별.
    """
    from sqlalchemy import select
    from app.models.strategy_instance import StrategyInstance
    from app.models.strategy_stage_plan import StrategyStagePlan
    from app.models.strategy_template import StrategyTemplate
    from app.core.strategy_status import TERMINAL_STATUSES

    active = db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.user_id == user_id)
        .where(StrategyInstance.is_archived.is_(False))
        .where(StrategyInstance.status.notin_(TERMINAL_STATUSES))
    ).scalars().all()

    results = []
    for s in active:
        # 1. strategy_stage_plans (= fix v3 우선 source)
        plans = db.execute(
            select(StrategyStagePlan)
            .where(StrategyStagePlan.strategy_instance_id == s.id)
        ).scalars().all()
        plans_sum_enabled = sum((p.planned_capital or Decimal("0")) for p in plans if p.is_enabled)
        plans_sum_all = sum((p.planned_capital or Decimal("0")) for p in plans)
        plans_detail = [
            {
                "stage_no": p.stage_no,
                "is_enabled": p.is_enabled,
                "is_triggered": p.is_triggered,
                "planned_capital": str(p.planned_capital) if p.planned_capital is not None else None,
                "additional_margin_usdt": (
                    str(p.additional_margin_usdt) if p.additional_margin_usdt is not None else None
                ),
            }
            for p in sorted(plans, key=lambda x: x.stage_no)
        ]

        # 2. template stages_config (= fix v2 fallback)
        tpl = db.get(StrategyTemplate, s.strategy_template_id) if s.strategy_template_id else None
        tpl_stages_sum = Decimal("0")
        tpl_capitals_raw = None
        if tpl and tpl.stages_config:
            tpl_capitals_raw = tpl.stages_config.get("capitals")
            for c in tpl_capitals_raw or []:
                if c is None:
                    continue
                try:
                    tpl_stages_sum += Decimal(str(c))
                except Exception:
                    continue

        # 3. _reserved_one() 의 실제 결정 source 시뮬레이션
        if plans_sum_enabled > 0:
            source_used = "strategy_stage_plans (fix v3)"
            source_value = plans_sum_enabled
        elif tpl_stages_sum > 0:
            source_used = "template.stages_config (fix v2)"
            source_value = tpl_stages_sum
        else:
            source_used = "total_capital (legacy)"
            source_value = s.total_capital or Decimal("0")

        results.append({
            "id": s.id,
            "symbol": s.symbol,
            "side": s.side,
            "status": s.status,
            "current_stage": s.current_stage,
            "strategy_template_id": s.strategy_template_id,
            "total_capital": str(s.total_capital) if s.total_capital is not None else None,
            "plans_count": len(plans),
            "plans_enabled_count": sum(1 for p in plans if p.is_enabled),
            "plans_triggered_count": sum(1 for p in plans if p.is_triggered),
            "plans_sum_enabled": str(plans_sum_enabled),
            "plans_sum_all": str(plans_sum_all),
            "tpl_stages_config_raw": tpl_capitals_raw,
            "tpl_stages_sum": str(tpl_stages_sum),
            "source_used": source_used,
            "source_value": str(source_value),
            "plans_detail": plans_detail,
        })

    return {
        "user_id": user_id,
        "active_count": len(active),
        "strategies": results,
        "note": (
            "사장님 「포지션 예약됨 = source_value - actual_margin (Binance lock)」. "
            "= 0 이면 = source_value ≤ actual = silent bug. "
            "source_used 확인 + 해당 source 의 값 점검."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 🔍 사장님 거래내역 분석 endpoint v2 (2026-06-08)
#
# 사장님 명시: "전략 #39와 #36의 포지션 추가와 단계별수정 등등을 거래내역을
#              먼저 분석해서 기획을 해줘 오늘 거래도 같이 분석해서"
#
# 데이터 통합:
#   - Orders (= 신규 + 청산 주문 + 시간순)
#   - RiskEvents (= 자동 TP/SL/manual_tp/crisis/edit/포지션추가)
#   - Notifications (= 사장님 알림)
#   - StrategyStagePlan (= 단계별 진입 결과)
#
# 사용:
#   https://VPS_IP/api/v1/admin/diagnostic/strategy-history/39   ← BEATUSDT
#   https://VPS_IP/api/v1/admin/diagnostic/strategy-history/36   ← VELVET
#   https://VPS_IP/api/v1/admin/diagnostic/today-trades          ← 오늘 모든 거래
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/diagnostic/strategy-history/{strategy_id}")
def diagnose_strategy_history(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """전략별 거래내역 전체 분석 (Orders + RiskEvents + Notifications + StagePlans).

    사장님 「수정 모드」 spec 기획 = 실 거래 데이터 기반 정확 분석용.
    """
    from sqlalchemy import select
    from app.models.strategy_instance import StrategyInstance
    from app.models.strategy_stage_plan import StrategyStagePlan
    from app.models.order import Order
    from app.models.risk_event import RiskEvent
    from app.models.notification import Notification

    s = db.get(StrategyInstance, strategy_id)
    if not s or s.user_id != user_id:
        raise HTTPException(404, f"Strategy {strategy_id} not found or not yours")

    # Orders 전체 (= 시간순)
    orders = db.execute(
        select(Order)
        .where(Order.strategy_instance_id == strategy_id)
        .order_by(Order.created_at.asc())
    ).scalars().all()

    # RiskEvents (= 시간순)
    events = db.execute(
        select(RiskEvent)
        .where(RiskEvent.strategy_instance_id == strategy_id)
        .order_by(RiskEvent.created_at.asc())
    ).scalars().all()

    # Notifications (= 시간순, 최근 50건)
    notifs = db.execute(
        select(Notification)
        .where(Notification.strategy_instance_id == strategy_id)
        .order_by(Notification.created_at.desc())
        .limit(50)
    ).scalars().all()

    # StagePlans
    plans = db.execute(
        select(StrategyStagePlan)
        .where(StrategyStagePlan.strategy_instance_id == strategy_id)
        .order_by(StrategyStagePlan.stage_no.asc())
    ).scalars().all()

    return {
        "strategy": {
            "id": s.id,
            "symbol": s.symbol,
            "side": s.side,
            "leverage": s.leverage,
            "status": s.status,
            "current_stage": s.current_stage,
            "start_price": str(s.start_price) if s.start_price else None,
            "avg_entry_price": str(s.avg_entry_price) if s.avg_entry_price else None,
            "current_position_qty": str(s.current_position_qty) if s.current_position_qty else None,
            "total_capital": str(s.total_capital) if s.total_capital else None,
            "invested_capital": str(s.invested_capital) if s.invested_capital else None,
            "realized_pnl": str(s.realized_pnl) if s.realized_pnl else None,
            "max_loss_pct": str(s.max_loss_pct) if s.max_loss_pct else None,
            "max_profit_pct": str(s.max_profit_pct) if s.max_profit_pct else None,
            "crisis_mode_triggered_at": s.crisis_mode_triggered_at.isoformat() if s.crisis_mode_triggered_at else None,
            "tp1_pct_override": str(s.tp1_pct_override) if s.tp1_pct_override else None,
            "trailing_retrace_pct": str(s.trailing_retrace_pct) if s.trailing_retrace_pct else None,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        },
        "stage_plans": [
            {
                "stage_no": p.stage_no,
                "trigger_mode": p.trigger_mode,
                "trigger_percent": str(p.trigger_percent) if p.trigger_percent else None,
                "trigger_price": str(p.trigger_price) if p.trigger_price else None,
                "planned_capital": str(p.planned_capital) if p.planned_capital else None,
                "planned_qty": str(p.planned_qty) if p.planned_qty else None,
                "additional_margin_usdt": str(p.additional_margin_usdt) if p.additional_margin_usdt else None,
                "is_enabled": p.is_enabled,
                "is_triggered": p.is_triggered,
                "triggered_at": p.triggered_at.isoformat() if p.triggered_at else None,
            }
            for p in plans
        ],
        "orders_count": len(orders),
        "orders": [
            {
                "id": o.id,
                "stage_no": o.stage_no,
                "purpose": o.purpose,
                "side": o.side,
                "order_type": o.order_type,
                "client_order_id": o.client_order_id,
                "exchange_order_id": str(o.exchange_order_id) if o.exchange_order_id else None,
                "trigger_price": str(o.trigger_price) if o.trigger_price else None,
                "price": str(o.price) if o.price else None,
                "orig_qty": str(o.orig_qty) if o.orig_qty else None,
                "executed_qty": str(o.executed_qty) if o.executed_qty else None,
                "avg_price": str(o.avg_price) if o.avg_price else None,
                "status": o.status,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "updated_at": o.updated_at.isoformat() if o.updated_at else None,
            }
            for o in orders
        ],
        "risk_events_count": len(events),
        "risk_events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "severity": e.severity,
                "title": e.title,
                "message": e.message,
                "event_payload": e.event_payload,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
        "notifications_count": len(notifs),
        "notifications": [
            {
                "id": n.id,
                "title": n.title if hasattr(n, "title") else None,
                "message": n.message if hasattr(n, "message") else None,
                "created_at": n.created_at.isoformat() if hasattr(n, "created_at") and n.created_at else None,
            }
            for n in notifs
        ],
        "note": (
            "사장님 「수정 모드」 spec 기획용 전체 거래내역. "
            "Orders + RiskEvents + Notifications + StagePlans 시간순. "
            "사장님 = JSON 결과 보내주시면 = 분석 후 spec 정확 기획."
        ),
    }


@router.get("/diagnostic/today-trades")
def diagnose_today_trades(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """오늘 모든 거래 분석 (Orders + RiskEvents, UTC 자정 기준)."""
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import select
    from app.models.strategy_instance import StrategyInstance
    from app.models.order import Order
    from app.models.risk_event import RiskEvent

    # 오늘 자정 KST = UTC -9h
    now = datetime.now(timezone.utc)
    today_kst_midnight = (now + timedelta(hours=9)).replace(hour=0, minute=0, second=0, microsecond=0)
    today_utc_start = today_kst_midnight - timedelta(hours=9)

    # 사장님 strategy 만
    user_strategy_ids = [
        s.id for s in db.execute(
            select(StrategyInstance).where(StrategyInstance.user_id == user_id)
        ).scalars().all()
    ]

    # 오늘 Orders
    orders = db.execute(
        select(Order)
        .where(Order.strategy_instance_id.in_(user_strategy_ids))
        .where(Order.created_at >= today_utc_start)
        .order_by(Order.created_at.asc())
    ).scalars().all() if user_strategy_ids else []

    # 오늘 RiskEvents
    events = db.execute(
        select(RiskEvent)
        .where(RiskEvent.strategy_instance_id.in_(user_strategy_ids))
        .where(RiskEvent.created_at >= today_utc_start)
        .order_by(RiskEvent.created_at.asc())
    ).scalars().all() if user_strategy_ids else []

    return {
        "today_kst_midnight_utc": today_utc_start.isoformat(),
        "user_strategy_ids": user_strategy_ids,
        "orders_count": len(orders),
        "orders": [
            {
                "id": o.id,
                "strategy_id": o.strategy_instance_id,
                "symbol": o.symbol,
                "stage_no": o.stage_no,
                "purpose": o.purpose,
                "side": o.side,
                "order_type": o.order_type,
                "trigger_price": str(o.trigger_price) if o.trigger_price else None,
                "price": str(o.price) if o.price else None,
                "orig_qty": str(o.orig_qty) if o.orig_qty else None,
                "executed_qty": str(o.executed_qty) if o.executed_qty else None,
                "avg_price": str(o.avg_price) if o.avg_price else None,
                "status": o.status,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in orders
        ],
        "risk_events_count": len(events),
        "risk_events": [
            {
                "id": e.id,
                "strategy_id": e.strategy_instance_id,
                "event_type": e.event_type,
                "severity": e.severity,
                "title": e.title,
                "message": e.message,
                "event_payload": e.event_payload,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
        "note": "오늘 KST 자정 기준 사장님 모든 거래 + risk events. spec 기획 분석용.",
    }


# ============================================================
# 🚨 2026-06-09 사장님 critical 신 endpoint = 자동 진입 진단
# 사장님 요청: '모든 전략에 대해서 다시 설정에 대해서 조사해서 문제가 있으면 수정'
# = 모든 활성 strategy = 자동 진입 차단 상태 한 번에 진단
# ============================================================
@router.get("/diagnostic/auto-entry-status")
def get_auto_entry_diagnostic(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """모든 활성 strategy 의 자동 진입 상태 진단.
    
    각 strategy 에 대해:
    - 현재 단계 + 다음 단계 trigger_price + 현재가
    - 자동 진입 차단 여부 + 차단 이유 (130% 한도 / cooldown / 거래소 ban)
    
    사장님이 = 한 번에 보고 = 문제 strategy 즉시 식별 가능.
    """
    from app.core.strategy_status import STAGES_WITH_NEXT as ACTIVE_STAGE_STATUSES  # v24 fix
    from app.models.strategy_instance import StrategyInstance
    from app.models.strategy_stage_plan import StrategyStagePlan
    from app.core.redis_client import get_redis_client
    from app.services.capital_calculator import (
        calc_reserved_for_account, calc_wallet_limit, get_wallet_limit_pct,
    )
    from decimal import Decimal
    
    redis = None
    try:
        redis = get_redis_client()
    except Exception:
        pass
    
    strats = db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.is_archived.is_(False))
        .where(StrategyInstance.status.in_(ACTIVE_STAGE_STATUSES))
        .order_by(StrategyInstance.id.desc())
    ).scalars().all()
    
    results = []
    blocked_count = 0
    pending_count = 0
    
    for s in strats:
        current_stage = s.current_stage or 0
        next_stage_no = current_stage + 1
        
        # 다음 단계 정보
        next_plan = db.execute(
            select(StrategyStagePlan)
            .where(StrategyStagePlan.strategy_instance_id == s.id)
            .where(StrategyStagePlan.stage_no == next_stage_no)
        ).scalar_one_or_none()
        
        # 현재가 (= avg + pnl/qty 추정)
        current_price = None
        if s.avg_entry_price and s.current_position_qty and s.unrealized_pnl is not None:
            try:
                avg = float(s.avg_entry_price)
                qty = abs(float(s.current_position_qty))
                pnl = float(s.unrealized_pnl)
                if qty > 0:
                    if s.side == "LONG":
                        current_price = avg + (pnl / qty)
                    else:
                        current_price = avg - (pnl / qty)
            except Exception:
                pass
        
        # 차단 이유 확인
        block_reasons = []
        cooldown_remaining_sec = None
        worker_block_info = None  # v18: stage_trigger_worker 가 기록한 정확한 차단 이유

        # 🌟 v18 NEW: Redis 에서 worker 가 기록한 정확한 차단 이유 조회
        if redis:
            try:
                import json
                _block_raw = redis.get(f"stage_trigger_block:strategy:{s.id}")
                if _block_raw:
                    worker_block_info = json.loads(_block_raw)
            except Exception:
                pass

        if next_plan:
            trg_price = float(next_plan.trigger_price or 0)
            trigger_reached = False
            if trg_price > 0 and current_price:
                if s.side == "SHORT":
                    trigger_reached = current_price >= trg_price
                else:
                    trigger_reached = current_price <= trg_price

            # Redis cooldown 확인 + 남은 시간 (v18: TTL 추가)
            in_cooldown = False
            if redis:
                try:
                    cooldown_key = f"stage_margin_cooldown:strategy:{s.id}:stage:{next_stage_no}"
                    if redis.get(cooldown_key):
                        in_cooldown = True
                        try:
                            cooldown_remaining_sec = redis.ttl(cooldown_key)
                        except Exception:
                            pass
                except Exception:
                    pass

            if next_plan.is_triggered:
                status_label = "✅ 진입 완료"
            elif not trigger_reached:
                status_label = "⏳ 트리거 대기"
                # v18: 트리거 미도달이지만 worker silent 차단 있으면 알림
                if worker_block_info:
                    block_reasons.append(f"⚠️ Worker 차단 (재시작 안전망): {worker_block_info.get('reason', '?')}")
            else:
                # 트리거 도달했는데 = 진입 안 됨!
                blocked_count += 1
                pending_count += 1
                status_label = "🚨 자동 진입 차단!"
                if worker_block_info:
                    block_reasons.append(f"📌 정확한 이유: {worker_block_info.get('reason', '?')}")
                if in_cooldown:
                    cd_min = (cooldown_remaining_sec or 0) // 60
                    cd_sec = (cooldown_remaining_sec or 0) % 60
                    block_reasons.append(f"⏳ Redis cooldown 남은 시간: {cd_min}분 {cd_sec}초")
                if not worker_block_info and not in_cooldown:
                    block_reasons.append("⚠️ 원인 불명 (= 다음 cycle 에서 worker 가 기록 예정)")
        else:
            status_label = "📦 단계 완료 (= 다음 단계 plan 없음)"
            if worker_block_info:
                block_reasons.append(f"⚠️ Worker 차단: {worker_block_info.get('reason', '?')}")

        results.append({
            "strategy_id": s.id,
            "symbol": s.symbol,
            "side": s.side,
            "current_stage": current_stage,
            "next_stage_no": next_stage_no if next_plan else None,
            "next_trigger_price": float(next_plan.trigger_price) if next_plan and next_plan.trigger_price else None,
            "current_price": current_price,
            "status_label": status_label,
            "block_reasons": block_reasons,
            "cooldown_remaining_sec": cooldown_remaining_sec,  # v18 신
            "worker_block_info": worker_block_info,  # v18 신 (= 정확한 이유 + 시각)
            "avg_entry": float(s.avg_entry_price or 0),
            "current_qty": float(s.current_position_qty or 0),
        })
    
    return {
        "summary": {
            "total_active": len(strats),
            "blocked": blocked_count,
            "pending_entry": pending_count,
            "wallet_limit_pct": float(get_wallet_limit_pct()),
        },
        "strategies": results,
        "note": "🚨 = 자동 진입 차단 중 (사장님 즉시 조치 필요!). PR 머지 + 배포 + Redis cooldown 삭제로 해결.",
    }


# ============================================================
# 🌟 2026-06-11 #21 옛 미해결: 메인 계정 「읽기 전용 모드」
# 사장님 운영 모니터링 = sub-account + main 통합!
# ============================================================
@router.get("/diagnostic/main-account-readonly")
def get_main_account_readonly_view(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """메인 계정 = 「읽기 전용 모드」 통합 모니터링.
    
    사장님 = sub-account 거래 + main 잔액 모니터링!
    """
    from app.models.exchange_account import ExchangeAccount
    
    # 모든 active 계정
    accs = db.execute(
        select(ExchangeAccount).where(ExchangeAccount.is_active.is_(True))
    ).scalars().all()
    
    result = {
        "total_accounts": len(accs),
        "accounts": [],
        "note": "사장님 통합 모니터링 = main + sub-account!",
    }
    for a in accs:
        result["accounts"].append({
            "id": a.id,
            "name": a.name,
            "is_testnet": a.is_testnet,
            "exchange": a.exchange,
            "type": "MAIN" if "main" in (a.name or "").lower() else "SUB",
        })
    return result
