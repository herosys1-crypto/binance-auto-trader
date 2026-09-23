"""📊 Fix 380 (2026-09-19 사장님) — 볼밴 계열 실매매에 「세력 CCI 방향」 게이트.

사장님: "우리 모든자동매매 거래에 적용해주고 특히 볼밴전략도 적극적으로 적용해줘" (첨부 전략서 「볼린저 밴드 & 세력 CCI」)
        → 선택 「실매매 볼밴 계열에 바로 적용」

검증 (docs/learning/BB_FORCE_CCI_2026-09-19.md · 404종목 · 모든 자리 83,927개):
  · 전략서 그대로(스퀴즈 돌파·눌림목 + 전략서 청산)는 12개 변형 전부 두 기간 손실 → 진입 방아쇠는 쓰지 않는다.
  · 두 기간 모두 방향이 맞은 부품 = **세력 CCI 방향**:
      LONG 은 세력 CCI > 0 일 때만 : 통과 +0.61 / +0.18 vs 제외 −0.44 / −0.15 (무작위 대비 · 10일 중 6일 우세)
      SHORT 은 세력 CCI < 0 일 때만 : 통과 +0.44 / +0.18 vs 제외 −0.62 / −0.22
    효과는 작다 → 기본은 **shadow(판정만 기록)**, 켜기(on)는 관제실에서 사장님이 가족별로.

세력 CCI (전략서 그대로, 1시간 완성봉):
  TP = (고가+저가+종가)/3 · MB = SMA(TP, 20) · MD = 평균 |TP − MB| · CCI = (TP − MB) / (0.015·MD)
  VW = clip(거래량 / SMA(거래량, 20), 0.5, 3.0) · 세력 CCI = CCI × VW  (마지막 완성봉 값)

적용 지점 = `StrategyService.create_strategy_instance` — 차트 자리 게이트(Fix 376) 바로 뒤 · 계좌 조회 앞.
대상 = 볼밴 계열 5 가족만: 볼밴 분할 · 볼밴 스윙 · 볼밴 중단선 · BB 이탈 자동 · BB 손절 뒤 재진입.
  사람 전략 · 규칙 가족 · 다른 계열은 보지 않는다. 기존 포지션의 추가·다음 단계는 새 인스턴스가 아니라 지나지 않는다.
모드 = `<가족>_force_cci_gate` → `force_cci_gate_default` → **shadow** (Claude가 정함).
막힘 = ValueError(「세력 CCI 게이트」) — `auto_family_registry.is_limit_error` 가 「다음에 다시」로 알아본다.
API = 1시간봉 60개 1번(무게 1) · (심볼) Redis 캐시 5분(실패 1분) · 계정 ban 중이면 조회 안 함(unknown).
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Sequence

logger = logging.getLogger(__name__)

FIX = "Fix380"
BLOCK_TAG = "세력 CCI 게이트"
DEFAULT_KEY = "force_cci_gate_default"
DEFAULT_MODE = "shadow"
BB_FAMILIES: tuple[str, ...] = ("pump_split", "bb_swing", "bb_mid_line", "bb_break", "bb_reentry")
N = 20
VW_LO, VW_HI = 0.5, 3.0
LIMIT_1H = 60
CACHE_TTL = 300
CACHE_TTL_UNKNOWN = 60
SHADOW_TTL = 7 * 86400
FORCE_MODE: str | None = None           # 테스트 전용 (tests/conftest.py 가 "off" — 네트워크 금지)


def force_cci(bars: Sequence[Sequence[float]], n: int = N) -> float | None:
    """마지막 봉의 세력 CCI. bars = [t,o,h,l,c,v] 완성봉. 봉이 모자라거나 평균편차 0 이면 None."""
    if len(bars) < n:
        return None
    win = [list(map(float, b[:6])) for b in bars[-n:]]
    tp = [(b[2] + b[3] + b[4]) / 3 for b in win]
    mb = sum(tp) / n
    md = sum(abs(x - mb) for x in tp) / n
    if md <= 0:
        return None
    cci = (tp[-1] - mb) / (0.015 * md)
    vs = sum(b[5] for b in win) / n
    vw = min(max((win[-1][5] / vs) if vs > 0 else 1.0, VW_LO), VW_HI)
    return cci * vw


def evaluate(side: str, fc: float | None) -> dict[str, Any]:
    side = str(side or "").upper()
    if fc is None:
        return {"verdict": "unknown", "why": ["no_chart"], "force_cci": None}
    ok = fc > 0 if side == "LONG" else fc < 0
    why = [] if ok else [f"세력 CCI {fc:+.0f} ({'>0' if side == 'LONG' else '<0'} 이어야)"]
    return {"verdict": "pass" if ok else "fail", "why": why, "force_cci": round(fc, 2)}


def blocks(mode: str, res: dict[str, Any]) -> bool:
    return mode == "on" and res.get("verdict") != "pass"


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
    if FORCE_MODE is not None:
        return FORCE_MODE
    for key in (f"{fam_key}_force_cci_gate", DEFAULT_KEY):
        v = _setting(db, key)
        if v in ("off", "shadow", "on"):
            return v
    return DEFAULT_MODE


def judge(db: Any, *, symbol: str, side: str, exchange_account_id: int | None = None,
          client: Any = None, redis_client: Any = None) -> dict[str, Any]:
    """캐시 → 1시간봉 조회 → 판정. 예외를 올리지 않는다 (실패 = unknown)."""
    from app.services import chart_state as CS
    r = redis_client
    if r is None:
        try:
            from app.core.redis_client import get_redis_client
            r = get_redis_client()
        except Exception:  # noqa: BLE001
            r = None
    key = f"force_cci:live:{symbol}"            # 값은 방향과 무관 → 심볼별 캐시
    fc: float | None = None
    cached = False
    if r is not None:
        try:
            hit = r.get(key)
            if hit:
                fc = json.loads(hit).get("fc")
                cached = True
        except Exception:  # noqa: BLE001
            pass
    if not cached:
        try:
            if exchange_account_id:
                from app.core.api_backoff import is_account_banned
                if is_account_banned(exchange_account_id, r):
                    return {**evaluate(side, None), "why": ["api_ban"], "source": "ban"}
            bc = client
            if bc is None:
                from app.services.chart_gate_live import _client_for
                bc = _client_for(db, exchange_account_id)
            if bc is not None:
                raw = bc.get_klines(symbol=symbol, interval="1h", limit=LIMIT_1H)
                fc = force_cci(CS.normalize(raw, "1h", int(time.time() * 1000)))
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s] %s 1시간봉 조회 실패 → unknown: %s", FIX, symbol, e)
            fc = None
        if r is not None:
            try:
                r.setex(key, CACHE_TTL if fc is not None else CACHE_TTL_UNKNOWN, json.dumps({"fc": fc}))
            except Exception:  # noqa: BLE001
                pass
    return {**evaluate(side, fc), "source": "cache" if cached else "fetch"}


def check(db: Any, *, strategy_type: str | None, template_name: str | None, entry_origin: str | None,
          symbol: str, side: str, exchange_account_id: int | None, where: str = "전략 생성") -> dict | None:
    """볼밴 계열 자동 전략 생성 직전. on 이고 세력 CCI 방향이 반대면 ValueError. 대상 밖 = None."""
    from app.services import auto_family_registry as AF
    fam = AF.family_for(strategy_type=strategy_type, template_name=template_name, entry_origin=entry_origin)
    if fam is None or fam.key not in BB_FAMILIES:
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
    res = {"mode": mode, "family": fam.key, **judge(db, symbol=symbol, side=side, exchange_account_id=exchange_account_id)}
    if mode == "shadow":
        try:
            from app.core.redis_client import get_redis_client
            get_redis_client().setex(f"force_cci:shadow:{fam.key}:{symbol}:{int(time.time())}", SHADOW_TTL,
                                     json.dumps({"side": side, **res}, default=str))
        except Exception:  # noqa: BLE001
            pass
    if blocks(mode, res):
        why = ", ".join(res.get("why") or []) or res.get("verdict")
        logger.info("[%s] ⛔ %s %s %s %s 차단 — %s", FIX, fam.label, symbol, side, where, why)
        raise ValueError(f"⛔ [{BLOCK_TAG}] {fam.label} {symbol} {side} 세력 CCI 방향 반대 — {why} "
                         f"(조정: system_settings {fam.key}_force_cci_gate)")
    logger.info("[%s] %s %s %s 세력 CCI %s (%s · %s)", FIX, fam.label, symbol, side, res.get("verdict"), mode,
                res.get("source"))
    return res


def is_gate_error(exc: BaseException | str) -> bool:
    return BLOCK_TAG in str(exc)
