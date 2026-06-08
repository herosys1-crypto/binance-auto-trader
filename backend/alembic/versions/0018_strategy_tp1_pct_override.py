"""strategy_instances.tp1_pct_override — 사장님 TP1 임계 옵션 (2026-06-08).

배경 (사장님 명시 2026-06-08, 본인 정정 후):
"크라이시스만 -5% 부터 기본으로 실행하고 익절 tp1 시작을 기본 +10% 에서
 +15 +20 +25 를 선택할 수 있게 하는 거야"

값 정책:
- NULL = template default (10, 옛 동작)
- 10/15/20/25 = 사장님 선택 (정상 모드)
- Crisis 모드 = 사장님 옵션 무시 = 옛 CRISIS_OVERRIDE 그대로 (TP1=5)

코드 흐름:
risk_service.evaluate_take_profit_level:
- 정상 모드: tp1_pct_override 적용 (= 사장님 옵션 10/15/20/25)
- Crisis 모드: CRISIS_OVERRIDE 그대로 (TP1=5/TP2=10/TP3=15/TP4=20)

영구 spec: TP1_THRESHOLD_OPTION_SPEC_2026-06-08.md
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0018_tp1_pct_override"
down_revision = "0017_trailing_retrace_pct"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strategy_instances",
        sa.Column(
            "tp1_pct_override",
            sa.Numeric(5, 2),
            nullable=True,
            comment=(
                "사장님 TP1 임계 옵션. "
                "NULL=template default (10), 10/15/20/25=사장님 선택. "
                "정상 모드 = 사장님 옵션 적용, Crisis 모드 = 옛 CRISIS_OVERRIDE 그대로 (TP1=5). "
                "운영 중 PATCH /strategies/{id}/tp1-threshold 로 실시간 변경. "
                "TP1_THRESHOLD_OPTION_SPEC_2026-06-08.md 참조."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("strategy_instances", "tp1_pct_override")
