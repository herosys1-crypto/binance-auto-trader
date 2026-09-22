"""🔍 Fix 391 — 바이낸스 호출 가중치 진단표 (읽기 전용).

IP 차단(418) 원인 추적용. 최근 2시간의 분당 값을 보여준다:

  · 우리추정  = 코드가 센 값 (`estimate_weight` 합)
  · 바이낸스  = 응답 헤더 `X-MBX-USED-WEIGHT-1M` = **거래소가 센 값** (한도 2400)
  · 차이      = 아직 세지 않는 경로의 규모
  · 엔드포인트별 = 그 분에 무엇이 썼는지

쓰는 법 (VPS, 읽기만):
    ssh root@<VPS> "cd ~/binance-auto-trader/backend && docker compose exec -T api python -" \
      < backend/scripts/weight_report.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/app")

LIMIT = 2400  # Binance USD-M 분당 REQUEST_WEIGHT 한도


def main(minutes: int = 120) -> None:
    from app.integrations.binance.client import get_ip_ban_remaining_sec, get_weight_breakdown

    rows = get_weight_breakdown(minutes=minutes)
    if not rows:
        print("기록 없음 — Fix 391 계측이 배포된 뒤의 시간만 남는다 (api·scheduler 재시작 필요).")
        return

    ban = get_ip_ban_remaining_sec()
    print(f"지금 IP 차단: {'남은 ' + str(ban) + '초' if ban > 0 else '없음'} · 한도 {LIMIT}/분\n")
    print(f"{'분(UTC)':>12} {'우리추정':>8} {'바이낸스':>8} {'차이':>7} {'한도%':>6}  상위 엔드포인트")
    print("-" * 100)
    worst = None
    for row in rows:                      # 최신순
        est, used = row["est"], row["used"]
        gap = used - est if used else 0
        pct = (used * 100 // LIMIT) if used else 0
        top = sorted(row["by_endpoint"].items(), key=lambda kv: -kv[1])[:4]
        top_s = " · ".join(f"{k.rsplit('/', 1)[-1]} {v}" for k, v in top)
        m = row["minute"]
        print(f"{m[4:6]}-{m[6:8]} {m[8:10]}:{m[10:12]} {est:8d} {used:8d} {gap:+7d} {pct:5d}%  {top_s}")
        if used and (worst is None or used > worst["used"]):
            worst = row

    if worst:
        print("\n■ 가장 높았던 분 —", worst["minute"])
        for k, v in sorted(worst["by_endpoint"].items(), key=lambda kv: -kv[1]):
            print(f"   {k:34s} {v:6d}  ({v * 100 // max(1, worst['est'])}% of 우리추정)")
        print(f"   우리추정 {worst['est']} · 바이낸스 실측 {worst['used']} "
              f"({worst['used'] * 100 // LIMIT}% of 한도) · 차이 {worst['used'] - worst['est']:+d}")
        print("   차이가 크면 = 아직 계측 밖인 경로가 있다 (또는 같은 IP 의 다른 프로세스).")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 120)
