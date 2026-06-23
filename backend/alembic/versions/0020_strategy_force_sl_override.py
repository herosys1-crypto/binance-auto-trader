"""strategy_instances.force_sl_*_override — 전략별 손실 한도 강제 청산 override (2026-06-24).

배경 (사장님 명시 2026-06-24):
"각각 전략에 따라 다르게 하고 싶은데 가능할까? 모두에게 같은 적용을 하는데
 각각의 전략에 우선하는 방식으로 만들어줘."

= 전역 설정(system_settings.force_sl_*) = 모든 전략 기본 적용 +
  전략별 override = 있으면 우선 (NULL = 전역 상속).

값 정책 (둘 다 nullable, NULL = 전역 상속):
- force_sl_enabled_override: NULL=전역 따름, True/False=전략 강제 on/off
- force_sl_roi_override:     NULL=전역 따름, 5/10/15/20=전략 한도(%)

운영 중 PATCH /strategies/{id}/force-sl 로 실시간 변경.
영구 spec: FORCE_SL_LOSS_LIMIT_SPEC_2026-06-24.md
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0020_force_sl_override"
down_revision = "0019_template_is_favorite"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strategy_instances",
        sa.Column(
            "force_sl_enabled_override",
            sa.Boolean(),
            nullable=True,
            comment=(
                "전략별 손실 한도 강제 청산 활성 override. "
                "NULL=전역 설정(force_sl_{long|short}_enabled) 따름, True/False=전략 우선. "
                "FORCE_SL_LOSS_LIMIT_SPEC_2026-06-24.md 참조."
            ),
        ),
    )
    op.add_column(
        "strategy_instances",
        sa.Column(
            "force_sl_roi_override",
            sa.Numeric(5, 2),
            nullable=True,
            comment=(
                "전략별 손실 한도 강제 청산 ROI override (양수). "
                "NULL=전역 설정(force_sl_{long|short}_roi) 따름, 5/10/15/20=전략 우선. "
                "ROI <= -값 시 발동. PATCH /strategies/{id}/force-sl 로 실시간 변경."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("strategy_instances", "force_sl_roi_override")
    op.drop_column("strategy_instances", "force_sl_enabled_override")
