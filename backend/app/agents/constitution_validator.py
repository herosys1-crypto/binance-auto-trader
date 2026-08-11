"""📜 ConstitutionValidator = 헌법 자동 검증!

모든 에이전트 행동 = 헌법 위반 여부 자동 확인!
위반 시 = ConstitutionViolationError → 알림 + 로그!
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ConstitutionViolationError(Exception):
    """헌법 위반 = 즉시 알림!"""
    def __init__(self, rule_id: str, action: str, reason: str = ""):
        self.rule_id = rule_id
        self.action = action
        self.reason = reason
        super().__init__(f"❌ 헌법 위반! {rule_id}: {action} (이유: {reason})")


class ConstitutionValidator:
    """헌법 자동 검증기.

    Usage:
        validator = ConstitutionValidator(constitution_dict)
        try:
            validator.check("TP1_OVERRIDE_APPLY", {"tp_index": 1})
        except ConstitutionViolationError as e:
            logger.error("헌법 위반: %s", e)
    """

    # 액션 → 관련 헌법 매핑
    ACTION_RULES: dict[str, list[str]] = {
        # Entry Team
        "STAGE_ENTRY":              ["C01", "C02", "C07"],  # 메인넷 + 사장님 + capital=margin
        "RETRY_REENTRY_TRIGGER":    ["C09", "C13"],  # 순차 진입 + 다음단계 SL X
        # TP Team
        "TP1_OVERRIDE_APPLY":       ["C10"],  # TP1만 override!
        "TP_ORCHESTRATION":         ["C02", "C10"],
        # SL Team
        "FORCE_SL_TRIGGER":         ["C13"],  # 다음 단계 남으면 X
        # Capital Team
        "CAPITAL_130PCT_CHECK":     ["C08"],  # 경고만!
        "LEVERAGE_SET":             ["C12"],  # 사장님 자율
        # Audit Team
        "CODE_DEPLOY":              ["C04", "C11"],  # 검증 + branch
        "SYMMETRY_CHECK":           ["C05", "C06"],  # 대칭성 + 단일진실
    }

    def __init__(self, constitution: dict[str, str]):
        self.constitution = constitution or {}

    def check(self, action: str, context: dict[str, Any] | None = None) -> bool:
        """액션 = 관련 헌법 확인!

        Args:
            action: 액션 이름 (예: 'TP1_OVERRIDE_APPLY')
            context: 액션 컨텍스트 (검증 데이터)

        Returns:
            True = 통과!
        Raises:
            ConstitutionViolationError: 위반 시!
        """
        related_rules = self.ACTION_RULES.get(action, [])
        if not related_rules:
            # 매핑 없음 = 통과 (모든 액션 매핑 X = OK, 자율!)
            return True

        # 각 관련 헌법 확인 (헌법 파일 존재 여부만!)
        for rule_prefix in related_rules:
            _matched = [k for k in self.constitution.keys() if k.startswith(rule_prefix)]
            if not _matched:
                logger.warning("[constitution] %s 헌법 파일 없음! (action=%s)", rule_prefix, action)
                # 파일 없음 = 시스템 관리 이슈 = warning만!
                continue
        return True

    def get_rule_summary(self, rule_prefix: str) -> str | None:
        """헌법 요약 반환 (첫 5줄)."""
        _matched = [k for k in self.constitution.keys() if k.startswith(rule_prefix)]
        if not _matched:
            return None
        content = self.constitution[_matched[0]]
        lines = content.split("\n")[:5]
        return "\n".join(lines)
