"""🖥 선물거래 터미널 전용 API (`/static/perp-terminal.html` 이 쓴다).

## 이 파일이 존재하는 이유 — 「합쳐서 1회로 준다」

터미널 화면은 한 심볼을 계속 들여다보는 화면이라 갱신 요구가 대시보드보다 훨씬
잦다. 브라우저가 필요한 조각을 각각 부르면 **같은 화면 한 칸을 위해 서버→바이낸스
요청이 3~4배**로 늘어난다.

이 저장소는 2026-08-26 에 **IP ban(418) 무한 연장** 사고를 겪었다
(`app/integrations/binance/client.py` Fix 116 주석). 그 사고의 교훈은
「가드를 루프 앞이 아니라 네트워크 직전에 둔다」와 「불필요한 서버발 호출을
애초에 만들지 않는다」 두 가지다. 그래서:

  · **공개 시세(가격·호가·체결·캔들)는 서버가 아예 만지지 않는다.**
    브라우저가 `wss://fstream.binance.com/market/stream` 에 직접 붙는다.
    서버 IP 부담 0 + 사용자 브라우저 IP 사용.
  · 서버가 부르는 것은 **WS 로 못 얻는 것뿐**이다:
      - 미결제약정 / 심볼 정밀도  → WS 스트림에 없다
      - 계정 잔고 / 포지션 / 미체결 → **API 키가 필요**하다.
        키를 브라우저에 내려보내는 설계는 금지이므로 서버가 대신 부른다.
  · 서버가 부르는 것은 전부 **Redis 캐시 + 낮은 폴링 주기**를 전제로 한다.
    각 엔드포인트 docstring 에 권장 주기를 적어 두었다.

## 🚨 왜 `BinanceClient` 를 쓰는가 (market.py 의 생짜 `requests.get` 을 복제하지 않는다)

`app/api/v1/market.py` 는 `requests.get(...)` 을 직접 부른다. 그 경로는
`BinanceClient._request` 안의 두 안전장치를 **통째로 우회**한다:

  · Fix 116 IP ban 전역 회로 차단기 (`client.py:652`)
  · Fix 124 weight 거버너            (`client.py:667`)

지금은 호출량이 적어 티가 안 날 뿐이다. 터미널은 상시 열어 두는 화면이라
호출량이 늘어나므로, 여기서는 **공개 데이터도 `BinanceClient` 를 경유**시킨다.
공개(unsigned) 호출은 키가 필요 없으므로 빈 자격증명으로 생성해도 된다
(`_request` 가 `signed`/`api_key_required` 일 때만 헤더를 붙인다).

## 🚨 보안 — 응답에 절대 넣지 않는 것

api_key / api_secret / *_enc / passphrase / X-MBX-APIKEY / HMAC signature /
listenKey / DB 접속문자열 / .env 값.

그리고 **예외 객체를 `detail` 에 문자열 보간하지 않는다.** `requests` 의
`HTTPError` 문자열에는 요청 URL 전체가 들어 있어 `signature=<hmac>` 가 그대로
브라우저 응답 body 로 새어 나간다 (`exchange_accounts.py:750` 이 실제로 그렇다).
여기서는 `logger.warning(..., exc_info=True)` 로 서버에만 남기고 응답에는
고정 문구만 준다.

## 🚨 주문 발주 엔드포인트는 **일부러 만들지 않았다**

`GET /terminal/capabilities` 를 보라. 이유를 거기에 적어 두었다.
요약: 주문은 기존 3-콜 체인(템플릿 → 전략 → start)을 **프런트가 그대로** 탄다.
서버 래퍼를 새로 만들면 ①세 단계의 서로 다른 한글 400 사유가 하나로 뭉개지고
②검증되지 않은 **두 번째 주문 경로**가 실자금 시스템에 생긴다.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.crypto import decrypt_text
from app.core.strategy_status import ACTIVE_LIKE, TERMINAL_STATUSES
from app.integrations.binance.client import BinanceClient
from app.models.exchange_account import ExchangeAccount
from app.models.order import Order
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_template import StrategyTemplate
from app.models.symbol import Symbol

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/terminal", tags=["terminal"])


# ═══════════════════════════════════════════════════════════════════════════
# 공용 헬퍼
# ═══════════════════════════════════════════════════════════════════════════

_UPSTREAM_FAIL_DETAIL = "거래소 조회에 실패했습니다 (서버 로그 확인)"

# 🚨 보안 (2026-09-03 적대적 검증에서 추가): 심볼은 **반드시** 이 형태여야 한다.
#
# 왜 길이 제한(max_length=30)만으로는 부족한가:
#   심볼 문자열은 ①업스트림 쿼리 파라미터 ②Redis 캐시 키 ③서비스 게이트 인자
#   세 곳으로 그대로 흘러간다. 자유 문자열을 허용하면 호출자가 **매번 다른 문자열**을
#   넣어 캐시를 100% 미스로 만들 수 있다. 그러면
#     · 서버 IP 로 바이낸스 weight 가 무제한 누적 (2026-08-26 IP ban 418 무한연장 사고)
#     · `/fapi/v1/ticker/24hr` · `/fapi/v1/premiumIndex` 는 client.py `_SCAN_ENDPOINTS`
#       라서 **매매 워커의 스캔 예산(Fix 124)까지 같이 태운다** = 요청 하나로 자동매매
#       지표가 결손된다
#     · Redis 에 20초 TTL 짜리 쓰레기 키가 무제한 생성된다
#   실제 선물 심볼은 전부 대문자+숫자다(예 BTCUSDT / 1000PEPEUSDT). 그 밖은 거절한다.
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}$")


def _norm_symbol(symbol: object) -> str:
    """심볼 정규화 + 형식 검증. 형식이 아니면 400 — 업스트림·Redis 로 내려보내지 않는다."""
    sym = str(symbol or "").strip().upper()
    if not _SYMBOL_RE.match(sym):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="심볼 형식이 올바르지 않습니다 (영문 대문자·숫자 2~20자, 예: BTCUSDT)",
        )
    return sym


def _d(v: Any, default: Decimal = Decimal("0")) -> Decimal:
    """어떤 값이든 Decimal 로. 실패하면 default — 화면이 죽지 않게."""
    if v is None or v == "":
        return default
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _s(v: Decimal | None) -> str | None:
    """Decimal → 문자열. 부동소수 오차를 프런트로 흘리지 않기 위해 str 로 준다."""
    return None if v is None else str(v)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redis():
    """Redis 클라이언트. 없으면 None — 캐시는 있으면 좋고 없어도 동작해야 한다."""
    try:
        from app.core.redis_client import get_redis_client
        return get_redis_client()
    except Exception:
        return None


def _cache_get(key: str) -> dict | list | None:
    # dict 뿐 아니라 list 도 돌려준다 — `binance:position_risk:{id}` 처럼
    # 다른 모듈과 **공유하는 키**는 그쪽이 정한 형식(bare list)을 그대로 써야 한다.
    r = _redis()
    if r is None:
        return None
    try:
        raw = r.get(key)
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        return json.loads(raw)
    except Exception:
        return None


def _cache_set(key: str, value: dict | list, ttl: int) -> None:
    r = _redis()
    if r is None:
        return
    try:
        r.setex(key, ttl, json.dumps(value, default=str))
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# 🚨 업스트림 호출 예산 (분당) — 무인증 경로가 IP 를 태우지 못하게 막는 마지막 방어선
#
# 배경: 2026-08-26 IP ban(418) 무한연장 사고. 그때의 결론은 두 가지였다.
#   ① 가드는 「루프 앞」이 아니라 「네트워크 직전」에 둔다  (Fix 116)
#   ② 캐시만으로는 부족하다 — 넘기 전에 스스로 끊어야 한다 (Fix 124 weight 거버너)
#
# `GET /terminal/symbol-meta` 는 **무인증인데 서버→바이낸스 호출을 3개 유발**한다.
# 심볼별 Redis 캐시 20초는 「같은 심볼 반복」만 막는다. 심볼을 바꿔가며 부르면
# (거래 가능 심볼 754개) 캐시는 **한 번도 안 맞고** 754 × weight 3 = 2,262 weight
# 가 한 번에 나간다 — 한도(2400/분)를 혼자서 거의 다 먹는다. 그러면 워커의
# 주문·포지션 조회까지 같이 죽는다.
#
# 그래서 「캐시 미스로 업스트림에 나가는 횟수」 자체에 분당 상한을 건다.
#   · 프로세스 로컬 카운터 = Redis 가 죽어도 반드시 동작한다 (Fix 116 의 1차 방어와 같은 구조)
#   · Redis 카운터        = api 컨테이너가 여러 개여도 합산된다
#   두 카운터 **모두** 통과해야 나간다.
#
# 초과하면 502 가 아니라 **DB 값만 담은 부분 응답**을 준다.
# 화면은 「모름」을 표시할 뿐 「0」으로 떨어지지 않는다 (fail-OFF 사고 재발 방지).
# ═══════════════════════════════════════════════════════════════════════════
_SYMBOL_META_MISS_BUDGET_PER_MIN = 40      # × weight 3 = 최대 120 weight/분 (한도의 5%)
_local_miss_counts: dict[str, int] = {}    # {"YYYYmmddHHMM|bucket": n}


def _upstream_budget_ok(bucket: str, limit: int) -> bool:
    """이번 분에 이 버킷이 업스트림으로 더 나가도 되는가.

    🚨 여기서 세는 것은 「요청 수」가 아니라 **「캐시를 못 맞아 실제로 거래소로
    나가는 횟수」**다. 캐시 히트는 세지 않는다 — 세면 정상 사용이 스스로를 막는다
    (Fix 127 이 정확히 그 실수를 되돌린 적 있다: 차단된 요청까지 세어 카운터가
    부풀고 → 더 차단하고 → 더 부푸는 악순환).
    """
    minute = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    lkey = f"{minute}|{bucket}"

    # ① 프로세스 로컬 (Redis 장애에도 반드시 동작)
    if len(_local_miss_counts) > 8:         # 지난 분 잔재 정리 (무한 성장 방지)
        for k in [k for k in _local_miss_counts if not k.startswith(minute)]:
            _local_miss_counts.pop(k, None)
    local = _local_miss_counts.get(lkey, 0) + 1
    _local_miss_counts[lkey] = local
    if local > limit:
        return False

    # ② Redis (컨테이너 합산). 실패하면 ①만으로 판단 = fail-open,
    #    단 ① 이 이미 상한을 걸고 있으므로 무제한이 되지는 않는다.
    r = _redis()
    if r is None:
        return True
    try:
        key = f"terminal:upstream_budget:{minute}:{bucket}"
        total = int(r.incr(key))
        r.expire(key, 120)
        return total <= limit
    except Exception:
        return True


def _public_client() -> BinanceClient:
    """공개(unsigned) 호출 전용 클라이언트.

    키가 없어도 된다 — `_request` 는 `signed` / `api_key_required` 일 때만
    `X-MBX-APIKEY` 를 붙인다. 그래도 `BinanceClient` 를 쓰는 이유는 위 모듈
    docstring 참조(Fix 116 IP ban 차단기 + Fix 124 weight 거버너를 타기 위해).
    """
    return BinanceClient(api_key="", api_secret="", is_testnet=False)


def _pick_account(db: Session, user_id: int, account_id: int | None) -> ExchangeAccount:
    """쓸 거래소 계정 하나를 고른다.

    시안에 계정 선택 UI 가 없어서 「활성 계정 중 첫 번째」를 기본으로 한다.
    계정이 둘 이상이면 **엉뚱한 계정에 주문이 나갈 수 있으므로** 응답에
    `account_id` 와 `multiple_accounts` 를 실어 화면이 선택기를 띄울 수 있게 한다.
    (`/positions/external` 이 여러 계정을 순회하는 것과 같은 조회 패턴.)
    """
    if account_id is not None:
        acc = db.execute(
            select(ExchangeAccount)
            .where(ExchangeAccount.id == account_id)
            .where(ExchangeAccount.user_id == user_id)
        ).scalar_one_or_none()
        if acc is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="거래소 계정 없음 또는 본인 소유 아님")
        return acc

    accs = db.execute(
        select(ExchangeAccount)
        .where(ExchangeAccount.user_id == user_id)
        .where(ExchangeAccount.is_active.is_(True))
        .order_by(ExchangeAccount.id)
    ).scalars().all()
    if not accs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="활성 거래소 계정이 없습니다")
    return accs[0]


def _account_count(db: Session, user_id: int) -> int:
    return len(db.execute(
        select(ExchangeAccount.id)
        .where(ExchangeAccount.user_id == user_id)
        .where(ExchangeAccount.is_active.is_(True))
    ).scalars().all())


def _client_for(account: ExchangeAccount) -> BinanceClient:
    """계정 자격증명으로 서명 클라이언트 생성 (키워드 인자 필수).

    🚨 복호화한 키는 이 함수 밖으로 절대 나가지 않는다. 로그에도 남기지 않는다.
    """
    try:
        return BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=account.is_testnet,
        )
    except Exception:
        logger.error("terminal: 키 복호화 실패 account_id=%s", account.id, exc_info=True)
        raise HTTPException(status_code=500, detail="거래소 자격증명을 사용할 수 없습니다") from None


def _upstream_502(where: str, account_id: int | None = None):
    """거래소 호출 실패 → 502. 예외 문자열을 응답에 넣지 않는다.

    🚨 `detail=f"...: {e}"` 로 쓰면 requests 예외에 담긴 요청 URL
    (= `signature=<hmac>` 포함)이 브라우저로 흘러간다. 서버 로그에만 남긴다.
    """
    logger.warning("terminal %s 실패 account_id=%s", where, account_id, exc_info=True)
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=_UPSTREAM_FAIL_DETAIL)


# ═══════════════════════════════════════════════════════════════════════════
# 1) 심볼 헤더 — 24h 통계 + 미결제약정 + 펀딩 + 심볼 정밀도를 한 번에
# ═══════════════════════════════════════════════════════════════════════════

class SymbolMetaResponse(BaseModel):
    """시안 심볼 헤더 한 줄에 들어가는 값 전부. 화이트리스트 — raw JSON 통과 금지."""

    symbol: str
    fetched_at: str
    # 24h 통계 (초기 스냅샷용 — 이후 갱신은 브라우저 WS `<sym>@ticker`)
    last_price: str | None = None
    price_change: str | None = None
    price_change_pct: str | None = None
    high_price: str | None = None
    low_price: str | None = None
    volume: str | None = None            # base 자산 수량
    quote_volume: str | None = None      # USDT 환산 거래대금
    trade_count: int | None = None
    # 미결제약정 — WS 스트림에 없다. 이것 때문에 이 엔드포인트가 필요하다.
    open_interest: str | None = None         # 코인 수량 (Binance 원본)
    open_interest_usdt: str | None = None    # × markPrice (시안 표기가 USDT 라서 필요)
    # 마크가 / 펀딩 (초기값. 이후 갱신은 브라우저 WS `<sym>@markPrice@1s` 의 p/r/T)
    mark_price: str | None = None
    index_price: str | None = None
    funding_rate: str | None = None          # 원본 비율 (예 "0.00010000")
    funding_rate_pct: str | None = None      # ×100 = 화면 표기 % (예 "0.0100")
    next_funding_time: int | None = None     # ms — 클라이언트가 카운트다운
    # 심볼 정밀도 (우리 symbols 테이블 = exchangeInfo 동기화본)
    tick_size: str | None = None
    step_size: str | None = None
    min_qty: str | None = None
    min_notional: str | None = None
    price_precision: int | None = None
    quantity_precision: int | None = None
    symbol_status: str | None = None         # "TRADING" 등
    known_symbol: bool = False               # symbols 테이블에 있는가
    # 어떤 조각이 결손인지 화면이 「모름」과 「0」을 구분할 수 있게 남긴다
    partial: list[str] = []


@router.get("/symbol-meta", response_model=SymbolMetaResponse)
def get_symbol_meta(
    symbol: str = Query(..., min_length=1, max_length=30),
    db: Session = Depends(get_db),
) -> SymbolMetaResponse:
    """심볼 헤더용 메타 — 3개 업스트림을 **서버에서 합쳐 1회로** 준다.

    ## 왜 합치는가
    브라우저가 `ticker24h` / `openInterest` / `premiumIndex` 를 각각 부르면
    **같은 화면 한 줄을 위해 요청이 3배**가 된다. 심볼을 바꿀 때마다 3배가
    누적된다. IP ban 사고를 겪은 저장소라 이건 그냥 3배 위험이다.

    ## 왜 브라우저가 직접 바이낸스를 안 부르는가
    바이낸스 REST 를 브라우저에서 부르면 CORS 는 통과하지만 **사용자 IP 가
    바이낸스 rate limit 을 직접 먹는다.** 그리고 openInterest 는 WS 스트림에
    아예 없어서 REST 말고는 얻을 방법이 없다. 대신 **가격·호가·체결·캔들처럼
    WS 로 얻을 수 있는 것은 여기에 넣지 않았다** — 그건 브라우저가
    `wss://fstream.binance.com/market/stream` 에 직접 붙어서 받는다.

    ## 권장 폴링 주기: **30초** (심볼 변경 시 즉시 1회 추가)
    24h·펀딩·마크가는 WS 로 계속 갱신되므로 여기서 다시 받을 이유가 없다.
    실질적으로 이 폴링이 필요한 값은 **미결제약정 하나**뿐이다.
    Redis 캐시 20초 — 여러 탭이 열려 있어도 업스트림은 20초에 한 번.

    ## weight
    ticker/24hr(symbol 지정) 1 + openInterest 1 + premiumIndex(symbol 지정) 1 = **3**.
    symbol 을 반드시 지정하기 때문에 40 이 아니라 1 이다 (`client.estimate_weight`).

    ## 인증 + 남용 방어 (2중)
    공개 데이터라 인증을 걸지 않았다 (`market.py` 와 같은 정책).
    🚨 다만 이 경로는 **무인증인데 서버→바이낸스 호출을 유발**한다. 방어는 둘이다:
      ① 심볼별 Redis 캐시 20초 — 「같은 심볼 반복」을 막는다.
      ② 분당 업스트림 예산 40회(`_upstream_budget_ok`) — ①이 못 막는
         **「심볼을 바꿔가며 부르기」**를 막는다. 거래 가능 심볼이 754개라
         캐시가 한 번도 안 맞으면 754 × 3 = 2,262 weight 가 한 번에 나가
         한도(2400/분)를 혼자 다 먹는다. 그러면 워커의 주문·포지션 조회까지
         같이 죽는다 — 2026-08-26 사고와 같은 그림이다.
      초과 시 502 가 아니라 **DB 값만 담은 부분 응답**(`partial` 에
      `upstream_rate_limited`)을 준다. 주문에 필요한 틱/스텝은 그대로 나간다.
    """
    sym = _norm_symbol(symbol)      # 🚨 형식 검증 — 자유 문자열을 업스트림/Redis 로 못 보낸다
    cache_key = f"terminal:symbol_meta:{sym}"
    cached = _cache_get(cache_key)
    if isinstance(cached, dict) and cached:
        # 정밀도는 DB 값이라 캐시에 함께 담겨 있다 (심볼당 고정값이라 안전).
        return SymbolMetaResponse(**cached)

    # ── 🚨 「우리가 아는 심볼」만 통과 (무인증 경로의 카디널리티 상한) ──────
    # 순서가 중요하다: **예산 가드보다 먼저** 본다.
    #   예산 가드(`_upstream_budget_ok`)는 부를 때마다 토큰을 하나 쓴다. 모르는 심볼을
    #   먼저 거르지 않으면 무작위 문자열(AAAA0001 …)이 남의 예산을 다 태워, 정상
    #   사용자는 24h·펀딩·미결제가 전부 「모름」으로 떨어진다.
    #   symbols 테이블(= exchangeInfo 동기화본, ≈754행)로 묶으면 서로 다른 캐시 키의
    #   개수가 그 크기로 고정되어 캐시가 반드시 듣는다 = 업스트림이 늘지 않는다.
    # 🚨 「모르는 심볼」을 조용히 빈 응답으로 주지 않고 404 로 명시한다 —
    #    이 저장소는 「모름」을 「0/꺼짐」으로 표시해 사고를 겪었다(2026-08-28 fail-OFF).
    # 이 조회는 우리 DB 만 본다 = 거래소 호출 0. 그래서 예산을 쓰지 않는다.
    row = db.execute(select(Symbol).where(Symbol.symbol == sym)).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="알 수 없는 심볼입니다 (symbols 동기화 목록에 없어 거래소 조회를 하지 않습니다)",
        )

    # ── 🚨 업스트림 예산 확인 (무인증 경로의 마지막 방어선) ─────────────
    # 캐시를 못 맞았고 심볼도 진짜일 때만 여기까지 온다. 분당 상한을 넘으면 거래소를
    # 부르지 않고 **DB 값만** 돌려준다. 틱/스텝/최소수량 같은 주문에 꼭 필요한 값은
    # 그대로 나가므로 주문 화면이 죽지 않고, 24h·미결제·펀딩만 「모름」이 된다.
    if not _upstream_budget_ok("symbol_meta", _SYMBOL_META_MISS_BUDGET_PER_MIN):
        logger.warning(
            "terminal symbol-meta 업스트림 예산 초과 — DB 값만 반환 symbol=%s (분당 %d회 상한)",
            sym, _SYMBOL_META_MISS_BUDGET_PER_MIN,
        )
        return SymbolMetaResponse(
            symbol=sym,
            fetched_at=_now_iso(),
            tick_size=_s(row.tick_size),
            step_size=_s(row.step_size),
            min_qty=_s(row.min_qty),
            min_notional=_s(row.min_notional),
            price_precision=row.price_precision,
            quantity_precision=row.quantity_precision,
            symbol_status=row.status,
            known_symbol=True,
            # 화면이 「모름」과 「0」을 구분할 수 있게 사유를 남긴다.
            partial=["ticker24h", "open_interest", "funding", "upstream_rate_limited"],
        )

    bc = _public_client()
    partial: list[str] = []

    # ── 24h 통계 ────────────────────────────────────────────────────────
    t24: dict[str, Any] = {}
    try:
        raw = bc._request("GET", "/fapi/v1/ticker/24hr", signed=False, params={"symbol": sym})
        if isinstance(raw, dict):
            t24 = raw
    except Exception:
        logger.warning("terminal symbol-meta ticker24h 실패 symbol=%s", sym, exc_info=True)
        partial.append("ticker24h")

    # ── 미결제약정 ──────────────────────────────────────────────────────
    oi_raw: dict[str, Any] = {}
    try:
        raw = bc._request("GET", "/fapi/v1/openInterest", signed=False, params={"symbol": sym})
        if isinstance(raw, dict):
            oi_raw = raw
    except Exception:
        logger.warning("terminal symbol-meta openInterest 실패 symbol=%s", sym, exc_info=True)
        partial.append("open_interest")

    # ── 마크가 / 펀딩 ───────────────────────────────────────────────────
    prem: dict[str, Any] = {}
    try:
        raw = bc._request("GET", "/fapi/v1/premiumIndex", signed=False, params={"symbol": sym})
        if isinstance(raw, dict):
            prem = raw
        elif isinstance(raw, list) and raw:
            prem = raw[0]
    except Exception:
        logger.warning("terminal symbol-meta premiumIndex 실패 symbol=%s", sym, exc_info=True)
        partial.append("funding")

    if len(partial) == 3:
        # 셋 다 실패 = 업스트림이 통째로 죽었거나 IP ban. 502 로 명확히 알린다.
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=_UPSTREAM_FAIL_DETAIL)

    # ── 미결제약정 USDT 환산 ────────────────────────────────────────────
    # 🚨 시안은 「9.14M USDT」인데 /fapi/v1/openInterest 는 **코인 수량**을 준다.
    #    markPrice 를 곱해야 USDT 다. 어느 쪽인지 헷갈리지 않도록 **둘 다** 준다.
    mark = _d(prem.get("markPrice"), Decimal("0"))
    oi_coin = _d(oi_raw.get("openInterest"), Decimal("-1"))
    oi_usdt: Decimal | None = None
    if oi_coin >= 0 and mark > 0:
        oi_usdt = (oi_coin * mark).quantize(Decimal("0.01"))

    funding = prem.get("lastFundingRate")
    funding_pct: str | None = None
    if funding not in (None, ""):
        try:
            funding_pct = str((_d(funding) * 100).quantize(Decimal("0.0001")))
        except Exception:
            funding_pct = None

    # ── 심볼 정밀도 (우리 DB = exchangeInfo 동기화본) ──────────────────
    # 거래소 exchangeInfo 를 매번 부르지 않는 이유: weight 가 크고(전체 심볼),
    # 값이 거의 바뀌지 않는다. symbols 테이블이 이미 단일 진실이다.
    # 🚨 `row` 는 **업스트림을 부르기 전에** 이미 조회했다(모르는 심볼이면 그 자리에서
    #    404). 여기서 다시 조회하지 않는다 — 같은 질의를 두 번 하면 그 사이에 값이
    #    갈라질 수 있고, 무엇보다 「모르는 심볼인데 거래소는 이미 불렀다」가 된다.

    payload = SymbolMetaResponse(
        symbol=sym,
        fetched_at=_now_iso(),
        last_price=t24.get("lastPrice"),
        price_change=t24.get("priceChange"),
        price_change_pct=t24.get("priceChangePercent"),
        high_price=t24.get("highPrice"),
        low_price=t24.get("lowPrice"),
        volume=t24.get("volume"),
        quote_volume=t24.get("quoteVolume"),
        trade_count=(int(t24["count"]) if str(t24.get("count") or "").isdigit() else None),
        open_interest=(str(oi_coin) if oi_coin >= 0 else None),
        open_interest_usdt=_s(oi_usdt),
        mark_price=(prem.get("markPrice") or None),
        index_price=(prem.get("indexPrice") or None),
        funding_rate=(funding or None),
        funding_rate_pct=funding_pct,
        next_funding_time=(int(prem["nextFundingTime"]) if prem.get("nextFundingTime") else None),
        tick_size=_s(row.tick_size) if row else None,
        step_size=_s(row.step_size) if row else None,
        min_qty=_s(row.min_qty) if row else None,
        min_notional=_s(row.min_notional) if row else None,
        price_precision=row.price_precision if row else None,
        quantity_precision=row.quantity_precision if row else None,
        symbol_status=row.status if row else None,
        known_symbol=row is not None,
        partial=partial,
    )
    _cache_set(cache_key, payload.model_dump(), ttl=20)
    return payload


# ═══════════════════════════════════════════════════════════════════════════
# 2) 계정 요약 — 순자산 / 사용가능 / 유지증거금 / 증거금비율
# ═══════════════════════════════════════════════════════════════════════════

class AccountSummaryResponse(BaseModel):
    """계정 요약. **숫자만** — 키·라벨·이메일 등 식별정보는 넣지 않는다."""

    account_id: int
    is_testnet: bool
    multiple_accounts: bool            # 계정이 2개 이상이면 화면이 선택기를 띄워야 한다
    asset: str = "USDT"
    fetched_at: str
    total_wallet_balance: str          # 지갑만
    total_unrealized_pnl: str
    total_margin_balance: str          # 지갑 + 미실현 = 시안의 「순자산」
    available_balance: str             # 거래소 availableBalance
    our_available_balance: str         # 지갑 − 우리 예약자본 (보수적)
    reserved_for_strategies: str
    active_strategy_count: int
    total_position_initial_margin: str
    total_open_order_initial_margin: str
    total_maint_margin: str            # 시안의 「유지 증거금」
    margin_ratio_pct: str              # 시안의 「증거금 비율」
    open_positions_count: int


@router.get("/account", response_model=AccountSummaryResponse)
def get_account_summary(
    account_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> AccountSummaryResponse:
    """계정 요약 (순자산 / 사용가능 / 유지증거금 / 증거금비율).

    ## 왜 브라우저가 직접 안 부르는가
    `/fapi/v2/account` 는 **서명 호출**이다. API 키와 시크릿이 있어야 한다.
    브라우저에 키를 내려보내는 순간 그 키는 유출된 것으로 봐야 한다.
    그래서 계정성 데이터는 **예외 없이 서버가 대신 부른다.**

    ## 왜 합쳐서 주는가
    시안 상단(순자산)과 주문 패널(사용 가능)과 하단(증거금 비율·유지 증거금)이
    **전부 같은 `/fapi/v2/account` 한 방에서 나온다.** 칸마다 따로 부르면
    같은 응답을 3번 받는 꼴이다.

    ## 권장 폴링 주기: **5초** (`if (!document.hidden)` 안에서)
    Redis 캐시 15초를 `exchange_accounts.get_balance` 와 **같은 키**로 공유하므로
    (`binance:account_info:{id}`), 대시보드와 터미널을 같이 열어도 업스트림
    호출은 15초에 한 번이다.
    🚨 그러므로 3초로 당겨도 **값이 더 새로워지지 않는다** — 캐시 히트가 늘 뿐이고
       그만큼 FastAPI 워커·외부 Neon DB 왕복(활성 전략 조회)만 더 쓴다.
       「폴링을 캐시 TTL 보다 빠르게 돌리지 않는다」가 이 화면의 규칙이다.

    ## `our_available_balance` 주의
    활성 전략의 `total_capital` 합을 예약으로 본 **보수적 근사**다.
    `/exchange-accounts/{id}/balance` 는 여기에 더해 거래소 실 증거금
    (`positionRisk.isolatedWallet`)으로 상향 보정까지 한다 — 정밀한 값이
    필요하면 그쪽이 단일 진실이다. 여기서 그 보정을 복제하지 않은 이유는
    **같은 계산을 두 곳에 두면 반드시 어긋나기 때문**이다(이 저장소 반복 사고).
    """
    account = _pick_account(db, user_id, account_id)

    cache_key = f"binance:account_info:{account.id}"   # get_balance 와 캐시 공유
    info = _cache_get(cache_key)
    if not isinstance(info, dict):      # 공유 키 — 형식이 다르면 없는 것으로 본다
        info = None
    if info is None:
        bc = _client_for(account)
        try:
            info = bc.get_account()
        except Exception as e:
            raise _upstream_502("account", account.id) from e
        _cache_set(cache_key, info, ttl=15)

    total_wallet = _d(info.get("totalWalletBalance"))
    total_unreal = _d(info.get("totalUnrealizedProfit"))
    total_margin = _d(info.get("totalMarginBalance"))
    total_maint = _d(info.get("totalMaintMargin"))
    margin_ratio = (
        (total_maint / total_margin * 100).quantize(Decimal("0.01"))
        if total_margin > 0 else Decimal("0")
    )
    positions = info.get("positions") or []
    open_count = sum(1 for p in positions if _d(p.get("positionAmt")) != 0)

    actives = db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.exchange_account_id == account.id)
        .where(StrategyInstance.is_archived.is_(False))
        .where(StrategyInstance.status.notin_(TERMINAL_STATUSES))
    ).scalars().all()
    reserved = sum((s.total_capital or Decimal("0")) for s in actives) or Decimal("0")

    return AccountSummaryResponse(
        account_id=account.id,
        is_testnet=account.is_testnet,
        multiple_accounts=_account_count(db, user_id) > 1,
        fetched_at=_now_iso(),
        total_wallet_balance=str(total_wallet),
        total_unrealized_pnl=str(total_unreal),
        total_margin_balance=str(total_margin),
        available_balance=str(_d(info.get("availableBalance"))),
        our_available_balance=str(total_wallet - reserved),
        reserved_for_strategies=str(reserved),
        active_strategy_count=len(actives),
        total_position_initial_margin=str(_d(info.get("totalPositionInitialMargin"))),
        total_open_order_initial_margin=str(_d(info.get("totalOpenOrderInitialMargin"))),
        total_maint_margin=str(total_maint),
        margin_ratio_pct=str(margin_ratio),
        open_positions_count=open_count,
    )


# ═══════════════════════════════════════════════════════════════════════════
# 3) 포지션 — 거래소 실포지션 + 「어느 전략이 만들었나」
# ═══════════════════════════════════════════════════════════════════════════

# 전략 종류 → 사장님이 읽는 배지.
# 🚨 **접두사 매칭**이다. 정확 일치로 하면 안 된다 —
#    `strategies-list.js:894` 가 `=== 'auto_bb_break'` 정확 일치라서
#    접미사가 붙은 자동(`auto_bb_break_SAJANGNIM_TOP` 등)이 전부 「수동」으로
#    잘못 표시되고 있다. 여기서 그 실수를 반복하지 않는다.
_TYPE_BADGES: tuple[tuple[str, str], ...] = (
    ("auto_bb_break", "🤖 자동(BB이탈)"),
    ("pump_split", "🤖 볼밴분할"),
    ("bb_mid_line", "🤖 중단선"),
    ("surge_peak_ladder", "🤖 급등사다리"),
    ("realtime_reentry", "🤖 재진입"),
    ("sajangnim_top", "🤖 정점SHORT"),
    ("chart_pattern", "🤖 차트패턴"),
    ("terminal_manual", "👤 터미널"),
    ("DYNAMIC_", "👤 수동"),
    ("manual", "👤 수동"),
)

# `auto_bb_break` 접미사 → 세부 라벨
_SUFFIX_LABELS: tuple[tuple[str, str], ...] = (
    ("_SAJANGNIM_TOP", "정점SHORT"),
    ("_SAJANGNIM_BOTTOM", "저점LONG"),
    ("_UNIFIED_15M", "통합15m"),
    ("_PENDING_HC_FAST", "HC속행"),
    ("_OBV_HOLD", "OBV보류"),
    ("_success", "피라미딩"),
)


def _badge_for(strategy_type: str | None) -> tuple[str, str]:
    """(배지, 세부라벨). 모르는 값은 **원문 그대로** 돌려준다.

    🚨 fallback 이 중요하다. VPS 실서버에서 어떤 `strategy_type` 이 실제로 도는지
    이 작업에서는 확인하지 못했다(배포·SSH 금지). 매핑에 없는 값을 「수동」으로
    떨어뜨리면 자동 진입이 수동으로 둔갑한다 — 「모름」은 「모름」으로 보여야 한다.
    """
    st = str(strategy_type or "").strip()
    if not st:
        return "❔ 알 수 없음", ""
    detail = ""
    if st.startswith("auto_bb_break"):
        for suf, lab in _SUFFIX_LABELS:
            if suf in st:
                detail = lab
                break
        if not detail and "_reentry" in st:
            detail = "재진입"
    for prefix, badge in _TYPE_BADGES:
        if st.startswith(prefix):
            return badge, detail
    return st, detail   # 모르는 값 = 원문 노출 (조용히 뭉개지 않는다)


def _is_manual_template(template_name: str | None, strategy_type: str | None) -> bool:
    """수동 진입인가.

    판정 기준을 **두 개** 본다:
      · 템플릿 이름 `_quick_` / `TERMINAL_`  ← 사장님 모달 / 이 터미널이 만든 것
      · strategy_type `DYNAMIC_` / `manual`  ← 옛 전략

    🚨 백엔드 게이트(`chg24_entry_gate._is_manual`)는 **템플릿 이름 `_quick_` 만**
    본다. 이름과 타입이 어긋나면 화면 배지와 실제 게이트 적용이 달라진다 —
    그래서 아래 `gate_exempt_manual` 을 별도로 내려 「게이트가 실제로 면제되는가」를
    이름 기준으로 정확히 알려준다. 배지를 게이트 근거로 쓰지 말 것.
    """
    name = str(template_name or "")
    st = str(strategy_type or "")
    return name.startswith("_quick_") or name.startswith("TERMINAL_") \
        or st.startswith("DYNAMIC_") or st == "manual"


class TerminalPosition(BaseModel):
    """포지션 1행. 거래소 실데이터 + 우리 전략 정보."""

    symbol: str
    side: str                          # LONG / SHORT (헤지모드면 positionSide, 원웨이면 부호로 판정)
    position_side_raw: str | None = None   # 거래소 원본 (BOTH / LONG / SHORT)
    size: str                          # 절대값 수량
    entry_price: str | None = None
    mark_price: str | None = None
    liquidation_price: str | None = None
    leverage: int | None = None
    margin_mode: str | None = None     # ISOLATED / CROSSED — 하드코딩 금지, 실값
    isolated_wallet: str | None = None     # 원 증거금 (손익 무관)
    unrealized_pnl: str | None = None
    roi_pct: str | None = None         # 분모 = isolatedWallet (Fix 302)
    # ── 우리 전략 정보 (매칭 실패 시 전부 None) ──
    strategy_id: int | None = None
    template_name: str | None = None
    strategy_type: str | None = None
    badge: str | None = None
    badge_detail: str | None = None
    is_manual: bool | None = None
    gate_exempt_manual: bool | None = None   # `_quick_` = 24h 순위 게이트 면제 (실제 백엔드 기준)
    current_stage: int | None = None
    total_active_stages: int | None = None
    strategy_status: str | None = None
    tracked: bool = False              # False = 도구 밖 포지션 (청산 버튼 비활성 대상)


class PositionsResponse(BaseModel):
    account_id: int
    fetched_at: str
    positions: list[TerminalPosition]
    hedge_mode_enabled: bool


@router.get("/positions", response_model=PositionsResponse)
def get_terminal_positions(
    account_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> PositionsResponse:
    """보유 포지션 + 「어느 전략이 만들었나」.

    ## 🚨🚨 현재 이 엔드포인트는 **아무도 부르지 않는다** (2026-09-03 최종통합 확인)
    perp-terminal.html 의 포지션 표는 `/exchange-accounts/{id}/binance-positions` 와
    `/strategies` 를 받아 **프런트에서** 조인한다. 즉 아래에 적어 둔 「프런트마다
    조인 규칙이 달라져 어긋난다」가 **지금 실제로 벌어져 있는 상태**다 —
    같은 판정(배지·단계·잔량·tracked 여부)이 서버와 프런트 두 곳에 있다.
    이 저장소가 반복해서 당한 실패 방식이라 그대로 두면 안 된다.

    다음 사람에게: 둘 중 하나를 반드시 하라.
      (A) 프런트 renderPositions 를 이 엔드포인트로 옮기고 프런트 조인을 지운다 (권장)
      (B) 이 엔드포인트를 지운다
    실서버 검증 없이 (A) 를 하는 것이 더 위험해서 최종통합에서는 손대지 않았다.

    ## 왜 합쳐서 주는가
    포지션 행 하나에 거래소 값(수량·진입가·청산가)과 우리 값(전략 id·단계·자동/수동)이
    **같이** 있어야 의미가 있다. 프런트가 `/binance-positions` 와 `/strategies` 를
    각각 받아 조인하면 ①요청 2배 ②조인 규칙이 프런트마다 달라져 어긋난다.
    매칭 규칙은 `positions.py:88~92` 의 `tracked_set` 과 **같은 규칙**으로 서버에서
    한 번만 한다.

    ## 왜 브라우저가 직접 안 부르는가
    `/fapi/v2/positionRisk` 는 서명 호출 = API 키 필요.

    ## 왜 「도구 밖」을 같은 목록에 합치는가
    index.html 은 외부 포지션을 **별도 패널**로 뺐는데, 그러면 화면 하나에서
    전체 노출을 볼 수 없다. 여기서는 `tracked=false` 로 같은 표에 넣고,
    프런트가 「🚪 도구 밖」 배지 + **청산 버튼 비활성**으로 처리한다
    (`positions.py:37`: 도구 밖 포지션은 「가시성 only — 자동 청산/관리 대상 아님」).

    ## 권장 폴링 주기: **5초** (Redis 캐시 5초 — 실제 업스트림은 5초에 1회)
    weight 5 → 최대 12회/분 = 60 weight/분. 표시가·미실현손익은
    **WS markPrice 로 프런트가 덮어쓴다** — 이 응답의 `mark_price` 는 초기값일 뿐이다.
    그래서 폴링을 3초로 당겨 봐야 얻는 것이 없고 서버 CPU·DB 조회만 늘어난다.

    ## 🚨 캐시 키를 `exchange_accounts` 와 **공유**한다
    `binance:position_risk:{id}` 는 `/exchange-accounts/{id}/balance` 가 이미 쓰는
    키다(같은 5초 TTL). 여기서 `terminal:position_risk:{id}` 같은 **다른 키**를 쓰면
    똑같은 `/fapi/v2/positionRisk` 를 두 벌 받아 **업스트림이 정확히 2배**가 된다.
    터미널과 대시보드는 같이 열어 두는 화면이라 그 2배가 항상 발생한다.
    저장 형식도 그쪽에 맞춰 **bare list** 로 쓴다 (그쪽은 `for p in (data or [])`).

    ## 🚨 헤지모드 주의
    원웨이 모드면 `positionSide` 가 `BOTH` 라 방향을 못 만든다. 그때는
    `positionAmt` 부호로 판정한다(`exchange_accounts.py:747` 과 같은 방식).
    실계정의 `hedge_mode_enabled` 를 응답에 실어 프런트가 상황을 알 수 있게 했다.
    """
    account = _pick_account(db, user_id, account_id)

    # 🚨 `exchange_accounts.get_balance` 와 **같은 키**(위 docstring 참조).
    #    저쪽이 먼저 채워 놓았으면 여기서는 업스트림 호출이 아예 없다.
    cache_key = f"binance:position_risk:{account.id}"
    cached = _cache_get(cache_key)
    if cached is None:
        bc = _client_for(account)
        try:
            data = bc.get_position_risk()
        except Exception as e:
            raise _upstream_502("positions", account.id) from e
        if isinstance(data, dict):
            data = [data]
        cached = data or []
        _cache_set(cache_key, cached, ttl=5)
    # 공유 키라 저쪽이 쓴 형식(list)과 옛 우리 형식({"rows": [...]}) 둘 다 받는다.
    rows = cached if isinstance(cached, list) else (cached.get("rows") or [])

    # ── 우리 전략 인덱스: (SYMBOL, SIDE) → 전략 ─────────────────────────
    # ACTIVE_LIKE 만 본다. 종료 전략까지 매칭하면 옛 전략의 단계·배지가 붙는다.
    # 🚨 StrategyInstance 에는 `strategy_type` 컬럼이 **없다** — 템플릿에 있다.
    #    한 번의 조인으로 이름·타입·단계수를 같이 가져온다 (행마다 재조회 금지).
    stmt = (
        select(StrategyInstance, StrategyTemplate)
        .join(StrategyTemplate, StrategyTemplate.id == StrategyInstance.strategy_template_id, isouter=True)
        .where(StrategyInstance.exchange_account_id == account.id)
        .where(StrategyInstance.is_archived.is_(False))
        .where(StrategyInstance.status.in_(ACTIVE_LIKE))
    )
    index: dict[tuple[str, str], tuple[StrategyInstance, StrategyTemplate | None]] = {}
    for st_row, tpl_row in db.execute(stmt).all():
        key = ((st_row.symbol or "").upper(), (st_row.side or "").upper())
        # 같은 (심볼, 방향) 이 둘 이상이면 최신 것을 쓴다 (중복 가드가 있어 정상은 1건)
        prev = index.get(key)
        if prev is None or (st_row.id or 0) > (prev[0].id or 0):
            index[key] = (st_row, tpl_row)

    # 단계 총수 = 템플릿 `stages_config.capitals` 길이 (admin/templates.py:147 가 이 키로 저장).
    # 없으면 구 컬럼 stage1~4_capital 개수. 둘 다 없으면 **None** — 억지로 추정하지 않는다
    # (「모름」을 숫자로 채우면 화면이 거짓말을 한다).
    def _total_stages(tpl: StrategyTemplate | None) -> int | None:
        if tpl is None:
            return None
        cfg = tpl.stages_config or {}
        caps = cfg.get("capitals") if isinstance(cfg, dict) else None
        if isinstance(caps, list) and caps:
            return len(caps)
        n = sum(1 for i in (1, 2, 3, 4) if getattr(tpl, f"stage{i}_capital", None) is not None)
        return n or None

    out: list[TerminalPosition] = []
    for p in rows:
        sym = str(p.get("symbol") or "").upper()
        if not sym:
            continue
        amt = _d(p.get("positionAmt"))
        if amt == 0:
            continue

        ps_raw = str(p.get("positionSide") or "").upper() or None
        if ps_raw in ("LONG", "SHORT"):
            side = ps_raw
        else:
            side = "LONG" if amt > 0 else "SHORT"   # 원웨이(BOTH) → 부호로 판정

        entry = _d(p.get("entryPrice"))
        mark = _d(p.get("markPrice"))
        upnl = _d(p.get("unRealizedProfit"))
        liq = _d(p.get("liquidationPrice"))
        iso_wallet = _d(p.get("isolatedWallet"))
        # 🚨 Fix 302 와 같은 분모: isolatedWallet(원 자본, 손익 무관).
        #    isolatedMargin(= wallet + 미실현)을 쓰면 손실이 커질수록 분모가 같이
        #    작아져 손실률이 가속 왜곡된다 (실측 -49.85% 를 -99.39% 로 표시).
        roi = (upnl / iso_wallet * 100).quantize(Decimal("0.01")) if iso_wallet > 0 else None

        try:
            lev = int(p.get("leverage") or 0) or None
        except (TypeError, ValueError):
            lev = None

        item = TerminalPosition(
            symbol=sym,
            side=side,
            position_side_raw=ps_raw,
            size=str(abs(amt)),
            entry_price=_s(entry) if entry > 0 else None,
            mark_price=_s(mark) if mark > 0 else None,
            liquidation_price=_s(liq) if liq > 0 else None,
            leverage=lev,
            margin_mode=str(p.get("marginType") or "").upper() or None,
            isolated_wallet=_s(iso_wallet) if iso_wallet > 0 else None,
            unrealized_pnl=_s(upnl),
            roi_pct=_s(roi),
        )

        found = index.get((sym, side))
        if found:
            inst, tpl = found
            tpl_name = tpl.name if tpl else None
            stype = tpl.strategy_type if tpl else None
            badge, detail = _badge_for(stype)
            item.strategy_id = inst.id
            item.template_name = tpl_name
            item.strategy_type = stype
            item.badge = badge
            item.badge_detail = detail or None
            item.is_manual = _is_manual_template(tpl_name, stype)
            item.gate_exempt_manual = str(tpl_name or "").startswith("_quick_")
            item.current_stage = inst.current_stage
            item.total_active_stages = _total_stages(tpl)
            item.strategy_status = inst.status
            item.tracked = True
        else:
            item.badge = "🚪 도구 밖"
            item.tracked = False

        out.append(item)

    out.sort(key=lambda x: x.symbol)
    return PositionsResponse(
        account_id=account.id,
        fetched_at=_now_iso(),
        positions=out,
        hedge_mode_enabled=bool(account.hedge_mode_enabled),
    )


# ═══════════════════════════════════════════════════════════════════════════
# 4) 미체결 주문 (시안 「미체결 (3)」 탭)
# ═══════════════════════════════════════════════════════════════════════════

class TerminalOpenOrder(BaseModel):
    exchange_order_id: str | None = None
    client_order_id: str | None = None
    symbol: str
    side: str | None = None            # BUY / SELL
    position_side: str | None = None
    order_type: str | None = None
    price: str | None = None
    stop_price: str | None = None
    orig_qty: str | None = None
    executed_qty: str | None = None
    notional: str | None = None
    reduce_only: bool = False
    order_status: str | None = None
    time_ms: int | None = None
    # ── 우리 DB 매칭 (취소 버튼이 이걸 필요로 한다) ──
    our_order_id: int | None = None       # None 이면 취소 경로 없음 → 버튼 비활성
    our_strategy_id: int | None = None
    is_adhoc: bool = False                # stage_no IS NULL = 사장님 「💉 지정가」
    cancellable: bool = False             # our_order_id 와 our_strategy_id 가 둘 다 있을 때만


class OpenOrdersResponse(BaseModel):
    account_id: int
    symbol: str | None
    fetched_at: str
    orders: list[TerminalOpenOrder]
    count: int


@router.get("/open-orders", response_model=OpenOrdersResponse)
def get_terminal_open_orders(
    symbol: str | None = Query(default=None, max_length=30),
    account_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> OpenOrdersResponse:
    """미체결 주문 **행 목록**.

    ## 왜 새로 만드는가
    기존 `/exchange-accounts/{id}/binance-open-orders-summary` 는 **개수·명목
    합계만** 준다 (`exchange_accounts.py:951~962`). 시안의 미체결 테이블은
    행 단위 값이 필요해서 그 요약으로는 못 채운다.

    ## 왜 우리 DB 를 조인해서 주는가
    취소 버튼이 기존 `DELETE /strategies/{sid}/open-orders/{oid}` 를 부르려면
    **우리 `Order.id` 와 `strategy_instance_id`** 가 있어야 한다. 프런트가 이걸
    따로 조회할 방법이 없으므로 서버가 `client_order_id` 로 매칭해 붙여 준다.
    매칭이 안 되면 `cancellable=false` → 프런트는 버튼을 비활성화하고
    「Binance 앱에서 직접 취소」를 안내한다 (거래소에만 있는 도구 밖 주문).

    ## 왜 브라우저가 직접 안 부르는가
    `/fapi/v1/openOrders` 는 서명 호출 = API 키 필요.

    ## 🚨 weight — `symbol` 을 반드시 넘겨라
    symbol 지정 시 **1**, 미지정이면 **40** 이다 (`client.estimate_weight:145`).
    「현재 종목만 보기」가 켜져 있으면 프런트는 반드시 `symbol` 을 넘긴다.

    ## 권장 폴링 주기: **5초**
    캐시 TTL 을 symbol 유무로 **비대칭**으로 준다 (아래 구현부 주석 참조):
      · symbol 지정  → TTL  5초 → 최대 12회/분 × weight  1 =  12 weight/분
      · symbol 미지정 → TTL 30초 → 최대  2회/분 × weight 40 =  80 weight/분
    미지정에 5초를 주면 12 × 40 = **480 weight/분**이 되어 터미널 탭 5개가
    한도(2400)를 통째로 먹는다. 그래서 서버 쪽에서 스스로 조인다.
    """
    account = _pick_account(db, user_id, account_id)
    # 🚨 symbol 은 업스트림 쿼리 파라미터 + Redis 캐시 키로 둘 다 흘러간다 → 형식 검증.
    #    (인증은 걸려 있지만, 토큰 하나로도 자유 문자열이면 캐시 키를 무한히 만들 수 있다.)
    sym = _norm_symbol(symbol) if symbol else None

    cache_key = f"terminal:open_orders:{account.id}:{sym or 'ALL'}"
    cached = _cache_get(cache_key)
    if not isinstance(cached, dict):
        cached = None
    if cached is None:
        bc = _client_for(account)
        try:
            data = bc.list_open_orders(symbol=sym)
        except Exception as e:
            raise _upstream_502("open-orders", account.id) from e
        if isinstance(data, dict):
            data = [data]
        cached = {"rows": data or []}
        # ═══════════════════════════════════════════════════════════════
        # 🚨 TTL 을 symbol 유무로 **비대칭**으로 준다 — weight 가 40배 다르다.
        #
        #   symbol 지정 : weight 1  → 5초 캐시  = 최대 12회/분 =  12 weight/분
        #   symbol 미지정: weight 40 → 30초 캐시 = 최대  2회/분 =  80 weight/분
        #
        # 만약 미지정에도 5초를 주면 12회 × 40 = **480 weight/분** 이다.
        # Binance 한도가 분당 2400 이므로 **터미널 탭 5개가 한도를 다 먹는다.**
        # (Fix 124 거버너는 `/fapi/v1/openOrders` 를 「스캔」으로 분류하지 않아
        #  — 주문 관련이라 막으면 안 되기 때문에 — 여기서 스스로 조여야 한다.)
        #
        # 그래서 프런트는 「현재 종목만 보기」를 켜고 symbol 을 넘기는 것이
        # **기본**이어야 한다. 전체 조회는 사람이 눌러서 보는 화면이지
        # 초 단위로 도는 폴링이 아니다.
        # ═══════════════════════════════════════════════════════════════
        _cache_set(cache_key, cached, ttl=(5 if sym else 30))
    rows = cached.get("rows") or []

    # ── client_order_id → 우리 Order 매칭 ───────────────────────────────
    client_ids = {str(o.get("clientOrderId")) for o in rows if o.get("clientOrderId")}
    our_by_cid: dict[str, Order] = {}
    if client_ids:
        strategy_ids = db.execute(
            select(StrategyInstance.id)
            .where(StrategyInstance.exchange_account_id == account.id)
        ).scalars().all()
        if strategy_ids:
            for o in db.execute(
                select(Order)
                .where(Order.client_order_id.in_(client_ids))
                .where(Order.strategy_instance_id.in_(strategy_ids))
            ).scalars().all():
                our_by_cid[o.client_order_id] = o

    out: list[TerminalOpenOrder] = []
    for o in rows:
        osym = str(o.get("symbol") or "").upper()
        if not osym:
            continue
        price = _d(o.get("price"))
        qty = _d(o.get("origQty"))
        cid = str(o.get("clientOrderId") or "") or None
        ours = our_by_cid.get(cid) if cid else None
        out.append(TerminalOpenOrder(
            exchange_order_id=(str(o.get("orderId")) if o.get("orderId") is not None else None),
            client_order_id=cid,
            symbol=osym,
            side=(str(o.get("side") or "") or None),
            position_side=(str(o.get("positionSide") or "") or None),
            order_type=(str(o.get("type") or "") or None),
            price=_s(price),
            stop_price=(str(o.get("stopPrice")) if o.get("stopPrice") not in (None, "") else None),
            orig_qty=_s(qty),
            executed_qty=_s(_d(o.get("executedQty"))),
            notional=_s((price * qty).quantize(Decimal("0.00000001"))),
            reduce_only=bool(o.get("reduceOnly")),
            order_status=(str(o.get("status") or "") or None),
            time_ms=(int(o["time"]) if str(o.get("time") or "").isdigit() else None),
            our_order_id=(ours.id if ours else None),
            our_strategy_id=(ours.strategy_instance_id if ours else None),
            is_adhoc=bool(ours is not None and ours.stage_no is None),
            cancellable=bool(ours is not None),
        ))

    out.sort(key=lambda x: (x.symbol, -(x.time_ms or 0)))
    return OpenOrdersResponse(
        account_id=account.id,
        symbol=sym,
        fetched_at=_now_iso(),
        orders=out,
        count=len(out),
    )


# ═══════════════════════════════════════════════════════════════════════════
# 5) 심볼별 자동매매 관문 상태 — 주문 전 「미리보기」
# ═══════════════════════════════════════════════════════════════════════════

class Chg24Gate(BaseModel):
    enabled: bool
    mode: str | None = None            # "rank" | "abs"
    top_n: int | None = None
    min_abs: float | None = None
    passes: bool | None = None         # 🚨 None = 「모름」. 절대 False(=차단)로 뭉개지 않는다
    reason: str | None = None


class TrimInfo(BaseModel):
    enabled: bool
    keep_notional_usdt: str | None = None


class ReentryInfo(BaseModel):
    waiting: bool = False
    reason_ko: str | None = None
    rebound_pct: float | None = None
    rebound_need_pct: float | None = None
    stale: bool = True                 # True = 워커 기록 없음 (= 「대기 0건」과 다르다)


class SymbolStatusResponse(BaseModel):
    symbol: str
    fetched_at: str
    excluded: bool
    excluded_reason: str | None = None
    chg24_gate: Chg24Gate
    support_gate_enabled: bool
    trim: TrimInfo
    reentry: ReentryInfo


@router.get("/symbol-status", response_model=SymbolStatusResponse)
def get_symbol_status(
    symbol: str = Query(..., min_length=1, max_length=30),
    account_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> SymbolStatusResponse:
    """이 심볼이 지금 자동매매 관문을 통과하는가 — **읽기 전용**.

    ## 왜 필요한가 (이게 없으면 화면을 만들 수 없다)
    진입 게이트 설정은 전부 `SystemSetting` 에만 있고 **어떤 라우터·JS 로도
    노출된 적이 없다**(전수 grep 확인):
      `entry_chg24_gate_enabled` / `entry_chg24_gate_mode` / `entry_rank_top_n`
      / `support_score_gate_enabled` / `stage_trim_before_next_enabled`
      / `stage_keep_notional_usdt` / `excluded_symbols`
    그래서 지금은 터미널에서 BTCUSDT 를 골라 주문하면 **아무 예고 없이**
    `_place_stage_entry_order` 에서 400 으로 떨어진다
    (`execution_service.py:1927~1933`, Fix 303). 그 400 을 **누르기 전에** 보여준다.

    ## 왜 서버가 판정하는가
    게이트 판정 함수(`chg24_entry_gate.passes`)가 서버에만 있고, 그 안에서
    `bc.get_24hr_ticker()` 를 부른다. 프런트가 같은 판정을 재구현하면
    **화면과 실제 진입 판정이 갈라진다** — 이 저장소가 반복해서 겪은 사고다.

    ## 🚨 `template_name` 을 넘기지 않는 이유
    `chg24_entry_gate.passes(..., template_name=...)` 에 `_quick_` 이름을 넘기면
    **무조건 통과**로 나온다(`chg24_entry_gate.py:120` `_is_manual`).
    화면은 「자동 진입과 같은 판정」을 보여야 하므로 이름을 넘기지 않는다.

    ## 🚨 「모름」과 「차단」을 다르게 준다
    게이트 조회가 실패하면 `passes=null` + 사유 문자열이다. `false` 로 떨어뜨리면
    고장이 「정상 차단」으로 보인다 — 이 저장소는 「모름」을 「꺼짐」으로 표시한
    fail-OFF 사고를 겪었다(2026-08-28).

    ## 서버 부하 — 정상 상황에서는 사실상 0, 단 Redis 가 전제다
    `bc.get_24hr_ticker()`(symbol 없이 = **weight 40**)는 Fix 117 **Redis 30초
    공유 캐시**를 탄다(`client.py:65` `_TICKER_ALL_TTL_SEC = 30`). 그 캐시는
    30초 주기 워커 3개가 항상 데워 두므로 이 엔드포인트가 만드는 추가 업스트림은
    보통 **0**이다. 나머지는 전부 DB/Redis 조회다.

    🚨 **Redis 가 죽으면 이 계산이 통째로 무너진다.** 캐시도 없고 Fix 124 거버너의
       카운터도 Redis 라 스로틀도 안 걸려, 폴링 1회 = weight 40 이 그대로 나간다.
       15초 폴링이면 탭 1개당 160 weight/분. 탭 여러 개면 한도(2400)를 위협한다.
       → 폴링 주기를 여기서 임의로 당기지 말 것. 화면은 15초로 고정돼 있다.

    ## 권장 폴링 주기: **15초** (심볼 변경 시 즉시 1회 추가)
    게이트 설정은 사람이 손으로 바꾸는 값이라 초 단위로 볼 이유가 없다.

    ## 이 엔드포인트는 주문을 만들지 않는다. 상태만 읽는다.
    """
    # 🚨 이 심볼은 `chg24_entry_gate.passes` 를 통해 `bc.get_24hr_ticker()` 로 흘러간다
    #    (= 업스트림 호출 + Redis 캐시 키). 자유 문자열을 그대로 내려보내지 않는다.
    sym = _norm_symbol(symbol)

    # ── Fix 303 제외 심볼 ───────────────────────────────────────────────
    try:
        from app.services.symbol_exclusion import is_excluded
        excluded = bool(is_excluded(db, sym))
    except Exception:
        logger.warning("terminal symbol-status 제외목록 조회 실패 symbol=%s", sym, exc_info=True)
        excluded = False
    excluded_reason = (
        "자동매매 제외 심볼 (Fix 303) — MIN_NOTIONAL 이 커서 「10 USDT 잔량 유지」가 불가능합니다"
        if excluded else None
    )

    # ── Fix 310/325 24h 순위 게이트 ─────────────────────────────────────
    gate = Chg24Gate(enabled=False)
    try:
        from app.services import chg24_entry_gate as g
        gate.enabled = bool(g.gate_enabled(db))
        gate.mode = g.gate_mode(db)
        gate.top_n = g.top_n(db)
        gate.min_abs = g.min_abs_chg24(db)
        if not gate.enabled:
            gate.passes = True
            gate.reason = "게이트 꺼짐 (모든 심볼 통과)"
        else:
            # 🚨 계정이 없으면 **판정 자체가 불가능**하다 — 「통과」로도 「차단」으로도
            #    적지 않는다. 사유를 구체적으로 남겨 화면이 원인을 말할 수 있게 한다.
            try:
                account = _pick_account(db, user_id, account_id)
            except HTTPException:
                account = None
            if account is None:
                gate.passes = None
                gate.reason = "활성 거래소 계정이 없어 24h 순위를 조회할 수 없습니다"
            else:
                bc = _client_for(account)
                ok, reason = g.passes(db, bc, sym, template_name=None)
                gate.passes = bool(ok)
                gate.reason = reason or None
    except Exception:
        logger.warning("terminal symbol-status 24h 게이트 판정 실패 symbol=%s", sym, exc_info=True)
        gate.passes = None                          # 🚨 「모름」 — false 로 뭉개지 않는다
        gate.reason = "게이트 상태를 확인하지 못했습니다 (조사 필요)"

    # ── Fix 327 지지선 게이트 (on/off 만 — 판정은 진입 시점 캔들 기준) ──
    try:
        from app.services.support_score import gate_enabled as support_gate_enabled
        support_on = bool(support_gate_enabled(db))
    except Exception:
        logger.warning("terminal symbol-status 지지선 게이트 조회 실패", exc_info=True)
        support_on = False

    # ── Fix 304~318 부분손절 잔량 설정 ──────────────────────────────────
    trim = TrimInfo(enabled=False)
    try:
        from app.services import stage_trim as stg
        trim.enabled = bool(stg.trim_enabled(db))
        trim.keep_notional_usdt = str(stg.keep_notional(db))
    except Exception:
        logger.warning("terminal symbol-status 부분손절 설정 조회 실패", exc_info=True)

    # ── Fix 301 재진입 대기 (이 심볼 1건만) ─────────────────────────────
    # 전체 목록은 index.html 의 Fix 301 패널과 중복이라 넣지 않는다.
    reentry = ReentryInfo()
    try:
        from app.api.v1.reentry_alerts import _reason_ko
        from app.workers.realtime_reentry_worker import WATCHLIST_REDIS_KEY
        data = _cache_get(WATCHLIST_REDIS_KEY)
        if isinstance(data, dict):
            reentry.stale = False
            for it in (data.get("items") or []):
                if not isinstance(it, dict):
                    continue
                if str(it.get("symbol") or "").upper() != sym:
                    continue
                reentry.waiting = not bool(it.get("entered"))
                reentry.reason_ko = "진입함" if it.get("entered") else _reason_ko(it.get("reason"))
                reentry.rebound_pct = it.get("rebound_pct")
                reentry.rebound_need_pct = it.get("rebound_need_pct")
                break
    except Exception:
        logger.warning("terminal symbol-status 재진입 감시 조회 실패", exc_info=True)

    return SymbolStatusResponse(
        symbol=sym,
        fetched_at=_now_iso(),
        excluded=excluded,
        excluded_reason=excluded_reason,
        chg24_gate=gate,
        support_gate_enabled=support_on,
        trim=trim,
        reentry=reentry,
    )


# ═══════════════════════════════════════════════════════════════════════════
# 6) 능력 선언 — 프런트가 주문 버튼을 켤지 끌지 결정하는 근거
# ═══════════════════════════════════════════════════════════════════════════

class OrderPathStep(BaseModel):
    step: int
    method: str
    path: str
    note: str


class CapabilitiesResponse(BaseModel):
    can_place_order: bool
    reason: str
    order_path: list[OrderPathStep]
    template_name_prefix: str
    strategy_type: str
    idempotency_header: str
    disabled_order_types: list[str]
    disabled_order_types_reason: str
    notes: list[str]


@router.get("/capabilities", response_model=CapabilitiesResponse)
def get_capabilities(user_id: int = Depends(get_current_user_id)) -> CapabilitiesResponse:
    """터미널이 무엇을 할 수 있는지 — 프런트는 이 응답만 보고 버튼을 켠다.

    ## 🚨 왜 서버에 「주문 발주 엔드포인트」를 만들지 않았는가

    주문 경로는 확정됐다(아래 `order_path`). 그런데 그 3단계를 감싸는 서버
    래퍼를 **일부러 만들지 않았다.** 이유 셋:

      1. **한글 사유가 뭉개진다.** 세 단계가 각각 다른 이유로 400 을 낸다.
         ②는 8개 안전 게이트(중복 전략 / Kill-Switch / 레버리지 상한 /
         화이트리스트 / 동시 상한 / 거래소 통신 fail-closed / 실포지션 잔재 /
         잔액·예약자본, `strategy_service.py:140~325`), ③은 24h 순위 게이트와
         제외 심볼(`execution_service.py:207~228`, `:1927`). 이 문구들을
         **가공하지 말고 그대로** 사장님에게 보여야 한다. 하나로 감싸면
         「어느 관문에서 막혔는지」가 사라진다.
      2. **두 번째 주문 경로가 생긴다.** 실자금 시스템에 검증 없이 새 주문
         경로를 추가하는 것은 이 저장소가 반복해서 손해 본 패턴이다
         (헌법 69/70/71 = 실 검증 전에는 완료가 아니다). 이 작업에서는
         실주문 검증이 금지돼 있어 **검증할 방법 자체가 없다.**
      3. **부분 실패가 남는다.** ①만 성공하고 ②가 400 이면 템플릿 행이
         고아로 남는다. 프런트가 단계별로 진행하면 어디서 멈췄는지 그대로 보인다.

    → 그래서 `can_place_order=true` 이되, **프런트가 기존 3-콜 체인을 직접**
      탄다. 참조 구현이 이미 있다: `app/static/js/cm-submit.js:202/251/289`.
      raw `BinanceClient.place_order` 는 어떤 경우에도 부르지 않는다 —
      그건 위 8개 게이트 + 손절/부분손절/TP 사다리/force SL 을 전부 우회한다.
      실측이 「수동 진입 = 전체 손실의 94.3%」라고 말하고 있다.

    ## 🚨 템플릿 이름 접두어를 `_quick_` 으로 하지 않는 이유
    `chg24_entry_gate._is_manual` 이 `_quick_` 이면 24h 순위 게이트를
    **통과**시킨다(`chg24_entry_gate.py:120`). 터미널이 그 이름을 쓰면
    「기존 전략 경로를 태워 게이트가 그대로 걸리게 한다」는 이 작업의 취지가
    정면으로 무너진다. 그래서 `TERMINAL_<yyyymmddhhmmss>_<모달키4자>` 를 쓴다.
    (뒤 4자는 2026-09-03 추가 — `strategy_templates.name` 이 UNIQUE 라 같은 초에
     두 번 확인하면 IntegrityError 로 500 이 났다.)

    ## 권장 호출: 페이지 로드 시 **1회** (거래소 호출 없음)
    """
    return CapabilitiesResponse(
        can_place_order=True,
        reason=(
            "주문은 기존 전략 생성 3-콜 체인으로만 나갑니다 (손절·TP·진입 게이트가 "
            "그대로 걸립니다). 프런트가 단계별로 직접 호출하며, 각 단계의 400 한글 "
            "사유를 가공 없이 그대로 표시해야 합니다."
        ),
        order_path=[
            OrderPathStep(
                step=1, method="POST", path="/api/v1/admin/strategy-templates",
                note="템플릿 생성. name=TERMINAL_<yyyymmddhhmmss>_<모달키4자> (UNIQUE 충돌 방지), "
                     "capitals/trigger_percents/additional_margins 길이 일치 필수 (아니면 400). "
                     "②가 실패하면 이 템플릿을 DELETE 해서 고아를 남기지 말 것.",
            ),
            OrderPathStep(
                step=2, method="POST", path="/api/v1/strategies",
                note="전략 인스턴스 생성. 여기서 8개 안전 게이트가 전부 걸린다. "
                     "실패는 400 + 한글 detail — 그대로 모달에 노출할 것.",
            ),
            OrderPathStep(
                step=3, method="POST", path="/api/v1/strategies/{id}/start",
                note="1단계 LIMIT 주문 발송. 24h 순위 게이트(Fix 310/325) / 지지선 게이트"
                     "(Fix 327) / 제외 심볼(Fix 303)이 여기서 걸린다.",
            ),
        ],
        template_name_prefix="TERMINAL_",
        strategy_type="terminal_manual",
        idempotency_header="Idempotency-Key",
        disabled_order_types=["MARKET", "STOP_LIMIT"],
        disabled_order_types_reason=(
            "전략 생성 경로는 1단계 LIMIT(start_price) 진입만 지원합니다. "
            "시장가·스탑 지정가에 대응하는 파라미터가 StrategyCreateRequest / "
            "StrategyTemplateCreate 에 없습니다."
        ),
        notes=[
            "확인 모달 없이는 어떤 POST 도 보내지 않는다 (심볼·방향·수량·금액·레버리지·"
            "예상청산가 재표시 + 명시적 「확인」).",
            "확인 시 POST 에 Idempotency-Key 헤더(crypto.randomUUID())를 붙인다. "
            "1시간 중복 방지, 같은 키에 다른 payload 면 409 (app/middleware/idempotency.py).",
            "「예상 청산가」는 진입 전 정확 계산 불가 — MMR 티어 테이블이 저장소에 없다. "
            "「근사」 라벨을 붙이거나 「진입 후 표시」로 둘 것.",
            "capital = 증거금(margin), qty = capital × leverage / price (헌법 v107). "
            "검산은 POST /api/v1/strategies/preview-inline.",
            "「교차 마진」은 하드코딩하지 말고 /terminal/positions 의 margin_mode 실값을 쓸 것.",
            "입금 / 현물 / 스테이킹 / 마켓 / 자산 은 대응 기능이 없다 — 비활성 처리.",
        ],
    )
