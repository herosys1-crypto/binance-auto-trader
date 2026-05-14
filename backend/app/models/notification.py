from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    strategy_instance_id: Mapped[int | None] = mapped_column(ForeignKey("strategy_instances.id", ondelete="SET NULL"), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(nullable=False)
    send_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    external_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 2026-05-14 Phase 5: created_at 인덱스 — recent-activity / get_notifications_by_title /
    # get_operation_stats 모두 ORDER BY created_at DESC 또는 WHERE created_at >= cutoff 사용.
    # 알림 row 가 누적되면 (운영 1주 = 수천 건) full scan 부담.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    strategy_instance = relationship("StrategyInstance", back_populates="notifications")
