"""Fix 494 운영 — testnet 차단이 mainnet 키에 들어간 것을 지운다 (사장님 실행).

1) mainnet /fapi/v1/time 을 1번(무게 1) 불러 200 일 때만 지운다 (진짜 mainnet 차단이면 지우지 않음 = 연장 방지).
2) mainnet 차단·예열 키 삭제 → 다음 재시작부터 mainnet 정상. testnet 키는 그대로 둔다.
사용: docker compose exec -T api python - < scripts/clear_testnet_polluted_ban.py
"""
import requests

from app.core.redis_client import get_redis_client
from app.integrations.binance import client as C

r = get_redis_client()
before = {k: r.get(k) for k in (C._IP_BAN_REDIS_KEY, C._WARMUP_REDIS_KEY, C._TESTNET_BAN_REDIS_KEY)}
print("before", {k: (v.decode() if isinstance(v, bytes) else v) for k, v in before.items()})
resp = requests.get("https://fapi.binance.com/fapi/v1/time", timeout=10)
print("mainnet /time", resp.status_code, "used-weight-1m", resp.headers.get("x-mbx-used-weight-1m"))
if resp.status_code == 200:
    r.delete(C._IP_BAN_REDIS_KEY, C._WARMUP_REDIS_KEY)
    print("cleared mainnet ban + warmup keys")
else:
    print("mainnet 응답이 200 이 아님 → 지우지 않음 (진짜 차단일 수 있다)")
print("after", {k: r.get(k) for k in (C._IP_BAN_REDIS_KEY, C._WARMUP_REDIS_KEY)})
