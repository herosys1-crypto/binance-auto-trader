"""strategy_suggestions 테이블 = 자동 전략 제안! (v132 Strategy Suggestion Team!)

배경 (사장님 요청 2026-08-11):
"매일 학습하면서 급등과 급락이 예상되고 급락후 추가 지속적인 하락일경우
 새전략을 만들어 분석한 전략으로 만들어줘 그것을 보고 자동또는 수동으로
 매매를 할수 있게 해주고 기본은 수동으로 내가 실행할수 있게 해주고
 차후에 자동으로도 할수 있게 선택옵션을 넣어서만들어주고 바로 사용하지
 않은 전략은 유지 삭제 관리 가능하게 만들어진 시간도 표기해서 해줘"

= 신 팀 = Strategy Suggestion Team!
= spec: docs/STRATEGY_SUGGESTION_SPEC_v132.html

컬럼:
- id, symbol, side (LONG/SHORT)
- suggestion_type (pump_expected/dump_continuation/reversal_up/pump_end)
- strategy_config JSONB = 자본, 트리거, TP/SL 등 (사장님 신 default!)
- confidence_score DECIMAL(4,3) = 0.000~1.000
- reason TEXT = 분석 이유
- status = PENDING/EXECUTED/DISMISSED/EXPIRED
- execution_mode = MANUAL/AUTO (기본 MANUAL!)
- executed_at, executed_strategy_id (실 실행 후!)
- dismissed_at, dismissed_reason
- created_at (⭐ 만들어진 시간 - 사장님 요구!)

헌법:
- C02 (사장님 사상 우선) = 기본 수동!
- C04 (검증 없는 코드 X) = confidence_score 필수!
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = "0027_strategy_suggestions"
down_revision = "0024_retry_stage_trigger_pcts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. strategy_suggestions 테이블!
    op.create_table(
        "strategy_suggestions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(30), nullable=False, index=True),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("suggestion_type", sa.String(30), nullable=False),
        sa.Column("strategy_config", JSONB, nullable=False),
        sa.Column("confidence_score", sa.Numeric(4, 3)),
        sa.Column("reason", sa.Text),
        sa.Column(
            "status", sa.String(20),
            nullable=False, server_default="PENDING", index=True,
        ),
        sa.Column(
            "execution_mode", sa.String(10),
            nullable=False, server_default="MANUAL",
        ),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.Column("executed_strategy_id", sa.BigInteger),
        sa.Column("dismissed_at", sa.DateTime(timezone=True)),
        sa.Column("dismissed_reason", sa.Text),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
            index=True,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
    )

    # 2. system_settings에 자동 실행 세팅 추가! (기본 OFF!)
    op.execute("""
        INSERT INTO system_settings (key, value, description) VALUES
            ('suggestion_auto_execute_enabled', 'false',
             '전략 제안 자동 실행 (기본 OFF - 사장님 사상!)'),
            ('suggestion_confidence_threshold', '0.85',
             '자동 실행 최소 신뢰도 (0.000~1.000)'),
            ('suggestion_daily_auto_limit', '3',
             '일일 자동 실행 한도 (안전장치!)'),
            ('suggestion_auto_dismiss_hours', '24',
             '미실행 자동 삭제 시간 (0=삭제 안 함)')
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM system_settings WHERE key IN (
            'suggestion_auto_execute_enabled',
            'suggestion_confidence_threshold',
            'suggestion_daily_auto_limit',
            'suggestion_auto_dismiss_hours'
        )
    """)
    op.drop_table("strategy_suggestions")
