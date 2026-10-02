"""verify_ip_weight (Fix 405·406 배포 검사) — Duel_Lab verify-ip-weight GPT 초안 테스트 + 리드 추가(Claude 감사 수용분)."""
import json
import os
from datetime import datetime, timezone

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from verify_ip_weight import (
    CODE_MARKERS, EXTERNAL_FILE, LOOP_END, LOOP_START, OLD_CALL,
    check_ip_weight,
)

MINUTE = 1_800_000_000  # UTC 분 경계
NOW = MINUTE + 30


def stamp(epoch):
    return datetime.fromtimestamp(
        epoch, timezone.utc
    ).strftime("%Y%m%d%H%M")


class FakeRedis:
    def __init__(self):
        self.values = {
            "paper_trading:last_cycle": json.dumps({
                "at": NOW - 60,
                "symbols": 12,
                "klines": {
                    "incremental": 1, "weight": 40, "fetch_calls": 2,
                    "full": 1, "closed_hit": 10, "fallback": 0,
                    "fetch_errors": 0,
                },
            }),
            "ext:last_cycle": json.dumps({
                "at": NOW - 60, "symbols": 12, "gate_skip": 4,
                "kl_weight": 5, "fujimoto": "on", "mach7": "off",
            }),
        }
        self.paper = 40
        self.external = 5
        self.hashes = {}
        self.get_errors = set()
        self.hash_errors = set()
        self.reads = []

    def get(self, key):
        self.reads.append(("get", key))
        if key in self.get_errors:
            raise RuntimeError("get unavailable")
        if key.startswith("binance:used_weight:"):
            return self.values.get(key, b"55")
        return self.values.get(key)

    def hgetall(self, key):
        self.reads.append(("hgetall", key))
        if key in self.hash_errors:
            raise RuntimeError("hgetall unavailable")
        return self.hashes.get(key, {
            b"paper_trading": str(self.paper).encode(),
            "external_strategies": str(self.external),
            b"other": b"10",
        })


@pytest.fixture
def deployment(tmp_path):
    start = MINUTE - 35 * 60 + 10
    for relative, markers in CODE_MARKERS.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(markers)
        if relative == EXTERNAL_FILE:
            text += f"\n{LOOP_START}\n    bars = _closed_bars()\n    {LOOP_END}\n"
        path.write_text(text, encoding="utf-8")
        os.utime(path, (start - 5, start - 5))
    return {
        "root": str(tmp_path),
        "code_only": False,
        "process_start_epoch": start,
        "get_setting": lambda key: None,
        "redis": FakeRedis(),
        "now_epoch": NOW,
        "cold_min": 0,          # 냉시작 제외는 test_cold_start_minutes_excluded 에서 따로
    }


def run(options):
    reports = {"ok": [], "fail": [], "skip": []}
    check_ip_weight(
        reports["ok"].append, reports["fail"].append, reports["skip"].append,
        **options,
    )
    return reports


def contains(reports, level, text):
    return any(text in message for message in reports[level])


def rewrite(deployment, relative, transform):
    path = os.path.join(deployment["root"], relative)
    with open(path, encoding="utf-8") as file:
        text = file.read()
    with open(path, "w", encoding="utf-8") as file:
        file.write(transform(text))
    mtime = deployment["process_start_epoch"] - 5
    os.utime(path, (mtime, mtime))


def test_normal_deployment(deployment, capsys):
    result = run(deployment)
    assert not result["fail"]
    assert contains(result, "ok", "코드")
    assert contains(result, "ok", "재시작 확인")
    assert contains(result, "ok", "Redis paper_trading:last_cycle")
    assert contains(result, "ok", "무게 판정 paper_trading")
    output = capsys.readouterr().out
    assert "⚖️ IP 무게 절감" in output
    assert "paper_kline_incremental = 1 [기본]" in output
    assert "전체 호출자 무게: 평균=55.00/분 최대=55" in output
    assert "used_weight: 평균=55.00/분 최대=55" in output
    assert "대비 감소율=" in output


def test_missing_marker(deployment):
    rewrite(
        deployment, "app/services/kline_incremental.py",
        lambda text: text.replace("allow_reuse=False", ""),
    )
    result = run(deployment)
    assert len(result["fail"]) == 1
    assert contains(result, "fail", "표식 없음 — allow_reuse=False")


def test_missing_file(deployment):
    os.unlink(os.path.join(deployment["root"], EXTERNAL_FILE))
    result = run(deployment)
    assert contains(result, "fail", "파일 읽기/조회 실패")


def test_old_call_in_loop(deployment):
    rewrite(
        deployment, EXTERNAL_FILE,
        lambda text: text.replace(LOOP_START, LOOP_START + "\n    " + OLD_CALL),
    )
    assert contains(run(deployment), "fail", "루프 머리에 옛 호출 남음")


def test_old_call_outside_loop_is_allowed(deployment):
    rewrite(deployment, EXTERNAL_FILE, lambda text: OLD_CALL + "\n" + text)
    assert not run(deployment)["fail"]


@pytest.mark.parametrize("marker", [LOOP_START, LOOP_END])
def test_missing_loop_marker(deployment, marker):
    rewrite(deployment, EXTERNAL_FILE, lambda text: text.replace(marker, ""))
    assert contains(run(deployment), "fail", "루프 머리 표식 없음")


def test_restart_required(deployment):
    deployment["process_start_epoch"] -= 10
    assert contains(run(deployment), "fail", "docker compose restart api scheduler")


def test_equal_mtime_is_valid(deployment):
    deployment["process_start_epoch"] -= 5
    assert contains(run(deployment), "ok", "재시작 확인")


def test_no_process_start(deployment):
    deployment["process_start_epoch"] = None
    result = run(deployment)
    assert contains(result, "skip", "컨테이너 밖")
    assert contains(result, "skip", "측정 구간 확정 불가")
    assert not result["fail"]


@pytest.mark.parametrize("elapsed,expected_minutes", [(12, 11), (20, 19)])
def test_insufficient_complete_minutes(deployment, elapsed, expected_minutes):
    deployment["process_start_epoch"] = MINUTE - elapsed * 60 + 10
    result = run(deployment)
    assert contains(result, "skip", f"지금 {expected_minutes}분")
    assert not contains(result, "ok", "무게 판정")


def test_25_minutes_low_weight_passes(deployment):
    deployment["process_start_epoch"] = MINUTE - 25 * 60 + 10
    result = run(deployment)
    assert contains(result, "ok", "paper_trading: 평균=40.00")
    assert contains(result, "ok", "external_strategies: 평균=5.00")
    assert not result["fail"]


def test_high_paper_weight_fails(deployment):
    deployment["redis"].paper = 130
    assert contains(run(deployment), "fail", "paper_trading: 평균=130.00")


def test_minute_boundaries_are_excluded(deployment, capsys):
    start = MINUTE - 25 * 60 + 10
    deployment["process_start_epoch"] = start
    redis = deployment["redis"]
    forbidden = {
        f"binance:weight:by_caller:{stamp(start)}",
        f"binance:weight:by_caller:{stamp(NOW)}",
    }
    for key in forbidden:
        redis.hashes[key] = {
            b"paper_trading": b"999999",
            b"external_strategies": b"999999",
        }
        redis.values[key.replace("weight:by_caller", "used_weight")] = b"999999"
    result = run(deployment)
    assert not result["fail"]
    assert contains(result, "ok", "paper_trading: 평균=40.00")
    assert not forbidden.intersection(key for _, key in redis.reads)
    assert "UTC 완결된 24분" in capsys.readouterr().out


@pytest.mark.parametrize(
    "key,required",
    [("paper_trading:last_cycle", "klines"), ("ext:last_cycle", "gate_skip")],
)
@pytest.mark.parametrize("stale", [False, True])
def test_missing_cycle_field(deployment, key, required, stale):
    at = deployment["process_start_epoch"] - 1 if stale else NOW - 60
    deployment["redis"].values[key] = json.dumps({
        "at": at, "symbols": 1, "fujimoto": "on", "mach7": "off",
    })
    result = run(deployment)
    if stale:
        assert contains(result, "skip", "재시작 뒤 아직 사이클 없음")
        assert not result["fail"]
    else:
        assert contains(result, "fail", f"사이클 기록에 {required} 없음")


def test_disabled_incremental_settings_skip_judgment(deployment, capsys):
    deployment["get_setting"] = lambda key: "0"
    deployment["redis"].paper = 900
    deployment["redis"].external = 900
    result = run(deployment)
    assert contains(result, "skip", "무게 판정 paper_trading: 설정 끔")
    assert contains(result, "skip", "무게 판정 external_strategies: 설정 끔")
    assert not result["fail"]
    assert "끔 — 절감 없음" in capsys.readouterr().out


def test_both_external_modes_off(deployment):
    deployment["redis"].values["ext:last_cycle"] = json.dumps({
        "at": NOW - 60, "fujimoto": "off", "mach7": "off",
    })
    deployment["redis"].external = 900
    result = run(deployment)
    assert contains(result, "skip", "외부 전략 꺼짐")
    assert not result["fail"]


def test_redis_get_error_is_local(deployment):
    deployment["redis"].get_errors.add("paper_trading:last_cycle")
    result = run(deployment)
    assert contains(result, "skip", "get unavailable")
    assert contains(result, "ok", "Redis ext:last_cycle")
    assert contains(result, "ok", "무게 판정 paper_trading")
    assert not result["fail"]


def test_hash_error_does_not_create_false_pass(deployment):
    key = f"binance:weight:by_caller:{stamp(MINUTE - 60)}"
    deployment["redis"].hash_errors.add(key)
    result = run(deployment)
    assert contains(result, "skip", "hgetall unavailable")
    assert not contains(result, "ok", "무게 판정")


def test_malformed_json_is_local(deployment):
    deployment["redis"].values["paper_trading:last_cycle"] = b"{"
    result = run(deployment)
    assert contains(result, "skip", "읽기/JSON 오류")
    assert contains(result, "ok", "Redis ext:last_cycle")
    assert not result["fail"]


def test_setting_error_is_local(deployment):
    def setting(key):
        if key == "paper_kline_incremental":
            raise RuntimeError("DB unavailable")
        return ""

    deployment["get_setting"] = setting
    result = run(deployment)
    assert contains(result, "skip", "DB unavailable")
    # Gemini 심판 수용: 읽기 오류여도 기본(켬) 가정으로 판정한다 — 판정을 빼면 회귀를 놓친다
    assert contains(result, "ok", "무게 판정 paper_trading")
    assert contains(result, "ok", "무게 판정 external_strategies")


def test_code_only_does_not_touch_operational_dependencies(deployment):
    def forbidden_setting(key):
        pytest.fail("code_only에서 설정 접근")

    deployment["code_only"] = True
    deployment["get_setting"] = forbidden_setting
    result = run(deployment)
    assert not deployment["redis"].reads
    assert contains(result, "skip", "--code-only: 운영 층 생략")
    assert not result["fail"]


def test_unexpected_exception_becomes_fail(deployment):
    deployment["window_min"] = -1
    result = run(deployment)
    assert contains(result, "fail", "예기치 못한 예외")

# ── 리드 추가: Claude 교차 감사 수용분 ──────────────────────────────────────
def test_no_records_at_all_is_not_a_pass(deployment):
    """해시가 통째로 없는 분 = 기록 없음. 0 평균으로 ok(허위 PASS) 하지 않는다."""
    redis = deployment["redis"]
    redis.hgetall = lambda key: {}
    result = run(deployment)
    assert not contains(result, "ok", "무게 판정")
    assert contains(result, "skip", "실측 기록 있는 분 0/")


def test_setting_not_injected_still_judges_with_default(deployment, capsys):
    deployment["get_setting"] = None
    deployment["redis"].paper = 130
    result = run(deployment)
    assert contains(result, "fail", "무게 판정 paper_trading")       # 회귀를 놓치지 않는다
    assert "기본 가정 — 설정 미확인" in capsys.readouterr().out


def test_non_utf8_file_fails_that_file_and_continues(deployment):
    path = os.path.join(deployment["root"], "app/services/bar_gate.py")
    with open(path, "wb") as f:
        f.write(b"\xff\xfe broken")
    os.utime(path, (deployment["process_start_epoch"] - 5,) * 2)
    result = run(deployment)
    assert contains(result, "fail", "app/services/bar_gate.py")
    assert contains(result, "ok", "Redis paper_trading:last_cycle")     # 나머지 층은 계속


def test_ms_epoch_at_before_restart_is_skip(deployment):
    at_ms = int((deployment["process_start_epoch"] - 120) * 1000)
    deployment["redis"].values["paper_trading:last_cycle"] = json.dumps({"at": at_ms, "symbols": 3})
    result = run(deployment)
    assert contains(result, "skip", "재시작 뒤 아직 사이클 없음")
    assert not contains(result, "fail", "klines")


def test_naive_iso_at_with_missing_field_is_fail_not_skip(deployment):
    deployment["redis"].values["paper_trading:last_cycle"] = json.dumps({"at": "2026-10-02T10:00:00", "symbols": 3})
    result = run(deployment)
    assert contains(result, "fail", "klines 없음")


@pytest.mark.parametrize("key, raw, judged", [
    ("paper_kline_incremental", "false", True),     # 서버(float ≥ 0.5, 해석 실패 = 켬) 와 같게
    ("paper_kline_incremental", "0.0", False),
    ("ext_kline_incremental", "false", False),      # 서버(parse_flag) 와 같게
    ("ext_kline_incremental", "on", True),
])
def test_off_rules_match_server(deployment, key, raw, judged):
    deployment["get_setting"] = lambda k: raw if k == key else None
    result = run(deployment)
    name = "paper_trading" if key.startswith("paper") else "external_strategies"
    assert contains(result, "ok", f"무게 판정 {name}") is judged


def test_missing_minutes_do_not_dilute_average(deployment):
    """Gemini 심판: 기록 없는 분을 0 으로 넣고 전체 분으로 나누면 80/분이 53/분으로 보여 PASS 였다."""
    redis = deployment["redis"]
    redis.paper = 130
    real = redis.hgetall
    keys = []

    def sparse(key):
        keys.append(key)
        return {} if len(keys) % 3 == 0 else real(key)          # 3분에 1분은 기록 없음
    redis.hgetall = sparse
    result = run(deployment)
    assert contains(result, "fail", "무게 판정 paper_trading: 평균=130.00/분")


def test_setting_read_error_still_judges(deployment):
    def boom(key):
        raise RuntimeError("db glitch")
    deployment["get_setting"] = boom
    deployment["redis"].paper = 130
    result = run(deployment)
    assert contains(result, "fail", "무게 판정 paper_trading")


def test_cold_start_minutes_excluded(deployment):
    """재시작 직후 냉캐시 첫 사이클(전체 조회)은 측정에서 뺀다 — 운영 첫 시험에서 12:01 냉사이클 ≈1,900 이 평균을 끌어올려 허위 FAIL."""
    deployment["cold_min"] = 20                     # 시작 35분 전 → 냉시작 20분 빼면 14분 < 20 → 보류
    result = run(deployment)
    assert contains(result, "skip", "재시작 20분 뒤부터 측정")
    assert not contains(result, "ok", "무게 판정") and not contains(result, "fail", "무게 판정")
