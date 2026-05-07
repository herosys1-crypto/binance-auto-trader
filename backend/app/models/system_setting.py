"""SystemSetting — 운영자 런타임 토글 (key/value 설정).

배경 (2026-05-07): mainnet/testnet 운영 정책을 .env 재시작 없이 UI 에서 토글.
첫 사용처: whitelist_enabled (화이트리스트 적용/미적용).

키 규칙: snake_case, prefix 권장 (예: 'whitelist_enabled', 'kill_switch_auto_clear_after_min').
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
