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
