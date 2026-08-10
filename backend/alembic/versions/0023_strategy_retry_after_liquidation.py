"""strategy_instances에 = 청산 후 자동 재진입 + 자본 관리 컬럼! (v131 사장님!)

배경 (사장님 요청 2026-08-09, spec: docs/AUTO_RETRY_AFTER_LIQUIDATION_SPEC_v131.md):
  1단계 진입 후 손실 발생 청산되면 = 선택한 트리거 만큼 오르거나 내리면
  → 다음 단계 자동 진입!
  단계별 진입금액 = 이전 청산 후 손실만큼 자동 차감!
  = 2~3단계 = 실용 한계! (사장님 정확 인식!)

스키마 (모두 default = OFF! 기존 전략 = 100% 옛 동작 유지!):
  retry_after_liquidation_enabled BOOLEAN DEFAULT FALSE
    = 활성 시 = 청산 후 STAGE_PENDING 상태로 대기!
  retry_trigger_pct DECIMAL(10,2) DEFAULT 10
    = 청산가 기준 ±이 % 도달 시 다음 단계!
    = 순수 가격 변동 (레버리지 무관!)
  capital_management_mode VARCHAR(20) DEFAULT 'fixed'
    = 'fixed' = 세팅값 그대로 (사장님 자율!)
    = 'auto_deduct' = 이전 손실 자동 차감 (안전!)
  cumulative_realized_loss DECIMAL(20,8) DEFAULT 0
    = 누적 실현 손실 (USDT!) — 자본 차감 계산용!
  last_liquidation_price DECIMAL(20,8) NULL
    = 마지막 청산가 — 다음 단계 트리거 기준!

backward-compat:
  - 기존 전략 = retry_after_liquidation_enabled=FALSE
    → 청산 시 = 기존 STOPPED 종료 (안전!)
  - 신규 전략 = 사장님 UI 체크박스 켜야만 활성!
  - 옵션 OFF 전략 = risk_service.on_liquidation = 옛 동작 유지!

헌법 v131 (신!):
  '청산 후 재진입 = 사장님 자율 DCA 강화 = 실 자본 완전 통제!'
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0023_retry_after_liquidation"
down_revision = "0022_template_trigger_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 옵션 활성 여부
    op.add_column(
        "strategy_instances",
        sa.Column(
            "retry_after_liquidation_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # 재진입 트리거 % (레버리지 무관!)
    op.add_column(
        "strategy_instances",
        sa.Column(
            "retry_trigger_pct",
            sa.Numeric(10, 2),
            nullable=False,
            server_default="10",
        ),
    )
    # 자본 관리 모드 = 'fixed' or 'auto_deduct'
    op.add_column(
        "strategy_instances",
        sa.Column(
            "capital_management_mode",
            sa.String(length=20),
            nullable=False,
            server_default="fixed",
        ),
    )
    # 누적 실현 손실 (USDT!)
    op.add_column(
        "strategy_instances",
        sa.Column(
            "cumulative_realized_loss",
            sa.Numeric(20, 8),
            nullable=False,
            server_default="0",
        ),
    )
    # 마지막 청산가 (다음 단계 트리거 기준!)
    op.add_column(
        "strategy_instances",
        sa.Column(
            "last_liquidation_price",
            sa.Numeric(20, 8),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("strategy_instances", "last_liquidation_price")
    op.drop_column("strategy_instances", "cumulative_realized_loss")
    op.drop_column("strategy_instances", "capital_management_mode")
    op.drop_column("strategy_instances", "retry_trigger_pct")
    op.drop_column("strategy_instances", "retry_after_liquidation_enabled")
