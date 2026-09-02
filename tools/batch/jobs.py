"""배치로 돌릴 작업 정의 — 실시간이 아니어도 되는 것만.

## 무엇을 배치로 돌리나

배치는 **요청끼리 독립**이고 **결과를 나중에 봐도 되는** 일에만 맞는다.
파일 하나당 요청 하나로 쪼개지는 일이 이상적이다.

  ✅ 맞는 것   문서화 / 테스트 초안 / 죽은코드 탐지 / 주석-코드 불일치 감사 / 리팩터링 분석
  ❌ 안 맞는 것 실시간 매매 판정, 배포 검증, 대화형 디버깅, 서로 결과를 참조해야 하는 일

## 🚨 이 저장소에 특히 값진 작업

`docstring_audit` — 이 저장소는 **주석이 코드와 어긋나 사고가 난 적이 있다**
(「전체자산 1~2%」가 코드에 0건인데 주석은 구현됐다고 적혀 있었다 / 죽은 상수 7건).
파일 하나씩 독립으로 검사하면 되므로 배치에 정확히 맞고, 사람이 읽기 전까지
결과가 급할 이유도 없다.

## 모델 배정 (사장님 Phase 4 라우팅)

  린트·포맷·분류    Haiku   — 기계적 판정, 코드를 고치지 않는 것
  일반 구현·문서    Sonnet  — 판단이 필요하지만 매매 로직이 아닌 것
  아키텍처·어려운 디버깅  Opus — 여기서는 기본 안 쓴다(배치로 돌릴 일이 아니다)

🚨 **매매 로직·손절·자금 계산을 싼 모델에 맡기지 않는다.** 이 저장소는 실자금이
   걸려 있고, 잘못된 손절 하나가 배치로 아낀 돈을 몇 백 배로 날린다.
   배치 작업은 전부 **읽고 보고만** 하며, 코드를 고치지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["JOBS", "Job", "collect_targets"]

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"


@dataclass(frozen=True)
class Job:
    key: str
    label: str
    tier: str                       # pricing.MODELS 키 (haiku/sonnet/opus)
    effort: str                     # low | medium | high
    max_tokens: int
    instruction: str                # 파일마다 붙는 지시문
    globs: tuple[str, ...]
    out_ext: str = ".md"
    est_output_tokens: int = 1500
    exclude: tuple[str, ...] = field(default_factory=lambda: ("__pycache__", "/tests/"))
    # 🚨 공유 접두부에 실을 저장소 규약 문서. **작업마다 다르다.**
    #   판단이 필요한 작업(감사·리팩터링·테스트)은 이 저장소의 사고 이력을 알아야
    #   결과가 쓸모 있다. 기계적 작업(죽은코드·문서화)은 넣어봐야 입력만 늘린다.
    #   넣으면 접두부가 커져 캐싱이 실제로 걸리는 부수 효과도 있다.
    context_docs: tuple[str, ...] = ()


SHARED_CONTEXT = """\
너는 실제 돈이 걸린 바이낸스 USD-M 선물 자동매매 시스템의 코드를 검토한다.
Python 3.12 / FastAPI / SQLAlchemy 2.0 / PostgreSQL / APScheduler 워커 구조다.

이 저장소에서 **반복해서 사고가 난 지점**(보고할 때 특히 눈여겨볼 것):

  1. 주석·독스트링이 코드와 **어긋난다**. 「구현됐다」고 적혀 있는데 실제로는
     호출되는 곳이 0곳인 경우가 실제로 있었다.
  2. **죽은 상수** — 값을 바꿔도 아무 일이 안 일어나는 상수가 여러 개 있었다.
  3. 설정값이 **두 곳에 저장**돼 화면과 엔진이 서로 다른 값을 본다.
  4. 함수 안 `from X import Y` 가 그 이름을 **함수 전역 지역변수**로 만들어
     UnboundLocalError 를 낸다.
  5. 손절·자본 계산은 **fail-closed** 여야 한다(모르면 하지 않는다).
     반대로 종목을 고르는 필터는 fail-open 이어야 한다(못 골랐다고 멈추지 않는다).

보고 규칙:
  - 추측 금지. 근거는 **행 번호**로 대라.
  - 「~일 수도 있다」는 쓰지 마라. 구체적으로 무엇이 잘못됐는지 못 쓰면 빼라.
  - **코드를 고치지 마라.** 너는 읽고 보고만 한다.
  - 한국어로 답해라.
"""


JOBS: dict[str, Job] = {
    "docstring_audit": Job(
        key="docstring_audit",
        context_docs=(
            "docs/SYSTEM_DEVELOPMENT_PRINCIPLES_2026-06-11.md",
            "docs/DEVELOPMENT_LESSONS_LEARNED_2026-06-13.md",
            "docs/MASTER_REBUILD_PLAN_2026-06-25.md",
        ),
        label="주석-코드 불일치 감사",
        tier="sonnet",
        effort="medium",
        max_tokens=8000,
        est_output_tokens=1200,
        globs=("backend/app/workers/*.py", "backend/app/services/*.py"),
        instruction="""\
이 파일의 **독스트링·주석이 주장하는 것**과 **코드가 실제로 하는 것**을 대조해라.

찾을 것:
  1. 「구현했다 / 적용된다 / 막는다」고 적혀 있는데 그 코드가 없거나 호출되지 않는 것
  2. 주석에 적힌 숫자·임계값이 실제 상수/설정과 다른 것
  3. 이 파일 안에서 **한 번도 읽히지 않는 상수**
     🚨 **「안 읽힘 = 죽은 상수」가 아니다.** 다음은 오탐이니 보고하지 마라:
        · `__all__` 에 들어 있는 것 (명시적으로 내보내는 것)
        · 파일이 상수/설정 **전용 모듈**인 경우 (risk_constants 같은)
        · `Final[...]` 로 선언된 공개 상수
     그 밖의 경우에도 「이 파일 안에서는 미사용」이라고만 쓰고,
     「죽었다」고 단정하려면 **주석이 그 상수가 쓰인다고 주장할 때**만 해라
     (예: 「다른 곳 참조 유지용」이라고 적혀 있는데 이 파일이 유일한 정의부인 경우).
  4. 조건이 절대 참/거짓이 될 수 없어 도달 불가능한 분기
  5. 같은 값이 **두 곳에 따로 적혀 있어** 한쪽을 바꿔도 동작이 안 바뀌는 것
     (주기·임계값·자본이 상수와 스케줄러/설정에 이중으로 있는 경우)

각 발견마다: 행 번호 / 주석이 뭐라고 하는지 / 코드가 실제로 뭘 하는지 / 왜 어긋나는지.
**확인한 것만** 써라 — 「아마 안 쓰일 것」은 발견이 아니다.
어긋나는 것이 없으면 「불일치 없음」 한 줄만 써라. 억지로 만들지 마라.""",
    ),
    "dead_code": Job(
        key="dead_code",
        label="죽은 코드·미사용 심볼 탐지",
        tier="haiku",
        effort="low",
        max_tokens=4000,
        est_output_tokens=600,
        globs=("backend/app/workers/*.py", "backend/app/services/*.py"),
        instruction="""\
이 파일 **안에서만** 판정할 수 있는 것을 찾아라 (다른 파일은 못 보므로 단정하지 마라):

  1. 정의됐지만 이 파일 안에서 한 번도 쓰이지 않는 모듈 수준 상수
     → 다른 파일에서 import 할 수 있으니 「이 파일 안에서는 미사용」이라고만 써라
  2. 정의됐지만 호출되지 않는 내부 함수(`_` 로 시작하는 것)
  3. 도달 불가능한 코드 (return 뒤, 항상 거짓인 조건)
  4. 같은 이름이 **두 번 정의**된 것 (뒤 정의가 앞을 덮는다 — 실제 사고가 있었다)

표 형식으로: 이름 / 종류 / 행 / 근거. 없으면 「없음」.""",
    ),
    "tests": Job(
        key="tests",
        context_docs=(
            "docs/SYSTEM_DEVELOPMENT_PRINCIPLES_2026-06-11.md",
            "docs/DEVELOPMENT_LESSONS_LEARNED_2026-06-13.md",
            "docs/MASTER_REBUILD_PLAN_2026-06-25.md",
        ),
        label="테스트 초안 생성",
        tier="sonnet",
        effort="high",
        max_tokens=16000,
        est_output_tokens=4000,
        out_ext=".py",
        globs=("backend/app/services/*.py",),
        instruction="""\
이 모듈의 **순수 함수**(외부 I/O 없이 입력→출력이 결정되는 것)에 대한
pytest 테스트 초안을 써라.

규칙:
  - DB·네트워크·Redis 를 건드리는 함수는 **건너뛴다** (모킹 테스트를 만들지 마라)
  - 경계값과 **fail-closed/fail-open 방향**을 반드시 시험해라
    (손절·자본 판정은 실패 시 「하지 않는」 쪽이어야 한다)
  - 테스트 이름은 한국어로, 무엇을 보장하는지 드러나게
  - `from app.services.<모듈> import ...` 로 임포트
  - 실행 가능한 파일 하나를 통째로 출력해라. 설명 문장은 붙이지 마라.

시험할 순수 함수가 없으면 `# 순수 함수 없음 — 테스트 생략` 한 줄만 출력해라.""",
    ),
    "docs": Job(
        key="docs",
        label="모듈 문서화",
        tier="haiku",
        effort="low",
        max_tokens=4000,
        est_output_tokens=800,
        globs=("backend/app/workers/*.py", "backend/app/services/*.py"),
        instruction="""\
이 모듈의 참조 문서를 써라 (마크다운):

  ## 무엇을 하나        한 문단
  ## 언제 도는가        스케줄/호출 경로 (파일 안에서 알 수 있는 만큼만)
  ## 설정 키            SystemSetting 키와 기본값 표
  ## 진입/차단 조건     어떤 조건에서 행동하고 어떤 조건에서 멈추는가
  ## 부작용             DB 쓰기 / 주문 / Redis / 알림
  ## 주의               이 파일 주석이 경고하는 함정

파일에서 확인되는 것만 써라. 모르면 「파일에서 확인 불가」라고 써라.""",
    ),
    "refactor": Job(
        key="refactor",
        context_docs=(
            "docs/SYSTEM_DEVELOPMENT_PRINCIPLES_2026-06-11.md",
            "docs/DEVELOPMENT_LESSONS_LEARNED_2026-06-13.md",
            "docs/MASTER_REBUILD_PLAN_2026-06-25.md",
        ),
        label="리팩터링 분석",
        tier="sonnet",
        effort="high",
        max_tokens=8000,
        est_output_tokens=1800,
        globs=("backend/app/workers/*.py",),
        instruction="""\
이 파일의 **구조적 문제**만 보고해라 (스타일·포맷은 보지 마라):

  1. 같은 판정이 여러 곳에 복사돼 한쪽만 고쳐질 위험이 있는 것
  2. 한 함수가 너무 많은 책임을 져서 실수가 숨는 자리
  3. 예외 처리가 실패를 **삼켜서** 조용히 잘못된 값이 흐르는 자리
  4. 설정값이 코드 상수와 이중으로 존재하는 자리

각각: 행 / 문제 / 실제로 무엇이 잘못될 수 있는지 / 어떻게 고치면 되는지 한 문장.
🚨 매매 규칙 자체를 바꾸자는 제안은 하지 마라 — 구조만 본다.""",
    ),
}


def collect_targets(job: Job, limit: int | None = None) -> list[Path]:
    """이 작업의 대상 파일 목록. 저장소 루트 기준."""
    out: list[Path] = []
    seen: set[Path] = set()
    for g in job.globs:
        for p in sorted(REPO.glob(g)):
            rp = p.resolve()
            if rp in seen or not p.is_file():
                continue
            s = str(p).replace("\\", "/")
            if any(x in s for x in job.exclude):
                continue
            seen.add(rp)
            out.append(p)
    return out[:limit] if limit else out
