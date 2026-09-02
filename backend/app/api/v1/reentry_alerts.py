"""신 재진입 알람 API (v130 → v131!)

사장님 요청 (v130): 알람 지우거나 = 선택해서 = 신 전략 즉시 생성!
사장님 요청 (v131 2026-08-09):
  - 자동 실행 옵션 = 알람 감지 시 자동 신 전략 생성
  - 수동 관리자 승인 = 알람만 표시, 사장님 클릭!
  - 손절가 옵션 확장 (0~100)

Endpoints:
  GET  /reentry-alerts               = 활성 알람 리스트
  DELETE /reentry-alerts/{id}        = 알람 개별 삭제
  GET  /reentry-alerts/settings      = 자동 실행 세팅 조회 (v131!)
  PUT  /reentry-alerts/settings      = 자동 실행 세팅 저장 (v131!)
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.risk_constants import FORCE_SL_ALLOWED_ROI
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reentry-alerts", tags=["reentry-alerts"])

REDIS_KEY_ALERTS = "reentry_alerts:v1"

# 🌟 v131 자동 실행 설정 keys (system_settings 테이블!)
KEY_AUTO_EXECUTE_ENABLED = "reentry_auto_execute_enabled"
KEY_AUTO_EXECUTE_CAPITAL = "reentry_auto_execute_capital"
KEY_AUTO_EXECUTE_FORCE_SL_ROI = "reentry_auto_execute_force_sl_roi"
KEY_AUTO_EXECUTE_LEVERAGE = "reentry_auto_execute_leverage"

# 기본값 (사장님 신 default)
DEFAULT_AUTO_EXECUTE_ENABLED = False  # OFF = 수동 승인 (기존!)
DEFAULT_AUTO_EXECUTE_CAPITAL = "100"  # 100 USDT (소액!)
DEFAULT_AUTO_EXECUTE_FORCE_SL_ROI = "15"  # -15%
DEFAULT_AUTO_EXECUTE_LEVERAGE = "2"  # 2x


@router.get("")
def list_reentry_alerts(user_id: int = Depends(get_current_user_id)) -> list[dict]:
    """활성 재진입 알람 리스트 (최근 24h)."""
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        if not r:
            return []
        # Sorted set에서 최근 순 (score desc)
        alert_keys = r.zrevrange(REDIS_KEY_ALERTS, 0, 100)
        out: list[dict] = []
        for key in alert_keys:
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            data = r.get(key)
            if not data:
                # 만료된 알람 = sorted set에서 제거
                r.zrem(REDIS_KEY_ALERTS, key)
                continue
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            try:
                alert = json.loads(data)
                alert["_key"] = key  # frontend가 삭제 시 필요
                out.append(alert)
            except Exception as e:
                logger.warning("[reentry_alerts] parse 실패: %s", e)
        return out
    except Exception as e:
        logger.warning("[reentry_alerts] list 실패: %s", e)
        return []


@router.delete("/{alert_key}")
def delete_reentry_alert(
    alert_key: str,
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """알람 개별 삭제 (사장님 무시!)."""
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        if not r:
            return {"deleted": False, "reason": "redis unavailable"}
        # key 검증 = "reentry_alert:" prefix만
        if not alert_key.startswith("reentry_alert:"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="잘못된 alert_key"
            )
        r.delete(alert_key)
        r.zrem(REDIS_KEY_ALERTS, alert_key)
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("[reentry_alerts] delete 실패: %s", e)
        return {"deleted": False, "reason": str(e)}


# =====================================================================
# 🌟 v131 자동 실행 세팅 API (사장님 요청 2026-08-09!)
# =====================================================================
class ReentrySettingsResponse(BaseModel):
    auto_execute_enabled: bool = False
    auto_execute_capital: str = "100"
    auto_execute_force_sl_roi: str = "15"
    auto_execute_leverage: str = "2"
    allowed_force_sl_roi: list[str] = []
    allowed_leverage: list[int] = []


class ReentrySettingsUpdate(BaseModel):
    auto_execute_enabled: bool = Field(default=False)
    auto_execute_capital: str = Field(default="100")
    auto_execute_force_sl_roi: str = Field(default="15")
    auto_execute_leverage: str = Field(default="2")


def _get_setting(db: Session, key: str, default: str) -> str:
    """SystemSetting에서 값 조회 (없으면 default)."""
    row = db.get(SystemSetting, key)
    return row.value if row and row.value is not None else default


def _set_setting(db: Session, key: str, value: str, user_id: int, description: str) -> None:
    """SystemSetting 저장 (upsert)."""
    row = db.get(SystemSetting, key)
    if row:
        row.value = value
        row.updated_by = user_id
        row.description = description
    else:
        row = SystemSetting(key=key, value=value, updated_by=user_id, description=description)
        db.add(row)


@router.get("/settings", response_model=ReentrySettingsResponse)
def get_reentry_settings(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> ReentrySettingsResponse:
    """자동 실행 세팅 조회 (v131 신!)."""
    enabled_str = _get_setting(db, KEY_AUTO_EXECUTE_ENABLED, "false")
    capital_str = _get_setting(db, KEY_AUTO_EXECUTE_CAPITAL, DEFAULT_AUTO_EXECUTE_CAPITAL)
    force_sl_str = _get_setting(db, KEY_AUTO_EXECUTE_FORCE_SL_ROI, DEFAULT_AUTO_EXECUTE_FORCE_SL_ROI)
    leverage_str = _get_setting(db, KEY_AUTO_EXECUTE_LEVERAGE, DEFAULT_AUTO_EXECUTE_LEVERAGE)
    return ReentrySettingsResponse(
        auto_execute_enabled=(enabled_str.lower() == "true"),
        auto_execute_capital=capital_str,
        auto_execute_force_sl_roi=force_sl_str,
        auto_execute_leverage=leverage_str,
        allowed_force_sl_roi=[str(x) for x in FORCE_SL_ALLOWED_ROI],
        allowed_leverage=[1, 2, 3, 5, 10, 20, 50, 75, 100, 125],
    )


@router.put("/settings", response_model=ReentrySettingsResponse)
def update_reentry_settings(
    payload: ReentrySettingsUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> ReentrySettingsResponse:
    """자동 실행 세팅 저장 (v131 신!)."""
    # 검증 = force_sl_roi 는 허용 리스트 값만!
    try:
        _sl_val = Decimal(str(payload.auto_execute_force_sl_roi))
        if _sl_val not in FORCE_SL_ALLOWED_ROI:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"강제 SL ROI는 다음 값만 허용: {[str(x) for x in FORCE_SL_ALLOWED_ROI]}"
            )
    except InvalidOperation:
        raise HTTPException(status_code=400, detail="강제 SL ROI = 숫자!")

    # 검증 = capital 은 양수
    try:
        _cap_val = Decimal(str(payload.auto_execute_capital))
        if _cap_val <= 0:
            raise HTTPException(status_code=400, detail="자본 = 양수!")
    except InvalidOperation:
        raise HTTPException(status_code=400, detail="자본 = 숫자!")

    # 검증 = leverage 는 1~125
    try:
        _lev = int(payload.auto_execute_leverage)
        if _lev < 1 or _lev > 125:
            raise HTTPException(status_code=400, detail="레버리지 = 1~125!")
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="레버리지 = 정수!")

    _set_setting(db, KEY_AUTO_EXECUTE_ENABLED,
                 "true" if payload.auto_execute_enabled else "false",
                 user_id, "재진입 알람 자동 실행 ON/OFF")
    _set_setting(db, KEY_AUTO_EXECUTE_CAPITAL,
                 str(payload.auto_execute_capital),
                 user_id, "자동 실행 자본 (USDT)")
    _set_setting(db, KEY_AUTO_EXECUTE_FORCE_SL_ROI,
                 str(payload.auto_execute_force_sl_roi),
                 user_id, "자동 실행 강제 SL ROI (%)")
    _set_setting(db, KEY_AUTO_EXECUTE_LEVERAGE,
                 str(payload.auto_execute_leverage),
                 user_id, "자동 실행 레버리지 (x)")
    db.commit()

    return get_reentry_settings(db, user_id)


# ═══════════════════════════════════════════════════════════════════════
# 🌟 Fix 301 (2026-09-03 사장님): 재진입 「대기 모니터링」을 화면에 남긴다.
#
#   사장님: "대기 모니터링도 전략 인스턴스에 남겨두고 종료 숨김 처럼
#            선택적으로 볼수 있게 하는것도 좋은것 같아"
#
#   🚨 사장님 1안(「99% 청산하고 남겨두기」)은 쓸 수 없다 — 두 가지 이유가
#      각각 단독으로 치명적이다:
#
#      (1) **재진입이 완전히 막힌다.** `realtime_reentry_worker` 는 후보를
#          `status ∈ TERMINAL_STATUSES`(청산 완료)에서 고르고, 그 뒤
#          `if symbol in active_syms: continue` 로 활성 심볼을 건너뛴다.
#          1% 를 남기면 상태가 STAGE*_OPEN 으로 살아 있어 **두 관문에 다 걸린다.**
#      (2) **dust orphan.** 거래소 MIN_NOTIONAL 은 5.00 USDT 인데
#          1차 진입 10 USDT × 레버 2 = 명목 20, 그 1% 는 **0.20 USDT** 다.
#          reduceOnly 주문이 거부되어 영원히 청산할 수 없다.
#          (이 저장소는 dust orphan 하나로 계정 전체가 막힌 전력이 있다.)
#
#   그래서 포지션은 지금처럼 100% 청산하고, **감시 중인 심볼과 각각이 왜
#   아직 진입하지 않았는지**를 워커가 매 주기 Redis 에 남겨 여기서 보여준다.
#   재진입 판정은 손대지 않는다 — 보이기만 한다.
# ═══════════════════════════════════════════════════════════════════════

# 사유 코드 → 사장님이 읽는 말
_REASON_KO: dict[str, str] = {
    "already_active": "이미 포지션 보유 중",
    "rebound_too_small": "아직 반등이 부족",
    "stop_wait_too_short": "손절 직후 대기 시간 중",
    "no_stop_price": "기준가 결손 (조사 필요)",
    "max_reentry_count": "재진입 횟수 소진",
    "ladder_exhausted_reset_to_stage1": "사다리 소진 → 1단계로",
    "learning_gate": "학습 게이트가 보류",
    "concurrent_limit_full": "동시 보유 상한 가득",
    "slot_exhausted_midloop": "재진입 슬롯 소진",
    "24h_change_limit": "24h 변동 제한",
    "stage3_wait_too_short": "3단계 대기 시간 중",
    "indicator_fetch_error": "지표 조회 실패",
    "no_exchange_account": "거래소 계정 없음",
}


def _reason_ko(code: str | None) -> str:
    if not code:
        return "조건 확인 중"
    if code.startswith("indicator_gate_need"):
        return f"지표 반전 부족 ({code.replace('indicator_gate_need', '')}개 필요)"
    if code.startswith("capital_none"):
        return "자본 계산 실패 (조사 필요)"
    return _REASON_KO.get(code, code)


@router.get("/watchlist")
def get_reentry_watchlist(user_id: int = Depends(get_current_user_id)) -> dict:
    """지금 재진입 감시 중인 심볼과 각각의 대기 사유.

    화면은 이걸 「종료 숨김」과 **독립된 목록**으로 띄운다 — 청산된 전략은
    숨겨도, 재진입 감시는 계속 보여야 하기 때문이다.

    비어 있음(`items: []`)에는 두 가지 뜻이 있어 구분해 돌려준다:
      · `stale=false` → 워커가 돌았고 감시 대상이 실제로 없다
      · `stale=true`  → 워커 기록이 없다/만료됐다 (= 워커가 안 돌고 있을 수 있다)
    """
    empty = {"items": [], "count": 0, "waiting": 0, "entered": 0,
             "updated_at": None, "stale": True, "note": None}
    try:
        from app.core.redis_client import get_redis_client
        from app.workers.realtime_reentry_worker import WATCHLIST_REDIS_KEY
        r = get_redis_client()
        if not r:
            return empty
        raw = r.get(WATCHLIST_REDIS_KEY)
        if not raw:
            return empty
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        data = json.loads(raw)
    except Exception as e:                       # 화면이 죽으면 안 된다
        logger.warning("[Fix301] watchlist 조회 실패: %s", e)
        return empty

    items = []
    for it in (data.get("items") or []):
        if not isinstance(it, dict):
            continue
        code = it.get("reason")
        items.append({
            **it,
            "reason_code": code,
            "reason_ko": "진입함" if it.get("entered") else _reason_ko(code),
        })
    # 대기 중을 위로, 그 안에서는 반등이 많이 온 순 (= 곧 들어갈 것부터)
    items.sort(key=lambda x: (x.get("entered") or False,
                              -(x.get("rebound_pct") or -999)))
    return {
        "items": items,
        "count": len(items),
        "waiting": sum(1 for x in items if not x.get("entered")),
        "entered": sum(1 for x in items if x.get("entered")),
        "updated_at": data.get("updated_at"),
        "note": data.get("note"),
        "stale": False,
    }
