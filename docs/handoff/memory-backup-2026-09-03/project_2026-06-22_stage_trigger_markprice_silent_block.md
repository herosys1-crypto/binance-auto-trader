---
name: ""
metadata: 
  node_type: memory
  originSessionId: 3a7c8fc6-6afa-4af2-8926-abe6b890367e
---

🚨 2026-06-22 사장님 critical: "또 2단계가 진행되지 않았어" (#221 IDUSDT / #220 AINUSDT / #215 / #217 / #218 / #219 전부 단계2에서 "mark_price 없음 (mark-price-stream 점검 필요)" 차단).

**진짜 원인 (silent bug)**: mark_price 소스가 2개인데 자동 진입만 잘못된 걸 봄.
- Redis 실시간 캐시 `get_mark_price` (markPrice@1s, 1초 신선) ← UI 현재가 / PNL(helpers.py) / 수동 진입(control.py L1043/L1363) 이 사용
- DB Position snapshot `latest_pos.mark_price` (reconcile 2분 주기, 1단계 체결 직후엔 None) ← **stage_trigger_worker 자동 진입만 이걸 봄**
- 결과: 1단계 체결 후 reconcile가 채우기 전까지 stage 2 자동 진입 영구 보류. **화면엔 live 현재가가 멀쩡히 보이는데** 자동 진입만 막힘. 알림이 "mark-price-stream 점검 필요"라 stream을 의심하게 만들지만 stream(Redis)은 정상 — 자동 진입 코드가 안 읽을 뿐.

**진짜 ROOT CAUSE (더 검토로 발견)**: `stream_service.py:260` handle_account_update 가 ACCOUNT_UPDATE 마다 `mark_price=None` 스냅샷 생성. ACCOUNT_UPDATE payload 엔 markPrice 없음 → None. 근데 포지션 변동마다 발생 → 이 None 스냅샷이 "latest" 되어 reconcile(2분) 가 채운 값을 곧바로 덮음 = **1시간+ None 지속 원인** (#221 03:49 + 05:00 둘 다 차단 설명됨).

**같은 버그 4개 reader 동시 피해** (전부 latest snapshot.mark_price 읽고 None이면 silent skip):
- stage_trigger_worker.py:246 — 2단계 자동 진입 차단
- **liquidation_risk_worker.py:87 — 청산 위험 감시 통째로 skip (자본 보호 critical gap!)**
- tp_miss_detector_worker.py:103 — TP 미스 감지 skip
- setting_preservation_agent.py:210 — mark=None 전달 (degraded)

**Fix (v51) = 2곳**:
1. ROOT: `stream_service.py:260` — `mark_price=None` → `get_mark_price(symbol)` Redis 실시간. = latest 오염 X = 4개 reader 동시 치유.
2. 방어선: `stage_trigger_worker.py:246` — 자동 진입도 Redis 우선 + DB fallback (가장 critical 경로 read 시점 live).
둘 다 헌법 6번 단일 진실 (= 화면 현재가와 같은 소스).

**메타 교훈**: 같은 개념("현재가")인데 writer가 None을 박고 reader 4개가 silent skip = silent bug. [[project_2026-06-22_mobile_scroll_lessons]] 와 동급 = 단일 진실 위반 패턴. **검토 더 하라는 사장님 지시("2")가 핵심 root cause + 청산 감시 silent gap 발견으로 이어짐.**

**PR 상태**: 브랜치 `fix/stage-trigger-markprice-silent-block-2026-06-23` push 완료 (origin/main 기반, 커밋 `5d546e7`). gh 미설치 → 웹 UI로 PR 생성 필요: https://github.com/herosys1-crypto/binance-auto-trader/pull/new/fix/stage-trigger-markprice-silent-block-2026-06-23 . origin/main = PR #225로 mobile-ui feat 이미 머지됨 (feat 브랜치 = main에 0 커밋 추가).

**미배포**: PR 머지 후 VPS 배포 필요 (`api` 서비스 = stream_service / `scheduler` = stage_trigger 호스트, **둘 다 배포** — 한쪽만 하면 root/방어선 한쪽만 적용). 배포 전엔 수동 「▶ 다음 단계」로 메움. mark_price_stream_consumer 프로세스가 떠 있어야 Redis 캐시 채워짐 (UI 현재가 보이면 = 정상).
