"""strategy_templates 에 tp11~tp20_percent + tp11~tp20_qty_ratio 컬럼 — 익절 20단계 확장.

배경 (사장님 요청 2026-07-22):
  익절 단계를 10 → 20 으로 확장. TP1~10 유지 + TP11~20 추가.
  각 신 단계 = 잔량의 25% (default). 사장님이 명시 설정 시 그 값.

스키마 (모두 nullable, default NULL):
  tp11~tp20_percent NUMERIC(8,4) — 임계 PnL%
  tp11~tp20_qty_ratio NUMERIC(8,4) — 잔량 청산 비율 (default 25)

backward-compat:
  - 기존 strategy 는 tp11~20 모두 NULL → 10단계 동작 그대로
  - 신규 strategy 가 TP11+ 채우면 자동 20단계 동작
  - risk_service = range(1, 21) 자동 확장 (v118)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0021_template_tp11_to_tp20"
down_revision = "0020_force_sl_override"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for n in range(11, 21):  # 11..20
        op.add_column(
            "strategy_templates",
            sa.Column(f"tp{n}_percent", sa.Numeric(8, 4), nullable=True),
        )
        op.add_column(
            "strategy_templates",
            sa.Column(f"tp{n}_qty_ratio", sa.Numeric(8, 4), nullable=True),
        )


def downgrade() -> None:
    for n in range(20, 10, -1):  # 20..11
        op.drop_column("strategy_templates", f"tp{n}_qty_ratio")
        op.drop_column("strategy_templates", f"tp{n}_percent")
