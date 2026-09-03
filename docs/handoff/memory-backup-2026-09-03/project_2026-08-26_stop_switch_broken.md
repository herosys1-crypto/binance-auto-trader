---
name: 2026-08-26-stop-switch-broken
description: "🚨 정지 스위치가 고장나 있었음 (Fix 107~110). 「0 = OFF」가 20으로 둔갑 / UI 422는 Content-Type 누락 / UI·워커 카운터 불일치. 헌법 83~85 신설."
metadata:
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-08-26T01:48:38.595Z
---

# 🚨 정지 스위치가 눌러도 안 꺼지던 사건 (2026-08-26)

**발단**: 사장님 UI = 「오늘 자동 진입 137/0」 + 활성 47건 전부 SHORT + 자동 순 PnL −143.17
        → 한도 0인데 137건 진입!

## Fix 108 ★가장 심각★ — 「0 = OFF」가 20으로 둔갑

```python
# auto_short_at_top:68 / auto_long_at_bottom:643 (옛)
for key in ("sajangnim_top_short_daily_limit", "auto_bb_break_daily_limit"):
    if row and row.value:
        v = int(row.value)
        if v > 0:              # ← 0 이면 return 안 하고 루프 계속!
            return v
return DEFAULT_DAILY_LIMIT     # ← 전 키가 0 이면 20 반환!!
```
- 사장님이 「끄기」로 0을 넣을 때마다 **시스템은 20으로 읽음**
- 정지 스위치가 존재하지만 **실제로는 작동하지 않는 상태**
- **fix**: 값이 있으면 0이어도 존중 → `return 0` + warning 로그
- 검증: 실 로그 `"자동 진입 완전 OFF (사장님 명시 정지!)"` 30초마다 확인 ✅

## Fix 107 — UI 422 진짜 원인 = Content-Type 누락 (Fix 86은 헛다리!)

```javascript
// api.js (옛)
if (opts.body && typeof opts.body === 'object' && ...) {
    headers['Content-Type'] = 'application/json';   // ← object 일 때만!
    opts.body = JSON.stringify(opts.body);
}
```
- 호출부가 `body: JSON.stringify(payload)` 로 **이미 문자열**을 넘기면 헤더 미설정
- 브라우저가 `text/plain` 전송 → FastAPI가 **문자열로 인식** → 422 dict_type
- 에러의 `"input":"{\"a\":1}"` 이 **따옴표로 감싸진 것**이 결정적 단서
- L1459(헤더 직접 지정)만 되고 L1093/L1139는 실패 = **호출부마다 성공/실패 갈림**
- **fix**: api.js에서 문자열 body에도 Content-Type 부착 (FormData/Blob 제외)
- ⚠️ `api.js` cache-bust가 `20260722` = 7월 이후 안 올려서 옛 캐시 가능성도 있었음

## Fix 109 — 진입 워커 조기 return 무로그 (헌법 80 확산)

- `auto_short_at_top` / `auto_long_at_bottom` 조기 return 5곳 전부 무로그
- 「워커 사망」과 「조용한 종료」 구별 불가 → realtime_reentry(Fix 103) 재발
- **fix**: 모든 조기 return에 사유 로그

## Fix 110 — UI ↔ 워커 카운터/한도 불일치

| | 워커 | UI (옛) |
|---|---|---|
| daily_used | 모든 SHORT AUTO, **익절 제외**, 사장님 리셋 반영 | `sajangnim_top_short`만, **익절 포함**, KST 고정 |
| daily_limit | fallback 체인 (→DEFAULT 20) | 단일 키만 조회 |

→ 화면 "137/0 = 정지"인데 워커는 "20으로 진입 가능" = **사장님이 화면을 봐도 실제를 알 수 없었음**
→ **fix**: UI가 워커 함수(`_count_v219_used_slots`/`_get_daily_limit`)를 그대로 재사용

## 🚨 헌법 신설

**헌법 83: 「0 = OFF」는 반드시 0을 그대로 반환할 것!**
- `if v > 0: return v` 패턴 금지 — 0이 fallback으로 새어나가 기본값이 됨
- 정지 스위치는 **작동을 로그로 증명**해야 함

**헌법 84: fetch body가 문자열이어도 Content-Type을 붙일 것!**
- `typeof body === 'object'` 조건 안에 헤더 설정을 두면 문자열 body에서 누락
- 422 `input`이 따옴표로 감싸져 있으면 = 헤더 문제 (이중 인코딩 아님!)

**헌법 85: UI 숫자와 워커 판정은 같은 함수를 쓸 것!**
- 화면과 실제가 다르면 사장님이 상태를 오판 → 자본 위험
- API는 워커 함수를 import해서 재사용 (헌법 6 확장)

## 검증된 정지 절차 (앞으로 이걸로)

```bash
# 정지
docker compose exec api python -c "
from app.core.database import SessionLocal
from app.models.system_setting import SystemSetting
db = SessionLocal()
for k in ('sajangnim_top_short_daily_limit','auto_bb_break_daily_limit',
          'unified_entry_enabled','sajangnim_reentry_daily_limit'):
    s = db.query(SystemSetting).filter_by(key=k).first()
    if s: s.value='0'
    else: db.add(SystemSetting(key=k, value='0'))
db.commit(); db.close()"

# 증명 (30초 내 로그가 나와야 진짜 정지!)
docker compose logs scheduler --since 2m | grep -E "Fix108|daily_limit=0|재진입 OFF"
```

## ⚠️ 아직 열려 있는 경로 (다음 세션 최우선)

한도와 **무관하게** 활성 포지션에 마틴게일을 붙이는 경로:
- `peak_break_reversal_worker` — 전고점 반전 → 단계 증액
- `resistance_reversal_worker` — 저항 반전 → 2단계
- `stage_trigger_worker` — 다음 단계 자동 발주 (24h 필터 fail-open!)
- `auto_reentry_worker` — 지표 검증 **전무**
- `success_pyramiding_worker` — ticker 실패 시 무검증 통과

→ Fix 106 정점 게이트를 이들에도 확산 필요 (완전 차단보다 게이트 권장)

## 관련
- [[2026-08-26-reentry-structural-failure]] (헌법 80~82)
- [[feedback-verify-before-complete]] (헌법 69~71 = 실 로그 검증!)
