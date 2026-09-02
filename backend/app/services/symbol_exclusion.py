"""🚫 자동매매 제외 심볼 — 사장님 2026-09-03 지시 (Fix 303).

## 사장님 원문

    "BTCUSDT / BTCUSDC / BTCUSD1   50   50 USDT
     ETHUSDT / ETHUSDC / LTCUSDT / LINKUSDT / ETCUSDT / BCHUSDT   20   20 USDT
     이것들은 포지션에서 제외해줘"

## 왜 이 종목들인가 — 실측

사장님 사양은 **「모든 단계에서 10 USDT 만 남기고 청산하고 다음 단계 진입」** 이다.
그런데 거래소 `MIN_NOTIONAL` 이 10 을 넘는 종목에서는 10 USDT 잔량을 남길 수 없다.
남기면 그 잔량은 reduceOnly 주문이 거부되어 **영원히 팔 수 없는 dust** 가 된다.
(이 저장소는 dust orphan 하나로 계정 전체가 막힌 전력이 있다.)

754심볼 전수 검산 (2026-09-03, 실시세 기준):

    ✅ 10 USDT 잔량 그대로 가능        743개  (98.5%)
    ⚠️ MIN_NOTIONAL > 10                9개  (1.2%)   ← 사장님이 제외 지시
    ⚠️ stepSize 로 10 을 못 맞춤         2개  (0.3%)   ← 같은 이유로 함께 제외

    MIN_NOTIONAL 50 : BTCUSDT, BTCUSDC, BTCUSD1
    MIN_NOTIONAL 20 : ETHUSDT, ETHUSDC, LTCUSDT, LINKUSDT, ETCUSDT, BCHUSDT
    stepSize 0.001  : BTCUSDT_261225, BTCUSDT_260925  (분기 선물, 최소 잔량 ≈ 78 USDT)

## 제외해도 잃는 것 (실측)

    30일간 이 종목 진입 = 9건 / 손익 +54.86 USDT   (전체의 1% 미만)
    지시 시점 열린 포지션 = **0건**  → 기존 포지션에 영향 없음

## 설계

- 기본 목록은 **코드에 박아 둔다**. 설정 조회가 실패해도 제외는 계속 적용돼야
  한다 — 여기서 fail-open 하면 사장님이 빼라고 한 종목에 자금이 들어간다.
- 설정 `excluded_symbols` 가 있으면 그것으로 **대체**한다 (사장님이 목록을 완전히
  통제). 빈 문자열을 넣으면 제외 없음 = 명시적 해제.
- 🚨 **기존 포지션은 건드리지 않는다.** 이 모듈은 **신규 진입만** 막는다.
  이미 열린 포지션을 코드가 임의로 청산하는 것은 실제 자금 조작이고,
  그건 사장님 판단이어야 한다.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = [
    "SETTING_KEY", "DEFAULT_EXCLUDED",
    "excluded_symbols", "is_excluded", "drop_excluded",
]

SETTING_KEY = "excluded_symbols"      # 콤마 구분. 있으면 기본 목록을 **대체**한다.

DEFAULT_EXCLUDED: frozenset[str] = frozenset({
    # MIN_NOTIONAL 50 — 10 USDT 잔량 불가
    "BTCUSDT", "BTCUSDC", "BTCUSD1",
    # MIN_NOTIONAL 20 — 10 USDT 잔량 불가
    "ETHUSDT", "ETHUSDC", "LTCUSDT", "LINKUSDT", "ETCUSDT", "BCHUSDT",
    # stepSize 0.001 x 고가 = 최소 잔량 ≈ 78 USDT — 같은 이유
    "BTCUSDT_261225", "BTCUSDT_260925",
})


def _norm(s: object) -> str:
    return str(s or "").strip().upper()


def excluded_symbols(db) -> frozenset[str]:
    """제외 목록. 설정이 있으면 그것으로 대체, 없거나 실패하면 기본 목록.

    🚨 조회 실패 시 **기본 목록을 그대로 쓴다** (제외가 계속 걸린다).
       빈 집합으로 떨어뜨리면 사장님이 빼라고 한 종목에 자금이 들어간다.
    """
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, SETTING_KEY)
        if row is None or row.value is None:
            return DEFAULT_EXCLUDED
        raw = str(row.value).strip()
        if not raw:
            # 명시적 빈 값 = 사장님이 제외를 해제한 것
            return frozenset()
        return frozenset(_norm(x) for x in raw.split(",") if _norm(x))
    except Exception as e:
        logger.warning("[Fix303] %s 조회 실패 → 기본 목록 유지: %s", SETTING_KEY, e)
        return DEFAULT_EXCLUDED


def is_excluded(db, symbol: object) -> bool:
    """이 심볼이 자동매매 제외 대상인가."""
    sym = _norm(symbol)
    if not sym:
        # 심볼을 모르면 막는다 — 알 수 없는 대상에 자금을 넣지 않는다
        return True
    return sym in excluded_symbols(db)


def drop_excluded(db, rows, *, key="symbol", tag: str = "") -> list:
    """후보 목록에서 제외 심볼을 걷어낸다. 몇 건을 왜 뺐는지 로그로 남긴다.

    `key` 는 dict 키 또는 객체 속성 이름. 둘 다 지원한다.
    """
    ex = excluded_symbols(db)
    if not ex:
        return list(rows or [])

    def _sym_of(r):
        return _norm(r.get(key)) if isinstance(r, dict) else _norm(getattr(r, key, None))

    out, dropped = [], []
    for r in (rows or []):
        if _sym_of(r) in ex:
            dropped.append(_sym_of(r))
        else:
            out.append(r)
    if dropped:
        logger.info(
            "[Fix303]%s 제외 심볼 %d건 스킵: %s",
            f" {tag}" if tag else "", len(dropped), ", ".join(sorted(set(dropped))),
        )
    return out
