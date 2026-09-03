"""⏰ Fix 337 — 6시간 주기 잡이 구조적으로 굶고 있었다 (misfire_grace_time 1초).

## 감사 실측 (2026-09-03)

    Run time of job "(trigger: interval[6:00:00]...)" was missed by 0:00:01.95
    72시간: interval[6:00:00] → Running 0 / missed 18

→ `chart_patterns` 테이블 **0행** — 2026-08-16 사장님 지시로 만든 차트분석 팀이
  한 번도 실행된 적이 없었다. `binance_changelog_monitor` 도 같이 굶었다.

## OBV 자동 진입 30일 0건에 대한 판정 (고치지 않았다 — 근거)

`run_auto_bb_breakdown` 등록부가 주석 처리된 이유는 **사장님 v224 통합 지시**다:

    "지금까지 모든 자동매매는 오늘 15분 차트 급등과 급락한 심볼만 자동매매를
     하는걸로 통합해서 운영할수 있게 하나도 통합정리해줘"  (2026-08-23)

즉 auto_bb_breakdown → unified_15m_entry 로 대체된 것은 **사장님 결정**이고,
주석을 푸는 것은 사상 변경이라 이번 수정 범위 밖이다. 다만 감사가 확인한 대로
unified_15m_entry 는 `OBV_REVERSE` 를 **생성하지 않는다**(docstring 의
"OBV_REVERSE 포함"은 거짓). 이 공백은 사장님 판단이 필요해 보고서에 남긴다.

## 이 테스트가 지키는 것

1. `job_defaults.misfire_grace_time` 이 1초보다 충분히 크다
2. `coalesce=True` — 밀린 실행을 몰아서 돌리지 않는다 (8/26 IP ban 전력)
3. 이 값의 **근거가 주석에 남아 있다**
"""
import ast
from pathlib import Path


def _src() -> str:
    from app.workers import scheduler_runner as S
    return Path(S.__file__).read_text(encoding="utf-8")


def _blocking_scheduler_call() -> ast.Call:
    tree = ast.parse(_src())
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            name = getattr(f, "id", None) or getattr(f, "attr", None)
            if name == "BlockingScheduler":
                return n
    raise AssertionError("BlockingScheduler(...) 호출을 못 찾음")


def _kw(call: ast.Call, key: str):
    for k in call.keywords:
        if k.arg == key:
            return k.value
    return None


def test_job_defaults_가_설정돼_있다():
    call = _blocking_scheduler_call()
    jd = _kw(call, "job_defaults")
    assert jd is not None, "job_defaults 가 없다 → misfire_grace_time 기본 1초로 6시간 잡이 굶는다"


def test_misfire_grace_time_이_1초보다_크다():
    call = _blocking_scheduler_call()
    jd = _kw(call, "job_defaults")
    assert isinstance(jd, ast.Dict)
    vals = {ast.literal_eval(k): ast.literal_eval(v) for k, v in zip(jd.keys, jd.values)}
    assert vals.get("misfire_grace_time", 1) >= 60, vals
    assert vals.get("misfire_grace_time", 1) <= 900, "너무 크면 한참 지난 실행을 뒤늦게 돌린다"


def test_coalesce_가_켜져_있다():
    """밀린 여러 회를 1회로 — 거래소 API 폭주 방지."""
    call = _blocking_scheduler_call()
    jd = _kw(call, "job_defaults")
    vals = {ast.literal_eval(k): ast.literal_eval(v) for k, v in zip(jd.keys, jd.values)}
    assert vals.get("coalesce") is True


def test_auto_bb_breakdown_은_여전히_주석이다():
    """🚨 사장님 v224 통합 지시로 꺼진 것 — 이 수정이 몰래 되살리면 안 된다."""
    src = _src()
    assert '# id="auto_bb_breakdown",' in src or "#     id=\"auto_bb_breakdown\"" in src
    # 실제 등록(주석 아닌 줄)은 없어야 한다
    live = [ln for ln in src.splitlines()
            if 'id="auto_bb_breakdown"' in ln and not ln.strip().startswith("#")]
    assert live == [], f"auto_bb_breakdown 이 되살아났다: {live}"


def test_실측_근거가_주석에_남아_있다():
    src = _src()
    for token in ("missed by 0:00:01.95", "Running **0** / missed **18**", "chart_patterns", "IP ban"):
        assert token in src, token
