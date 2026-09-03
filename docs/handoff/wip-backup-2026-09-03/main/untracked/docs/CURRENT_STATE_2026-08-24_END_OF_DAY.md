# 현 상태 스냅샷 - 2026-08-24 End of Day

> 목적: 다음 세션 즉시 파악용 현재 세팅 스냅샷
> 최종 갱신: 2026-08-24 세션 종료 시점

---

## 1. 현 시각 / 배포 정보

- 날짜: 2026-08-24 (오늘 세션 최종!)
- main HEAD: `1c0f141` (Fix 61 통합!)
- git tag: `v-2026-08-24-session-final-fix47-61`
- 배포 상태: VPS 반영 완료 (`git pull && docker compose restart api scheduler`)

---

## 2. SystemSetting (활성 세팅!)

| 키 | 값 | 비고 |
|---|---|---|
| `sajangnim_top_short_daily_limit` | 20 | LONG + SHORT 통합 카운터! |
| `sajangnim_max_stage` | 2 | 사장님 default (3단계 = 신중!) |
| `auto_bb_break_daily_limit` | 0 | Fix 32/33 = 비활성! |
| `unified_15m_entry_enabled` | 확인 필요 | v224 이후 OFF 예상 |
| `pending_hc_fast_enabled` | 확인 필요 | Fix 32 이후 OFF 예상 |
| `success_pyramiding_enabled` | 확인 필요 | Fix 32 이후 OFF 예상 |
| `auto_bb_breakdown_enabled` | 0 | Fix 33 DISABLE flag! |

### 사장님 = 실제 값 확인 명령:

```bash
cd ~/binance-auto-trader/backend
docker compose exec api python -c "
from app.db.session import SessionLocal
from app.models.system_setting import SystemSetting
s = SessionLocal()
keys = [
  'sajangnim_top_short_daily_limit',
  'sajangnim_max_stage',
  'auto_bb_break_daily_limit',
  'auto_bb_breakdown_enabled',
  'unified_15m_entry_enabled',
  'pending_hc_fast_enabled',
  'success_pyramiding_enabled',
]
for k in keys:
  row = s.query(SystemSetting).filter_by(key=k).first()
  print(f'{k} = {row.value if row else None}')
s.close()
"
```

---

## 3. 활성 워커 (스케줄러!)

### v219 계열 (사장님 실 성공 로직!)
- `auto_short_at_top` - 매 30초, 7중 정점 SHORT 자동 진입
- `pump_top_detector` - 매 5분, 정점 후보 탐지

### LONG 계열 (대칭!)
- `auto_long_at_bottom` - LONG 자동 진입
- `long_bottom_detector` - 바닥 후보 탐지

### 마틴게일 / 재진입 관리
- `peak_break_reversal` - 정점 돌파 반전
- `resistance_reversal` - 저항 반전 SHORT 2단계 (Fix 29)
- `time_reverse_exit` - 시간 역방향 청산 (Fix 31)
- `realtime_reentry` - 실시간 재진입 (v202)
- `success_pyramiding` - 성공 피라미딩 (v218, Fix 32 OFF 검토)

### 오케스트라 검증
- `martingale_gate_validator` - 마틴게일 게이트 감지
- `spec_audit_worker` - spec 감사
- `silent_bug_detector` - silent bug 탐지

### 자동 유지
- `auto_add_margin` - 증거금 자동 추가 (ISOLATED)

---

## 4. 활성 심볼 스냅샷 (2026-08-24 08:30 UTC 기준)

- 총 활성: 36건 (SHORT 11 + LONG 25!)
- SL 세팅: 모두 -5% 안전!
- 최대 총 손실 (전량 SL 발동 시): -540 USDT
- 활성 심볼 목록은 아래 명령으로 확인:

```bash
docker compose exec api python -c "
from app.db.session import SessionLocal
from app.models.strategy import StrategyInstance
s = SessionLocal()
rows = s.query(StrategyInstance).filter(
  StrategyInstance.status.in_(['STAGE_1_OPEN','STAGE_2_OPEN','STAGE_3_OPEN','PENDING_HC','ACTIVE'])
).all()
print(f'total={len(rows)}')
for r in rows:
  print(f'{r.id} {r.symbol} {r.side} {r.status}')
s.close()
"
```

---

## 5. 오늘 손절 통계 (2026-08-24)

- 총 청산 실패: 18건 = **-362.16 USDT**
- SHORT 8건 = **-197.39 USDT**
- LONG 10건 = **-164.77 USDT**
- Fix 47 대량 실패 포함 (주식/ETF 심볼 오진입 사고)

---

## 6. Fix 47 ~ Fix 61 정리 (오늘 세션!)

### 코드 (배포 완료!)
- Fix 47: 대량 실패 원인 조사 및 blocklist 초기 도입
- Fix 48~52: v219 트리거 세밀화, 로그 강화
- Fix 53: martingale_gate_validator 신설
- Fix 54: Blocklist 프레임 도입 (P1 강화 계속 필요)
- Fix 55: 마틴게일 재정의
- Fix 56~60: 안정화 fix (오케스트라 검증 통합)
- Fix 61: LONG+SHORT 통합 daily limit = 20 (신 진입 상한!)

### 오케스트라
- 모두 활성! (martingale_gate_validator / spec_audit_worker / silent_bug_detector 실행 중)

### 테스트
- 36 tests CI 통과!
- github actions 자동 검증!

### spec
- 25 사상 등록 (docs/ 폴더!)

---

## 7. 다음 세션 관찰 우선순위

1. **활성 36건 outcome** (24h 관찰!)
   - 실 성공/실패 통계 = -540 USDT 방어 성공?
2. **Fix 61 신 진입 하루 20건 이내 검증**
   - `sajangnim_top_short_daily_limit=20` 실제 동작?
3. **Fix 55 마틴게일 발동 사례 확인**
   - 2단계 진입 실제 케이스 학습!
4. **martingale_gate_validator 감지 결과**
   - 오케스트라 알림 로그 확인!

---

## 8. 다음 개발 (필요 시!)

- **Fix 54 P1**: Blocklist 강화 (반복 실패 심볼 자동 등록!)
- **주식/ETF 심볼 blocklist**: QQQ / SPY / GOOGL 계열 (Fix 47 사고 재발 방지!)
- **시간대 필터**: KST 08~10시 급변동 시간대 skip 검토
- **BinanceClient testnet 파라미터 fix**: 테스트 환경 안정화

---

## 9. 헌법 준수 상태

- 헌법 65/66: 100% 준수 (신 fix 전 Agent 검증!)
- 헌법 69/70/71: 완료 전 VPS + API + UI 3단계 실 검증!
- 헌법 64: 급등 반대매매 금지 (v219 = 예외 = 헌법 68!)
