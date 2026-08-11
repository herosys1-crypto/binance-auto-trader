"""🧠 MemoryReader = 메모리 4계층 자동 로드!

사장님 사상 (2026-08-11):
"메모리 기능도 알려주고 같이 활용해서 서버에이젼트에 모두 적용해서
 지금까지 기획하고 수정하고 개발하면서 확정한 내용을 모두 정리해서 활용할수 있게 하고싶어"

= 모든 에이전트 = 시작 시 메모리 로드!
= 실행 시 = 참조!
= 결과 = 저장!
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 메모리 루트 = backend/memory/
MEMORY_ROOT = Path(__file__).parent.parent.parent / "memory"


class MemoryReader:
    """서버 에이전트용 메모리 시스템 리더!

    Usage:
        reader = MemoryReader(team="entry")
        constitution = reader.load_constitution()
        specs = reader.load_specs()
        defaults = reader.load_defaults()
    """

    def __init__(self, team: str | None = None):
        """
        Args:
            team: 팀 이름 (entry/tp/sl/monitoring/alert/capital/analysis/maintenance/ui/audit)
                  None = 모든 메모리 로드!
        """
        self.team = team
        self.root = MEMORY_ROOT
        if not self.root.exists():
            logger.warning("[memory] 메모리 폴더 없음: %s (자동 생성 X, 관리자 확인!)", self.root)

    def load_constitution(self) -> dict[str, str]:
        """헌법 (Layer 1) 로드 = 절대 원칙!

        Returns:
            {rule_id: content} 딕셔너리
            예: {"C01": "메인넷 = 실 자금...", ...}
        """
        return self._load_layer("constitution")

    def load_specs(self) -> dict[str, str]:
        """사양 (Layer 2) 로드 = 상세 규칙!"""
        return self._load_layer("specs")

    def load_defaults(self) -> dict[str, str]:
        """신 default (Layer 3) 로드!"""
        return self._load_layer("defaults")

    def load_silent_bugs(self) -> dict[str, str]:
        """Silent bug (Layer 4) 로드 = 재발 방지!"""
        return self._load_layer("silent_bugs")

    def _load_layer(self, layer: str) -> dict[str, str]:
        """단일 layer 로드."""
        layer_path = self.root / layer
        if not layer_path.exists():
            logger.warning("[memory] Layer 없음: %s", layer_path)
            return {}
        result: dict[str, str] = {}
        for md_file in sorted(layer_path.glob("*.md")):
            if md_file.name == "INDEX.md":
                continue  # index 제외
            try:
                _id = md_file.stem  # 파일명 (확장자 제외)
                _content = md_file.read_text(encoding="utf-8")
                result[_id] = _content
            except Exception as e:
                logger.warning("[memory] 파일 로드 실패 %s: %s", md_file, e)
        return result

    def get_constitution_rule(self, rule_id: str) -> str | None:
        """특정 헌법 조회 (예: 'C10_tp1_override_tp1_only')."""
        return self.load_constitution().get(rule_id)

    def get_default(self, default_id: str) -> str | None:
        """특정 신 default 조회 (예: 'leverage_2x')."""
        return self.load_defaults().get(default_id)

    def get_spec(self, spec_id: str) -> str | None:
        """특정 spec 조회."""
        return self.load_specs().get(spec_id)

    def summary(self) -> dict[str, int]:
        """메모리 시스템 요약 통계 (개수)."""
        return {
            "constitution": len(self.load_constitution()),
            "specs": len(self.load_specs()),
            "defaults": len(self.load_defaults()),
            "silent_bugs": len(self.load_silent_bugs()),
        }
