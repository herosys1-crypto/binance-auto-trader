"""🎯 Fix 375 (2026-09-17 사장님) — 차트로 확인한 「이기는 진입 자리」 게이트.

사장님 verbatim:
  "켜면 안 되는 규칙 가족 (무작위 진입보다 나쁨) 이것을 좋은 방향으로 할수 있게 차트를 분석하고 진입할수 있어야지"
  "모든 매매에서 포지션진입조건을 찾아서 성공하는 방향으로 포지션 진입으로 수정할수 있게 정리해줘"

근거 (docs/learning/ENTRY_CONDITIONS_2026-09-17.md):
  가상매매 실시간 진입 22,652건(9/9~9/16) 마다 **진입 시점에 닫힌 봉만으로** 운영과 같은 chart_state 를 다시 계산
  (운영 기록 893건과 값 일치). 조건은 사전등록 이전(9/9~9/13)에서 고르고 이후(9/14~9/16)에서만 검증했다.
  규칙마다 따로 고른 조건은 대부분 검증에서 뒤집혔다(과적합) → **방향별 공통 조건**만 남겼다.

  SHORT = 「최근 16시간 고점에서 3% 안」 그리고 「일봉 볼밴 중단선이 오르는 중(UP)이 아님」
          검증: 충족 무작위 대비 +1.70 vs 불충족 −0.93 · 평균 ROI +6.2 · 승률 80% · 규칙 10개 중 9개 개선.
          = 떨어진 뒤에 쫓아 들어가는 SHORT(−8%·신저점 이탈)가 진 이유. 고점 근처에서, 일봉이 오르지 않을 때만.
  LONG  = 「24시간 −5% 이하 급락 뒤」 또는 「5분봉 4시간 고점 대비 −4% 이하 조정 뒤」
          검증: 충족 무작위 대비 +1.50 vs 나머지 · 평균 ROI +0.05(전체 −1.9) · 승률 58%.
          = 사장님 원칙 「LONG 은 급락·조정 뒤」. ⚠️ LONG 은 걸러도 절대 수익이 0 근처 — 시장 국면 영향이 크다.
  한계: 검증 기간 3~4일 · 하락장 위주. 판정은 7일 사전등록 표본(보고서 P5·P6)으로 다시 한다.

설계:
  · 순수 함수. 입력 = 가상매매 행의 snapshot(chart_state 포함)과 24h 변동. 봉을 새로 받지 않는다.
  · 차트 값이 없으면 verdict="unknown" — 게이트가 on 이면 **막는다**(자본이 나가는 판정은 모르면 막는다, 헌법 118).
  · 숫자는 설정 `entry_chart_gate_params`(JSON)로 덮을 수 있다 — 모두 「Claude가 정함」(분석에서 고른 값 그대로).
  · 가족별 모드 `<가족>_chart_gate` = off | shadow(판정만 기록) | on(불충족이면 진입 안 함). 규칙 가족 기본 on.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Mapping

logger = logging.getLogger(__name__)

FIX = "Fix375"
PARAMS_KEY = "entry_chart_gate_params"
GATE_MODES = ("off", "shadow", "on")
DEFAULT_PARAMS: dict[str, Any] = {
    "short_max_below_high_pct": 3.0,        # SHORT: 1시간봉 16개 고점 대비 −3% 이내 (분석 S1)
    "short_block_d1_trend": ["UP"],         # SHORT: 일봉 볼밴 추세가 이 값이면 막음 (분석 S2)
    "long_min_drop_24h_pct": 5.0,           # LONG: 24h 변동 ≤ −5% 면 통과 (분석 L2)
    "long_min_pullback_5m_pct": 4.0,        # LONG: 5분봉 48개 고점 대비 −4% 이하면 통과 (분석 L4)
    "short_allow_no_daily_trend": False,    # SHORT: 일봉 30개 미만(상장 약 한 달 미만)이라 추세를 모를 때 — False = 막음 (분석과 같음)
    # 🎯 Fix 377 (2026-09-18 사장님 「상승 초입 LONG 전략을 자세히 분석하고 가상매매로 완성」) — 이 가족만 쓰는 조건
    "surge_min_pullback_1h_pct": 1.5,       # 1시간봉 16개 고점에서 이만큼은 내려와 있어야 한다 (고점 바로 밑 추격 금지)
    "surge_max_chg24_pct": 20.0,            # 24h 변동이 이 이상이면 과열 — 진입 안 함
    "surge_dead_zone_chg24": [0.0, 5.0],    # 24h 이 구간(미동)은 두 기간 모두 손실이라 제외
}

# 가족별 전용 조건 (없는 가족은 방향 공통 조건). 이름 = 이 모듈의 함수 접미사.
FAMILY_RULES: dict[str, str] = {"rf_surge_long": "surge_pullback"}


def params(db: Any = None) -> dict[str, Any]:
    """기본값 + 설정 JSON 덮어쓰기. 손상·범위 밖 값은 기본값으로 (조용히 넘기지 않고 경고)."""
    out = dict(DEFAULT_PARAMS)
    if db is None:
        return out
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, PARAMS_KEY)
        if row is None or not str(row.value or "").strip():
            return out
        data = json.loads(row.value)
        for k in ("short_max_below_high_pct", "long_min_drop_24h_pct", "long_min_pullback_5m_pct",
                  "surge_min_pullback_1h_pct", "surge_max_chg24_pct"):     # 🎯 Fix 377 상승 초입 LONG 전용 숫자
            if k in data:
                v = float(data[k])
                if 0 < v <= 500:
                    out[k] = v
                else:
                    logger.warning("[%s] %s.%s=%r 범위 밖 → 기본 %s", FIX, PARAMS_KEY, k, data[k], DEFAULT_PARAMS[k])
        if isinstance(data.get("surge_dead_zone_chg24"), list) and len(data["surge_dead_zone_chg24"]) == 2:
            try:
                lo, hi = (float(x) for x in data["surge_dead_zone_chg24"])
                if lo <= hi:
                    out["surge_dead_zone_chg24"] = [lo, hi]
                else:
                    logger.warning("[%s] surge_dead_zone_chg24 앞이 더 큼 %r → 기본", FIX, data["surge_dead_zone_chg24"])
            except (TypeError, ValueError):
                logger.warning("[%s] surge_dead_zone_chg24 숫자 아님 %r → 기본", FIX, data["surge_dead_zone_chg24"])
        if "short_allow_no_daily_trend" in data:
            out["short_allow_no_daily_trend"] = bool(data["short_allow_no_daily_trend"])
        if isinstance(data.get("short_block_d1_trend"), list):
            out["short_block_d1_trend"] = [str(x).upper() for x in data["short_block_d1_trend"]]
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] %s 읽기 실패 → 기본값: %s", FIX, PARAMS_KEY, e)
    return out


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def features(snapshot: Mapping[str, Any] | None, chg_24h: Any = None) -> dict[str, Any]:
    """게이트가 보는 값만 뽑는다. 없는 값은 None."""
    snap = snapshot or {}
    cs = snap.get("chart_state") or {}
    h1 = cs.get("h1") or {}
    m5 = cs.get("m5") or {}
    d1bb = (cs.get("d1") or {}).get("bb") or {}
    chg = _num(chg_24h if chg_24h is not None else snap.get("chg_24h"))
    return {
        "h1_from_hi_pct": _num(h1.get("from_hi_pct")),
        "m5_from_hi_pct": _num(m5.get("from_hi_pct")),
        "d1_trend": (str(d1bb["trend"]).upper() if d1bb.get("trend") else None),
        "chg_24h": chg,
    }


def _rule_surge_pullback(f: Mapping[str, Any], p: Mapping[str, Any]) -> dict[str, Any]:
    """🎯 Fix 377 상승 초입 LONG(surge_start_346) 전용 — 가상 1,239건 분석 (발견 9/9~9/13 · 검증 9/14~9/18).
    통과 31% · 검증 평균 ROI +3.08 (막힌 쪽 −0.24) · 무작위 대비 +2.19 (막힌 쪽 −1.07) · 검증 5일 모두 양수.
    발견 기간에도 통과가 막힌 쪽보다 나았다(−0.87 vs −1.13). 세 조건 모두 「하지 말 것」이다:
      ① 1시간 고점 바로 밑에서 추격하지 않는다  ② 24h 과열(≥20%)에 들어가지 않는다  ③ 24h 0~5% 미동 구간은 건너뛴다
    ⚠️ 이 조건은 이 가족에서만 두 기간 일치했다 — 무작위 진입에는 발견 기간에서 반대였다(일반 규칙으로 쓰지 말 것)."""
    hi, chg = f["h1_from_hi_pct"], f["chg_24h"]
    if hi is None or chg is None:
        return {"verdict": "unknown", "why": ["no_chart"], "features": f}
    why: list[str] = []
    need = float(p["surge_min_pullback_1h_pct"])
    if hi > -need:
        why.append(f"1시간 고점 바로 밑 추격 {hi:+.1f}% (−{need:g}% 이하여야)")
    if chg >= float(p["surge_max_chg24_pct"]):
        why.append(f"24h 과열 {chg:+.1f}%")
    lo, hiz = (list(p["surge_dead_zone_chg24"]) + [0.0, 0.0])[:2]
    if lo <= chg < hiz:
        why.append(f"24h 미동 구간 {chg:+.1f}% ({lo:g}~{hiz:g}%)")
    return {"verdict": "fail" if why else "pass", "why": why, "features": f}


def evaluate(side: str, snapshot: Mapping[str, Any] | None, *, chg_24h: Any = None,
             p: Mapping[str, Any] | None = None, family: str | None = None) -> dict[str, Any]:
    """{"verdict": pass|fail|unknown, "why": [...], "features": {...}} — 가족 전용 조건이 있으면 그것을 쓴다."""
    p = {**DEFAULT_PARAMS, **(p or {})}
    f = features(snapshot, chg_24h)
    side = str(side or "").upper()
    rule = FAMILY_RULES.get(str(family or ""))
    if rule == "surge_pullback":
        out = _rule_surge_pullback(f, p)
        out["rule"] = rule
        return out
    why: list[str] = []
    if side == "SHORT":
        hi, tr = f["h1_from_hi_pct"], f["d1_trend"]
        if hi is None or (tr is None and not p.get("short_allow_no_daily_trend")):
            return {"verdict": "unknown", "why": ["no_chart" if hi is None else "no_daily_trend (상장 한 달 미만?)"], "features": f}
        if hi < -float(p["short_max_below_high_pct"]):
            why.append(f"고점에서 너무 내려옴 {hi:+.1f}% (허용 −{p['short_max_below_high_pct']:g}%)")
        if tr is not None and tr in p["short_block_d1_trend"]:
            why.append(f"일봉 추세 {tr}")
        return {"verdict": "fail" if why else "pass", "why": why, "features": f}
    if side == "LONG":
        chg, pb = f["chg_24h"], f["m5_from_hi_pct"]
        if chg is None and pb is None:
            return {"verdict": "unknown", "why": ["no_chart"], "features": f}
        drop_ok = chg is not None and chg <= -float(p["long_min_drop_24h_pct"])
        pull_ok = pb is not None and pb <= -float(p["long_min_pullback_5m_pct"])
        if drop_ok or pull_ok:
            return {"verdict": "pass", "why": ["24h 급락 뒤" if drop_ok else "5분 조정 뒤"], "features": f}
        return {"verdict": "fail",
                "why": [f"급락·조정 아님 (24h {'?' if chg is None else format(chg, '+.1f')}% · "
                        f"5분 고점 대비 {'?' if pb is None else format(pb, '+.1f')}%)"],
                "features": f}
    return {"verdict": "unknown", "why": ["side"], "features": f}


def blocks(mode: str, result: Mapping[str, Any]) -> bool:
    """게이트 모드와 판정으로 「진입을 막는가」. shadow·off 는 막지 않는다."""
    return str(mode).lower() == "on" and result.get("verdict") != "pass"
