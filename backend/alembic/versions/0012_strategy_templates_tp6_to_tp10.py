"""strategy_templates 에 tp6~tp10_percent + tp6~tp10_qty_ratio 컬럼 — 익절 10단계 확장.

배경 (사용자 요청 2026-05-06):
  익절 단계를 5 → 10 으로 확장. 각 단계는 잔량의 25% 청산 (기존 의미 유지),
  마지막 활성 TP (사용자가 채운 가장 높은 단계) 발동 시 잔량 100% 청산.

스키마 (모두 nullable, default NULL):
  tp6~tp10_percent NUMERIC(8,4) — 임계 PnL%
  tp6~tp10_qty_ratio NUMERIC(8,4) — 잔량 청산 비율 (default 25)

backward-compat:
  - 기존 strategy 는 tp6~10 모두 NULL → 5단계 동작 그대로
  - 신규 strategy 가 TP6+ 채우면 자동 10단계 동작
  - 마지막 활성 TP detection 은 NULL 검사 기반이라 자동 호환
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0012_template_tp6_to_tp10"
down_revision = "0011_strategy_archived"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for n in range(6, 11):  # 6, 7, 8, 9, 10
        op.add_column(
            "strategy_templates",
            sa.Column(f"tp{n}_percent", sa.Numeric(8, 4), nullable=True),
        )
        op.add_column(
            "strategy_templates",
            sa.Column(f"tp{n}_qty_ratio", sa.Numeric(8, 4), nullable=True),
        )


def downgrade() -> None:
    for n in range(10, 5, -1):  # 10..6
        op.drop_column("strategy_templates", f"tp{n}_qty_ratio")
        op.drop_column("strategy_templates", f"tp{n}_percent")
