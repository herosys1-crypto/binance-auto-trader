"""🔍 Fix 363/364 배포 검증 — 「만들었는데 실제로 반영되지 않았고 개발도 되어 있지 않은 경우가 너무 많았어」(사장님 2026-09-09)

한 번에 세 층을 검사한다. 어느 층이 FAIL 이면 그 층에서 멈춘 것이다.
  ① 코드 층  : 지금 컨테이너 안의 파일에 Fix 364 함수·상수·배선이 있는가 (AST 로 호출 경로까지, 중복 정의 없음)
  ② 프로세스 층: 이 컨테이너의 프로세스가 그 파일보다 **나중에** 시작됐는가 (= 재시작 됐는가. grep 은 디스크지 프로세스가 아니다)
  ③ 운영 층  : 살아 있는 OBV 자동 인스턴스마다 단계 계획·손절 override·잔량·차단 사유(Redis)·피라미딩 횟수를 그대로 찍는다
               + Fix 364 설정 키의 **실효값**(DB 행 없으면 기본값)

사용 (VPS, ~/binance-auto-trader/backend):
  docker compose exec -T scheduler python scripts/verify_fix364_deploy.py     # 워커가 도는 컨테이너 (②가 중요)
  docker compose exec -T api       python scripts/verify_fix364_deploy.py     # API 컨테이너
  docker compose exec -T api       python scripts/verify_fix364_deploy.py --code-only   # DB/Redis 없이 ①②만

읽기 전용이다 — 주문·DB 쓰기 없음.
"""
from __future__ import annotations

import ast
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
                print(f"        차단/대기 사유: {str(block)[:220]}")
            else:
                print("        차단/대기 사유: 없음 (이익 중 대기이거나 아직 1사이클 전)")
    finally:
        db.close()


if __name__ == "__main__":
    print(f"verify_fix364_deploy — {datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z} (cwd {_ROOT})")
    check_code()
    check_process()
    if CODE_ONLY:
        skip("--code-only: 운영 층 생략")
    else:
        check_ops()
    print("─" * 70)
    if _fails:
        print(f"결과: FAIL {len(_fails)}건")
        for m in _fails:
            print(f"  • {m}")
        sys.exit(1)
    print("결과: PASS — 코드·프로세스 층 통과. 운영 층은 위 인스턴스 표를 그대로 읽으면 된다.")
