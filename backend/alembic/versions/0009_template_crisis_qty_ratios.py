"""strategy_templates 에 crisis_qty_ratios JSONB 컬럼 추가.

배경:
- 기존: 크라이시스 모드 TP qty ratio 가 코드 hardcoded
  ({"TP1":25,"TP2":25,"TP3":50,"TP4":100}, tp_sl_orchestrator.py).
- 한계: 사용자가 전략별로 다른 회복 속도 (예: 보수적 = 더 빠른 청산)
  로 튜닝할 수 없음.
- 변경: nullable JSONB 컬럼 추가. NULL 이면 기존 기본값 그대로 사용
  (backward-compat 보존). 일부 키만 채우면 나머지는 기본값.

스키마:
  crisis_qty_ratios JSONB NULL
  형식: {"TP1": int 0~100, "TP2": int 0~100, "TP3": int 0~100, "TP4": int 0~100}

검증:
- 모델 read 시 tp_sl_orchestrator 가 키별 fallback 처리 — invalid 값은 기본값 사용.
- 새로 추가된 컬럼만 있으므로 데이터 마이그레이션 불필요.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0009_template_crisis_qty_ratios"
down_revision = "0008_risk_events_sid_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strategy_templates",
        sa.Column("crisis_qty_ratios", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("strategy_templates", "crisis_qty_ratios")
