"""exchange_accounts 에 daily_loss_limit_usdt 컬럼 추가 — 계정별 한도 override.

배경:
- 일일 손실 한도 v1/v2 (016b678, 9c0ef1f) 가 global env var
  (settings.daily_loss_limit_usdt) 만 지원.
- 운영 시 mainnet vs testnet, 또는 다중 계정 사용 시 계정별로 다른 한도가 자연스러움.
- 이 마이그레이션이 계정별 override 가능한 nullable 컬럼 추가.

스키마:
  daily_loss_limit_usdt NUMERIC(20,8) NULL
  - NULL → settings.daily_loss_limit_usdt (global) 사용
  - 양수 → 이 계정 전용 한도, global 보다 우선
  - 0 또는 음수 → 비활성 의미 (aggregator 가 skip)

데이터 마이그레이션 불필요 (기본 NULL = 기존 동작 유지).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0010_ex_acc_daily_loss_limit"
down_revision = "0009_template_crisis_qty_ratios"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "exchange_accounts",
        sa.Column("daily_loss_limit_usdt", sa.Numeric(20, 8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("exchange_accounts", "daily_loss_limit_usdt")
