"""🛡️ Fix 240 — 진입 지표가 **빈 채로 굳는** 경로를 막는다.

## 실측 (2026-08-31, 종료 전략 1,075건 전수 분석)

    entry_context 가 채워진 건 ...... 130 / 1075  =  12.1%

그래서 분석 리포트의 「이긴 진입과 진 진입의 지표 차이」 섹션이 **한 줄도 못 나왔다**.
사장님 요구 —
  "실패보다는 익절을 많이 할수 있는 로직을 만들수 있게 **데이터를 수집**해줘"
— 인데 수집 자체가 안 되고 있었다.

## 원인

`learning_sync_worker` 는 4분마다 돈다.
- 새 전략을 보면 `on_entry(...)` 로 record 를 만들면서 `_entry_context()` 를 붙인다.
- 그런데 그 순간 Binance 조회가 실패하거나 client 가 None 이면 **빈 dict** 로 저장된다.
- 다음 사이클부터는 record 가 이미 있으므로 `snapshot` 분기로 가고,
  **entry_context 를 다시 시도하지 않는다.**

=> 첫 시도 한 번 실패하면 그 전략의 진입 지표는 **영원히 비어 있다.**

## 고침

record 가 있어도 `entry_context` 가 비어 있고 아직 fresh 창(15분) 안이면 **한 번 더 채운다**.
창을 넘겼으면 「지금 차트」를 붙이는 것이 오히려 오염이므로 건드리지 않는다
(같은 파일 :162-164 가 스스로 금지하는 「가짜 셋업 등급」 문제).
"""
from __future__ import annotations

from pathlib import Path

WORKER = (
    Path(__file__).resolve().parents[2] / "app" / "workers" / "learning_sync_worker.py"
)


def _code() -> str:
    return "\n".join(
        ln for ln in WORKER.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_open_records_retry_empty_entry_context():
    """🚨 snapshot 분기가 빈 entry_context 를 재시도하지 않으면 12.1% 로 되돌아간다."""
    code = _code()
    assert "if not (record.entry_context or {}):" in code, (
        "OPEN record 의 빈 entry_context 를 재시도하는 분기가 없다"
    )
    assert "_entry_context(client, s)" in code


def test_backfill_respects_the_fresh_window():
    """🚨 창을 넘긴 backlog 에 「지금 차트」를 붙이면 승률 통계가 오염된다.

    이건 이 파일 자신이 :162-164 에서 금지한 것이다 — 재시도가 그 금지를 깨면 안 된다.
    """
    code = _code()
    idx = code.index("if not (record.entry_context or {}):")
    window = code[idx: idx + 700]
    assert "fresh_cutoff" in window, "재시도가 fresh 창 검사 없이 아무 때나 붙인다"
    assert 'startswith("STAGE")' in window, "진입 전 상태에도 붙이려 한다"


def test_backfill_failure_is_loud():
    """헌법 v139 — 학습 저장 실패는 warning 이 아니라 error 다. 조용히 삼키면 안 된다."""
    code = _code()
    idx = code.index("if not (record.entry_context or {}):")
    window = code[idx: idx + 900]
    assert "logger.error" in window, "재시도 실패가 로그에 안 남는다 = 또 조용한 실패"


def test_backfill_count_is_reported():
    """몇 건을 복구했는지 안 보이면 고쳐졌는지 확인할 방법이 없다."""
    code = _code()
    assert "backfilled" in code
    assert '"backfilled": backfilled' in code, "반환값에 복구 건수가 없다"
    assert "backfilled=%d" in code, "완료 로그에 복구 건수가 없다"


def test_detector_would_have_caught_the_old_code():
    """음성 대조군 (헌법 170) — 옛 코드에는 이 분기가 실제로 없었는가."""
    old_snapshot_branch = (
        '                elif record.status == "OPEN":\n'
        "                    # 진행 중 = snapshot!\n"
        "                    if tls.snapshot(s):"
    )
    assert "if not (record.entry_context or {}):" not in old_snapshot_branch, (
        "대조군 무효 — 옛 코드 조각에 이미 재시도가 있다"
    )
