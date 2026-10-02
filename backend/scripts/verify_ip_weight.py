"""Fix 405·406 배포 검사 — IP 무게 절감 (가상매매 증분 캐시 · 외부 전략 봉 마감 게이트). 파일/설정/Redis 읽기만.

verify_fix364_deploy.py 가 check_ip_weight(...) 한 줄로 부른다. Duel_Lab verify-ip-weight:
GPT 초안 바탕 + Claude 교차 감사 수용(기록 없는 분을 0 으로 세어 허위 PASS · 설정 미주입 시 판정 소실 ·
디코드 오류 · at 해석 · 서버와 같은 「끔」 규칙).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

TITLE = "⚖️ IP 무게 절감 (Fix 405 가상매매 증분 캐시 · Fix 406 외부 전략 봉 마감 게이트)"

CODE_MARKERS = {
    "app/services/kline_incremental.py": (
        "def get_closed(", "allow_reuse=False",
    ),
    "app/workers/paper_trading_worker.py": (
        "_KC.get_closed(", "paper_kline_incremental",
    ),
    "app/services/bar_gate.py": (
        "SETTLE_DEFAULT_MS = 5_000", "def already_judged(",
        "class BarNotSettled",
    ),
    "app/workers/external_strategies_worker.py": (
        "def _closed_bars(", "BG.already_judged(seen, ts)",
    ),
}
EXTERNAL_FILE = "app/workers/external_strategies_worker.py"
LOOP_START = "for sym in universe:"
LOOP_END = "c = [float(b[4]) for b in bars]"
OLD_CALL = "bc.get_klines(symbol=sym, interval=interval, limit=KLINE_LIMIT)"
DEFAULTS = {
    "paper_kline_incremental": "1",
    "ext_kline_incremental": "1",
    "ext_bar_settle_ms": "5000",
}
# Claude가 정함: 호출자별 분당 평균 무게의 배포 판정 문턱 — 2026-10-02 배포 뒤 실측으로 재설정.
#   가상매매 따뜻한 사이클 = 봉 568 + 규칙 발동 종목 차트 상태 조회(가변) → 750~1,100/15분 = 50~73/분 (회귀 = 전체 조회 128+/분)
#   외부 전략 = 봉은 경계마다만(≈4/분) + 감시 종목 선정 24h 티커 40/분 (회귀 = 160/분)
LIMITS = {"paper_trading": 100, "external_strategies": 60}
COLD_MIN = 20   # Claude가 정함: 재시작 직후 냉캐시 첫 사이클(전체 조회, 가상매매 ≈1,900·6분)을 측정에서 뺀다
BASELINES = {"paper_trading": 128, "external_strategies": 147}


def _text(value):
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _epoch(value):
    if value is None:
        return None
    text = _text(value).strip()
    try:
        number = float(value) if isinstance(value, (int, float)) else float(text)
        return number / 1000 if number > 1e11 else number      # 밀리초 epoch 도 받는다
    except ValueError:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("at의 ISO 시각에 시간대가 없음")
        return dt.timestamp()


def _local(epoch):
    return time.strftime("%m-%d %H:%M:%S", time.localtime(epoch))


def _setting_off(key, value):
    """서버 워커와 같은 규칙. paper = float ≥ 0.5 면 켬(해석 실패 = 기본 켬) · ext = bar_gate.parse_flag."""
    text = _text(value).strip().lower()
    if key == "paper_kline_incremental":
        try:
            return float(text) < 0.5
        except ValueError:
            return False
    return text in {"0", "false", "off", "no"}


def _off(value):
    """명시적인 off만 인정한다. 누락/알 수 없는 값은 off로 추정하지 않는다."""
    if isinstance(value, dict):
        return "enabled" in value and _off(value["enabled"])
    if value is False or value == 0:
        return True
    if isinstance(value, (str, bytes)):
        return _text(value).strip().lower() in {"0", "off", "false", "disabled"}
    return False


def _check_code(root, ok, fail):
    mtimes = []
    external = None
    for relative, markers in CODE_MARKERS.items():
        path = Path(root) / relative
        try:
            source = path.read_text(encoding="utf-8")
            mtimes.append(path.stat().st_mtime)
        except (OSError, UnicodeDecodeError) as exc:
            fail(f"코드 {relative}: 파일 읽기/조회 실패 — {exc!r}")
            continue
        if relative == EXTERNAL_FILE:
            external = source
        missing = [marker for marker in markers if marker not in source]
        if missing:
            fail(f"코드 {relative}: 표식 없음 — {', '.join(missing)}")
        else:
            ok(f"코드 {relative}: 필수 표식 확인")

    if external is not None:
        start = external.find(LOOP_START)
        end = external.find(LOOP_END, start) if start >= 0 else -1
        if start < 0 or end < 0:
            fail(f"코드 {EXTERNAL_FILE}: 루프 머리 표식 없음")
        elif OLD_CALL in external[start:end]:
            fail(f"코드 {EXTERNAL_FILE}: 루프 머리에 옛 호출 남음 — {OLD_CALL}")
        else:
            ok("코드 외부 전략: 루프 머리에 직접 get_klines 호출 없음")
    return mtimes


def _check_process(mtimes, start, ok, fail, skip):
    if start is None:
        skip("프로세스 층: 컨테이너 밖 — PID1 시작 시각 없음")
    elif len(mtimes) != len(CODE_MARKERS):
        skip("프로세스 층: 코드 파일 mtime 전체를 확보하지 못함")
    else:
        latest = max(mtimes)
        detail = f"프로세스 {_local(start)} / 최신 파일 {_local(latest)}"
        if start >= latest:
            ok(f"프로세스 층: 재시작 확인 — {detail}")
        else:
            fail(
                "프로세스 층: 재시작 안 됨 — "
                f"{detail} — docker compose restart api scheduler"
            )


def _settings(get_setting, skip):
    effective = {}
    for key, default in DEFAULTS.items():
        if get_setting is None:
            effective[key] = default
            print(f"{key} = {default} [기본 가정 — 설정 미확인]")
            continue
        try:
            raw = get_setting(key)
            defaulted = raw is None or _text(raw).strip() == ""
            value = default if defaulted else _text(raw).strip()
            effective[key] = value
            suffix = " — 끔 — 절감 없음" if key != "ext_bar_settle_ms" and _setting_off(key, value) else ""
            print(f"{key} = {value} [{'기본' if defaulted else 'DB'}]{suffix}")
        except Exception as exc:
            effective[key] = default   # 읽기 오류로 판정을 통째로 빼지 않는다 — 기본(켬) 가정으로 판정 (Gemini 심판)
            skip(f"설정 {key}: 읽기 오류 → 기본 {default} 가정 — {exc!r}")
    return effective


def _cycle(redis, key, start, ok, fail, skip):
    """외부 전략 두 모드가 명시적으로 off인 경우에만 True를 반환한다."""
    try:
        raw = redis.get(key)
        if raw is None:
            skip(f"Redis {key}: 사이클 기록 없음")
            return False
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("사이클 JSON은 객체여야 함")
        try:
            at = _epoch(data.get("at"))
        except Exception:      # at 을 못 읽으면 「재시작 전 기록」을 증명할 수 없다 → 필드 누락이면 fail 쪽(보수적)
            at = None
        external = key == "ext:last_cycle"
        both_off = external and all(
            name in data and _off(data[name]) for name in ("fujimoto", "mach7")
        )
        if both_off:
            skip(f"Redis {key}: 외부 전략 꺼짐")
            return True

        required = "gate_skip" if external else "klines"
        if required not in data:
            if start is not None and at is not None and at < start:
                skip(f"Redis {key}: 재시작 뒤 아직 사이클 없음")
            else:
                fix = "406" if external else "405"
                label = "외부 전략" if external else "가상매매"
                fail(
                    f"{label} 사이클 기록에 {required} 없음 — "
                    f"Fix {fix} 미반영 프로세스"
                )
            return False

        if external:
            fields = ("at", "symbols", "gate_skip", "kl_weight", "fujimoto", "mach7")
            detail = " ".join(f"{name}={data.get(name, '-')}" for name in fields)
        else:
            klines = data["klines"]
            if not isinstance(klines, dict):
                raise ValueError("klines는 객체여야 함")
            # 요구 목록의 중복 incremental은 한 번만 표시한다.
            fields = (                  # enabled = 캐시 켬(Fix 405 직후엔 incremental 횟수 키에 덮여 있었다)
                "enabled", "incremental", "weight", "fetch_calls", "full",
                "closed_hit", "fallback", "fetch_errors",
            )
            detail = (
                f"at={data.get('at', '-')} symbols={data.get('symbols', '-')} "
                "klines={"
                + ", ".join(f"{name}={klines.get(name, '-')}" for name in fields)
                + "}"
            )
        ok(f"Redis {key}: {detail}")
    except Exception as exc:
        skip(f"Redis {key}: 읽기/JSON 오류 — {exc!r}")
    return False


def _integer(value):
    number = int(_text(value))
    if number < 0:
        raise ValueError("무게가 음수임")
    return number


def _measure(redis, start, now, window, settings, external_off, ok, fail, skip, cold_min=COLD_MIN):
    if start is None:
        skip("실측 무게: 프로세스 시작 시각 없음 — 측정 구간 확정 불가")
        return
    if not isinstance(window, int) or window < 1:
        raise ValueError("window_min은 양의 정수여야 함")

    current_minute = int(now // 60)
    start_minute = int(start // 60)
    # 현재 분과 시작 분을 제외한다. window개의 과거 분 중 적격 분만 읽는다.
    minutes = [
        minute for minute in range(current_minute - window, current_minute)
        if minute > start_minute + cold_min
    ]
    count = len(minutes)
    if count < 20:
        skip(f"실측 무게: 재시작 {cold_min}분 뒤부터 측정 — 지금 {count}분 (20분 필요, 재시작 뒤 약 {cold_min + 21}분부터 판정)")
        return

    callers = {name: [] for name in LIMITS}
    totals, used = [], []
    recorded = 0
    hash_errors, used_errors = [], []
    for minute in minutes:
        stamp = datetime.fromtimestamp(
            minute * 60, timezone.utc
        ).strftime("%Y%m%d%H%M")
        hash_key = f"binance:weight:by_caller:{stamp}"
        used_key = f"binance:used_weight:{stamp}"
        try:
            values = {
                _text(key): _integer(value)
                for key, value in redis.hgetall(hash_key).items()
            }
            if values:          # 기록 없는 분은 평균에서 뺀다 — 0 으로 넣고 전체 분으로 나누면 80/분이 53/분으로 보여 PASS (Gemini 심판)
                recorded += 1
                totals.append(sum(values.values()))
                for name in callers:
                    callers[name].append(values.get(name, 0))   # 기록 있는 분에 그 호출자가 없음 = 진짜 0
        except Exception as exc:
            hash_errors.append(f"{hash_key}: {exc!r}")
        try:
            raw = redis.get(used_key)
            # 기록 없는 분은 0. 읽기 오류는 0으로 대체하지 않는다.
            used.append(0 if raw is None else _integer(raw))
        except Exception as exc:
            used_errors.append(f"{used_key}: {exc!r}")

    print(f"실측 구간: UTC 완결된 {count}분, 시작 분·진행 중 분 제외")
    if used_errors:
        skip(f"used_weight: 읽기 오류 {len(used_errors)}분 — {used_errors[0]}")
    else:
        print(f"used_weight: 평균={sum(used) / count:.2f}/분 최대={max(used)}")

    if hash_errors:
        # 일부 실패를 0으로 처리하면 허위 PASS가 발생하므로 판정하지 않는다.
        skip(f"호출자/전체 무게: 읽기 오류 {len(hash_errors)}분 — {hash_errors[0]}")
        return

    if recorded < 20:
        # 해시가 통째로 없는 분 = 「호출 0」이 아니라 「기록 없음」(기록기 미배포·키 형식 차이) → 0 평균으로 PASS 하지 않는다
        skip(f"호출자/전체 무게: 실측 기록 있는 분 {recorded}/{count} — 20분 미만이라 판정 보류")
        return
    print(f"전체 호출자 무게: 평균={sum(totals) / recorded:.2f}/분 최대={max(totals)} (기록 있는 분 {recorded}/{count})")
    for name, samples in callers.items():
        average = sum(samples) / recorded
        reduction = (1 - average / BASELINES[name]) * 100
        print(
            f"{name}: 평균={average:.2f}/분 — 배포 전 "
            f"{BASELINES[name]}/분(2026-10-02 실측) 대비 감소율={reduction:.1f}%"
        )
        setting_key = (
            "paper_kline_incremental" if name == "paper_trading"
            else "ext_kline_incremental"
        )
        setting = settings[setting_key]
        if name == "external_strategies" and external_off:
            skip(f"무게 판정 {name}: 외부 전략 꺼짐")
        elif setting is None:
            skip(f"무게 판정 {name}: 설정 실효값 확인 불가")
        elif _setting_off(setting_key, setting):
            skip(f"무게 판정 {name}: 설정 끔 — 절감 없음")
        else:
            report = ok if average <= LIMITS[name] else fail
            report(
                f"무게 판정 {name}: 평균={average:.2f}/분 "
                f"문턱={LIMITS[name]}/분"
            )


def check_ip_weight(ok, fail, skip, *, root: str, code_only: bool,
                    process_start_epoch: float | None,
                    get_setting=None, redis=None, now_epoch: float | None = None,
                    window_min: int = 30, cold_min: int = COLD_MIN) -> None:
    """절 제목을 출력하고 코드·프로세스·운영 층을 읽기 전용으로 검사한다."""
    try:
        print(TITLE)
        mtimes = _check_code(root, ok, fail)
        _check_process(mtimes, process_start_epoch, ok, fail, skip)
        if code_only:
            skip("--code-only: 운영 층 생략")
            return

        settings = _settings(get_setting, skip)
        if redis is None:
            for label in ("paper_trading:last_cycle", "ext:last_cycle", "실측 무게"):
                skip(f"Redis {label}: redis 미주입")
            return

        _cycle(redis, "paper_trading:last_cycle",
               process_start_epoch, ok, fail, skip)
        external_off = _cycle(
            redis, "ext:last_cycle", process_start_epoch, ok, fail, skip,
        )
        _measure(
            redis, process_start_epoch,
            time.time() if now_epoch is None else now_epoch,
            window_min, settings, external_off, ok, fail, skip, cold_min,
        )
    except Exception as exc:
        try:
            fail(f"IP 무게 검사 예기치 못한 예외 — {exc!r}")
        except Exception:
            # 호출자 출력 함수 자체의 오류도 검사기 전체로 전파하지 않는다.
            pass