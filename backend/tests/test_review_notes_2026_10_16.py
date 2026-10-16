"""10/16 전 전략 검토 — 관제실 줄에 「왜 이 상태인가」 설명 (사장님 「3번 진행」)."""
from app.services import auto_control as AC
from app.services import rule_families as RF


def test_review_notes_keys_are_real_families():
    assert set(RF.REVIEW_NOTES) <= set(RF.FAMILY_BY_KEY)
    assert "유지" in RF.REVIEW_NOTES["rf_zone_s4"] and "그림자" in RF.REVIEW_NOTES["rf_bottom_long"]
    for k in ("rf_surge_long", "rf_s2_short", "rf_confirm_peak", "rf_s1_breakdown", "rf_consensus_long", "rf_pumptop30", "rf_pumptop_mid"):
        assert "폐기" in RF.REVIEW_NOTES[k]


def test_control_room_note_shows_review():
    panels = {p.fam: p for p in AC._rule_panels()}
    assert "10/16 검토" in panels["rf_surge_long"].note and "신호 = 가상매매 규칙" in panels["rf_surge_long"].note
    assert "10/16" not in panels["rf_wick_long"].note
