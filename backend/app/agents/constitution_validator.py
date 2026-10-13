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


# 🎼 Fix 449: 실제 검사 함수 등록 — 범용 템플릿(templates/orchestra/rules.py)과 같은 원칙.
#   check(action, ctx) -> 위반 사유(str) | None. 검사 오류는 기본 위반(fail-closed), 보조 검사만 fail_open=True.
#   지금 등록된 검사는 0개 → 동작은 예전과 같다(파일 존재만 확인·경고). 규칙을 넣을 때는 사장님 승인 뒤.
#   ⚠️ actions=["*"] 금지 — STAGE_ENTRY·SUGGESTION_(AUTO_)EXECUTE 같은 진입 경로에도 걸려, 검사 함수 오류 하나가 진입을 막는다.
#   그리고 정지(team_lead_base._STOPPED)는 프로세스 단위다 — api 에서 걸어도 scheduler 는 따로 돈다.
_CHECKS: dict[str, list[tuple[str, Any, bool]]] = {}


def register_check(rule_id: str, actions: list[str], check, *, fail_open: bool = False) -> None:
    for a in actions:
        lst = _CHECKS.setdefault(a, [])
        if any(r == rule_id for r, _c, _f in lst):
            raise ValueError(f"duplicate check {rule_id} for {a}")
        lst.append((rule_id, check, fail_open))


def registered_checks() -> dict[str, list[str]]:
    return {a: [r for r, _c, _f in lst] for a, lst in _CHECKS.items()}


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
        for rule_id, fn, fail_open in list(_CHECKS.get(action, [])) + list(_CHECKS.get("*", [])):
            try:
                reason = fn(action, dict(context or {}))
            except Exception as e:  # noqa: BLE001
                if fail_open:
                    logger.warning("[constitution] %s 검사 오류(통과 처리): %s", rule_id, e)
                    continue
                raise ConstitutionViolationError(rule_id, action, f"검사 오류: {e}") from e
            if reason:
                raise ConstitutionViolationError(rule_id, action, str(reason))
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
