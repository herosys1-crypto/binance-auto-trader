"""strategy_templates.crisis_max_loss_threshold — 사용자 정의 크라이시스 임계 (2026-05-14).

배경 (사용자 요청 2026-05-14):
크라이시스 모드 진입 임계가 hardcoded -50% 였음. 사용자 마다 위험 선호 다름:
- 보수적 사용자: -60%, -70%, -80% 까지 기다리고 싶음
- 매우 보수적 / 비활성화: -100% (도달 불가능 → 크라이시스 영원히 미발동)

값 정책:
- NULL (default) = global -50% 사용 (기존 동작)
- Decimal -50 ~ -100 = 그 값 사용
- -100 (또는 그 이하) = 크라이시스 비활성 (어떤 손실로도 진입 안 함)

코드 흐름:
risk_service._should_trigger_crisis_mode 가 template.crisis_max_loss_threshold 우선 사용,
없으면 global CRISIS_MAX_LOSS_THRESHOLD (-50).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0015_crisis_threshold"
down_revision = "0014_stage_addmargin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strategy_templates",
        sa.Column(
            "crisis_max_loss_threshold",
            sa.Numeric(8, 4),
            nullable=True,
            comment="크라이시스 모드 진입 임계 ROI (사용자 정의). NULL=global -50%, -100=비활성.",
        ),
    )


def downgrade() -> None:
    op.drop_column("strategy_templates", "crisis_max_loss_threshold")
