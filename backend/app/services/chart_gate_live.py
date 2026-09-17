"""🎯 Fix 376 (2026-09-17 사장님) — 실매매 워커에도 차트 자리 게이트.

사장님 verbatim: "실매매 워커에도 차트 게이트 적용해줘"

판정 규칙은 Fix 375 `entry_conditions` 그대로다 (가상 22,652건 재계산 · 사전등록 이후 검증):
  SHORT = 1시간봉 16개 고점 −3% 이내 & 일봉 볼밴 추세 UP 아님
  LONG  = 24h −5% 이하 급락 뒤 또는 5분봉 48개 고점 대비 −4% 이하 조정 뒤
가상매매 계열 개선: 정점 SHORT(confirm_peak_111) 통과 ROI +4.74 vs 막힘 +2.25 · 저점 LONG(bottom_331) −0.50 vs −3.15.

적용 지점 = **`StrategyService.create_strategy_instance` 한 곳** (자동 전략 인스턴스를 만드는 유일한 곳 — 2026-09-16 grep).
  자동매매 중단 게이트(Fix 371) 바로 뒤 · 가족별 하루 최대(advisory lock) **앞** — 봉 조회 동안 DB 잠금을 쥐지 않는다.
  사람이 만든 전략(entry_origin=manual_modal 등, auto_family_registry.family_for = None)은 보지 않는다.
  규칙 가족(rf_*)은 제외 — 규칙 가족 워커가 가상행 snapshot 으로 이미 판정했다(Fix 375).
  ⚠️ 이미 있는 포지션에 대한 추가·다음 단계·반전 진입(저항 반전·전고점 돌파의 단계 진입 등)은 새 인스턴스가 아니라 이 게이트를 지나지 않는다.

모드 (가족별, system_settings — 재시작 불필요):
  `<가족키>_chart_gate` = off | shadow(판정만 기록) | on(차트 자리가 아니면 전략을 만들지 않음)
  행이 없으면 `chart_gate_default`, 그것도 없으면 **on** (사장님 「적용해줘」 · 진입을 줄이기만 한다 — Claude가 정함).
막힘 오류 = ValueError(「차트 자리 게이트」) — `auto_family_registry.is_limit_error` 가 같이 알아본다
  → 하루 최대와 똑같이 「영구 실패」가 아니라 「다음에 다시」로 처리된다 (재진입 워커 등 기존 처리 재사용).

API 부담 (IP ban 418 전력):
  봉 3번(1d 60 · 1h 60 · 5m 120 = 무게 4). 판정은 (심볼, 방향)별 Redis 캐시 5분 · 조회 실패는 1분.
  계정 ban 중이면 조회하지 않고 unknown(= on 이면 막음). BinanceClient 자체에도 IP ban 회로 차단기가 있다(Fix 116).
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

FIX = "Fix376"
BLOCK_TAG = "차트 자리 게이트"
DEFAULT_KEY = "chart_gate_default"
DEFAULT_MODE = "on"
CACHE_TTL = 300
CACHE_TTL_UNKNOWN = 60
SHADOW_TTL = 7 * 86400
LIMITS = {"1d": 60, "1h": 60, "5m": 120}
FORCE_MODE: str | None = None           # 테스트 전용 — None 이면 설정을 읽는다 (tests/conftest.py 가 "off" 로 둔다: 네트워크 금지)


def _setting(db: Any, key: str) -> str | None:
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, key)
        v = None if row is None or row.value is None else str(row.value).strip().lower()
        return v or None
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] %s 조회 실패: %s", FIX, key, e)
        return None


def mode_for(db: Any, fam_key: str) -> str:
    """가족 모드. 손상 값은 무시하고 다음 단계로 (가족 → 기본 키 → on)."""
    if FORCE_MODE is not None:
        return FORCE_MODE
    for key in (f"{fam_key}_chart_gate", DEFAULT_KEY):
        v = _setting(db, key)
        if v in ("off", "shadow", "on"):
            return v
    return DEFAULT_MODE


def _is_rule_family(fam_key: str) -> bool:
    try:
        from app.services.rule_families import FAMILY_BY_KEY
        return fam_key in FAMILY_BY_KEY
    except Exception:  # noqa: BLE001
        return fam_key.startswith("rf_")


def _chg24_from_1h(raw: list) -> float | None:
    """24h 변동 % ≈ 마지막(진행 중 포함) 1시간봉 종가 / 24봉 전 종가 − 1 (가상매매는 티커 값 — 근사)."""
    try:
        if len(raw) < 25:
            return None
        a, b = float(raw[-25][4]), float(raw[-1][4])
        return (b / a - 1) * 100 if a > 0 else None
    except (TypeError, ValueError, IndexError):
        return None


def _client_for(db: Any, exchange_account_id: int | None):
    from sqlalchemy import select
    from app.core.crypto import decrypt_text
    from app.integrations.binance.client import BinanceClient
    from app.models.exchange_account import ExchangeAccount
    q = select(ExchangeAccount)
    q = q.where(ExchangeAccount.id == exchange_account_id) if exchange_account_id else q.where(ExchangeAccount.is_testnet.is_(False))
    acc = db.execute(q).scalars().first()
    if acc is None:
        return None
    return BinanceClient(api_key=decrypt_text(acc.api_key_enc), api_secret=decrypt_text(acc.api_secret_enc),
                         is_testnet=bool(acc.is_testnet))


def judge(db: Any, *, symbol: str, side: str, exchange_account_id: int | None = None,
          client: Any = None, redis_client: Any = None, family: str | None = None) -> dict[str, Any]:
    """{"verdict","why","features","source"} — 캐시 → 조회. 예외를 올리지 않는다(실패 = unknown)."""
    from app.services import chart_state as CS
    from app.services import entry_conditions as EC
    side = str(side or "").upper()
    key = f"chart_gate:live:{symbol}:{side}" + (f":{family}" if family and family in EC.FAMILY_RULES else "")
    r = redis_client
    if r is None:
        try:
            from app.core.redis_client import get_redis_client
            r = get_redis_client()
        except Exception:  # noqa: BLE001
            r = None
    if r is not None:
        try:
            hit = r.get(key)
            if hit:
                out = json.loads(hit)
                out["source"] = "cache"
                return out
        except Exception:  # noqa: BLE001
            pass

    out: dict[str, Any]
    try:
        if exchange_account_id:
            from app.core.api_backoff import is_account_banned
            if is_account_banned(exchange_account_id, r):
                return {"verdict": "unknown", "why": ["api_ban"], "features": {}, "source": "ban"}
        bc = client if client is not None else _client_for(db, exchange_account_id)
        if bc is None:
            out = {"verdict": "unknown", "why": ["no_client"], "features": {}}
        else:
            raw = {iv: bc.get_klines(symbol=symbol, interval=iv, limit=n) for iv, n in LIMITS.items()}
            now_ms = int(time.time() * 1000)
            cs = CS.capture(None, symbol, side, now_ms=now_ms, klines=raw, include_1m=False,
                            th=CS.thresholds(db), intervals=("1d", "1h", "5m"))
            out = EC.evaluate(side, {"chart_state": cs}, chg_24h=_chg24_from_1h(raw.get("1h") or []), p=EC.params(db),
                              family=family)
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] %s %s 차트 조회 실패 → unknown: %s", FIX, symbol, side, e)
        out = {"verdict": "unknown", "why": [f"fetch_error: {str(e)[:80]}"], "features": {}}
    out["source"] = "fetch"
    if r is not None:
        try:
            r.setex(key, CACHE_TTL if out["verdict"] != "unknown" else CACHE_TTL_UNKNOWN, json.dumps(out, default=str))
        except Exception:  # noqa: BLE001
            pass
    return out


def precheck(db: Any, *, fam_key: str, symbol: str, side: str, exchange_account_id: int | None = None) -> tuple[bool, dict]:
    """워커가 자기 한도·쿨다운을 쓰기 **전에** 물어보는 용도. (막힐 것인가, 판정)."""
    mode = mode_for(db, fam_key)
    if mode == "off" or _is_rule_family(fam_key):
        return False, {"mode": mode}
    res = judge(db, symbol=symbol, side=side, exchange_account_id=exchange_account_id, family=fam_key)
    from app.services.entry_conditions import blocks
    return blocks(mode, res), {"mode": mode, **res}


def check(db: Any, *, strategy_type: str | None, template_name: str | None, entry_origin: str | None,
          symbol: str, side: str, exchange_account_id: int | None, where: str = "전략 생성") -> dict | None:
    """자동 전략 생성 직전 판정. on 이고 차트 자리가 아니면 ValueError. 사람 전략·규칙 가족 = None."""
    from app.services import auto_family_registry as AF
    from app.services.entry_conditions import blocks
    fam = AF.family_for(strategy_type=strategy_type, template_name=template_name, entry_origin=entry_origin)
    if fam is None or _is_rule_family(fam.key):
        return None
    try:
        from app.services.auto_trading_halt import halt_enabled
        if halt_enabled(db):
            return None          # 자동 생성은 뒤의 Fix 371 게이트가 어차피 막는다 — 봉을 조회하지 않는다
    except Exception:  # noqa: BLE001
        pass
    mode = mode_for(db, fam.key)
    if mode == "off":
        return {"mode": "off", "family": fam.key}
    res = judge(db, symbol=symbol, side=side, exchange_account_id=exchange_account_id, family=fam.key)
    res = {"mode": mode, "family": fam.key, **res}
    if mode == "shadow":
        try:
            from app.core.redis_client import get_redis_client
            get_redis_client().setex(f"chart_gate:shadow:{fam.key}:{symbol}:{int(time.time())}", SHADOW_TTL,
                                     json.dumps({"side": side, **res}, default=str))
        except Exception:  # noqa: BLE001
            pass
    if blocks(mode, res):
        why = ", ".join(res.get("why") or []) or res.get("verdict")
        logger.info("[%s] ⛔ %s %s %s %s 차단 — %s", FIX, fam.label, symbol, side, where, why)
        raise ValueError(f"⛔ [{BLOCK_TAG}] {fam.label} {symbol} {side} 차트 자리 아님 — {why} "
                         f"(조정: system_settings {fam.key}_chart_gate)")
    logger.info("[%s] %s %s %s 차트 %s (%s · %s)", FIX, fam.label, symbol, side, res.get("verdict"), mode, res.get("source"))
    return res


def is_gate_error(exc: BaseException | str) -> bool:
    return BLOCK_TAG in str(exc)
