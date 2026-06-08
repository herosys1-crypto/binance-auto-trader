"""strategy_instances.trailing_retrace_pct — 사장님 trailing 옵션 (2026-06-08).

배경 (사장님 명시 2026-06-08):
"tp3단계 익절후 최고가 대비 -5% 하락할때 모두 청산하는 로직을
 전략 인스턴스에 추가로 -10% -15% -20% 세가지 선택박스를 만들어서
 적용할수 있는 기획서와 개발을 추가해줘"

값 정책:
- NULL 또는 5 (default) = 옛 동작 (peak - 5% 회귀 시 전량 청산)
- 10 / 15 / 20 = 사장님 선택 옵션 (더 큰 buffer)
- 운영 중 PATCH endpoint 로 = 실시간 변경 + 즉시 적용

코드 흐름:
risk_service.evaluate_take_profit_level 가 strategy.trailing_retrace_pct 우선 사용,
없으면 global TRAILING_RETRACE_PCT (=5).

영구 spec: TRAILING_RETRACE_POLICY_SPEC_2026-06-08.md
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0017_trailing_retrace_pct"
down_revision = "0016_hot_path_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strategy_instances",
        sa.Column(
            "trailing_retrace_pct",
            sa.Numeric(5, 2),
            nullable=True,
            comment=(
                "사장님 trailing 옵션 (% peak 회귀 시 전량 청산). "
                "NULL/5=default, 10/15/20=옵션 (사장님 선택). "
                "운영 중 PATCH /strategies/{id}/trailing-retrace 로 실시간 변경. "
                "TRAILING_RETRACE_POLICY_SPEC_2026-06-08.md 참조."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("strategy_instances", "trailing_retrace_pct")
