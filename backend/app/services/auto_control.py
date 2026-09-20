"""🎛 Fix 374 (2026-09-16 사장님) — 자동매매 관제실: 흩어진 자동매매 스위치를 **한 곳**에 모은다.

사장님 verbatim: "자동매매 준비 가족 12종과 모든 자동매매를 한곳으로 모아서 사용과 관리가 편리하게 ui를 개선해줘"

왜 필요한가 (2026-09-16 실측):
  · 규칙 가족 12종(rf_*)은 설정만 있고 **화면이 하나도 없었다** — `system_settings` 에 직접 SQL 을 넣어야 켜졌다.
  · `auto_trading_halt`(Fix 371) 도 화면이 없었다 — 전면 중단/재개를 DB 로만 할 수 있었다.
  · 나머지 자동매매 스위치는 세 곳에 흩어져 있다: 전략 제안 패널(`/strategy-suggestions/sajangnim-settings`),
    OBV 자동(`/strategy-suggestions/obv-settings`), 그리고 화면이 없는 키들.
  · 🚨 옛 키 `sajangnim_top_short_daily_limit` 은 이름이 「daily」지만 실제 의미는 **동시 보유 상한**이고
    (`services/position_limit.py:50` LIMIT_KEYS), 0 이면 그 계열 자동 진입이 **전부** 멈춘다. 화면 라벨을 이름대로
    적으면 사장님이 오해한다 → 여기서는 의미대로 적는다 (헌법 80: 조용한 오해 금지).

이 모듈이 하는 일 = **설정 읽기·검증·쓰기와 현황 집계뿐**. 판정·주문은 하지 않는다.
설정 값의 단일 진실은 각 모듈의 SETTINGS 다 (`rule_families` · `bb_swing_rules` · `external_strategies`) —
여기서 기본값을 다시 적지 않고 그 모듈에서 읽어 온다. 옛 워커 키는 자기 SETTINGS 가 없어 여기에 근거(파일:줄)와 함께 적는다.

화이트리스트: `apply` 는 `build` 가 만든 컨트롤 키 + `daily_max_<가족키>` 만 쓴다. 그 밖의 키는 거부한다.
켜기(on)는 **사장님만** 누른다 — 이 모듈은 어떤 경로로도 자동으로 on 을 쓰지 않는다 (CLAUDE.md 2).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)

FIX = "Fix374"
MODE3 = ("off", "shadow", "on")
OFF_WORDS = ("0", "off", "false", "no")

G_GLOBAL = "전체"
G_RULE = "규칙 가족 (가상매매 채택 규칙)"          # 🗺 Fix 387: 12 → 13 (S4 추가) — 숫자는 라벨에서 뺀다
G_WORKER = "실매매 워커"
G_EXTERNAL = "외부 매매법"
GROUPS = (G_GLOBAL, G_RULE, G_WORKER, G_EXTERNAL)


# ───────────────────────── 컨트롤 정의 ─────────────────────────
@dataclass(frozen=True)
class Ctl:
    """설정 한 칸. kind = mode3 | gate3 | switch | int | num | text | json."""
    key: str
    label: str
    kind: str
    default: str
    help: str = ""
    lo: float | None = None
    hi: float | None = None
    off_means: str = ""          # switch/int 에서 「이 값이면 꺼짐」 (예: "0")
    source: str = ""             # 값의 출처 (사장님 지시 / Claude가 정함 / 실코드 기본)
    ref: str = ""                # 이 키를 읽는 코드 (파일:줄) — 사장님이 되짚을 수 있게

    def clean(self, raw: Any) -> str:
        """입력값 → 저장 문자열. 못 쓰는 값이면 ValueError."""
        v = str(raw).strip()
        if self.kind in ("mode3", "gate3"):
            if v.lower() not in MODE3:
                raise ValueError(f"{self.key}: off | shadow | on 중 하나여야 합니다 (받은 값 {v!r})")
            return v.lower()
        if self.kind == "switch":
            if v.lower() in OFF_WORDS:
                return "0"
            if v.lower() in ("1", "on", "true", "yes"):
                return "1"
            raise ValueError(f"{self.key}: 0 또는 1 이어야 합니다 (받은 값 {v!r})")
        if self.kind in ("int", "num"):
            try:
                n = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{self.key}: 숫자여야 합니다 (받은 값 {v!r})") from None
            if n != n or n in (float("inf"), float("-inf")):
                raise ValueError(f"{self.key}: 숫자여야 합니다 (받은 값 {v!r})")
            if self.lo is not None and n < self.lo:
                raise ValueError(f"{self.key}: {self.lo} 이상이어야 합니다")
            if self.hi is not None and n > self.hi:
                raise ValueError(f"{self.key}: {self.hi} 이하여야 합니다")
            return str(int(n)) if self.kind == "int" else str(n)
        if self.kind == "json":
            import json as _json
            try:
                parsed = _json.loads(v or "{}")
            except ValueError:
                raise ValueError(f"{self.key}: JSON 형식이 아닙니다") from None
            if not isinstance(parsed, dict):
                raise ValueError(f"{self.key}: {{...}} 객체여야 합니다")
            return _json.dumps(parsed, ensure_ascii=False)
        if not v:
            raise ValueError(f"{self.key}: 빈 값은 저장하지 않습니다")
        if len(v) > 200:
            raise ValueError(f"{self.key}: 200자 이하여야 합니다")
        return v


@dataclass(frozen=True)
class Panel:
    """자동매매 한 덩어리 (= 가족 하나 = 카드 하나)."""
    fam: str                      # auto_family_registry 가족키 (daily_max_<fam>) · "" = 가족 없음
    label: str
    group: str
    gate: Ctl | None = None       # 켜기/끄기 한 칸 (없으면 코드 상수 = 화면에서 끌 수 없음)
    ctls: tuple[Ctl, ...] = ()
    job: str = ""                 # scheduler_runner job id
    every: str = ""
    note: str = ""
    daily: bool = True            # daily_max_<fam> 칸을 보여줄지


def _mod_settings(module_name: str) -> dict[str, tuple[str, str, str]]:
    """가족 모듈의 SETTINGS (없거나 import 실패 = 빈 dict — 화면이 죽지 않게)."""
    try:
        import importlib
        return dict(getattr(importlib.import_module(module_name), "SETTINGS", {}) or {})
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] %s SETTINGS 읽기 실패: %s", FIX, module_name, e)
        return {}


def _ctl_from(settings: dict[str, tuple[str, str, str]], key: str, label: str, kind: str,
              *, lo: float | None = None, hi: float | None = None, off_means: str = "", ref: str = "") -> Ctl | None:
    """모듈 SETTINGS 에서 기본값·설명·출처를 그대로 가져온다 (여기서 다시 적지 않는다)."""
    row = settings.get(key)
    if row is None:
        return None
    default, help_, source = row
    return Ctl(key=key, label=label, kind=kind, default=default, help=help_, lo=lo, hi=hi,
               off_means=off_means, source=source, ref=ref)


# ───────────────────────── 레지스트리 ─────────────────────────
def _rule_panels() -> list[Panel]:
    """규칙 가족 12 — 모든 값이 rule_families.SETTINGS 에 있다."""
    try:
        from app.services.rule_families import FAMILIES
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] rule_families 읽기 실패: %s", FIX, e)
        return []
    S = _mod_settings("app.services.rule_families")
    ref = "services/rule_families.py"
    out: list[Panel] = []
    for f in FAMILIES:
        gate = _ctl_from(S, f"{f.key}_mode", "모드", "mode3", ref=f"{ref} (mode_of)")
        ctls = [c for c in (
            _ctl_from(S, f"{f.key}_chart_gate", "차트 자리 게이트", "gate3", ref="services/entry_conditions.py (Fix 375)"),
            _ctl_from(S, f"{f.key}_entry", "진입 방식", "text", ref=f"{ref} (entry_of)"),
            _ctl_from(S, f"{f.key}_places", "자리", "text", ref=f"{ref} (places_of)"),
            _ctl_from(S, f"{f.key}_max_concurrent", "동시 보유 상한", "int", lo=0, hi=50, off_means="0", ref=ref),
            _ctl_from(S, f"{f.key}_cooldown_hours", "심볼 쿨다운(시간)", "num", lo=0, hi=240, ref=ref),
            _ctl_from(S, f"{f.key}_capital_usdt", "단일 진입 증거금", "num", lo=1, hi=100000, ref=ref),
            _ctl_from(S, f"{f.key}_sl_roi", "단일 진입 손절 ROI%", "num", lo=0, hi=100, ref=ref),
        ) if c is not None]
        out.append(Panel(fam=f.key, label=f"{f.label} ({f.side})", group=G_RULE, gate=gate, ctls=tuple(ctls),
                         job="rule_families", every="60초",
                         note=f"신호 = 가상매매 규칙 {f.rule} · 진입 = {f.prefix}_*"))
    return out


def _shared_rule_ctls() -> tuple[Ctl, ...]:
    """규칙 가족 12 공용 (분할 자본·TP·손절 등) — 한 칸 고치면 12종에 같이 적용된다."""
    S = _mod_settings("app.services.rule_families")
    ref = "services/rule_families.py (split_config)"
    got = (
        _ctl_from(S, "rf_split_capitals", "분할 1·2·3차 증거금", "text", ref=ref),
        _ctl_from(S, "rf_split_steps", "분할 심도 %", "text", ref=ref),
        _ctl_from(S, "rf_split_sl_roi", "분할 평단 손절 ROI%", "num", lo=1, hi=100, ref=ref),
        _ctl_from(S, "rf_split_tp1_pct", "분할 TP1 ROI%", "num", lo=1, hi=50, ref=ref),
        _ctl_from(S, "rf_split_trailing_pct", "분할 TP1 뒤 트레일링 %", "num", lo=0.5, hi=20, ref=ref),
        _ctl_from(S, "rf_leverage", "레버리지", "num", lo=1, hi=20, ref=ref),
        _ctl_from(S, "rf_allow_hedge", "같은 심볼 반대 방향 허용", "switch", off_means="0", ref=ref),
        _ctl_from(S, "rf_max_signal_age_min", "신호 유효 시간(분)", "num", lo=1, hi=240, ref=ref),
        _ctl_from(S, "rf_max_drift_pct", "가격 이동 상한 %", "num", lo=0.1, hi=20, ref=ref),
        _ctl_from(S, "rf_tp_percents", "단일 진입 TP1~4 ROI%", "text", ref=ref),
        _ctl_from(S, "entry_chart_gate_params", "차트 게이트 숫자 (JSON)", "json", ref="services/entry_conditions.py (params)"),
    )
    return tuple(c for c in got if c is not None)


def _worker_panels() -> list[Panel]:
    """옛 워커 — 자기 SETTINGS 가 없어 키·기본값·근거를 여기에 적는다 (전부 2026-09-16 코드 확인)."""
    bbs = _mod_settings("app.services.bb_swing_rules")
    W = "workers"
    return [
        # ── 정점·저점 계열 (v219/v226) — 2026-09-16 Fix 374 로 전용 스위치를 새로 달았다 ──
        Panel(fam="top_short", label="급등 정점 SHORT (v219)", group=G_WORKER, job="auto_short_at_top", every="30초",
              gate=Ctl("sajangnim_top_short_enabled", "켜기", "switch", "1",
                       "행이 없으면 켜짐 (Fix 374 이전과 같은 동작).", off_means="0",
                       source="Fix 374 신설", ref="services/worker_switch.py"),
              note="이 스위치 전에는 공용 상한 키를 0 으로 만드는 방법밖에 없었다 (다른 워커까지 멈춘다)"),
        Panel(fam="bottom_long", label="저점 LONG (v226)", group=G_WORKER, job="auto_long_at_bottom", every="30초",
              gate=Ctl("sajangnim_bottom_long_enabled", "켜기", "switch", "1",
                       "행이 없으면 켜짐 (Fix 374 이전과 같은 동작).", off_means="0",
                       source="Fix 374 신설", ref="services/worker_switch.py"),
              ctls=(Ctl("surge_pullback_long_enabled", "「급등 중 조정」 1순위 경로", "switch", "1",
                        "이 워커의 한 갈래만 끈다 (워커 전체가 아니다).", off_means="0",
                        source="사장님 선택 B (Fix 244)", ref=f"{W}/auto_long_at_bottom_worker.py:560"),)),
        Panel(fam="bb_reentry", label="실시간 재진입 (마틴게일)", group=G_WORKER, job="realtime_reentry", every="30초",
              gate=Ctl("realtime_reentry_enabled", "켜기", "switch", "1",
                       "행이 없으면 켜짐 (Fix 374 이전과 같은 동작).", off_means="0",
                       source="Fix 374 신설", ref="services/worker_switch.py")),
        Panel(fam="success_reentry", label="수익 추가 (피라미딩)", group=G_WORKER, job="success_pyramiding", every="30초",
              gate=Ctl("sajangnim_pyramid_enabled", "켜기", "switch", "1",
                       "🚨 기본 켜짐이다 (행이 없으면 ON). 9/13 KOMAUSDT·哈基米USDT 미실현 −108·−172 중 "
                       "−91·−134 가 이 자동 추가분이었다. 끄려면 0.", off_means="0",
                       source="기존 키 (Fix 138)", ref=f"{W}/success_pyramiding_worker.py:714"),
              ctls=(Ctl("sajangnim_pyramid_capital", "1회 추가 증거금", "num", "300", "", 1, 100000,
                        source="사장님 UI 값 (Fix 176)", ref="api/v1/strategy_suggestions.py:570"),
                    Ctl("pyramid_after_tp_enabled", "익절 뒤에도 추가", "switch", "1", "기본 켜짐", off_means="0",
                        source="기존 키", ref=f"{W}/success_pyramiding_worker.py:542"),
                    Ctl("pyramid_indicator_gate_enabled", "지표 게이트", "switch", "1",
                        "기본 켜짐 (끄면 조건 없이 추가)", off_means="0",
                        source="기존 키 (Fix 273)", ref=f"{W}/success_pyramiding_worker.py:520"),
                    Ctl("pyramid_cap_loss_enabled", "손절 ROI 래칫", "switch", "0",
                        "기본 꺼짐 (Fix 363 — 켜면 추가마다 손절을 몰래 낮춘다)", off_means="0",
                        source="기존 키 (Fix 363)", ref=f"{W}/success_pyramiding_worker.py:498"))),
        # 🚨 가족키를 두지 않는다 — 이 워커는 **원래 템플릿 그대로** 새 전략을 만들어서
        #    만들어진 전략의 가족은 그 템플릿의 가족이다 (여기에 하루 최대 칸을 두면 엉뚱한 가족을 세게 된다).
        Panel(fam="", label="사다리 재시작", group=G_WORKER, job="ladder_restart", every="5분", daily=False,
              gate=Ctl("ladder_restart_enabled", "켜기", "switch", "1",
                       "행이 없으면 켜짐. 관리 재진입이 프로브 모드면 이 워커는 스스로 양보한다.", off_means="0",
                       source="Fix 374 신설", ref="services/worker_switch.py"),
              note="원래 템플릿으로 다시 1단계부터 — 하루 최대는 그 템플릿의 가족 칸이 센다"),
        Panel(fam="", label="저항 반전 SHORT", group=G_WORKER, job="resistance_reversal", every="30초", daily=False,
              gate=Ctl("resistance_reversal_enabled", "켜기", "switch", "1",
                       "행이 없으면 켜짐 (Fix 374 이전과 같은 동작).", off_means="0",
                       source="Fix 374 신설", ref="services/worker_switch.py")),
        Panel(fam="", label="전고점 돌파 반전", group=G_WORKER, job="peak_break_reversal", every="30초", daily=False,
              gate=Ctl("peak_break_reversal_enabled", "켜기", "switch", "1",
                       "행이 없으면 켜짐 (Fix 374 이전과 같은 동작).", off_means="0",
                       source="Fix 374 신설", ref="services/worker_switch.py")),
        # ── 기존 스위치가 있던 것들 ──
        Panel(fam="unified_15m", label="통합 15분 진입 (v224)", group=G_WORKER, job="unified_15m_entry", every="30초",
              gate=Ctl("unified_entry_enabled", "켜기", "switch", "1", "기본 켜짐.", off_means="0",
                       source="기존 키", ref=f"{W}/unified_15m_entry_worker.py:164"),
              note="정점 감지(pump_top_detector)를 이 워커가 포괄한다 · 상한은 auto_bb_break_daily_limit"),
        Panel(fam="pump_split", label="볼밴 분할 (급등 분할 진입)", group=G_WORKER, job="pump_split", every="15분",
              gate=Ctl("pump_split_enabled", "켜기", "switch", "0", "기본 꺼짐 — 1 이어야 돈다.", off_means="0",
                       source="기존 키", ref=f"{W}/pump_split_entry_worker.py:761"),
              ctls=(Ctl("pump_split_max_concurrent", "동시 보유 상한", "int", "3", "", 0, 100, "0",
                        source="사장님 UI 값", ref="api/v1/strategy_suggestions.py:575"),
                    Ctl("pump_split_capitals", "1·2·3차 증거금", "text", "10,100,200", "",
                        source="사장님 2026-09-15 승인", ref="api/v1/strategy_suggestions.py:576"),
                    Ctl("pump_split_steps", "심도 %", "text", "3,5,7", "",
                        source="사장님 UI 값", ref="api/v1/strategy_suggestions.py:578"),
                    Ctl("pump_split_sl_roi", "평단 손절 ROI%", "num", "10", "", 1, 100,
                        source="사장님 UI 값", ref="api/v1/strategy_suggestions.py:579"))),
        Panel(fam="bb_swing", label="볼밴 스윙", group=G_WORKER, job="bb_swing", every="60초",
              gate=_ctl_from(bbs, "bb_swing_mode", "모드", "mode3", ref="services/bb_swing_rules.py:95"),
              note="상승장 SHORT 백테스트 전부 적자 · LONG 하단 지지만 흑자 (2026-09-14) → 권장 LONG"),
        Panel(fam="bb_mid_line", label="볼밴 중단선", group=G_WORKER, job="bb_mid_line", every="15분",
              gate=Ctl("bb_mid_line_mode", "모드", "mode3", "shadow", "off | shadow | on",
                       source="Claude가 정함", ref=f"{W}/bb_mid_line_worker.py:42"),
              ctls=(Ctl("bb_mid_line_max_concurrent", "동시 보유 상한", "int", "3", "", 0, 100, "0",
                        source="Claude가 정함 (표본 없음)", ref=f"{W}/bb_mid_line_worker.py:44"),
                    Ctl("bb_mid_line_capital", "증거금", "num", "100", "", 1, 100000,
                        source="Claude가 정함", ref=f"{W}/bb_mid_line_worker.py:46"),
                    Ctl("bb_mid_line_sl_price_pct", "손절 가격 %", "num", "5", "레버 2 에서 ROI −10%", 0.1, 50,
                        source="Claude가 정함", ref=f"{W}/bb_mid_line_worker.py:48"),
                    Ctl("bb_mid_line_top_n", "상위 몇 종목", "int", "30", "", 1, 200,
                        source="Claude가 정함", ref=f"{W}/bb_mid_line_worker.py:50"),
                    Ctl("bb_mid_resist_4h_ref_enabled", "4H 저항 기준 사용", "switch", "1", "", off_means="0",
                        source="Claude가 정함", ref=f"{W}/bb_mid_line_worker.py"))),
        Panel(fam="surge_ladder", label="급등 사다리", group=G_WORKER, job="surge_peak_ladder", every="30초",
              gate=Ctl("surge_ladder_mode", "모드", "mode3", "off", "기본 off (DEFAULT_MODE)",
                       source="Claude가 정함", ref=f"{W}/surge_peak_ladder_worker.py:70")),
        Panel(fam="managed_reentry", label="심볼 관리 재진입 (10 USDT 프로브)", group=G_WORKER,
              job="managed_symbols", every="60초",
              gate=Ctl("managed_symbol_entry_enabled", "진입 켜기", "switch", "1",
                       "0 = 감시만 하고 주문은 안 한다.", off_means="0",
                       source="기존 키 (Fix 365)", ref="services/managed_symbols.py:33"),
              ctls=(Ctl("managed_symbol_enabled", "심볼 관리 기능 자체", "switch", "1", "", off_means="0",
                        source="기존 키", ref="services/managed_symbols.py:32"),
                    Ctl("obv_loss_ladder_mode", "방식", "text", "probe",
                        "probe(기본, 10 USDT 반복) | ladder(Fix 364 사다리)",
                        source="사장님 2026-09-09", ref="services/managed_symbols.py:31"),
                    Ctl("managed_symbol_daily_entry_limit", "하루 재진입 상한", "int", "10", "", 0, 100, "0",
                        source="Claude가 정함", ref="services/managed_symbols.py:35"),
                    Ctl("managed_symbol_concurrent_slots", "전용 동시 보유 슬롯", "int", "5", "", 0, 50, "0",
                        source="Claude가 정함", ref="services/managed_symbols.py:42"),
                    Ctl("managed_symbol_stage1_capital", "1단계 증거금", "num", "10", "", 1, 100000,
                        source="사장님 「다시 10usdt로 진입」", ref="services/managed_symbols.py:43"),
                    Ctl("managed_symbol_max_attempts", "재진입 횟수 상한", "int", "10", "", 0, 100,
                        source="사장님", ref="services/managed_symbols.py:34"))),
        # 🚨 2026-09-16 확인: 이 키를 읽는 워커(auto_bb_breakdown)는 **스케줄에 등록돼 있지 않다**
        #    (scheduler_runner.py:354~360 주석 — v224 통합 15분 진입으로 대체). 켜도 지금은 아무 일도 없다.
        Panel(fam="", label="OBV 자동 진입 (옛 auto_bb_breakdown)", group=G_WORKER,
              job="auto_bb_breakdown", every="스케줄 등록 안 됨", daily=False,
              gate=Ctl("auto_obv_enabled", "켜기", "switch", "0",
                       "이 키를 읽는 워커가 스케줄에서 빠져 있어 지금은 효과가 없다 (되돌릴 때만 의미).",
                       off_means="0", source="기존 키", ref="workers/auto_bb_breakdown_worker.py:341"),
              note="v224 통합 15분 진입이 이 역할을 대신한다 — 되돌리려면 scheduler_runner 주석 해제 + unified_entry_enabled=0"),
        Panel(fam="", label="예약 진입 (사람이 예약한 전략)", group=G_WORKER, job="scheduled_entry",
              every="5분", daily=False,
              gate=Ctl("scheduled_entry_enabled", "켜기", "switch", "0", "기본 꺼짐 — 1 이어야 돈다.", off_means="0",
                       source="기존 키", ref=f"{W}/scheduled_entry_worker.py:64")),
    ]


# 주문을 만들지 않는 「감지 전용」 워커 — 켜기 칸을 두지 않는다 (2026-09-16 확인: 인스턴스·주문 생성 코드 0곳).
DETECTORS: tuple[tuple[str, str], ...] = (
    ("long_bottom_detector", "저점 감지 (5분) → 저점 LONG 워커가 사용"),
    ("pump_top_detector", "정점 감지 (5분) → 통합 15분 진입이 사용"),
    ("pump_dump_early_detector", "급등·급락 초기 감지 (5분) → 알람"),
    ("bb_upper_breakout_short", "BB 상단 돌파 감지 (5분) → 알람"),
    ("macd_reversal_15m", "MACD 반전 감지 (3분) → 알람"),
)


def _external_panels() -> list[Panel]:
    S = _mod_settings("app.services.external_strategies")
    ref = "services/external_strategies.py:104 (mode_of)"
    out = []
    for fam, key, label in (("fujimoto", "fujimoto_mode", "후지모토 3역 호전"),
                            ("mach7", "mach7_mode", "마하세븐 속임수 돌파")):
        gate = _ctl_from(S, key, "모드", "mode3", ref=ref)
        if gate is not None:
            out.append(Panel(fam=fam, label=label, group=G_EXTERNAL, gate=gate, job="external_strategies", every="50초"))
    return out


def global_ctls() -> tuple[Ctl, ...]:
    """전체 스위치. 🚨 halt 는 값의 의미가 거꾸로다 (1 = 중단) — 화면에서 라벨로 구분한다."""
    return (
        Ctl("auto_trading_halt", "자동매매 전면 중단", "switch", "1",
            "1 = 중단 (사람이 만든 전략·사람이 누른 버튼만 주문) · 0 = 자동매매 허용. "
            "행이 없거나 읽기 실패도 중단으로 본다 (fail-closed).",
            off_means="0", source="사장님 2026-09-14 「모든 자동매매는 중단해줘」",
            ref="services/auto_trading_halt.py:47 (halt_enabled)"),
        Ctl("chart_gate_default", "차트 자리 게이트 기본값", "gate3", "on",
            "가족 칸(<가족>_chart_gate)이 비어 있는 실매매 가족에 쓴다. 사람 전략·규칙 가족은 대상이 아니다.",
            source="사장님 2026-09-17 「실매매 워커에도 차트 게이트 적용해줘」", ref="services/chart_gate_live.py (DEFAULT_KEY)"),
        Ctl("force_cci_gate_default", "세력 CCI 게이트 기본값 (볼밴 계열)", "gate3", "shadow",
            "볼밴 계열 5 가족(볼밴 분할·스윙·중단선·BB 이탈·BB 손절 뒤 재진입)의 칸이 비어 있을 때 쓴다. "
            "shadow = 판정만 기록 · on = LONG 은 1시간 세력 CCI>0, SHORT 은 <0 일 때만 새 전략을 만든다.",
            source="사장님 2026-09-19 「볼밴전략도 적극적으로 적용해줘」 · 기본 shadow 는 Claude가 정함 (효과 작음)",
            ref="services/force_cci_gate.py (DEFAULT_KEY)"),
        Ctl("family_loss_breaker_enabled", "가족별 손실 차단기", "switch", "1",
            "켬 = 자동매매 가족의 최근 N일 실현 합이 −기준 밑이면 그 가족의 새 전략을 막고, 관제실에서 풀 때까지 유지 + 알림.",
            off_means="0", source="사장님 2026-09-19 「자동은 적게벌어도 벌어야」 → 「차단기만 개발」",
            ref="services/family_loss_breaker.py (Fix 384)"),
        Ctl("family_loss_breaker_days", "손실 차단기 — 최근 며칠", "int", "7", "이 기간 안에 끝난 전략의 실현 손익을 더한다.",
            lo=1, hi=30, source="Claude가 정함 (45일 모의 = 7일·−30·풀 때까지 유지가 가장 적게 잃음)",
            ref="services/family_loss_breaker.py (S_DAYS)"),
        Ctl("family_loss_breaker_usdt", "손실 차단기 — 기준 USDT", "num", "30", "실현 합이 −이 값 밑이면 막는다.",
            lo=1, hi=100000, source="Claude가 정함", ref="services/family_loss_breaker.py (S_USDT)"),
        Ctl("auto_daily_limit_enabled", "가족별 하루 최대 한도 사용", "switch", "1",
            "0 = 하루 최대 한도를 아예 보지 않는다 (위험).", off_means="0",
            source="사장님 2026-09-15 「모두 일최대 1개」", ref="services/auto_family_registry.py (enabled)"),
        Ctl("sajangnim_top_short_daily_limit", "옛 워커 동시 보유 상한", "int", "20",
            "🚨 이름은 daily 지만 실제 의미는 **동시 보유 상한**이고, 0 이면 정점 SHORT·저점 LONG·실시간 재진입·"
            "BB 이탈 계열 자동 진입이 전부 멈춘다.", lo=0, hi=200, off_means="0",
            source="사장님 UI 값 (Fix 112b)", ref="services/position_limit.py:50 (LIMIT_KEYS)"),
        Ctl("auto_bb_break_daily_limit", "옛 워커 동시 보유 상한 (2순위 키)", "int", "20",
            "위 키가 비어 있을 때만 쓰인다. 두 키를 다르게 두면 헷갈리니 같게 두는 것이 안전하다.",
            lo=0, hi=200, off_means="0", source="옛 카드 값", ref="services/position_limit.py:51"),
    )


# 🎯 Fix 376 반박 검증: 전략 생성 게이트·하루 최대는 적용되는데 화면 줄이 없던 가족 — 칸 두 개(차트 게이트·하루 최대)만 둔다.
_GATE_ONLY_FAMILIES: tuple[tuple[str, str, str], ...] = (
    ("human_template_auto", "사람 전략 자동 재시작·재진입", "청산 뒤 자동 재진입·사다리 재시작이 사람 템플릿을 다시 열 때"),
    ("pending_hc", "HC 속행", "auto_bb_break …PENDING_HC_FAST"),
    ("rt_lastchance", "라스트 찬스 재진입", "auto_bb_break …_lastchance"),
    ("obv_hold", "OBV 보류 진입", "auto_bb_break …OBV_HOLD"),
    ("bb_break", "BB 이탈 자동 (그 밖)", "auto_bb_break (꼬리 표식 없음)"),
    ("sajangnim_top", "정점 SHORT v219 (옛 종류)", "strategy_type sajangnim_top…"),
    ("chart_pattern", "차트 패턴", "strategy_type chart_pattern…"),
    ("auto_other", "기타 자동", "분류 안 되는 자동 전략 — 종류별 칸은 chart_gate_default 를 따른다"),
)


def _gate_only_panels() -> list[Panel]:
    out = []
    for fam, label, note in _GATE_ONLY_FAMILIES:
        gate = Ctl(f"{fam}_chart_gate", "차트 자리 게이트", "gate3", "on",
                   "on = 차트 자리가 아니면 이 가족의 새 전략을 만들지 않는다. 행이 없으면 chart_gate_default → on.",
                   source="사장님 2026-09-17 「실매매 워커에도 차트 게이트 적용해줘」",
                   ref="services/chart_gate_live.py (mode_for)")
        out.append(Panel(fam=fam, label=label, group=G_WORKER, gate=gate, job="(여러 워커)", every="—",
                         note=f"켜기 스위치가 따로 없는 가족 — {note}"))
    return out


def _with_live_gate(p: Panel) -> Panel:
    """🎯 Fix 376: 실매매 가족 줄에 「차트 자리 게이트」 칸 (판정 = services/chart_gate_live · 전략 생성 지점)."""
    if not p.fam:
        return p
    from dataclasses import replace
    gate = Ctl(f"{p.fam}_chart_gate", "차트 자리 게이트", "gate3", "on",
               "on = 차트 자리(SHORT 16시간 고점 −3% 이내·일봉 UP 아님 / LONG 24h −5% 또는 5분 고점 −4% 조정)가 아니면 "
               "전략을 만들지 않는다. 행이 없으면 chart_gate_default → on.",
               source="사장님 2026-09-17 「실매매 워커에도 차트 게이트 적용해줘」 · 숫자 Claude가 정함",
               ref="services/chart_gate_live.py (mode_for)")
    if p.fam == "success_reentry":
        gate = replace(gate, help="이 칸은 「익절 뒤 재진입」으로 **새 전략을 만들 때**만 본다. "
                                  "기존 포지션에 붙는 피라미딩 추가 주문은 새 전략이 아니라 이 게이트를 지나지 않는다.")
    return replace(p, ctls=(gate,) + tuple(p.ctls))


def _with_force_cci(p: Panel) -> Panel:
    """📊 Fix 380: 볼밴 계열 줄에 「세력 CCI 게이트」 칸 (판정 = services/force_cci_gate · 전략 생성 지점)."""
    from app.services.force_cci_gate import BB_FAMILIES
    if p.fam not in BB_FAMILIES:
        return p
    from dataclasses import replace
    gate = Ctl(f"{p.fam}_force_cci_gate", "세력 CCI 게이트", "gate3", "shadow",
               "on = LONG 은 1시간 세력 CCI>0, SHORT 은 <0 일 때만 이 가족의 새 전략을 만든다. "
               "행이 없으면 force_cci_gate_default → shadow(기록만). 근거 docs/learning/BB_FORCE_CCI_2026-09-19.md",
               source="사장님 2026-09-19 「볼밴전략도 적극적으로 적용해줘」 · 기본 shadow 는 Claude가 정함",
               ref="services/force_cci_gate.py (mode_for)")
    return replace(p, ctls=tuple(p.ctls) + (gate,))


def _with_loss_breaker(p: Panel) -> Panel:
    """⛔ Fix 384: 자동매매 가족 줄마다 「손실 차단」 칸 (1 = 막는 중 · 0 = 허용 — 풀면 그 뒤 손익만 다시 센다)."""
    if not p.fam:
        return p
    from dataclasses import replace
    c = Ctl(f"{p.fam}_loss_breaker", "손실 차단", "switch", "0",
            "막는 중 = 최근 손실로 차단기가 이 가족의 새 전략을 막고 있다. 「허용」으로 저장하면 풀리고, 그 시각 뒤 손익만 다시 센다.",
            source="Fix 384 가족별 손실 차단기 (자동으로 막는 중이 된다)", ref="services/family_loss_breaker.py (key_for)")
    return replace(p, ctls=tuple(p.ctls) + (c,))


def panels() -> list[Panel]:
    return [_with_loss_breaker(_with_force_cci(p)) for p in
            (_rule_panels() + [_with_live_gate(p) for p in _worker_panels() + _external_panels()]
             + _gate_only_panels())]


# ══════════════════════════════════════════════════════════════════════
# 🗂 Fix 381 (2026-09-19 사장님) — 한 줄씩 순서대로
#   사장님: "자동매매 전략 모두 한눈에 관리할수 있게 정리해서 한줄로 순서를 정해서 나열하고
#           선택하면 풀다운 메뉴로 볼수있게 정리해줘 자동매매 전략이 너무 많이 복잡해"
#   순서 = 사장님 사상(① 급등 정점 SHORT ② 저점 LONG ③ 급등 사다리) → 볼밴 → 재진입·추가 → 반전·기타 → 규칙 가족 → 외부.
#   줄 식별자 = 가족키, 가족키가 없는 줄은 켜기 스위치 키. 여기 없는 줄은 맨 끝 「기타」로 간다 (테스트가 빠짐을 잡는다).
# ══════════════════════════════════════════════════════════════════════
LINE_ORDER: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("① 사장님 핵심", ("top_short", "bottom_long", "surge_ladder")),
    ("② 볼밴 계열", ("pump_split", "bb_swing", "bb_mid_line", "bb_break")),
    ("③ 재진입 · 추가", ("bb_reentry", "success_reentry", "managed_reentry", "ladder_restart_enabled",
                      "rt_lastchance", "human_template_auto")),
    ("④ 반전 · 기타 실매매", ("unified_15m", "resistance_reversal_enabled", "peak_break_reversal_enabled",
                          "auto_obv_enabled", "obv_hold", "pending_hc", "scheduled_entry_enabled",
                          "chart_pattern", "sajangnim_top", "auto_other")),
    ("⑤ 규칙 가족 (가상매매 채택 규칙)", ("rf_s2_short", "rf_bottom_long", "rf_surge_long", "rf_confirm_peak",
                                      "rf_toprev", "rf_off8", "rf_s1_breakdown", "rf_wick_short", "rf_pullback_long",
                                      "rf_multiday_long", "rf_l1_hist_long", "rf_wick_long", "rf_zone_s4")),
    ("⑥ 외부 매매법", ("fujimoto", "mach7")),
)
SECTION_REST = "⑦ 기타"


def line_id(p: Panel) -> str:
    return p.fam or (p.gate.key if p.gate is not None else p.label)


def line_order() -> dict[str, tuple[int, str]]:
    """줄 식별자 → (순번 1부터, 묶음 이름)."""
    out: dict[str, tuple[int, str]] = {}
    n = 0
    for sec, ids in LINE_ORDER:
        for i in ids:
            n += 1
            out[i] = (n, sec)
    return out


def whitelist() -> dict[str, Ctl]:
    """쓸 수 있는 키 전체. daily_max_* 는 가족키에서 만든다."""
    out: dict[str, Ctl] = {c.key: c for c in global_ctls()}
    for c in _shared_rule_ctls():
        out[c.key] = c
    for p in panels():
        if p.gate is not None:
            out[p.gate.key] = p.gate
        for c in p.ctls:
            out[c.key] = c
        if p.fam and p.daily:
            out[f"daily_max_{p.fam}"] = Ctl(
                f"daily_max_{p.fam}", "하루 최대 진입", "int", "1",
                "KST 자정 기준. 0 = 이 가족 새 진입 없음.", lo=0, hi=1000, off_means="0",
                source="사장님 2026-09-15 「모두 일최대 1개」", ref="services/auto_family_registry.py (daily_max)")
    return out
