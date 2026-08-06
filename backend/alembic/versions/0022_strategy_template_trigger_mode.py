"""strategy_templates 에 trigger_mode 컬럼 = 신 「차트 OBV 자동」 지원!

배경 (사장님 요청 2026-08-06, spec: docs/CHART_REENTRY_STRATEGY_SPEC.md):
  1단계 진입 후 손절 시 = 4H OBV 첫 하락 봉 + 15m/1h 확인 + 10% 가격 조건
  → 자동 재진입 (같은 방향, 사장님 세팅 자본)

스키마:
  trigger_mode VARCHAR(32) DEFAULT 'PRICE_DOWN_PCT'
  값:
    'PRICE_DOWN_PCT' = 기존 (가격 도달 시 진입) — 기본!
    'OBV_REVERSE'    = 신 (4H OBV 첫 하락 봉 + 15m/1h + 10% 가격)

backward-compat:
  - 기존 template = trigger_mode NULL → 'PRICE_DOWN_PCT' 동작 (기존)
  - 신규 template = trigger_mode='OBV_REVERSE' 명시 → 신 로직
  - stage_trigger_worker = trigger_mode 분기 (chart_analyzer 호출)

헌법 v130:
  '차트 분석 신호 = OBV 반전 = 사장님 자율 정확 재진입!'
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0022_template_trigger_mode"
down_revision = "0021_template_tp11_to_tp20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strategy_templates",
        sa.Column(
            "trigger_mode",
            sa.String(length=32),
            nullable=False,
            server_default="PRICE_DOWN_PCT",
        ),
    )


def downgrade() -> None:
    op.drop_column("strategy_templates", "trigger_mode")
