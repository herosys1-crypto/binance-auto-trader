"""🔍 Fix 363/364 배포 검증 — 「만들었는데 실제로 반영되지 않았고 개발도 되어 있지 않은 경우가 너무 많았어」(사장님 2026-09-09)

한 번에 세 층을 검사한다. 어느 층이 FAIL 이면 그 층에서 멈춘 것이다.
  ① 코드 층  : 지금 컨테이너 안의 파일에 Fix 364 함수·상수·배선이 있는가 (AST 로 호출 경로까지, 중복 정의 없음)
  ② 프로세스 층: 이 컨테이너의 프로세스가 그 파일보다 **나중에** 시작됐는가 (= 재시작 됐는가. grep 은 디스크지 프로세스가 아니다)
  ③ 운영 층  : 살아 있는 OBV 자동 인스턴스마다 단계 계획·손절 override·잔량·차단 사유(Redis)·피라미딩 횟수를 그대로 찍는다
               + Fix 364 설정 키의 **실효값**(DB 행 없으면 기본값)
  ④ Fix 365  : 심볼 관리 재진입 명부·워커 사이클·프로브 배선
  ⑤ Fix 367  : 「➕ 새 전략 (기존 방식)」 = 처음 방식(TP1 +25 · 강제손절 없음) 배선 + 설정 실효값 + 최근 기존 방식 인스턴스 5건
  ⑥ Fix 368  : 외부 전략 2종(후지모토·마하세븐) 배선 · 모드 · 가상 규칙 8개 · 마지막 사이클 · 그림자 신호 수 · 활성 인스턴스

사용 (VPS, ~/binance-auto-trader/backend):
  docker compose exec -T scheduler python scripts/verify_fix364_deploy.py     # 워커가 도는 컨테이너 (②가 중요)
  docker compose exec -T api       python scripts/verify_fix364_deploy.py     # API 컨테이너
  docker compose exec -T api       python scripts/verify_fix364_deploy.py --code-only   # DB/Redis 없이 ①②만

읽기 전용이다 — 주문·DB 쓰기 없음.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import time
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows cp949 콘솔에서도 깨지지 않게
except Exception:  # noqa: BLE001
    pass
CODE_ONLY = "--code-only" in sys.argv
_fails: list[str] = []


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def fail(msg: str) -> None:
    _fails.append(msg)
    print(f"  ❌ {msg}")


def skip(msg: str) -> None:
    print(f"  ⏭  {msg}")


class _NoDB:
    """설정 행이 하나도 없는 DB 흉내 — 기본값 검사용."""

    def get(self, *_a, **_k):
        return None


# ─────────────────────────────────────────────────────────────────────────
# ① 코드 층
# ─────────────────────────────────────────────────────────────────────────
def _calls_in_order(src: str, first: str, second: str, window: int = 600) -> bool:
    i = src.find(first)
    return i >= 0 and second in src[i:i + window]


def _def_count(tree: ast.AST, name: str) -> int:
    return sum(1 for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def check_code() -> None:
    print("① 코드 층")
    st_path = os.path.join(_ROOT, "app", "workers", "stage_trigger_worker.py")
    py_path = os.path.join(_ROOT, "app", "workers", "success_pyramiding_worker.py")
    st_src = open(st_path, encoding="utf-8").read()
    py_src = open(py_path, encoding="utf-8").read()
    st_tree, py_tree = ast.parse(st_src), ast.parse(py_src)

    # 함수 존재 + 중복 정의 없음 (v211 사고: 함수 2번 정의 → 자동매매 전면 중단)
    for tree, name, label in [
        (st_tree, "_obv_stage_sl_roi", "stage_trigger._obv_stage_sl_roi"),
        (st_tree, "_apply_obv_stage_sl", "stage_trigger._apply_obv_stage_sl"),
        (st_tree, "_obv_prev_stage_stopped", "stage_trigger._obv_prev_stage_stopped (Fix 364b 잔량 게이트)"),
        (st_tree, "_obv_prev_stage_filled", "stage_trigger._obv_prev_stage_filled (Fix 363b 체결 확인)"),
        (st_tree, "_obv_stage_cooldown_seconds", "stage_trigger._obv_stage_cooldown_seconds"),
        (py_tree, "_apply_after_add_sl", "pyramiding._apply_after_add_sl (추가 뒤 −5%)"),
        (py_tree, "_is_obv_instance", "pyramiding._is_obv_instance"),
    ]:
        c = _def_count(tree, name)
        (ok if c == 1 else fail)(f"{label}: 정의 {c}개" + ("" if c == 1 else " (1개여야 함)"))

    # 배선 (호출 경로) — 함수가 있어도 안 불리면 없는 것이다
    (ok if _calls_in_order(st_src, "exec_service.trigger_next_stage(", "_apply_obv_stage_sl(db, strategy, next_stage_no)") else fail)(
        "단계 발주 직후 단계별 손절 적용 호출 (trigger_next_stage → _apply_obv_stage_sl)")
    (ok if _calls_in_order(st_src, "elif not _prev_ok363:", "elif not _stopped_ok364:") else fail)(
        "OBV 분기: 체결 확인 다음에 잔량 게이트 (Fix 364b)")
    (ok if "_obv_set_stage_cooldown(_redis, strategy.id, _obv_stage_cooldown_seconds(db))" in st_src else fail)(
        "쿨다운이 설정값(기본 60초)으로 발주 전에 설정됨")
    (ok if "force_market=(_ps_force_market or _is_obv_mode)" in st_src else fail)("OBV 단계 = 시장가 (Fix 363)")
    (ok if _calls_in_order(py_src, "db.add(sugg)", "_apply_after_add_sl(db, si, tpl=_parent_tpl, commit=False)", 200)
     and _calls_in_order(py_src, "_apply_after_add_sl(db, si, tpl=_parent_tpl, commit=False)", "db.commit()", 200) else fail)(
        "피라미딩 추가 기록과 같은 커밋에 −5% 적용 (Fix 364c C8)")
    # Fix 364c 추가 배선
    or_path = os.path.join(_ROOT, "app", "services", "tp_sl_orchestrator.py")
    ex_path = os.path.join(_ROOT, "app", "services", "execution_service.py")
    or_src = open(or_path, encoding="utf-8").read()
    ex_src = open(ex_path, encoding="utf-8").read()
    or_tree = ast.parse(or_src)
    for name, label in [("_residue_clock_anchor", "orchestrator._residue_clock_anchor (잔량 시계 = 체결·추가·부분손절 중 최신)"),
                        ("_record_partial_trim", "orchestrator._record_partial_trim (부분손절 이벤트)")]:
        c = _def_count(or_tree, name)
        (ok if c == 1 else fail)(f"{label}: 정의 {c}개")
    (ok if or_src.count("self._record_partial_trim(strategy, _c, _k, _why)") == 2 else fail)("부분손절 실행 2곳 모두 이벤트 기록")
    (ok if _calls_in_order(or_src, "def _residue_waited_hours(", "since = self._residue_clock_anchor(strategy)", 1200) else fail)(
        "잔량 24h 시계가 새 기준(anchor)을 쓴다")
    i_tr = ex_src.find("def _trim_before_stage(")
    i_cl = ex_src.find("for_stage_transition=True,", i_tr)
    (ok if i_cl > 0 and "reset_pyramid_count(strategy.id)" in ex_src[i_cl:i_cl + 700] else fail)("진입 전 정리 뒤 피라미딩 카운터 리셋 (Fix 364c C1)")
    for name, label in [("_obv_pyramid_count", "stage_trigger._obv_pyramid_count"), ("_obv_stage1_planned_capital", "stage_trigger._obv_stage1_planned_capital")]:
        c = _def_count(st_tree, name)
        (ok if c == 1 else fail)(f"{label}: 정의 {c}개")
    (ok if "compute_trim(db, strategy.symbol, qty, mark, leverage=lev)" in st_src else fail)("잔량 게이트가 부분손절과 같은 compute_trim 경계를 쓴다 (C2/C4)")
    (ok if _calls_in_order(st_src, "def _obv_prev_stage_filled(", "체결 직후 대기", 1500) else fail)("직전 단계 체결 직후 대기 (C5)")

    # 상수·기본값 (DB 행 없음 상태)
    try:
        from app.workers import stage_trigger_worker as W
        from app.workers import success_pyramiding_worker as P
        nodb = _NoDB()
        checks = [
            (W.OBV_STAGE_COOLDOWN_SEC == 60, f"OBV_STAGE_COOLDOWN_SEC = {W.OBV_STAGE_COOLDOWN_SEC} (60)"),
            (W.OBV_STAGE_LOSS_ROI_DEFAULT == -1.0, f"OBV_STAGE_LOSS_ROI_DEFAULT = {W.OBV_STAGE_LOSS_ROI_DEFAULT} (−1 = 스프레드 제외한 손실, 0 이면 사장님 원문)"),
            (W.OBV_STAGE_SL_DEFAULT == "25,15,25,25", f"OBV_STAGE_SL_DEFAULT = {W.OBV_STAGE_SL_DEFAULT}"),
            ([W._obv_stage_sl_roi(nodb, n) for n in (1, 2, 3, 4)] == [25.0, 15.0, 25.0, 25.0], "단계별 손절 25/15/25/25 (기본)"),
            (W._obv_stage_loss_threshold(nodb, 2) == -1.0 and W._obv_stage_loss_threshold(nodb, 3) == -1.0, "손실 조건 기본 = ROI ≤ −1"),
            (W._obv_residue_margin_max(nodb) == 20.0, f"3단계 이상 잔량 상한 = {W._obv_residue_margin_max(nodb)} USDT (20)"),
            (P.AFTER_ADD_SL_DEFAULT == 5.0 and P._after_add_sl_roi(nodb) == 5.0, "추가 뒤 손절 = 5 (기본)"),
            (P._after_add_sl_scope(nodb) == "obv", "추가 뒤 손절 범위 = obv (기본, OBV 자동 인스턴스만)"),
            (P._cap_loss_enabled(nodb) is False, "Fix 269 손절 래칫 = OFF (기본)"),
        ]
        for cond, label in checks:
            (ok if cond else fail)(label)
    except Exception as e:  # noqa: BLE001
        fail(f"워커 모듈 import 실패: {e!r}")


# ─────────────────────────────────────────────────────────────────────────
# ② 프로세스 층
# ─────────────────────────────────────────────────────────────────────────
def _pid1_start_epoch() -> float | None:
    try:
        with open("/proc/1/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        start_ticks = int(fields[19])                      # 22번째 필드(starttime), ')' 뒤 인덱스 19
        with open("/proc/stat") as f:
            btime = next(int(l.split()[1]) for l in f if l.startswith("btime"))
        hz = os.sysconf("SC_CLK_TCK")
        return btime + start_ticks / hz
    except Exception:  # noqa: BLE001
        return None


def check_process() -> None:
    print("② 프로세스 층 (이 컨테이너)")
    start = _pid1_start_epoch()
    if start is None:
        skip("/proc 없음 (컨테이너 밖) — VPS 컨테이너에서 실행해야 의미 있음")
        return
    files = [os.path.join(_ROOT, "app", "workers", "stage_trigger_worker.py"),
             os.path.join(_ROOT, "app", "workers", "success_pyramiding_worker.py"),
             os.path.join(_ROOT, "app", "services", "tp_sl_orchestrator.py"),
             os.path.join(_ROOT, "app", "services", "execution_service.py")]
    newest = max(os.path.getmtime(p) for p in files)
    s_dt = datetime.fromtimestamp(start, tz=timezone.utc).astimezone()
    f_dt = datetime.fromtimestamp(newest, tz=timezone.utc).astimezone()
    if start >= newest:
        ok(f"프로세스 시작 {s_dt:%m-%d %H:%M:%S} ≥ 파일 최신 {f_dt:%m-%d %H:%M:%S} → 새 코드로 돌고 있음 (기동 {(time.time()-start)/60:.0f}분 전)")
    else:
        fail(f"프로세스 시작 {s_dt:%m-%d %H:%M:%S} < 파일 최신 {f_dt:%m-%d %H:%M:%S} → **재시작 안 됨** (docker compose restart api scheduler)")


# ─────────────────────────────────────────────────────────────────────────
# ③ 운영 층
# ─────────────────────────────────────────────────────────────────────────
SETTING_KEYS = [
    ("obv_stage_sl_roi_pcts", "25,15,25,25", "단계별 손절 (단계 진입 직후 적용)"),
    ("obv_stage2_loss_roi_pct", "-1", "2단계 손실 조건 ROI ≤ (0 = 손실이면 곧)"),
    ("obv_stage3_loss_roi_pct", "-1", "3단계 손실 조건 ROI ≤"),
    ("obv_stage4_loss_roi_pct", "-1", "4단계 손실 조건 ROI ≤"),
    ("obv_stage_cooldown_sec", "60", "발주 뒤 체결 반영 대기(초)"),
    ("obv_stage_residue_margin_max_usdt", "20 (=잔량 10×2)", "3단계 이상 잔량 상한(증거금)"),
    ("pyramid_after_add_sl_roi", "5", "이익 구간 추가 뒤 손절"),
    ("pyramid_after_add_sl_scope", "obv", "추가 뒤 손절 적용 범위"),
    ("pyramid_cap_loss_enabled", "0", "Fix 269 손절 래칫"),
    ("pyramid_sides", "LONG,SHORT", "피라미딩 방향"),
    ("pyramid_trigger_roi_pct", "5", "피라미딩 트리거 ROI"),
    ("stage_residue_max_wait_hours", "24", "잔량 최대 대기(h)"),
    ("stage_keep_notional_usdt", "10", "부분손절 잔량(증거금)"),
    ("stage_trim_before_next_enabled", "(코드 기본)", "단계 정리 스위치"),
    ("force_sl_roi_new_default", "25", "새 인스턴스 손절 기본"),
]


def check_ops() -> None:
    print("③ 운영 층")
    try:
        from sqlalchemy import select
        from app.core.database import SessionLocal
        from app.models.system_setting import SystemSetting
        from app.models.strategy_instance import StrategyInstance
        from app.models.strategy_template import StrategyTemplate
        from app.models.strategy_stage_plan import StrategyStagePlan
    except Exception as e:  # noqa: BLE001
        skip(f"DB 모듈 import 실패 → 운영 층 생략: {e!r}")
        return
    try:
        from app.core.strategy_status import TERMINAL_STATUSES
    except Exception:  # noqa: BLE001
        TERMINAL_STATUSES = frozenset({"COMPLETED", "STOPPED", "CANCELLED", "FAILED", "LIQUIDATED"})
    redis = None
    try:
        from app.core.redis_client import get_redis_client
        redis = get_redis_client()
    except Exception as e:  # noqa: BLE001
        skip(f"Redis 없음 (차단 사유·피라미딩 횟수 생략): {e!r}")

    db = SessionLocal()
    try:
        print("  ▸ 설정 실효값 (DB 행 없음 = 기본값)")
        for key, default, label in SETTING_KEYS:
            row = db.get(SystemSetting, key)
            v = None if row is None else row.value
            src = "DB" if v not in (None, "") else "기본"
            print(f"     {key:<36} = {str(v) if src == 'DB' else default:<14} [{src}]  {label}")

        rows = db.execute(
            select(StrategyInstance, StrategyTemplate)
            .join(StrategyTemplate, StrategyInstance.strategy_template_id == StrategyTemplate.id)
            .where(StrategyTemplate.trigger_mode == "OBV_REVERSE")
            .where(~StrategyInstance.status.in_(tuple(TERMINAL_STATUSES)))
            .order_by(StrategyInstance.id.desc())
        ).all()
        print(f"  ▸ 살아 있는 OBV 자동 인스턴스: {len(rows)}건")
        if not rows:
            skip("없음 — 모달 「📊 새 전략 (OBV 자동)」로 10/300/600/600 을 만들면 여기에 나타난다")
        for si, tpl in rows:
            plans = db.execute(
                select(StrategyStagePlan).where(StrategyStagePlan.strategy_instance_id == si.id)
                .order_by(StrategyStagePlan.stage_no)
            ).scalars().all()
            caps = [f"{int(p.stage_no)}:{float(p.planned_capital or 0):g}{'✔' if p.is_triggered else ''}" for p in plans]
            block = None
            pyr = None
            if redis is not None:
                try:
                    b = redis.get(f"stage_trigger_block:strategy:{si.id}")
                    block = b.decode() if isinstance(b, bytes) else b
                    p = redis.get(f"pyramid_count:sid:{si.id}")
                    pyr = p.decode() if isinstance(p, bytes) else p
                except Exception as e:  # noqa: BLE001
                    block = f"(redis 오류 {e!r})"
            print(f"     #{si.id} {si.symbol} {si.side} lev{si.leverage} status={si.status} stage={si.current_stage} "
                  f"qty={si.current_position_qty} avg={getattr(si, 'avg_entry_price', None)} "
                  f"SL={'ON' if si.force_sl_enabled_override else si.force_sl_enabled_override}/−{si.force_sl_roi_override}% "
                  f"TP1={si.tp1_pct_override} 피라미딩={pyr or 0}")
            print(f"        단계: {' '.join(caps) or '(계획 없음)'}")
            n_plans = len(plans)
            if n_plans < 4:
                print(f"        ⚠ 단계 {n_plans}개 — 「3단계 한 번 더」(4단계)가 없다. 새로 만들 때 4칸을 채운다")
            if block:
                try:
                    _b = json.loads(block) if isinstance(block, str) and block.strip().startswith("{") else None
                    block = _b.get("reason") if isinstance(_b, dict) else block
                except Exception:  # noqa: BLE001
                    pass
                print(f"        차단/대기 사유: {str(block)[:220]}")
            else:
                print("        차단/대기 사유: 없음 (이익 중 대기이거나 아직 1사이클 전)")
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────
# ④ Fix 365 심볼 관리 재진입 (명부 · 워커 마지막 사이클 · 프로브 모드 배선)
# ─────────────────────────────────────────────────────────────────────────
def check_managed_symbols() -> None:
    print("④ Fix 365 심볼 관리 재진입")
    try:
        from app.services import managed_symbols as MS
        ok(f"모드 = {MS.loss_ladder_mode(_NoDB())} (probe = 손실이면 전량 청산 → 재진입 관리 / ladder = Fix 364)")
        assert MS.decide_entry(long_ok=True, short_ok=True, active_sides=set(), allow_hedge=False, attempts=0, max_attempts=10)[0] is None
        ok("진입 판정 함수 존재 (양방향 동시 신호 = 보류)")
    except Exception as e:  # noqa: BLE001
        fail(f"managed_symbols 모듈: {e!r}")
        return
    or_src = open(os.path.join(_ROOT, "app", "services", "tp_sl_orchestrator.py"), encoding="utf-8").read()
    (ok if or_src.count("_probe365, _probe_why365 = self._loss_ladder_disabled(strategy)") == 3 else fail)("orchestrator 프로브 훅 3곳 (손절 2 + 다음단계)")
    st_src = open(os.path.join(_ROOT, "app", "workers", "stage_trigger_worker.py"), encoding="utf-8").read()
    (ok if "if _probe365:" in st_src else fail)("stage 워커 OBV 분기 프로브 훅")
    sch = open(os.path.join(_ROOT, "app", "workers", "scheduler_runner.py"), encoding="utf-8").read()
    (ok if 'id="managed_symbols"' in sch else fail)("스케줄러 잡 managed_symbols (60초)")
    if CODE_ONLY:
        return
    try:
        import json as _json
        from sqlalchemy import select
        from app.core.database import SessionLocal
        from app.models.managed_symbol import ManagedSymbol
        db = SessionLocal()
        try:
            rows = db.execute(select(ManagedSymbol).order_by(ManagedSymbol.updated_at.desc())).scalars().all()
            print(f"  ▸ 명부 {len(rows)}건 (모드 {MS.loss_ladder_mode(db)} · 진입 {'ON' if MS.get_bool(db, MS.S_ENTRY) else 'OFF'} · 상한 {MS.get_int(db, MS.S_MAX_ATTEMPTS, 1, 100)}회 · 일일 {MS.get_int(db, MS.S_DAILY, 0, 1000)} · 전용 슬롯 {MS.managed_slots_used(db)}/{MS.get_int(db, MS.S_SLOTS, 0, 100)} · 재진입 1단계 {MS.stage1_capital(db)} USDT)")
            for r in rows[:30]:
                lr = r.last_reasons or {}
                print(f"     {r.symbol:<12} {r.status:<9} 실패 {r.attempts}/{r.max_attempts} 성공 {r.successes} 재진입 {r.total_entries} "
                      f"마지막 {r.last_side or '-'} {r.last_pnl if r.last_pnl is not None else '-'} 판정 {r.last_check_at:%m-%d %H:%M:%S} " if r.last_check_at else
                      f"     {r.symbol:<12} {r.status:<9} 실패 {r.attempts}/{r.max_attempts} 성공 {r.successes} 재진입 {r.total_entries} 마지막 {r.last_side or '-'} 판정 -")
                if lr:
                    print(f"        state: {str(lr.get('state', ''))[:120]}")
                    print(f"        LONG : {str(lr.get('LONG', ''))[:120]}")
                    print(f"        SHORT: {str(lr.get('SHORT', ''))[:120]}")
        finally:
            db.close()
        try:
            from app.core.redis_client import get_redis_client
            raw = get_redis_client().get(MS.REDIS_CYCLE_KEY)
            if raw:
                c = _json.loads(raw)
                print(f"  ▸ 워커 마지막 사이클 {c.get('at')}: 감시 {c.get('watching')} 판정 {c.get('checked')} 진입 {c.get('entered')} 해제 {c.get('released')} 사유 {c.get('skipped')} 등록 {c.get('register')}")
            else:
                skip("워커 사이클 기록 없음 (Redis) — 아직 한 번도 안 돌았거나 10분 넘게 멈춤")
        except Exception as e:  # noqa: BLE001
            skip(f"Redis 조회 실패: {e!r}")
    except Exception as e:  # noqa: BLE001
        fail(f"명부 조회 실패 (마이그레이션 0037 적용됐는지 확인): {e!r}")


# ─────────────────────────────────────────────────────────────────────────
# ⑤ Fix 367 「➕ 새 전략 (기존 방식)」 = 처음 방식 (TP1 +25 · 강제손절 없음)
# ─────────────────────────────────────────────────────────────────────────
LEGACY_SETTING_KEYS = [
    ("legacy_ladder_tp1_pct", "25", "기존 방식 새 전략 TP1 임계 (사장님 verbatim 25)"),
    ("legacy_ladder_force_sl_enabled", "0", "기존 방식 새 전략 강제손절 (0 = 없음, 1 = Fix 362 기본 -25)"),
    ("stage_trim_before_next_enabled", "(코드 기본 OFF)", "단계 정리(Fix 304) 전역 스위치"),
    ("stage_trim_exclude_legacy_manual", "1", "기존 방식은 단계 정리 제외 (1 = 처음 방식, 0 = Fix 304 대로 잔량 10 정리)"),
    ("legacy_ladder_tp1_qty_ratio", "25", "기존 방식 TP1 청산 비율 기준 (모달 기본, 어긋나면 ⚠)"),
]


class _NoRowDB(_NoDB):
    """SystemSettingsService.get 이 쓰는 execute().scalar_one_or_none() 도 None 을 돌려주는 빈 DB."""

    def execute(self, *_a, **_k):
        class _R:
            def scalar_one_or_none(self):
                return None
        return _R()


def check_legacy_ladder() -> None:
    print("⑤ Fix 367 기존 방식 새 전략 = 처음 방식 (TP1 +25 · 강제손절 없음)")

    def _read(rel: str) -> str:
        with open(os.path.join(_ROOT, rel), encoding="utf-8") as f:
            return f.read()

    try:
        ss_src = _read("app/services/strategy_service.py")
        crud_src = _read("app/api/v1/strategies/crud.py")
        tree = ast.parse(ss_src)
        n = _def_count(tree, "legacy_manual_family")
        (ok if n == 1 else fail)(f"strategy_service.legacy_manual_family 정의 {n}개 (1 이어야)")
        has_param = any(
            isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == "create_strategy_instance"
            and "entry_origin" in [a.arg for a in fn.args.kwonlyargs]
            for fn in ast.walk(tree)
        )
        (ok if has_param else fail)("create_strategy_instance(entry_origin=…) 파라미터")
        for pin, label in (
            ("get_legacy_ladder_defaults()", "기존 방식 → 설정 실효값 사용"),
            ("tp1_pct_override=_tp1_default", "TP1 임계가 가족 판정을 따른다"),
            ("force_sl_enabled_override=_fs_on_default", "강제손절 ON/OFF 가 가족 판정을 따른다"),
            ("force_sl_roi_override=_fs_roi_default", "강제손절 ROI 가 가족 판정을 따른다"),
            ("TP1_PCT_DEFAULT, True, _new_force_sl_roi", "OBV 자동·워커 경로는 Fix 362 기본 그대로"),
        ):
            (ok if pin in ss_src else fail)(f"{label}: {pin}")
        (ok if "entry_origin=ENTRY_ORIGIN_MANUAL" in crud_src else fail)("POST /strategies 가 entry_origin=manual_modal 을 넘긴다")
        from app.core import risk_constants as RC
        (ok if RC.LEGACY_LADDER_TP1_DEFAULT == 25 and RC.LEGACY_LADDER_FORCE_SL_DEFAULT is False else fail)(
            f"코드 기본값 TP1 {RC.LEGACY_LADDER_TP1_DEFAULT} / 강제손절 {RC.LEGACY_LADDER_FORCE_SL_DEFAULT}")
        from app.services.strategy_service import ENTRY_ORIGIN_MANUAL as _M, legacy_manual_family as _fam
        _D = "DYNAMIC_LONG"
        _cases = (
            (_fam("PRICE_DOWN_PCT", "fixed", _M, _D), True), (_fam("PRICE_UP_PCT", "scheduled", _M, "DYNAMIC_SHORT"), True),
            (_fam(None, None, _M, _D), True),
            (_fam("OBV_REVERSE", "fixed", _M, _D), False), (_fam("PRICE_DOWN_PCT", "fixed", None, _D), False),
            (_fam("PRICE_DOWN_PCT", "split_entry", _M, _D), False), (_fam("PRICE_DOWN_PCT", "stage_ladder", _M, _D), False),
            (_fam("PRICE_DOWN_PCT", "fixed", _M, "terminal_manual"), False), (_fam("PRICE_DOWN_PCT", "fixed", _M, None), False),
        )
        (ok if all(a == b for a, b in _cases) else fail)("가족 판정 9례 (모달 + 가격 트리거 + fixed/scheduled + DYNAMIC_* 만 True)")
        trim_src = _read("app/services/stage_trim.py")
        trim_tree = ast.parse(trim_src)
        (ok if _def_count(trim_tree, "is_legacy_manual_instance") == 1 and _def_count(trim_tree, "legacy_manual_excluded") == 1 else fail)(
            "stage_trim.is_legacy_manual_instance / legacy_manual_excluded 정의 1개씩")
        i_il = trim_src.find("def is_legacy_manual_instance(")
        (ok if 'getattr(strategy, "entry_profile", None)' in trim_src[i_il:i_il + 1500] and "db.get(StrategyTemplate" not in trim_src[i_il:i_il + 1500] else fail)(
            "런타임 판정은 entry_profile 표식만 본다 (템플릿 추정 없음 = 배포 전 인스턴스 불변)")
        (ok if "entry_profile=(LEGACY_MANUAL_PROFILE if _is_legacy367 else None)" in ss_src else fail)("생성 시 entry_profile 표식 저장")
        (ok if "entry_profile" in _read("app/models/strategy_instance.py") and os.path.exists(os.path.join(_ROOT, "alembic/versions/0039_strategy_instances_entry_profile.py")) else fail)(
            "모델 컬럼 + alembic 0039 파일")
        ms_src = _read("app/static/js/multi-symbol.js")
        (ok if "trigger_mode: cmState._triggerMode || 'PRICE_DOWN_PCT'" in ms_src else fail)("다중 심볼 템플릿도 trigger_mode 를 보낸다 (OBV 다중심볼이 가격 사다리로 저장되던 누락)")
        i_te = trim_src.find("def trim_enabled(")
        (ok if "if legacy_manual_excluded(db) and is_legacy_manual_instance(db, strategy):" in trim_src[i_te:i_te + 4000] else fail)(
            "trim_enabled 안에 기존 방식 제외 훅 (Fix 304 정리는 기존 방식에 안 붙는다)")
        es_src = _read("app/services/execution_service.py")
        (ok if "if trim_enabled(self.db, strategy) and stage_no > 1:" in es_src else fail)("_trim_before_stage 가 여전히 trim_enabled(db, strategy) 를 통과한다")
        from app.services.system_settings_service import SystemSettingsService as _SSS
        d = _SSS(_NoRowDB()).get_legacy_ladder_defaults()
        (ok if d == (RC.LEGACY_LADDER_TP1_DEFAULT, False, 0) else fail)(f"설정 행 없을 때 실효값 = {d} (25, False, 0 이어야)")
    except Exception as e:  # noqa: BLE001
        fail(f"코드 층 검사 실패: {e!r}")
        return
    if CODE_ONLY:
        skip("--code-only: 운영 층 생략")
        return
    try:
        from sqlalchemy import select
        from app.core.database import SessionLocal
        from app.models.system_setting import SystemSetting
        from app.models.strategy_instance import StrategyInstance
        from app.models.strategy_template import StrategyTemplate
    except Exception as e:  # noqa: BLE001
        skip(f"DB 모듈 import 실패 → 운영 층 생략: {e!r}")
        return
    db = SessionLocal()
    try:
        print("  ▸ 설정 실효값 (DB 행 없음 = 기본값)")
        for key, default, label in LEGACY_SETTING_KEYS:
            row = db.get(SystemSetting, key)
            v = None if row is None else row.value
            src = "DB" if v not in (None, "") else "기본"
            print(f"     {key:<36} = {str(v) if src == 'DB' else default:<14} [{src}]  {label}")
        rows = db.execute(
            select(StrategyInstance, StrategyTemplate)
            .join(StrategyTemplate, StrategyInstance.strategy_template_id == StrategyTemplate.id)
            .where(StrategyTemplate.trigger_mode.in_(("PRICE_DOWN_PCT", "PRICE_UP_PCT")))
            .where(StrategyTemplate.strategy_type.startswith("DYNAMIC_", autoescape=True))
            .where(StrategyInstance.capital_management_mode.in_(("fixed", "scheduled")))
            .order_by(StrategyInstance.id.desc())
            .limit(5)
        ).all()
        print(f"  ▸ 최근 기존 방식(모달·가격 트리거·DYNAMIC_*) 인스턴스 {len(rows)}건 — 배포 뒤 새로 만든 것은 ✔Fix367 로 보여야 한다")
        if not rows:
            skip("없음 — 「➕ 새 전략 (기존 방식)」 으로 하나 만들면 여기에 나타난다")
        from app.services.stage_trim import is_legacy_manual_instance as _is_leg, legacy_manual_excluded as _lex, trim_enabled as _trim_on
        from app.services.system_settings_service import SystemSettingsService as _SSS2
        _qty_ref = _SSS2(db).get_legacy_ladder_tp1_qty_ratio()
        _excl_on = _lex(db)
        for si, tpl in rows:
            _tp1, _on, _roi = si.tp1_pct_override, si.force_sl_enabled_override, si.force_sl_roi_override
            _prof = getattr(si, "entry_profile", None)
            _mark = "✔Fix367" if _prof == "legacy_manual" else "(표식 없음 = 배포 전 생성 → 옛 동작 그대로)"
            _made = f"{si.created_at:%m-%d %H:%M}" if getattr(si, "created_at", None) else "?"
            _fam_rt = _is_leg(db, si, tpl)
            _trim = _trim_on(db, si)
            _qty = tpl.tp1_qty_ratio
            _qty_flag = "" if (_qty is not None and float(_qty) == float(_qty_ref)) else f" ⚠TP1청산≠{_qty_ref}"
            print(f"     #{si.id} {si.symbol} {si.side} status={si.status} stage={si.current_stage} made={_made} "
                  f"TP1={_tp1} 강제SL={'끔' if _on is False else ('ON' if _on else '전역')}/{_roi} "
                  f"템플릿TP1청산={_qty}%{_qty_flag} 표식={_prof} 단계정리={'적용' if _trim else '제외'} {_mark}")
            if _fam_rt and _trim and _excl_on:
                fail(f"#{si.id} 기존 방식(표식)인데 단계 정리가 적용된다 — stage_trim_exclude_legacy_manual=1 인데도 제외가 안 됨")
    except Exception as e:  # noqa: BLE001
        fail(f"운영 층 조회 실패: {e!r}")
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────
# ⑥ Fix 368 외부 전략 2종 (후지모토 3역 호전 · 마하세븐 속임수 돌파)
# ─────────────────────────────────────────────────────────────────────────
def check_external_strategies() -> None:
    print("⑥ Fix 368 외부 전략 2종 (후지모토 3역 호전 · 마하세븐 속임수 돌파)")
    try:
        from app.services import external_strategies as ES
        from app.services import chart_learning as CL
        keys = {r.key for r in CL.RULES}
        want = {k for k, _s, _l, _f in ES.PAPER_RULES}
        (ok if want <= keys else fail)(f"가상 규칙 등록 {len(want & keys)}/{len(want)} (chart_learning.RULES)")
        (ok if CL.LABEL_VERSION >= 4 else fail)(f"LABEL_VERSION = {CL.LABEL_VERSION} (4 이상 = 옛 행 재라벨)")
        from app.services.single_entry_guard import SINGLE_ENTRY_STRATEGY_TYPES as _SET, SINGLE_ENTRY_TEMPLATE_PREFIXES as _SEP
        (ok if {ES.FUJIMOTO_TYPE, ES.MACH7_TYPE} <= set(_SET) and {ES.FUJIMOTO_PREFIX, ES.MACH7_PREFIX} <= set(_SEP) else fail)(
            "피라미딩 워커 제외 목록(single_entry_guard)에 두 가족 등록")
        with open(os.path.join(_ROOT, "app/workers/scheduler_runner.py"), encoding="utf-8") as f:
            sr = f.read()
        (ok if 'id="external_strategies"' in sr and "run_external_strategies_once" in sr else fail)("스케줄러 잡 external_strategies (60초)")
        with open(os.path.join(_ROOT, "app/workers/external_strategies_worker.py"), encoding="utf-8") as f:
            wk = f.read()
        for pin, label in (("create_surge_position(", "1차/단일 진입 = 검증된 create_surge_position 경로"),
                           ('mode="preserve"', "후지모토 2·3차 = preserve 추가"),
                           ("bars = kl[:-1]", "진행 중 봉 제외(완성봉만 판정)")):
            (ok if pin in wk else fail)(f"{label}: {pin}")
        (ok if ES.SETTINGS["fujimoto_mode"][0] == "shadow" and ES.SETTINGS["mach7_mode"][0] == "shadow" else fail)("코드 기본 모드 = shadow (주문 없음)")
    except Exception as e:  # noqa: BLE001
        fail(f"코드 층 검사 실패: {e!r}")
        return
    if CODE_ONLY:
        skip("--code-only: 운영 층 생략")
        return
    try:
        from app.core.database import SessionLocal
        from app.services import external_strategies as ES
        db = SessionLocal()
        try:
            print("  ▸ 설정 실효값 (DB 행 없음 = 기본값)")
            for key, (default, label, origin) in ES.SETTINGS.items():
                v = ES.setting(db, key)
                print(f"     {key:28} = {v:<12} [{'DB' if v != default else '기본'}]  {label} ({origin})")
            from app.workers.external_strategies_worker import _active_by_prefix
            for fam, prefix in (("후지모토", ES.FUJIMOTO_PREFIX), ("마하세븐", ES.MACH7_PREFIX)):
                act = _active_by_prefix(db, prefix)
                print(f"  ▸ {fam} 활성 인스턴스 {len(act)}건: " + ", ".join(f"#{si.id} {s} {si.side}" for s, si in act.items()))
        finally:
            db.close()
        try:
            from app.core.redis_client import get_redis_client
            r = get_redis_client()
            raw = r.get("ext:last_cycle")
            raw = raw.decode() if isinstance(raw, bytes) else raw
            if raw:
                cyc = json.loads(raw)
                print(f"  ▸ 마지막 사이클 {cyc.get('at')}: fujimoto={cyc.get('fujimoto')} mach7={cyc.get('mach7')} 심볼={cyc.get('symbols')} "
                      f"평가={cyc.get('eval')} 신호={cyc.get('sig')} 그림자={cyc.get('shadow')} 진입={cyc.get('entered')} 추가={cyc.get('added')} 오류={cyc.get('err')}")
            else:
                skip("워커 사이클 기록 없음 (Redis ext:last_cycle) — 아직 한 번도 안 돌았거나 두 모드 모두 off")
            n_fj = sum(1 for _ in r.scan_iter("ext:shadow:fujimoto:*", count=500))
            n_m7 = sum(1 for _ in r.scan_iter("ext:shadow:mach7:*", count=500))
            print(f"  ▸ 그림자 신호(7일 보관): 후지모토 {n_fj} · 마하세븐 {n_m7}")
        except Exception as e:  # noqa: BLE001
            skip(f"Redis 조회 실패: {e!r}")
    except Exception as e:  # noqa: BLE001
        fail(f"운영 층 조회 실패: {e!r}")


if __name__ == "__main__":
    print(f"verify_fix364_deploy — {datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z} (cwd {_ROOT})")
    check_code()
    check_process()
    if CODE_ONLY:
        skip("--code-only: 운영 층 생략")
    else:
        check_ops()
    check_managed_symbols()
    check_legacy_ladder()
    check_external_strategies()
    print("─" * 70)
    if _fails:
        print(f"결과: FAIL {len(_fails)}건")
        for m in _fails:
            print(f"  • {m}")
        sys.exit(1)
    print("결과: PASS — 코드·프로세스 층 통과. 운영 층은 위 인스턴스 표를 그대로 읽으면 된다.")
