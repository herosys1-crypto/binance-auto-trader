"""🤖 Agent — 한 가지 일을 하는 일꾼. 팀 리더가 부른다.

    class ReportWriter(Agent):
        TEAM = "report"
        NAME = "report_writer"
        ACTION = "WRITE_REPORT"          # 규칙집 검사 이름 (없으면 검사 생략)

        def execute(self, data):
            return {"pages": 3}

    ReportWriter(rules).run({"day": "2026-10-13"})   # 규칙 검사 → execute → 결과·시간 기록
"""
from __future__ import annotations

import logging
import time
from typing import Any

from orchestra.rules import Rulebook, RuleViolation

logger = logging.getLogger(__name__)


class Agent:
    TEAM: str = "unknown"
    NAME: str = "agent"
    ACTION: str | None = None

    def __init__(self, rules: Rulebook | None = None) -> None:
        self.rules = rules
        self.runs = 0
        self.failures = 0
        self.last_error: str | None = None
        self.last_ms: float | None = None

    def validate(self, action: str, context: dict[str, Any] | None = None) -> bool:
        if self.rules is None:
            return True
        return self.rules.check(action, context)

    def run(self, data: dict[str, Any] | None = None) -> Any:
        """규칙 검사(ACTION 이 있으면) → execute. 실패는 세고 다시 던진다 — 삼키지 않는다."""
        payload = dict(data or {})
        t0 = time.perf_counter()
        try:
            if self.ACTION:
                self.validate(self.ACTION, payload)
            out = self.execute(payload)
            self.runs += 1
            self.last_error = None
            return out
        except RuleViolation:
            self.failures += 1
            self.last_error = "rule_violation"
            raise
        except Exception as e:
            self.failures += 1
            self.last_error = f"{type(e).__name__}: {e}"
            logger.error("[%s/%s] 실패: %s", self.TEAM, self.NAME, e)
            raise
        finally:
            self.last_ms = round((time.perf_counter() - t0) * 1000, 2)

    def execute(self, data: dict[str, Any]) -> Any:
        raise NotImplementedError(f"{type(self).__name__}.execute() 를 구현하라")

    def status(self) -> dict[str, Any]:
        return {"name": self.NAME, "runs": self.runs, "failures": self.failures,
                "last_error": self.last_error, "last_ms": self.last_ms}
