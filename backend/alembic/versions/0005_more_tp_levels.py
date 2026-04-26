"""TP 단계 5개로 확장 — tp4/tp5 percent + qty_ratio 컬럼 추가.

기존 데이터(3단계 TP) 호환 유지: tp4_*, tp5_* 는 nullable 이라 NULL 이면 미사용으로 처리됨.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0005_more_tp_levels"
down_revision = "0004_dynamic_stages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("strategy_templates", sa.Column("tp4_percent", sa.Numeric(8, 4), nullable=True))
    op.add_column("strategy_templates", sa.Column("tp5_percent", sa.Numeric(8, 4), nullable=True))
    op.add_column("strategy_templates", sa.Column("tp4_qty_ratio", sa.Numeric(8, 4), nullable=True))
    op.add_column("strategy_templates", sa.Column("tp5_qty_ratio", sa.Numeric(8, 4), nullable=True))


def downgrade() -> None:
    op.drop_column("strategy_templates", "tp5_qty_ratio")
    op.drop_column("strategy_templates", "tp4_qty_ratio")
    op.drop_column("strategy_templates", "tp5_percent")
    op.drop_column("strategy_templates", "tp4_percent")
