"""strategy_suggestions에 outcome 학습 컬럼 추가! (v135 사장님!)

배경 (사장님 요청 2026-08-13):
"지금실행이 기타 분석 분석 실행전과 후 를 변동에 대해서도 분석된것을 학습해서
 추천 심볼에 적용해줘 지금은 학습이 어떻게 되고 있는지 어려운이 많네"

= 예측 후 = 실제 시장 변동 학습!
= 성공/실패 → 심볼별 성공률!
= 다음 예측 = 성공률 반영 → confidence 조정!

컬럼 (신):
- outcome_status: PENDING / SUCCESS / FAIL / EXPIRED
- outcome_change_1h, outcome_change_4h, outcome_change_24h (%)
- outcome_price_at_prediction (예측 시점 가격!)
- outcome_checked_at (마지막 확인 시각!)
- symbol_prior_success_rate (예측 시점의 심볼 과거 성공률!)

Revision ID: 0029_suggestion_outcomes
Revises: 0028_trade_learning_records
"""
from alembic import op
import sqlalchemy as sa


revision = '0029_suggestion_outcomes'
down_revision = '0028_trade_learning_records'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('strategy_suggestions', sa.Column(
        'outcome_status', sa.String(20), nullable=True, index=True,
    ))
    op.add_column('strategy_suggestions', sa.Column(
        'outcome_change_1h', sa.Numeric(10, 4), nullable=True,
    ))
    op.add_column('strategy_suggestions', sa.Column(
        'outcome_change_4h', sa.Numeric(10, 4), nullable=True,
    ))
    op.add_column('strategy_suggestions', sa.Column(
        'outcome_change_24h', sa.Numeric(10, 4), nullable=True,
    ))
    op.add_column('strategy_suggestions', sa.Column(
        'outcome_price_at_prediction', sa.Numeric(20, 8), nullable=True,
    ))
    op.add_column('strategy_suggestions', sa.Column(
        'outcome_checked_at', sa.DateTime(timezone=True), nullable=True,
    ))
    op.add_column('strategy_suggestions', sa.Column(
        'symbol_prior_success_rate', sa.Numeric(5, 4), nullable=True,
    ))


def downgrade() -> None:
    op.drop_column('strategy_suggestions', 'symbol_prior_success_rate')
    op.drop_column('strategy_suggestions', 'outcome_checked_at')
    op.drop_column('strategy_suggestions', 'outcome_price_at_prediction')
    op.drop_column('strategy_suggestions', 'outcome_change_24h')
    op.drop_column('strategy_suggestions', 'outcome_change_4h')
    op.drop_column('strategy_suggestions', 'outcome_change_1h')
    op.drop_column('strategy_suggestions', 'outcome_status')
