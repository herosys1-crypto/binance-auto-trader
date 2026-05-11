"""strategy_stage_plans.additional_margin_usdt — 단계별 증거금 추가 (사용자 요청).

배경 (2026-05-11 사용자 요청):
사용자가 strategy 의 단계 진입 trigger 발동 시 entry 주문 외에 추가 증거금을
명시적으로 투입할 수 있게 한다. 청산가를 더 멀리 밀어 안전 마진 확보.

동작:
  단계 N 진입 LIMIT 주문 체결됨 → additional_margin_usdt > 0 이면
  stage_trigger_worker 가 add_position_margin API 호출 → 거래소 isolated
  마진 추가. 단계 진입 시점에 사용자가 의도한 만큼.

설정 위치:
  - StrategyStagePlan.additional_margin_usdt (이 컬럼) — strategy 별 단계 plan
  - StrategyTemplate.stages_config["additional_margins"] (JSONB, migration 불필요)
    템플릿에서 default 값 정의 → strategy 생성 시 stage_plan 으로 복사

값:
  - NULL 또는 0 = 추가 안 함 (default — 기존 동작 유지)
  - 양수 = 그 단계 진입 시 추가 증거금 (USDT)
  - 음수 = 거부 (validation)

Isolated 마진 모드 필수 (Cross 에선 add_position_margin 불가능, Binance -4046).
ensure_isolated_margin 이 모든 strategy 진입 시 자동 호출되므로 보장됨.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# 2026-05-11 production fix: 처음엔 '0014_stage_plan_additional_margin' (33자) 였는데
# alembic_version.version_num 가 VARCHAR(32) 라 production 적용 실패. 짧게 변경.
revision = "0014_stage_addmargin"
down_revision = "0013_system_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strategy_stage_plans",
        sa.Column(
            "additional_margin_usdt",
            sa.Numeric(20, 8),
            nullable=True,
            comment="단계 진입 시 추가 isolated 증거금 (USDT). NULL/0 = 추가 안 함.",
        ),
    )


def downgrade() -> None:
    op.drop_column("strategy_stage_plans", "additional_margin_usdt")
