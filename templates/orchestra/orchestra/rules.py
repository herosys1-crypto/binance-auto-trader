"""📜 Rulebook — 프로젝트 규칙(원본의 「헌법」)을 행동마다 자동 검사.

원본(ConstitutionValidator)은 규칙 파일이 있는지만 보고 실제로는 막지 않았다. 여기서는 규칙이 **검사 함수**다:

    rules = Rulebook()

    @rules.rule("R01", "금액은 0보다 커야 한다", actions=["PAYMENT"])
    def positive_amount(action, ctx):
        if ctx.get("amount", 0) <= 0:
            return f"amount={ctx.get('amount')}"      # 위반 사유 (문자열) — 통과면 None

    rules.check("PAYMENT", {"amount": 0})           # → RuleViolation

규칙이 예외를 던지면 기본은 **위반으로 본다**(fail-closed). 보조 규칙이면 `fail_open=True`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

Check = Callable[[str, dict], "str | None"]


class RuleViolation(Exception):
    def __init__(self, rule_id: str, action: str, reason: str = "") -> None:
        self.rule_id, self.action, self.reason = rule_id, action, reason
        super().__init__(f"규칙 위반 {rule_id}: {action} ({reason})")


@dataclass
class Rule:
    rule_id: str
    title: str
    check: Check
    actions: tuple[str, ...] = ("*",)        # "*" = 모든 행동
    fail_open: bool = False


@dataclass
class Rulebook:
    rules: dict[str, Rule] = field(default_factory=dict)

    def add(self, rule_id: str, title: str, check: Check, *, actions: list[str] | tuple[str, ...] = ("*",),
            fail_open: bool = False) -> None:
        if rule_id in self.rules:
            raise ValueError(f"duplicate rule id {rule_id}")
        self.rules[rule_id] = Rule(rule_id, title, check, tuple(actions), fail_open)

    def rule(self, rule_id: str, title: str, *, actions: list[str] | tuple[str, ...] = ("*",), fail_open: bool = False):
        def deco(fn: Check) -> Check:
            self.add(rule_id, title, fn, actions=actions, fail_open=fail_open)
            return fn
        return deco

    def for_action(self, action: str) -> list[Rule]:
        return [r for r in self.rules.values() if "*" in r.actions or action in r.actions]

    def check(self, action: str, context: dict[str, Any] | None = None) -> bool:
        """모든 관련 규칙 통과 = True. 첫 위반에서 RuleViolation."""
        ctx = dict(context or {})
        for r in self.for_action(action):
            try:
                reason = r.check(action, ctx)
            except Exception as e:  # noqa: BLE001
                if r.fail_open:
                    logger.warning("[Rulebook] %s 검사 오류(통과 처리): %s", r.rule_id, e)
                    continue
                raise RuleViolation(r.rule_id, action, f"검사 오류: {e}") from e
            if reason:
                raise RuleViolation(r.rule_id, action, str(reason))
        return True

    def summary(self) -> list[dict[str, Any]]:
        return [{"id": r.rule_id, "title": r.title, "actions": list(r.actions), "fail_open": r.fail_open}
                for r in self.rules.values()]
