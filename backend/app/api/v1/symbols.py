"""심볼(거래쌍) 조회 API.

전략 생성 화면에서 심볼 자동완성/선택용으로 사용한다.
거래소 거래 가능한 심볼 목록(`/admin/symbol-sync` 으로 동기화된 것)을 노출.
"""
import json
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.redis_client import get_redis_client
from app.core.crypto import decrypt_text
from app.integrations.binance.client import BinanceClient
from app.models.exchange_account import ExchangeAccount
from app.models.symbol import Symbol

router = APIRouter(prefix="/symbols", tags=["symbols"])


class SymbolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    symbol: str
    base_asset: str
    quote_asset: str
    status: str
    price_precision: int | None = None
    quantity_precision: int | None = None
    tick_size: Decimal | None = None
    step_size: Decimal | None = None
    min_qty: Decimal | None = None
    min_notional: Decimal | None = None


@router.get("", response_model=list[SymbolResponse])
def list_symbols(
    q: str | None = Query(default=None, description="심볼 검색어 (예: BTC)"),
    only_trading: bool = Query(default=True, description="True 면 status='TRADING' 만 반환"),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[SymbolResponse]:
    """거래 가능 심볼 목록을 반환한다."""
    stmt = select(Symbol)
    if only_trading:
        stmt = stmt.where(Symbol.status == "TRADING")
    if q:
        stmt = stmt.where(Symbol.symbol.ilike(f"%{q.upper()}%"))
    stmt = stmt.order_by(Symbol.symbol).limit(limit)
    rows = db.execute(stmt).scalars().all()
    return [SymbolResponse.model_validate(r) for r in rows]


class WhitelistInfoResponse(BaseModel):
    """거래 화이트리스트 상태 — 사용자 진입 시점에 어떤 심볼이 허용되는지 표시.

    2026-05-07 사용자 요청: 「화이트리스트 거래량 적은 심볼은 검색시 확인 가능하게」.
    UI 가 심볼 입력 폼 옆에 표시해 사용자가 미리 알 수 있게 한다.
    """
    enabled: bool
    allowed_symbols: list[str]


@router.get("/whitelist-info", response_model=WhitelistInfoResponse)
def get_whitelist_info(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> WhitelistInfoResponse:
    """현재 적용 중인 심볼 화이트리스트 상태.

    enabled = (env 에 ALLOWED_SYMBOLS_CSV 값 있음) AND (DB 토글 ON).
    DB 토글이 OFF 면 env 에 값 있어도 가드 미적용 → 모든 심볼 허용.
    """
    from app.core.config import settings
    from app.services.system_settings_service import SystemSettingsService

    allowed = settings.allowed_symbols_set
    env_configured = allowed is not None
    db_toggle = SystemSettingsService(db).is_whitelist_enabled(default_from_env=env_configured)
    effective_enabled = env_configured and db_toggle
    return WhitelistInfoResponse(
        enabled=effective_enabled,
        allowed_symbols=sorted(allowed) if (effective_enabled and allowed) else [],
    )


# get_symbol 의 decorator 등록은 file 끝에서 add_api_route 로 처리
# (ranking 같은 specific path 가 catch-all `/{symbol}` 보다 먼저 등록되도록).
def get_symbol(
    symbol: str,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> SymbolResponse:
    """단일 심볼의 상세 정보 반환 (tick_size, step_size 등 정밀도 정보 포함).

    UI 의 시작가 +/- N% 버튼이 정확한 자릿수로 반올림하기 위해 사용.

    경로 등록: 이 함수의 `@router.get("/{symbol}")` decorator 는 의도적으로 제거.
    file 끝에서 `router.add_api_route` 로 명시 등록 — ranking 같은 specific path
    가 먼저 등록되어 FastAPI 의 first-match 라우팅에서 catch-all 이 잡지 않도록.
    """
    s = db.execute(select(Symbol).where(Symbol.symbol == symbol.upper())).scalars().first()
    if not s:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Symbol not found")
    return SymbolResponse.model_validate(s)


# ============================================================================
# 2026-05-06 (사용자 요청): 24h/주/월 변동률 순위 + 새 전략 모달 + 별도 페이지
# ============================================================================
class RankingItem(BaseModel):
    symbol: str
    last_price: Decimal
    change_pct: Decimal       # 기간 변동률 (%)
    quote_volume: Decimal     # 24h 기준 거래대금 (sort/필터용 참고)


class RankingResponse(BaseModel):
    period: str               # 1d, 2d, ..., 7d, 1w, 2w, 1m, 3m
    direction: Literal["gainers", "losers"]
    cached: bool
    count: int
    items: list[RankingItem]


# Redis cache TTL — period 별 적절히 (짧은 기간은 짧은 TTL).
_PERIOD_TO_KLINE_PARAMS: dict[str, tuple[str, int]] = {
    # period_key: (binance interval, candle count)
    # 변동률 = (close[N-1] - close[0]) / close[0] * 100  → N+1 개 candle 필요 (close[0] = 시작점)
    "1d":  ("1h", 25),    # 1d = 24h, 24h ago vs now
    "2d":  ("4h", 13),
    "3d":  ("4h", 19),
    "4d":  ("4h", 25),
    "5d":  ("4h", 31),
    "6d":  ("4h", 37),
    "7d":  ("1d", 8),
    "1w":  ("1d", 8),
    "2w":  ("1d", 15),
    "1m":  ("1d", 31),
    "3m":  ("1d", 91),
    "6m":  ("1d", 181),
    "1y":  ("1w", 53),
}
_CACHE_TTL_SEC = {  # period 별 캐시 시간
    "1d": 60, "2d": 120, "3d": 180, "4d": 300, "5d": 300, "6d": 300, "7d": 300,
    "1w": 300, "2w": 600, "1m": 1800, "3m": 3600, "6m": 7200, "1y": 14400,
}


def _ranking_cache_key(period: str) -> str:
    return f"symbol_ranking:{period}"


def _build_ranking_for_period(db: Session, period: str) -> list[dict]:
    """모든 TRADING 심볼에 대해 period 변동률 계산 + 정렬 가능 list 반환.

    1d 는 Binance 24hr ticker 한 번 호출로 종료 (priceChangePercent).
    그 외는 각 심볼 별 klines 호출 — N 심볼 × O(1) 호출 → 운영상 무거움.
    그래서 캐시 TTL 을 길게 (1m/3m 등) 잡고, 24hr 외 기간은 active strategies
    심볼만 추리거나 사용자가 explicit 요청 시만 빌드.

    여기서는 단순화: 1d 만 모든 심볼, 그 외는 1d 결과의 top 50 심볼만 추가 계산.
    이렇게 하면 한 화면당 거래소 호출 ≤ 51회 (1 ticker bulk + 50 klines).
    """
    if period not in _PERIOD_TO_KLINE_PARAMS:
        raise HTTPException(status_code=400, detail=f"Unknown period: {period}")

    # 1) 활성 exchange account 가져와 BinanceClient 생성
    account = db.execute(
        select(ExchangeAccount).where(ExchangeAccount.is_active.is_(True))
    ).scalars().first()
    if not account:
        raise HTTPException(status_code=400, detail="No active exchange account")
    client = BinanceClient(
        api_key=decrypt_text(account.api_key_enc),
        api_secret=decrypt_text(account.api_secret_enc),
        is_testnet=account.is_testnet,
    )

    # 2) 24h ticker (모든 심볼) — quote_volume + 1d 변동률 출처
    ticker_all = client.get_24hr_ticker()
    if not isinstance(ticker_all, list):
        ticker_all = [ticker_all]
    items_24h = [
        {
            "symbol": t["symbol"],
            "last_price": str(t.get("lastPrice", 0)),
            "change_pct": str(t.get("priceChangePercent", 0)),
            "quote_volume": str(t.get("quoteVolume", 0)),
        }
        for t in ticker_all
        if t.get("symbol", "").endswith("USDT") or t.get("symbol", "").endswith("USDC")
    ]

    if period == "1d":
        return items_24h

    # 3) 그 외 기간: top 50 심볼 (24h 거래대금 기준) 만 klines 로 정확 계산
    items_24h.sort(key=lambda x: float(x["quote_volume"]), reverse=True)
    top50 = items_24h[:50]
    interval, klines_limit = _PERIOD_TO_KLINE_PARAMS[period]

    out: list[dict] = []
    for it in top50:
        try:
            kl = client.get_klines(symbol=it["symbol"], interval=interval, limit=klines_limit)
            if not kl or len(kl) < 2:
                continue
            close_first = Decimal(str(kl[0][4]))
            close_last = Decimal(str(kl[-1][4]))
            if close_first <= 0:
                continue
            change_pct = (close_last - close_first) / close_first * Decimal("100")
            out.append({
                "symbol": it["symbol"],
                "last_price": str(close_last),
                "change_pct": str(change_pct),
                "quote_volume": it["quote_volume"],
            })
        except Exception:  # 한 심볼 실패해도 나머지 계속
            continue
    return out


@router.get("/ranking", response_model=RankingResponse)
def get_symbol_ranking(
    period: str = Query(default="1d", description="기간: 1d/2d/.../7d/1w/2w/1m/3m/6m/1y"),
    direction: Literal["gainers", "losers"] = Query(default="gainers"),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> RankingResponse:
    """심볼 변동률 순위 — 상승/하락 top N (USDT/USDC perpetual).

    2026-05-06 사용자 요청. period 별 Redis 캐시 (1d=60s, 1w=5m, 1m=30m 등).
    1d 는 모든 심볼, 그 외는 24h 거래대금 top 50 만 정확 계산 (운영 호출 수 제한).
    """
    if period not in _PERIOD_TO_KLINE_PARAMS:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported period: {period} (지원: {list(_PERIOD_TO_KLINE_PARAMS.keys())})",
        )

    # Redis 캐시 조회 (raw items 캐시 — direction/limit 별 재정렬은 server 에서)
    cache_key = _ranking_cache_key(period)
    cached_raw = None
    cached = False
    try:
        client = get_redis_client()
        v = client.get(cache_key)
        if v:
            cached_raw = json.loads(v.decode("utf-8") if isinstance(v, bytes) else v)
            cached = True
    except Exception:
        cached_raw = None

    if cached_raw is None:
        items_raw = _build_ranking_for_period(db, period)
        try:
            client = get_redis_client()
            client.set(cache_key, json.dumps(items_raw), ex=_CACHE_TTL_SEC.get(period, 300))
        except Exception:
            pass
    else:
        items_raw = cached_raw

    # direction 별 정렬 + 상위 limit
    items_raw.sort(
        key=lambda x: Decimal(x["change_pct"]),
        reverse=(direction == "gainers"),
    )
    top = items_raw[:limit]

    return RankingResponse(
        period=period,
        direction=direction,
        cached=cached,
        count=len(top),
        items=[
            RankingItem(
                symbol=it["symbol"],
                last_price=Decimal(it["last_price"]),
                change_pct=Decimal(it["change_pct"]),
                quote_volume=Decimal(it["quote_volume"]),
            )
            for it in top
        ],
    )


# ============================================================================
# Route 등록 — get_symbol 의 catch-all `/{symbol}` 을 마지막에 등록.
# /ranking (이미 위에서 @router.get 으로 등록됨) 가 먼저 매치됨.
# ============================================================================
router.add_api_route(
    "/{symbol}",
    get_symbol,
    methods=["GET"],
    response_model=SymbolResponse,
)
