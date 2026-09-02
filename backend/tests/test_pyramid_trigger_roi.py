"""Fix 300 — 추가 진입 트리거 ROI 설정화 단위 테스트.

사장님 2026-09-03: "추가 트리거가 ROI +5% 인데 안정 종목 TP1 이 3% 면
                   추가 전에 익절됩니다. 이것도 그러면 **+2%부터 진행**하면 될것 같아"

측정은 코드 docstring 에 남긴다. 여기서는 「설정이 실제로 먹히는가」만 본다.
"""
import ast
from pathlib import Path

from app.workers import success_pyramiding_worker as W

SRC = Path(W.__file__).read_text(encoding="utf-8")


class _DB:
    def __init__(self, val=None):
        self.val = val

    def get(self, _model, key):
        if key != W.SETTING_TRIGGER_ROI or self.val is None:
            return None
        return type("R", (), {"value": self.val})()


class _Boom:
    def get(self, *_a):
        raise RuntimeError("db down")


# ── 기본값 ────────────────────────────────────────────────────────────

def test_설정이_없으면_측정최선인_5퍼센트():
    """🚨 코드 기본값은 측정 최선(+656.95)을 유지한다.
    사장님 지시값 2.0 은 **설정 행**으로 넣어 되돌리기를 한 줄로 만든다."""
    assert W._trigger_roi(_DB()) == 5.0
    assert W.MIN_UNREALIZED_ROI_PCT == 5.0


def test_사장님_지시값_2퍼센트가_먹힌다():
    assert W._trigger_roi(_DB("2")) == 2.0
    assert W._trigger_roi(_DB("2.0")) == 2.0
    assert W._trigger_roi(_DB(" 2.5 ")) == 2.5


# ── fail-safe (헌법 167) ──────────────────────────────────────────────

def test_손상값이면_기본값():
    for bad in ("", "  ", "abc", None):
        assert W._trigger_roi(_DB(bad)) == 5.0, bad


def test_범위밖이면_기본값():
    """🚨 0 을 넣으면 「손실 중에도 물량을 키운다」가 된다 — 마틴게일이다.
    음수/0/과대값은 전부 막는다."""
    for bad in ("0", "-1", "0.1", "51", "9999"):
        assert W._trigger_roi(_DB(bad)) == 5.0, bad
    assert W._trigger_roi(_DB("0.5")) == 0.5      # 경계는 허용
    assert W._trigger_roi(_DB("50")) == 50.0


def test_DB가_죽어도_판정은_계속된다():
    assert W._trigger_roi(_Boom()) == 5.0


# ── 실제 판정 경로에 연결됐는가 (상수만 만들고 안 쓰면 소용없다) ──────

def test_판정에_실제로_쓰인다():
    assert "if roi_pct < _trig:" in SRC, "게이트가 옛 상수를 보면 설정이 죽는다"
    assert "if roi_pct < MIN_UNREALIZED_ROI_PCT:" not in SRC


def test_로그도_실제값을_찍는다():
    """🚨 이 저장소가 반복해서 당한 함정 — 로그가 옛 상수를 찍으면
    설정이 안 먹는 걸 눈으로 못 잡는다."""
    tail = SRC[SRC.find("[SUCCESS_PYRAMID] 완료"):]
    assert "_trig, MAX_PYRAMID_COUNT," in tail


def test_런당_1회만_조회한다():
    """후보마다 DB 를 때리면 30초 주기 워커가 느려진다."""
    # 정의부 "def _trigger_roi(db)" 는 세지 않는다 — 호출부만 본다
    assert SRC.count("= _trigger_roi(db)") == 1
    assert SRC.count("def _trigger_roi(db)") == 1


# ── UnboundLocalError 방지 (이 저장소 2회 발생) ───────────────────────

def test_trig_는_무조건_대입된_뒤에_쓰인다():
    fn = next(n for n in ast.walk(ast.parse(SRC))
              if isinstance(n, ast.FunctionDef) and n.name == "run_success_pyramiding")

    def top(body):
        out = []
        for st in body:
            out.append(st)
            if isinstance(st, ast.Try):
                out.extend(top(st.body))
        return out

    assigns = [st.lineno for st in top(fn.body)
               if isinstance(st, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "_trig" for t in st.targets)]
    uses = [n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Name) and n.id == "_trig" and isinstance(n.ctx, ast.Load)]
    assert len(assigns) == 1, "조건부 대입이면 UnboundLocalError 가 난다"
    assert uses and all(u > assigns[0] for u in uses)


# ── 측정 근거가 남아 있는가 ───────────────────────────────────────────

def test_측정표가_기록돼_있다():
    doc = W._trigger_roi.__doc__ or ""
    assert "+556.27" in doc and "+656.95" in doc, "2% 와 5% 의 실측 손익"
    assert "168" in doc and "63" in doc, "추가 횟수 2.7배 근거"
    assert "25%만" in doc, "「추가 전에 익절」이 왜 안 일어나는지"
