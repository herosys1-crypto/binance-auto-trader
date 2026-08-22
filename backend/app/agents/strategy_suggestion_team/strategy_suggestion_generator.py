"""🎯 StrategySuggestionGenerator = 신 전략 draft 실 DB 저장! ⭐

Team: Strategy Suggestion
사장님 요구: 매일 자동 제안 = 사장님 검토용!

로직:
1. 예상 심볼 → 전략 config 생성!
2. 사장님 신 default 자동!
3. DB `strategy_suggestions` 저장!
4. EventBus publish (SUGGESTION_CREATED!)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from app.agents.base import BaseAgent
from app.agents.orchestrator import EventType, get_event_bus

logger = logging.getLogger(__name__)


class StrategySuggestionGenerator(BaseAgent):
    TEAM = "strategy_suggestion"
    AGENT_NAME = "strategy_suggestion_generator"

    def execute(self, db, predictions: list[dict], force: bool = False) -> dict:
        """예상 심볼 → 전략 draft DB 저장!

        Args:
            force: True 시 = 오늘 PENDING 제안 = 자동 DISMISS 후 재생성!
                   (사장님 「지금 실행」 재실행 편의!)
        """
        self.validate("STRATEGY_SUGGESTION_GENERATE")

        if not predictions:
            return {"created": 0, "total": 0}

        from app.models.strategy_suggestion import StrategySuggestion
        from sqlalchemy import select, update

        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )

        # 🌟 v132 (2026-08-12 사장님!): force 모드 = 오늘 PENDING 자동 삭제!
        # 사장님 = LONG 예측 = 옛 SHORT가 있어서 skip!
        # force = true = 오늘 PENDING = 모두 DISMISS 후 재생성!
        if force:
            dismissed_count = db.execute(
                update(StrategySuggestion)
                .where(StrategySuggestion.created_at >= today_start)
                .where(StrategySuggestion.status == "PENDING")
                .values(
                    status="DISMISSED",
                    dismissed_at=datetime.now(timezone.utc),
                    dismissed_reason="force=True 재생성 (사장님 「지금 실행」!)",
                )
            ).rowcount
            db.commit()
            logger.info("[%s] force=True: 오늘 PENDING %d건 dismiss!", self.AGENT_NAME, dismissed_count)
            existing_set = set()  # 모두 재생성!
        else:
            # 중복 방지 = 오늘 이미 있는 심볼 skip!
            existing_today = db.execute(
                select(StrategySuggestion.symbol)
                .where(StrategySuggestion.created_at >= today_start)
                .where(StrategySuggestion.status == "PENDING")
            ).scalars().all()
            existing_set = set(existing_today)

        created_ids = []
        bus = get_event_bus()
        # 🎓 v135 (2026-08-13 사장님!): 심볼 성공률 캐시!
        success_rate_cache: dict[tuple[str, str], float] = {}

        for p in predictions:
            symbol = p["symbol"]
            if symbol in existing_set:
                continue  # 오늘 이미 있음!

            # 🌟 v132: predictor에서 side 명시 (LONG/SHORT!) or type 유추!
            side = p.get("side") or self._infer_side(p["type"])
            config = self._build_config(symbol, side, db=db)  # 프로필 참조!

            # 🎓 v220 Fix 20 (2026-08-23 사장님!):
            # Fix 12 검증 = "13/13 저장!"은 함정 (key만 존재 / value 전부 None!)
            # 원인: pump_dump_predictor 는 rsi/cci/obv/regime/mta 전부 미세팅 =>
            #      snapshot 이 있어도 pattern_learning._analyze_entry_snapshots 가
            #      `if rsi is not None: ...` 에서 전부 skip => RSI/CCI/OBV/regime/KST
            #      학습 데이터가 계속 0건!
            # 신: 여기서 직접 kline 조회하여 결측 지표 계산 후 채워넣음 (fail-open!)
            _kst_hour = (datetime.now(timezone.utc).hour + 9) % 24
            _rsi_val = p.get("rsi")
            _cci_val = p.get("cci")
            _obv_slope_val = p.get("obv_slope_pct")
            if _rsi_val is None or _cci_val is None or _obv_slope_val is None:
                _r, _c, _o = self._compute_missing_indicators(db, symbol)
                if _rsi_val is None:
                    _rsi_val = _r
                if _cci_val is None:
                    _cci_val = _c
                if _obv_slope_val is None:
                    _obv_slope_val = _o
            entry_snapshot = {
                "rsi": _rsi_val,
                "cci": _cci_val,
                "obv_slope_pct": _obv_slope_val,
                "regime": p.get("regime", "NEUTRAL"),
                "sustained_bars": p.get("sustained_bars", 0),
                # 🚨 Fix 20: predictor 는 change_pct 키를 씀! (change_24h 는 항상 None!)
                "change_24h": p.get("change_24h") or p.get("change_pct"),
                "source": p.get("type", "PREDICTION"),
                "kst_hour": _kst_hour,
                "mta_total": p.get("mta_total"),
                "entered_at": datetime.now(timezone.utc).isoformat(),
            }
            config = {**config, "entry_snapshot": entry_snapshot}

            # 🎓 v135: 심볼 성공률 반영 = confidence 조정!
            # 🎯 v172 (2026-08-17 사장님!): 신 심볼 우대 + 조정 완화!
            # 사장님 지적: "신뢰도 85% 이상 없을수 없는데 로직에 문제!"
            # 원인: 신 심볼(sr=0.5) = 배율 0.75 = 원본 0.90 → 0.675 (필터 탈락!)
            # 신 로직:
            #   - 학습 데이터 <5건 = 신 심볼 = 원본 conf 그대로! (판단 유보!)
            #   - 학습 데이터 5건+ = 완화된 조정 (0.5 → 0.75!)
            raw_conf = float(p.get("confidence", 0.5))
            try:
                from app.workers.prediction_outcome_worker import get_symbol_success_rate
                from sqlalchemy import select, func
                from app.models.strategy_suggestion import StrategySuggestion
                from datetime import timedelta

                key = (symbol, side)
                if key not in success_rate_cache:
                    sr_val = get_symbol_success_rate(db, symbol, side, days=30)
                    # v172: 학습 샘플 수 조회!
                    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
                    samples = db.execute(
                        select(func.count(StrategySuggestion.id))
                        .where(StrategySuggestion.symbol == symbol)
                        .where(StrategySuggestion.side == side)
                        .where(StrategySuggestion.created_at >= cutoff)
                        .where(StrategySuggestion.outcome_status.in_(["SUCCESS", "FAIL"]))
                    ).scalar() or 0
                    success_rate_cache[key] = (sr_val, samples)
                sr, samples = success_rate_cache[key]

                # v172: 신 심볼 (샘플 <5) = 원본 conf 그대로!
                if samples < 5:
                    adjusted_conf = raw_conf
                else:
                    # 학습 심볼 = 완화된 조정 (0.75 + sr * 0.25)
                    # sr=0.5 → 0.875 / sr=1.0 → 1.0 / sr=0 → 0.75
                    adjusted_conf = raw_conf * (0.75 + sr * 0.25)
                adjusted_conf = max(0.10, min(0.99, adjusted_conf))
            except Exception:
                sr = 0.5
                samples = 0
                adjusted_conf = raw_conf

            suggestion = StrategySuggestion(
                symbol=symbol,
                side=side,
                suggestion_type=p["type"],
                strategy_config=config,
                confidence_score=Decimal(str(round(adjusted_conf, 4))),
                reason=p.get("reason", ""),
                status="PENDING",
                execution_mode="MANUAL",  # ⭐ 기본 수동!
                symbol_prior_success_rate=Decimal(str(round(sr, 4))),
                outcome_status="PENDING",
            )
            db.add(suggestion)
            db.flush()
            created_ids.append(suggestion.id)

            # 이벤트 발신!
            bus.publish(EventType.SUGGESTION_CREATED, {
                "suggestion_id": suggestion.id,
                "symbol": symbol,
                "side": side,
                "confidence": p.get("confidence"),
            })

        db.commit()
        logger.info("[%s] 생성 완료: %d", self.AGENT_NAME, len(created_ids))
        return {"created": len(created_ids), "created_ids": created_ids}

    # 🎓 Fix 20 (2026-08-23): 심볼당 1회 조회 캐시 (사이클 내 재사용!)
    _INDICATOR_CACHE: dict[str, tuple[float | None, float | None, float | None]] = {}

    def _compute_missing_indicators(
        self, db, symbol: str,
    ) -> tuple[float | None, float | None, float | None]:
        """RSI(14) / CCI(20) / OBV slope(%, 최근 10봉) — 15m 캔들 기준.

        predictor(pump_dump_predictor 등)가 지표를 안 넘길 때 여기서 직접 계산.
        실패 시 모두 (None, None, None) 반환 = pattern_learning 이 조용히 skip!
        """
        cached = self._INDICATOR_CACHE.get(symbol)
        if cached is not None:
            return cached
        try:
            from app.core.crypto import decrypt_text
            from app.integrations.binance.client import BinanceClient
            from app.models.exchange_account import ExchangeAccount
            from app.services.chart_analyzer import ChartAnalyzer
            from app.services.bb_top_analyzer import BBTopAnalyzer
            from sqlalchemy import select as _sel

            account = db.execute(
                _sel(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
            ).scalar_one_or_none()
            if not account:
                self._INDICATOR_CACHE[symbol] = (None, None, None)
                return (None, None, None)
            bc = BinanceClient(
                api_key=decrypt_text(account.api_key_enc),
                api_secret=decrypt_text(account.api_secret_enc),
                is_testnet=False,
            )
            kl = bc.get_klines(symbol=symbol, interval="15m", limit=60) or []
            if len(kl) < 20:
                self._INDICATOR_CACHE[symbol] = (None, None, None)
                return (None, None, None)
            closes = [float(k[4]) for k in kl]
            rsi_series = BBTopAnalyzer.rsi(closes)
            rsi_v = rsi_series[-1] if rsi_series and rsi_series[-1] is not None else None
            cci_series = ChartAnalyzer.compute_cci(kl, period=20)
            cci_v = cci_series[-1] if cci_series else None
            obv_series = ChartAnalyzer.compute_obv(kl)
            obv_slope_v: float | None = None
            if len(obv_series) >= 10:
                _o0 = float(obv_series[-10])
                _o1 = float(obv_series[-1])
                if _o0 != 0:
                    obv_slope_v = round((_o1 - _o0) / abs(_o0) * 100, 2)
            result = (
                round(float(rsi_v), 2) if rsi_v is not None else None,
                round(float(cci_v), 2) if cci_v is not None else None,
                obv_slope_v,
            )
            self._INDICATOR_CACHE[symbol] = result
            return result
        except Exception as e:
            logger.debug("[%s] 지표 계산 실패 %s: %s", self.AGENT_NAME, symbol, e)
            self._INDICATOR_CACHE[symbol] = (None, None, None)
            return (None, None, None)

    def _infer_side(self, suggestion_type: str) -> str:
        """suggestion_type → side 유추 (fallback!). v132에서는 predictor가 side 명시!

        SHORT = dump_continuation, pump_end, dump_live (🌟 v133c!)
        LONG = pump_continuation, dump_reversal, pump_live (🌟 v133c!)
        """
        if suggestion_type in ("dump_continuation", "pump_end", "dump_live"):
            return "SHORT"
        # pump_continuation, dump_reversal, reversal_up, pump_live = LONG
        return "LONG"

    def _build_config(self, symbol: str, side: str, db=None) -> dict:
        """사장님 default 프로필 참조! (v132 신!)"""
        # 사장님 default 프로필 로드!
        profile_config = self._load_default_profile(db) if db else None
        if not profile_config:
            # fallback = 하드코딩 default!
            profile_config = {
                "leverage": 2,
                "capitals": [500, 500, 500, 500],
                "trigger_percents": [None, 10, 20, 20],
                "tp1_percent": 10, "tp2_percent": 15,
                "tp3_percent": 20, "tp4_percent": 25,
                "tp1_qty_ratio": 10, "tp2_qty_ratio": 15,
                "tp3_qty_ratio": 20, "tp4_qty_ratio": 25,
                "tp1_pct_override": 25,
                "force_sl_enabled_override": True,
                "force_sl_roi_override": 5,  # v166 사장님: -15% → -5%!
                "stop_loss_percent_of_capital": 90,
                "start_price": None,
                "retry_after_liquidation_enabled": False,
                "retry_trigger_pct": 10,
            }
        # symbol + side 추가!
        return {"symbol": symbol, "side": side, **profile_config}

    def _load_default_profile(self, db) -> dict | None:
        """system_settings에서 default 프로필 config 로드!"""
        import json
        from app.models.system_setting import SystemSetting

        _p_row = db.get(SystemSetting, "suggestion_default_profiles")
        _d_row = db.get(SystemSetting, "suggestion_current_default_profile")
        if not _p_row or not _d_row:
            return None
        try:
            profiles = json.loads(_p_row.value)
            default_name = _d_row.value
            for p in profiles:
                if p.get("name") == default_name:
                    return p.get("config") or {}
        except Exception as e:
            logger.warning("[%s] default profile 로드 실패: %s", self.AGENT_NAME, e)
        return None
