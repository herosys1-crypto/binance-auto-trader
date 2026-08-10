"""strategy_instances에 = 단계별 재진입 트리거 개별 세팅! (v131 사장님!)

배경 (사장님 요청 2026-08-09):
"기본세팅은 유효해야 하고 항상 이야기 하지만 개별세팅이 우선하는거야
 심플한건 좋은데 중간중간 나름 시장을 분석하고 세팅을 할수 있는게 중요해"

= 하이브리드!
  - retry_trigger_pct (기존!) = 기본값! (default 10%)
  - retry_stage_trigger_pcts (신!) = 단계별 개별 override!

스키마:
  retry_stage_trigger_pcts JSONB DEFAULT '{}'
  값 예:
    {}                        = 모든 단계 = 기본값!
    {"3": 15, "4": 20}        = 3/4단계만 개별!
    {"2": 5, "3": null}       = 2단계 5%, 3단계 = 기본 (null = 명시적 default!)

우선순위 (로직!):
  target_stage = current_stage + 1
  overrides = strategy.retry_stage_trigger_pcts or {}
  if str(target_stage) in overrides and overrides[key] is not None:
      → 개별값 사용!
  else:
      → retry_trigger_pct 기본값 사용!

backward-compat:
  - 기존 전략 = {} → 모든 재진입 = retry_trigger_pct 기본값 (기존 동작!)
  - 신규 전략 = 사장님이 특정 단계만 세팅 = 그 단계만 override!
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = "0024_retry_stage_trigger_pcts"
down_revision = "0023_retry_after_liquidation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strategy_instances",
        sa.Column(
            "retry_stage_trigger_pcts",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("strategy_instances", "retry_stage_trigger_pcts")
