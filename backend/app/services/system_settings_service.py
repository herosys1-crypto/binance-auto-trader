"""SystemSettingsService — 운영자 런타임 토글 (DB 영속).

배경 (사용자 요청 2026-05-07):
mainnet/testnet 운영 정책 (예: 화이트리스트 적용 여부) 을 .env 재시작 없이
UI 체크박스로 변경. row 없으면 코드의 default 사용 (backward-compat).

키 규칙:
- snake_case
- prefix: 영역 (whitelist_, kill_switch_, alert_)
- value 는 문자열로 저장 — 호출자가 bool/int/json 파싱

대표 키:
- 'whitelist_enabled' (bool) — settings.allowed_symbols_csv 의 가드 적용 여부
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.system_setting import SystemSetting


class SystemSettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, key: str, default: str | None = None) -> str | None:
        """key 의 raw string 값 반환. 없으면 default."""
        row = self.db.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        ).scalar_one_or_none()
        return row.value if row else default

    def get_bool(self, key: str, default: bool) -> bool:
        """key 의 boolean 값 반환. 'true'/'1'/'yes' (대소문자 무관) → True, 그 외 False.

        row 없으면 default. 모호한 값도 default (안전 fallback).
        """
        raw = self.get(key)
        if raw is None:
            return default
        return raw.strip().lower() in ("true", "1", "yes", "on")

    def get_decimal(self, key: str, default: Decimal) -> Decimal:
        """key 의 Decimal 값 반환. 없거나 파싱 실패 시 default (안전 fallback)."""
        raw = self.get(key)
        if raw is None:
            return default
        try:
            return Decimal(str(raw).strip())
        except (InvalidOperation, ValueError, TypeError):
            return default

    def set(
        self,
        key: str,
        value: Any,
        *,
        updated_by: int | None = None,
        description: str | None = None,
    ) -> SystemSetting:
        """key 값 갱신 (없으면 INSERT). value 는 문자열로 직렬화."""
        str_value = str(value).lower() if isinstance(value, bool) else str(value)
        row = self.db.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        ).scalar_one_or_none()
        if row:
            row.value = str_value
            row.updated_at = datetime.now(timezone.utc)
            if updated_by is not None:
                row.updated_by = updated_by
            if description is not None:
                row.description = description
        else:
            row = SystemSetting(
                key=key,
                value=str_value,
                updated_by=updated_by,
                description=description,
            )
            self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    # ─── 도메인-specific 헬퍼 ───
    def is_whitelist_enabled(self, *, default_from_env: bool) -> bool:
        """화이트리스트 가드 활성 여부 — DB toggle 우선, 없으면 env 기반 default.

        default_from_env: settings.allowed_symbols_set is not None (env 에 값 있으면 True)
        """
        return self.get_bool("whitelist_enabled", default=default_from_env)

    def get_force_sl(self, side: str) -> tuple[bool, Decimal]:
        """손실 한도 강제 청산 전역 설정 (side별) — (enabled, roi_한도_양수).

        FORCE_SL_LOSS_LIMIT_SPEC 2026-06-24. 롱/숏 독립. row 없으면 코드 default
        (롱 ON -10% / 숏 OFF -10%). roi 는 양수 (호출자가 ROI <= -roi 로 비교).
        """
        from app.core.risk_constants import (
            FORCE_SL_LONG_ENABLED_DEFAULT,
            FORCE_SL_LONG_ENABLED_KEY,
            FORCE_SL_LONG_ROI_KEY,
            FORCE_SL_ROI_DEFAULT,
            FORCE_SL_SHORT_ENABLED_DEFAULT,
            FORCE_SL_SHORT_ENABLED_KEY,
            FORCE_SL_SHORT_ROI_KEY,
        )
        if (side or "").upper() == "LONG":
            enabled = self.get_bool(FORCE_SL_LONG_ENABLED_KEY, default=FORCE_SL_LONG_ENABLED_DEFAULT)
            roi = self.get_decimal(FORCE_SL_LONG_ROI_KEY, default=FORCE_SL_ROI_DEFAULT)
        else:
            enabled = self.get_bool(FORCE_SL_SHORT_ENABLED_KEY, default=FORCE_SL_SHORT_ENABLED_DEFAULT)
            roi = self.get_decimal(FORCE_SL_SHORT_ROI_KEY, default=FORCE_SL_ROI_DEFAULT)
        return enabled, roi
