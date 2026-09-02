"""Fix 295~297 — 「손절 후 재진입이 한 건도 안 되던」 원인 세 가지.

사장님 보고: "손실일때 청산하고 모니터링 대기하고 진입이 없었어"

실측으로 확인된 것:
  ① 재진입 후보 **19건 중 19건**이 `last_liquidation_price` 결손
     → 기준가가 평단(avg_entry)으로 대체됨
  ② 평단 기준이면 LONG 은 **평단보다 위로** 올라가야 재진입 = 사상의 정반대
     (손절가 기준이면 손절 지점에서 +1% = 싸게 사는 것)
  ③ 화이트리스트가 `pump_split` 68건을 통째로 제외 (오늘 손절 25건 중 13건 제외)
"""
import ast
import inspect
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STREAM = ROOT / "app" / "services" / "stream_service.py"
WORKER = ROOT / "app" / "workers" / "realtime_reentry_worker.py"


# ═══════════════════════════════════════════════════════════════════════
# Fix 295 — 청산가를 **항상** 남긴다
# ═══════════════════════════════════════════════════════════════════════

def test_청산가_기록이_v131_분기_밖에_있다():
    """🚨 근본 원인: `last_liquidation_price` 를 쓰는 곳이
    `retry_after_liquidation_enabled` **분기 안** 한 곳뿐이었다.
    일반 손절은 안 채워서 재진입 기준가가 전건 결손이었다.
    """
    src = STREAM.read_text(encoding="utf-8")
    assert src.count("last_liquidation_price") >= 2, (
        "청산가를 남기는 곳이 하나뿐이면 일반 손절에서 또 결손이 난다"
    )
    # Fix 295 블록이 v131 분기(`_use_retry_flow`)보다 **앞**에 있어야
    # 어느 경로로 끝나든 기록된다
    i_fix = src.find("Fix 295")
    i_retry = src.find("_use_retry_flow = False")
    assert 0 < i_fix < i_retry, (
        "청산가 기록이 v131 분기 뒤에 있으면 일반 손절 경로를 못 탄다"
    )


def test_청산가_기록_실패가_청산을_막지_않는다():
    """기록은 부수 작업이다 — 실패해도 청산 처리는 계속돼야 한다."""
    src = STREAM.read_text(encoding="utf-8")
    blk = src[src.find("Fix 295"):src.find("_use_retry_flow = False")]
    assert "try:" in blk and "except" in blk, "기록을 try 로 감싸야 한다"


# ═══════════════════════════════════════════════════════════════════════
# Fix 296 — 기준가 fallback (주석이 적어 둔 것을 코드가 안 하고 있었다)
# ═══════════════════════════════════════════════════════════════════════

def test_실청산가가_평단보다_먼저다():
    """`exit_fill`(실 청산 체결가)이 손절가 그 자체다. 평단보다 먼저 써야 한다.

    옛 코드는 평단이 2순위라 exit_fill(3순위)에 **도달할 수 없었다**
    (평단이 0 이 아니면 거기서 멈춘다).
    """
    src = WORKER.read_text(encoding="utf-8")
    i_exit = src.find('_px_src = "exit_fill"')
    i_avg = src.find('_px_src = f"avg_entry-')
    assert i_exit > 0 and i_avg > 0, "두 소스가 모두 있어야 한다"
    assert i_exit < i_avg, "exit_fill 이 평단보다 먼저 시도돼야 한다"


def test_평단_fallback은_손절ROI를_역산한다():
    """주석이 이미 적어 둔 것: "SL -5% 로 청산됐으면 손절가 ≈ 평단 × 0.95".
    코드가 그걸 안 하고 평단을 그대로 쓰면 판정이 통째로 뒤집힌다.
    """
    src = WORKER.read_text(encoding="utf-8")
    assert 'avg_entry-' in src, "역산한 값을 소스 이름에 남겨 추적 가능해야 한다"
    # 역산식이 실제로 있는가 (ROI / 레버리지)
    assert "force_sl_roi_override" in src and "si.leverage" in src, (
        "손절 ROI 와 레버리지로 가격 변동폭을 역산해야 한다"
    )


def test_역산_방향이_LONG과_SHORT에서_반대다():
    """LONG 손절가는 평단 **아래**, SHORT 은 **위**."""
    src = WORKER.read_text(encoding="utf-8")
    blk = src[src.find("3순위 = 평단에서"):]
    blk = blk[:blk.find("4순위")]
    assert '(1 - _pp / 100) if side == "LONG"' in blk
    assert "(1 + _pp / 100)" in blk


def test_역산_배수에_방어가_있다():
    """설정이 깨져 손절 ROI 가 0 이나 999 여도 기준가가 망가지면 안 된다."""
    src = WORKER.read_text(encoding="utf-8")
    assert "min(max(_pp" in src, "역산 배수에 상·하한이 있어야 한다"


# ═══════════════════════════════════════════════════════════════════════
# Fix 297 — 화이트리스트
# ═══════════════════════════════════════════════════════════════════════

def test_주력전략_pump_split이_재진입_대상이다():
    """최근 7일 68건인데 통째로 빠져 있었다 (오늘 손절 25건 중 13건 제외)."""
    src = WORKER.read_text(encoding="utf-8")
    assert "strategy_type.like('pump_split%')" in src


def test_1회진입전략과_수동은_일부러_제외한다():
    """🚨 넣으면 안 되는 것들 — 넣지 않은 것이 실수가 아님을 못박는다.

    · 수동(DYNAMIC_*)  : 오늘 -124.72 를 잃었다. 자동 재진입 = 그 손실의 자동화.
    · bb_mid_line / surge_peak_ladder : 1회 진입 전략. 자기 쿨다운·재도전이 있다.
    """
    src = WORKER.read_text(encoding="utf-8")
    for bad in ("DYNAMIC_LONG", "DYNAMIC_SHORT", "'bb_mid_line", "'surge_peak_ladder"):
        assert f"strategy_type.like({bad}" not in src, f"{bad} 는 재진입 대상이 아니다"
    # 왜 뺐는지가 코드에 남아 있어야 다음 사람이 무심코 넣지 않는다
    assert "일부러 넣지 않는" in src


def test_single_entry_guard와_목록이_어긋나지_않는다():
    """1회 진입 전략 목록은 한 곳(single_entry_guard)이 진실이다."""
    from app.services.single_entry_guard import SINGLE_ENTRY_STRATEGY_TYPES
    src = WORKER.read_text(encoding="utf-8")
    for t in SINGLE_ENTRY_STRATEGY_TYPES:
        assert f"strategy_type.like('{t}" not in src, (
            f"{t} 는 1회 진입 전략이라 재진입 화이트리스트에 있으면 안 된다"
        )


def test_워커_구문이_온전하다():
    ast.parse(WORKER.read_text(encoding="utf-8"))
    ast.parse(STREAM.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════════════════════════
# Fix 298 — 자체 물타기 전략에 마틴게일 배수를 얹지 않는다
# ═══════════════════════════════════════════════════════════════════════

def test_재진입_자본이_사장님_사다리를_그대로_쓴다():
    """🚨 compute_reentry_capital 은 base_capital 을 **무시**한다 —
    사다리(10/300/600)를 그대로 돌려준다. 이걸 모르고 pump_split 을
    재진입 대상에 넣으면 100 → 300(×3) → 600(×6) 이 된다.
    """
    from app.services.sajangnim_capital import compute_reentry_capital
    from decimal import Decimal
    # base 를 100 으로 줘도 사다리 값이 나온다 (= base 무시)
    got = compute_reentry_capital(2, [Decimal("100")])
    assert got is not None
    assert got != Decimal("100"), (
        "이 함수가 base 를 존중하면 Fix 298 의 전제가 달라진다 — 재확인 필요"
    )


def test_자체물타기_전략은_배수를_안_받는다():
    """볼밴 분할은 이미 1→2→3차(100→200→500) 물타기를 한다.
    거기에 마틴게일을 또 얹으면 **이중 마틴게일** = 사상 ⑦ 위반.
    """
    src = WORKER.read_text(encoding="utf-8")
    assert "_own_ladder" in src, "자체 물타기 전략 판정이 있어야 한다"
    assert 'startswith("pump_split")' in src
    # 배수 분기보다 **먼저** 걸러야 한다
    i_own = src.find("if _own_ladder:")
    i_mart = src.find("compute_reentry_capital, MAX_REENTRY_STAGE")
    assert 0 < i_own < i_mart, "자체 물타기 판정이 마틴게일 계산보다 앞이어야 한다"


def test_자체물타기_판정_실패는_배수_없음으로():
    """자본이 커지는 판정이므로 fail-closed — 모르면 배수를 안 준다."""
    src = WORKER.read_text(encoding="utf-8")
    blk = src[src.find("Fix 298"):src.find("elif _use_success_reentry")]
    assert "_own_ladder = True" in blk.split("except")[-1], (
        "판정 실패 시 _own_ladder=True (배수 없음) 여야 한다"
    )
