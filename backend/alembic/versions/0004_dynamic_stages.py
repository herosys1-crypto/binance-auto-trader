"""dynamic stages config (1~10 stages)

Revision ID: 0004_dynamic_stages
Revises: 0003_daily_risk_limits
Create Date: 2026-04-25 11:00:00.000000

변경 사항:
  - strategy_templates 에 stages_config (JSONB) 컬럼 추가.
  - 기존 stage1_capital ~ stage4_capital 데이터를 stages_config 의
    {"capitals": [...]} 로 자동 변환.
  - 기존 stage1~4 컬럼은 backward-compat 을 위해 유지하되 nullable 로 변경.
  - stage2/3 trigger_percent, stage4 trigger_mode/percent 도 nullable 로 완화
    (신규 템플릿이 stages_config 만 채울 수 있도록).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_dynamic_stages"
down_revision = "0003_daily_risk_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) stages_config JSONB 컬럼 추가 (NULL 허용)
    op.add_column(
        "strategy_templates",
        sa.Column(
            "stages_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    # 2) 기존 stage1~4_capital 값을 stages_config 로 마이그레이션
    op.execute(
        """
        UPDATE strategy_templates
        SET stages_config = jsonb_build_object(
            'capitals',
            jsonb_build_array(stage1_capital, stage2_capital, stage3_capital, stage4_capital),
            'trigger_percents',
            jsonb_build_array(NULL, stage2_trigger_percent, stage3_trigger_percent, NULL),
            'last_stage_trigger_mode', stage4_trigger_mode,
            'last_stage_trigger_percent', stage4_trigger_percent
        )
        WHERE stages_config IS NULL
        """
    )

    # 3) 기존 stageX 컬럼들 nullable 화 (신규 템플릿은 stages_config 만 채워도 OK)
    with op.batch_alter_table("strategy_templates") as batch:
        batch.alter_column("stage1_capital", nullable=True)
        batch.alter_column("stage2_capital", nullable=True)
        batch.alter_column("stage3_capital", nullable=True)
        batch.alter_column("stage4_capital", nullable=True)
        batch.alter_column("stage2_trigger_percent", nullable=True)
        batch.alter_column("stage3_trigger_percent", nullable=True)
        batch.alter_column("stage4_trigger_mode", nullable=True)


def downgrade() -> None:
    # downgrade: stages_config 삭제, stage 컬럼들 not null 복원
    with op.batch_alter_table("strategy_templates") as batch:
        batch.alter_column("stage1_capital", nullable=False)
        batch.alter_column("stage2_capital", nullable=False)
        batch.alter_column("stage3_capital", nullable=False)
        batch.alter_column("stage4_capital", nullable=False)
        batch.alter_column("stage2_trigger_percent", nullable=False)
        batch.alter_column("stage3_trigger_percent", nullable=False)
        batch.alter_column("stage4_trigger_mode", nullable=False)
    op.drop_column("strategy_templates", "stages_config")
