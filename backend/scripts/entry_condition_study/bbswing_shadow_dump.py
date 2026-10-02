"""볼밴 스윙 그림자 신호 덤프 (읽기 전용) — Redis bbswing:shadow:* (30일 TTL — Fix 412) 를 JSON 한 줄씩 출력.

ssh root@VPS "cd ~/binance-auto-trader/backend && docker compose exec -T api python -" \
  < backend/scripts/entry_condition_study/bbswing_shadow_dump.py > backend/scripts/entry_condition_study/bbswing/shadow_$(date +%Y%m%d).jsonl
"""
import json

from app.core.redis_client import get_redis_client

r = get_redis_client()
n = 0
for k in r.scan_iter("bbswing:shadow:*", count=1000):
    v = r.get(k)
    if v:
        print(v if isinstance(v, str) else v.decode())
        n += 1
last = r.get("bbswing:last_cycle")
print(json.dumps({"_meta": True, "count": n,
                  "last_cycle": json.loads(last) if last else None}))
