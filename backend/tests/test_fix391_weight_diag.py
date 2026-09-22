"""🔍 Fix 391 — IP 차단(418) 원인 추적 계측 (2026-09-23).

사장님: "IP 차단 원인 추적 먼저 해줘"

추적하다 막힌 지점: 거버너 카운터는 335~717/분(한도 2400의 15~30%)인데 차단이 났다.
  · 9/21 20:40 · 9/22 08:40 = 429 (클러스터)
  · 9/22 18:49 = 418 IP ban 334초 → 그 6분간 시세 503 이 70건
왜 못 집었나 = ① 세지 않는 경로가 있고(생짜 `requests.get` 7곳)
              ② 엔드포인트별 분해가 없고
              ③ **차단을 맞은 요청의 경로를 로그에 안 남겼다**.

이 Fix 는 판정을 바꾸지 않고 그 셋을 메운다:
  ① `record_external_call` — 화면용 라우터의 생짜 호출도 계수 (막지는 않는다)
  ② `binance:weight:by_endpoint:{분}` 해시 + `binance:used_weight:{분}`
     (= 바이낸스가 준 `X-MBX-USED-WEIGHT-1M` = 거래소가 센 값)
  ③ 418/429 를 맞으면 method·path·params 를 ERROR 로 남긴다
진단 표는 `backend/scripts/weight_report.py`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.integrations.binance.client import estimate_weight, note_used_weight

SRC = Path(__file__).resolve().parent.parent / "app" / "integrations" / "binance" / "client.py"
MARKET = Path(__file__).resolve().parent.parent / "app" / "api" / "v1" / "market.py"
ACCOUNTS = Path(__file__).resolve().parent.parent / "app" / "api" / "v1" / "exchange_accounts.py"


class _Resp:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


def test_used_weight_header_is_parsed() -> None:
    """바이낸스 헤더에서 실제 사용량을 읽는다 (대문자·소문자 둘 다)."""
    assert note_used_weight(_Resp({"X-MBX-USED-WEIGHT-1M": "1234"}), path="/x") == 1234
    assert note_used_weight(_Resp({"x-mbx-used-weight-1m": "77"}), path="/x") == 77


@pytest.mark.parametrize("resp", [_Resp({}), _Resp({"X-MBX-USED-WEIGHT-1M": "abc"}), None, object()])
def test_used_weight_never_raises(resp: object) -> None:
    """진단이 거래 경로를 죽이면 안 된다 — 어떤 입력이든 0 을 돌려준다."""
    assert note_used_weight(resp, path="/x") == 0


def test_open_orders_without_symbol_is_weight_40() -> None:
    """대시보드가 쓰는 전체 openOrders 는 한 번에 40 — 이걸 안 세면 진단이 틀어진다."""
    assert estimate_weight("/fapi/v1/openOrders", {}) == 40
    assert estimate_weight("/fapi/v1/openOrders", {"symbol": "BTCUSDT"}) == 1
    assert estimate_weight("/fapi/v2/positionRisk", {}) == 5


def test_banned_request_path_is_logged() -> None:
    """③ 418/429 를 맞은 요청의 경로를 남긴다 (이게 없어서 이번 추적이 막혔다)."""
    src = SRC.read_text(encoding="utf-8")
    i_log = src.index("[Fix391] 🚨 %d 를 맞은 요청")
    i_mark = src.index("_mark_ip_ban_from_response(response)")
    assert i_log < i_mark, "경로 로그가 ban 마킹보다 앞이어야 남는다"
    assert "method, path" in src[i_log:i_mark]


def test_breakdown_recorded_in_add_weight() -> None:
    """② 엔드포인트별 분해가 _add_weight 안에서 같이 기록된다."""
    src = SRC.read_text(encoding="utf-8")
    fn = src[src.index("def _add_weight("):src.index("def note_used_weight(")]
    assert "_WEIGHT_BY_ENDPOINT_KEY" in fn and "hincrby" in fn
    assert "_DIAG_TTL_SEC" in fn


@pytest.mark.parametrize("path", [MARKET, ACCOUNTS])
def test_raw_calls_are_counted(path: Path) -> None:
    """① 생짜 requests 경로가 모두 계측된다 — 호출 지점마다 경로를 넘긴다."""
    src = path.read_text(encoding="utf-8")
    assert "record_external_call" in src
    raw = len(re.findall(r"^\s+_?r(?:esp)?\s*=\s*_?requests\.get\(", src, re.M))
    tagged = len(re.findall(r'_note_ip_ban\((?:r|_resp), path="', src))
    assert raw > 0
    assert tagged == raw, f"생짜 호출 {raw}곳 중 {tagged}곳만 경로를 넘긴다"


@pytest.mark.parametrize("path", [SRC, MARKET, ACCOUNTS])
def test_crlf_preserved(path: Path) -> None:
    """프로젝트 규칙 8 — 이 파일들은 CRLF 다."""
    raw = path.read_bytes()
    assert b"\r\n" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n")


class TestFix392OpenOrdersCache:
    """🚨 Fix 392 — 사장님 「openOrders 캐시 30초로 늘려줘」 (2026-09-23).

    근거(Fix 391 실측 21:43): 화면 1개가 열려 있을 때 분당 openOrders **160** = 한도의 7%
    (symbol 없는 전체 조회 = 회당 weight 40 × 15초 캐시 = 분당 4회).
    30초면 분당 2회 = 80 → 절반. 대가는 미체결 요약이 최대 30초 늦는 것.
    """

    def test_ttl_is_30_and_used_in_setex(self) -> None:
        src = ACCOUNTS.read_text(encoding="utf-8")
        assert "OPEN_ORDERS_CACHE_TTL_SEC = 30" in src
        assert "redis.setex(cache_key, OPEN_ORDERS_CACHE_TTL_SEC" in src

    def test_no_hardcoded_15_left(self) -> None:
        """옛 15초 리터럴이 이 캐시에 남아 있지 않다 (두 곳에 저장되던 사고 방지)."""
        src = ACCOUNTS.read_text(encoding="utf-8")
        assert "redis.setex(cache_key, 15" not in src


class TestFix393CallerBreakdown:
    """🔍 Fix 393 — 「klines 가 분당 885」 까지는 봤는데 **누가** 쓰는지 몰랐다 (2026-09-23).

    사장님 화면 실측(09-22 21:42~21:59): 바이낸스 실측 366~1189/분(한도의 15~49%),
    그중 klines 가 246~885 = 매 분 1위. 줄일 곳을 고르려면 잡별 분해가 필요하다.
    같이 고친 것 = 「우리추정 0 · 차이 +1189」로 보였던 진단표 결함
    (추정 키 TTL 180초 < 진단 보관 2시간 → 만료된 분이 0 으로 찍혔다. 누락 경로가 아니었다).
    """

    def test_caller_contextvar_and_key(self) -> None:
        src = SRC.read_text(encoding="utf-8")
        assert "_WEIGHT_BY_CALLER_KEY" in src
        assert "def set_caller(" in src and "def reset_caller(" in src
        fn = src[src.index("def _add_weight("):src.index("def note_used_weight(")]
        assert "_caller_var.get() or \"other\"" in fn

    def test_est_key_retention_matches_diag(self) -> None:
        """추정 키도 2시간 보관 — 거버너는 이번 분만 읽으므로 판정 영향 없음."""
        src = SRC.read_text(encoding="utf-8")
        fn = src[src.index("def _add_weight("):src.index("def note_used_weight(")]
        assert "r.expire(key, _DIAG_TTL_SEC)" in fn
        assert "r.expire(key, _WEIGHT_TTL_SEC)" not in fn

    def test_guarded_job_tags_caller(self) -> None:
        """스케줄러의 모든 잡이 자기 이름을 남긴다 (한 곳에서 처리)."""
        runner = SRC.parent.parent.parent / "workers" / "scheduler_runner.py"
        src = runner.read_text(encoding="utf-8")
        blk = src[src.index("def guarded_job("):src.index("scheduler.add_job(guarded_job(\"listenkey_keepalive\"")]
        assert "set_caller(job_name)" in blk
        assert "reset_caller(_tok)" in blk
        assert blk.index("set_caller(job_name)") < blk.index("fn()")

    def test_report_shows_callers(self) -> None:
        rpt = (SRC.parent.parent.parent.parent / "scripts" / "weight_report.py").read_text(encoding="utf-8")
        assert "by_caller" in rpt
        assert "잡(호출자)별" in rpt


class TestFix394ApiCallerTag:
    """🔍 Fix 394 — 화면 API 가 쓴 가중치를 경로 이름으로 분해 (2026-09-23).

    Fix 393 실측(22:16): klines 672 중 `paper_trading 278` · **`other 408`**.
    스케줄러에 스레드풀이 없어 ContextVar 는 잡마다 붙는다 → 그 other 는 api 컨테이너다.
    어느 화면 API 가 캔들을 쓰는지(예: strategy-suggestions 계열) 알아야 줄일 곳을 고른다.
    """

    def test_middleware_sets_and_resets_caller(self) -> None:
        main = SRC.parent.parent.parent / "main.py"
        src = main.read_text(encoding="utf-8")
        blk = src[src.index("async def _tag_binance_caller"):src.index("async def _no_store_api")]
        assert 'set_caller("api:"' in blk
        assert "reset_caller(tok)" in blk
        assert blk.index("set_caller(") < blk.index("await call_next("), "요청 처리 전에 태깅해야 잡힌다"
        assert "finally:" in blk, "예외가 나도 되돌려야 문맥이 새지 않는다"

    def test_only_api_paths_tagged(self) -> None:
        """정적 파일·헬스체크까지 태깅해 해시를 더럽히지 않는다."""
        main = SRC.parent.parent.parent / "main.py"
        src = main.read_text(encoding="utf-8")
        blk = src[src.index("async def _tag_binance_caller"):src.index("async def _no_store_api")]
        assert 'path.startswith("/api/v1/")' in blk
