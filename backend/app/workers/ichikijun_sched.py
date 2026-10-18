"""🗾 Fix 466 — 예약 전략(entry_signal = ichikijun*) 진입 신호 판정. scheduled_entry_worker 가 부른다.

판정 = 실험실과 같은 함수(app.services.ichikijun_apply.decide → ichimoku_kijun.entry_at).
같은 봉 재조회 금지: Redis ichisched:last:{sid}:{iv} = {"ts": 판정한 봉, "why": 대기 이유} (신호 없음일 때만 기록 —
신호가 났는데 진입이 실패하면 신선도 창 안에서 다음 사이클에 다시 본다).
klines 읽기만 — 주문은 호출 측(start_stage1)이 한다.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.services import ichikijun_apply as IA
from app.services import ichimoku_kijun as IK

logger = logging.getLogger(__name__)

KLINE_LIMIT = 300
K_LAST = "ichisched:last:{sid}:{iv}"
LAST_TTL = 3 * 86400
CHAMPION_KEY = "ichikijun_champion"


def _setting(db, key: str) -> str | None:
    from app.models.system_setting import SystemSetting
    row = db.get(SystemSetting, key)
    return None if row is None or row.value is None else str(row.value)


def expire_days(db) -> int:
    try:
        v = int(str(_setting(db, IA.EXPIRE_DAYS_KEY) or IA.EXPIRE_DAYS_DEFAULT).strip())
        return max(1, min(v, 365))
    except (TypeError, ValueError):
        return IA.EXPIRE_DAYS_DEFAULT


def _closed(bc, sym: str, iv: str, target: int) -> IK.Bars | None:
    kl = bc.get_klines(symbol=sym, interval=iv, limit=KLINE_LIMIT) or []
    kl = [b for b in kl if isinstance(b, (list, tuple)) and b and int(b[0]) <= target]
    if not kl or int(kl[-1][0]) != target:
        return None
    return IK.bars_from(kl)


def judge(db, bc, r, si: Any, now_ms: int) -> tuple[bool, str, dict]:
    """→ (진입, 이유, meta). meta 는 진입일 때만 채운다(변형·봉·손절폭·익절R·챔피언)."""
    var, why, extra = IA.resolve_variant(si.entry_signal, _setting(db, CHAMPION_KEY), si.side)
    if var is None:
        return False, why, {}
    target = IA.last_closed_open(now_ms, var.iv)
    key = K_LAST.format(sid=si.id, iv=var.iv)
    try:
        raw = r.get(key) if r is not None else None
        seen = json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001 — 기록 문제 = 다시 판정
        seen = None
    if isinstance(seen, dict) and seen.get("ts") == target and seen.get("variant") == var.key:
        return False, str(seen.get("why") or "대기"), {}
    B = _closed(bc, si.symbol, var.iv, target)
    btc = _closed(bc, "BTCUSDT", var.iv, target)
    if B is None or btc is None:
        return False, f"대기: {var.iv} 봉 정착 전/조회 실패", {}          # 기록 안 함 → 다음 사이클 다시
    ok, why2, meta = IA.decide(B, btc, si.side, var, now_ms)
    if not ok:
        try:
            if r is not None:
                r.setex(key, LAST_TTL, json.dumps({"ts": target, "variant": var.key, "why": why2}, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            pass
        return False, why2, {}
    meta.update(extra)
    meta["by"] = why
    return True, why2, meta


def apply_overrides(si: Any, meta: dict) -> bool:
    """진입 직전 인스턴스에 손절 ROI·TP1 ROI·meta 를 박는다. 값 계산 실패면 False(진입하지 않는다)."""
    from decimal import Decimal
    ov = IA.overrides(meta, si.leverage)
    if ov is None:
        return False
    sl, tp1 = ov
    si.force_sl_enabled_override = True
    si.force_sl_roi_override = Decimal(f"{sl:.2f}")
    si.tp1_pct_override = Decimal(f"{tp1:.2f}")
    si.entry_signal_meta = {**meta, "sl_roi": sl, "tp1_roi": tp1}
    return True
