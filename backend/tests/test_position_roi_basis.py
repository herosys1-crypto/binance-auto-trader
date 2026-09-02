"""Fix 302 — 손실율 분모 단위 테스트.

사장님 2026-09-03: "첫번째 이미지는 손실율 표기가 잘못된것 같고"

🚨 Binance positionRisk 의 두 필드는 이름이 비슷한데 뜻이 완전히 다르다:
     isolatedWallet = 실제로 넣은 증거금        (손익 무관 = 고정)
     isolatedMargin = isolatedWallet + 미실현손익 (손실 나면 줄어든다)

분모에 isolatedMargin 을 쓰면 손실이 커질수록 분모도 작아져 **손실률이 가속 왜곡**된다.
이 저장소는 v102 에서 같은 함정을 계정 요약 경로에서 이미 고쳤는데,
포지션 목록 경로에는 그대로 남아 있었다.
"""
from decimal import Decimal
from pathlib import Path

import app.api.v1.exchange_accounts as EA

SRC = Path(EA.__file__).read_text(encoding="utf-8")


def _roi(wallet, margin, upnl):
    """운영 코드와 같은 식 — 분모 선택 규칙만 재현한다."""
    basis = wallet if wallet > 0 else margin
    return (upnl / basis * 100) if basis > 0 else Decimal("0")


# ── 실측 사례 고정 ────────────────────────────────────────────────────

def test_실측_2032_AKEUSDT():
    """2026-09-03 실제 포지션. 화면은 -96.74% 를 보여줬다."""
    roi = _roi(Decimal("300.52482789"), Decimal("150.72380288"),
               Decimal("-149.80102501"))
    assert Decimal("-50.5") < roi < Decimal("-49.0"), roi     # 정답 ≈ -49.85%
    옛 = Decimal("-149.80102501") / Decimal("150.72380288") * 100
    assert 옛 < Decimal("-99"), "옛 식은 -99% 대였다"


def test_손실이_커질수록_옛식은_발산한다():
    """🚨 이게 이 버그가 위험한 이유 — 손실이 증거금에 근접하면 -100% 를 넘는다."""
    wallet = Decimal("300")
    for loss in ("-50", "-150", "-250", "-299"):
        upnl = Decimal(loss)
        margin = wallet + upnl                      # 거래소가 주는 isolatedMargin
        정답 = upnl / wallet * 100
        옛 = upnl / margin * 100
        assert Decimal("-100") <= 정답 <= Decimal("0"), 정답
        assert 옛 < 정답, f"옛 식이 항상 더 나쁘게 보인다: {옛} vs {정답}"
    # 마지막(-299)에서 옛 식은 -29900% 급으로 발산한다
    assert (Decimal("-299") / Decimal("1") * 100) < Decimal("-1000")


def test_이익일_때도_옛식은_과소표시():
    """이익이면 분모가 커져 수익률이 **작게** 보인다 — 방향만 반대로 같은 결함."""
    wallet, upnl = Decimal("300"), Decimal("150")
    assert _roi(wallet, wallet + upnl, upnl) == Decimal("50")
    assert (upnl / (wallet + upnl) * 100) < Decimal("50")


def test_ROI_는_증거금_대비로_정의된다():
    """레버 2배·명목 600·증거금 300 이면, 가격 -25% 는 ROI -50% 다."""
    assert _roi(Decimal("300"), Decimal("150"), Decimal("-150")) == Decimal("-50")


# ── fallback ─────────────────────────────────────────────────────────

def test_wallet_이_없으면_옛_필드로_떨어진다():
    """구 API/필드 결손이어도 화면이 비지 않아야 한다."""
    assert _roi(Decimal("0"), Decimal("200"), Decimal("-50")) == Decimal("-25")


def test_둘_다_없으면_0():
    assert _roi(Decimal("0"), Decimal("0"), Decimal("-50")) == Decimal("0")


# ── 코드에 실제로 반영됐는가 ──────────────────────────────────────────

def test_운영코드가_wallet_을_우선한다():
    assert 'iso_wallet = Decimal(str(p.get("isolatedWallet"' in SRC
    assert "iso_basis = iso_wallet if iso_wallet > 0 else iso_margin" in SRC
    assert "roi = upnl / iso_basis * 100" in SRC
    assert "roi = upnl / iso_margin * 100" not in SRC, "옛 식이 남아 있으면 안 된다"


def test_margin_표시도_같은_기준을_쓴다():
    """🚨 손익률과 「실투입」이 다른 분모를 쓰면 화면 두 칸이 서로 모순된다."""
    assert "margin_display = iso_basis" in SRC


def test_실측_근거가_주석에_남아_있다():
    """다음 사람이 무심코 isolatedMargin 으로 되돌리지 않도록."""
    assert "isolatedWallet + 미실현손익" in SRC
    assert "300.52" in SRC and "150.72" in SRC
    assert "v102" in SRC, "같은 함정을 이미 한 번 고쳤다는 사실"
