"""system_settings 테이블 — 운영자 런타임 토글 (whitelist on/off 등).

배경 (사용자 요청 2026-05-07):
mainnet 시뮬과 testnet 자유 운영을 모두 지원하기 위해 화이트리스트 가드를
.env 재시작 없이 UI 체크박스로 on/off. 향후 다른 운영 정책 토글도 같은 패턴.

스키마:
  key TEXT PK              — 설정 식별자 (예: 'whitelist_enabled')
  value TEXT NOT NULL      — 직렬화된 값 (bool/int/json)
  updated_at TIMESTAMP TZ  — 마지막 변경 시각
  updated_by INTEGER       — 변경한 user.id (audit, FK 없음 — user 삭제 후에도 추적)
  description TEXT NULL    — 설정 설명 (UI 툴팁)

backward-compat:
  - row 없으면 코드의 default 값 사용 (예: settings.allowed_symbols_csv 의 enabled 상태)
  - 신규 토글 추가는 row 1개 INSERT 만으로 가능 (스키마 변경 X)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0013_system_settings"
down_revision = "0012_template_tp6_to_tp10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("system_settings")
