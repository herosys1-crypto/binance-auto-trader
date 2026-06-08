"""strategy_templates.is_favorite — 사장님 즐겨찾기 5개 (2026-06-09).

배경 (사장님 명시 2026-06-09):
"새전략 만들 저장한 템플릿 노출 + 기본 세팅 5개 만들 수 있게 해줘"

정책:
- 사장님 = 자주 쓰는 template = is_favorite=True 마킹
- 「외부 포지션」 자리 = 「⭐ 즐겨찾기 템플릿 5개」 카드 표시
- 사장님 = 카드에서 = 1 클릭 = 신 전략 시작 (= 현재가 자동)
- 최대 5개 (= 사장님 추가 시 = 다른 즐겨찾기 해제 권장)
"""
from alembic import op
import sqlalchemy as sa


revision = "0019_template_is_favorite"
down_revision = "0018_tp1_pct_override"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strategy_templates",
        sa.Column(
            "is_favorite",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment=(
                "사장님 즐겨찾기 마킹. True = 「⭐ 즐겨찾기 템플릿」 카드 노출 (최대 5개). "
                "1 클릭 신 전략 시작 (= 현재가 자동). "
                "FAVORITE_TEMPLATES_SPEC_2026-06-09.md 참조."
            ),
        ),
    )
    op.create_index(
        "ix_strategy_templates_is_favorite",
        "strategy_templates",
        ["is_favorite"],
        postgresql_where=sa.text("is_favorite = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_templates_is_favorite", table_name="strategy_templates")
    op.drop_column("strategy_templates", "is_favorite")
