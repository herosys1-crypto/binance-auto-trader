# 인계서 — 집 → 다음 세션 (2026-04-30 저녁)

> 이전 인계서: `HANDOFF-2026-04-29-OFFICE-TO-HOME-EVENING.md`
> 이 문서: 2026-04-29 ~ 2026-04-30 집 PC 작업 누적 (이번 세션이 가장 critical)

---

## 1. 오늘 (집 PC) 한 일 — 8 가지 큰 변화

### A. 🔴 Critical Bug Fix: Stage 2~N 자동 진입
**증상**: stage 1 만 거래소에 발송되고 stage 2~N 은 자동 트리거 worker 가 없어서 진입 안 됨. 마틴게일 평단가 평균화의 핵심이 절름발이로 돌고 있었음.

**수정**: `app/workers/stage_trigger_worker.py` 신규 작성 + scheduler 등록 (10초 간격)
- 활성 STAGE{1~9}_OPEN 전략 감시
- 다음 stage 의 trigger_price 와 mark_price 비교
- SHORT: mark >= trigger / LONG: mark <= trigger 시 자동 LIMIT 발송
- `ExecutionService.trigger_next_stage()` 호출

**검증**: #57 TACUSDT stage 2 자동 진입 성공 (12:11:07). 평단 0.01545 → 0.01655 로 평균화, 손실 -39% → -15% 회복.

### B. 🔴 TP/SL 룰 사용자 기획 반영
**정상 모드**:
| 단계 | 임계 | 수량 |
|------|------|------|
| TP1 | +10% (leveraged ROI) | 25% |
| TP2 | +15% | 25% |
| TP3 | +20% | 50% (남은 수량) |
| TP4 | +30% 이상 | 100% (전량) |
| SL | -50% (leveraged) | **모든 단계 진입 후만** 발동 |

**크라이시스 모드**:
- 트리거: 손실 -30% 도달 후 현재 PnL 양수 전환
- TP1=+5%, TP2=+10%, TP3=+15%, TP4=+20%, qty 25/25/50/100

**파일**:
- `app/services/risk_service.py` — pnl_ratio 에 leverage 곱, SL threshold /leverage, crisis 트리거 + override
- `app/services/tp_sl_orchestrator.py` — 크라이시스 qty ratio override (25/25/50/100), SHORT abs() 청산 버그 fix

### C. 중복 활성 전략 정리 + 재발 방지
**문제**: TACUSDT/SHORT 에 #56, #57 동시 활성. Binance 는 통합 포지션으로만 관리하므로 TP/SL 충돌.

**조치**:
- #56 안전 정리 (cancel orders + STOPPED + qty=0). 거래소 포지션은 #57 이 단독 관리.
- `strategy_service.create_strategy_instance` 에 중복 검증 추가 → 한국어 에러로 거부.

### D. TP/SL 알림에 손익 금액 + 수익률(%) 추가
- `notification_service.py` — `pnl_pct` 파라미터 추가
- `tp_sl_orchestrator.py` — mark_price/avg/leverage 로 계산해서 알림에 전달
- 텔레그램 + 대시보드 활동 피드 모두 자동 반영

### E. 대시보드 PnL/ROI 광범위 노출 + Binance 스타일 테이블
- 상단 "미실현 손익" 카드: USD + 전체 ROI %
- 전략 인스턴스 테이블: **진입가/마크/청산 (3줄)** + **수량/마진 (2줄)** + **PnL/ROI (2줄)**
- Binance 거래소 포지션 패널과 같은 정보 밀도

### F. 차트 timeframe 일관성 + 보조지표 sync
- 1h/4h/1d 모든 timeframe 에서 "현재가" 라벨 동일 위치 (strategy 데이터로 mark 역산)
- candleSeries 자동 last-close 라벨 비활성화
- RSI/MACD/OBV 와 메인 차트 **양방향 시간축 sync** (TIME range 기반, logical range 였던 버그 fix)
- 범례에 "현재가" 추가

### G. 대시보드 레이아웃 개선
- 운영통계 → 빠른작업과 최근활동 사이로 이동
- 전략 인스턴스 → 시스템상태 옆 (상단 우측) 으로 확장
- 좌측 컬럼: 시스템상태 + 빠른작업 + 운영통계 stack
- 캐시 헤더 추가 (`/admin-ui` 에 `Cache-Control: no-cache`)

### H. (이전 작업) Neon DB 클라우드 마이그레이션
- 어제 완료 (2026-04-29 아침)
- 회사↔집 sync 가 git pull + 컨테이너 재시작 5분으로 단축

---

## 2. 현재 시스템 상태

### 활성 전략 (3 건, 모두 SHORT testnet)
| ID | 심볼 | 단계 | 평단 | 마크 | leveraged ROI | USD |
|----|------|------|------|------|--------------|-----|
| #57 | TACUSDT | 2/5 | 0.01655 | ~0.0173 | -9.5% | -50 USDT |
| #58 | NAORISUSDT | 1/5 | 0.11053 | ~0.1090 | +1.7% | +1.7 USDT |
| #59 | UBUSDT | 1/6 | 0.06461 | ~0.0670 | -3.9% | -4 USDT |

### Workers (scheduler)
- **listenkey_keepalive**: 30분
- **position_reconcile**: 1분
- **tp_sl**: 10초
- **stage_trigger** (NEW): 10초 ← 오늘 추가
- **auto_reentry**: 30초
- **symbol_sync_daily**: cron 03:00 UTC

### Git
- branch: `main`
- 최신 commit: `1aece19` (chart sync time range)
- 모든 변경 push 완료. 사무실 출근 시 `git pull` 만 하면 자동 sync.

---

## 3. 미커밋 변경 (있다면)

집 PC 에서 다음 명령으로 확인 + push:

```powershell
cd C:\Users\user\바이낸스\binance-auto-trader
git status
```

만약 modified 파일 보이면:
```powershell
git add -A
git commit -m "feat: strategy instance table Binance-style"
git push origin main
```

---

## 4. 다음 세션 시작 시 절차

### 4-A. 사무실 PC 에서 (출근 시)
```powershell
cd C:\Users\user\바이낸스\binance-auto-trader
git pull origin main
cd backend
docker compose restart api scheduler user-stream
```

### 4-B. 집 PC 에서 (계속할 때)
이미 동기화됨. 그냥 대시보드 열고 모니터링하시면 됩니다.

### 4-C. Cowork 에 컨텍스트 복원
"이 인계서 (`HANDOFF-2026-04-30-HOME-EVENING.md`) 읽고 컨텍스트 복원해주세요. 활성 전략 모니터링 이어가요."

---

## 4-D. 추가 변경사항 (저녁 늦게 추가됨)

### Stage 진입 텔레그램 알림 중복 발송 부분 수정 (미해결)
- **증상**: 1단계 진입 알림이 2~3번 중복 텔레그램으로 옴 (DOLOUSDT, SKYAIUSDT 등 새 전략 생성 시 모두 동일)
- **추정 원인 1**: Binance ORDER_TRADE_UPDATE 가 같은 주문에 대해 여러 번 (NEW → PARTIALLY_FILLED → FILLED → trade settlement) 발송
- **수정 1**: `stream_service.py` 에 `just_triggered_now` 플래그 추가 — `is_triggered` False→True 전환 시에만 알림 발송
- **수정 후에도 여전히 중복** → **추가 조사 필요**

### 사무실에서 우선 확인할 것

```powershell
cd C:\Users\user\바이낸스\binance-auto-trader\backend
# 1. 컨테이너 안 코드 확인 (수정사항 적용 여부)
docker compose exec user-stream grep -c "just_triggered_now" /app/app/services/stream_service.py
# → 2 가 나와야 정상. 0 이면 git pull 후 재시작 필요.

# 2. user-stream 컨테이너가 1 개만 도는지 (중복 의심)
docker ps --filter "name=user-stream"
docker ps -a | findstr user-stream

# 3. 모든 user-stream 흔적 정리 후 1 개만 재기동
docker ps -a --filter "name=user-stream" -q | ForEach-Object { docker stop $_; docker rm $_ }
docker compose up -d user-stream
```

### 가설
- A. 옛 `binance_auto_trader_project` 폴더의 user-stream 컨테이너가 살아있어서 같은 Binance WebSocket 받아 양쪽이 알림 발송. (어제 cleanup 후에도 잔존 가능성)
- B. user-stream WebSocket 이 재연결되며 같은 이벤트 replay. (heartbeat 30초마다 갱신은 정상이지만 WS 이벤트 자체가 중복)
- C. NotificationService.send_stage_entered_alert 가 다른 곳에서도 호출됨 (stream_service.py 외) — 추가 grep 검색 필요

### TP 알림 정보 보강 (2026-04-30 늦은 저녁 추가)
- 알림에 **청산 단가 + 청산 수량 + 남은 수량 + 손익 금액 + 수익률** 모두 표시
- 실제 청산 체결가 (close order avg_price) 기반 — mark_price 보다 정확
- 파일: `tp_sl_orchestrator.py` `_execute_take_profit`, `notification_service.py` `send_take_profit_alert`

### 사무실에서 실행할 진단 명령
```powershell
cd backend
# 알림 발송 호출 위치 추가 검색
docker compose exec user-stream grep -rn "send_stage_entered_alert" /app/app/ 2>$null
# → stream_service.py:44 외에 다른 곳에서도 호출되는지 확인.
```

---

## 5. 다음 우선순위 작업 (사용자 선택)

### A. 🔴 testnet stages 2~5 + TP1~4 풀 사이클 검증
- #57 stage 3 (trigger 0.01882) 까지 진입 후 회복 시 TP1 (+10%) 발동 확인
- TP1 25% 청산 → TP2 50% (남은 50%중 25%) → TP3 (남은 50% 의 50%) → TP4 (남은 25% 전량)
- 텔레그램 알림에 손익금액 + 수익률 자동 표시

### B. 🟡 옛 폴더 정리
컴퓨터 재부팅 후:
```powershell
Remove-Item -Path C:\Users\user\바이낸스\binance_auto_trader_project -Recurse -Force
```
(어제 lock 걸려있던 옛 프로젝트 폴더, 새 `binance-auto-trader\` 와 무관)

### C. 🟡 ngrok URL 동기화 (사무실 PC 가 사용하므로 자동 해결)
사무실 PC 가 이번 commits 를 pull 하고 컨테이너 재시작하면 ngrok 도 자동으로 새 layout 보임.

### D. 🟢 메인넷 전환 준비
testnet 풀 사이클 검증 완료 후:
- mainnet API 키 발급
- exchange_account 신규 row
- VPS 마이그레이션 (24/7 운영)
- 작은 금액 (5~10 USDT) 첫 거래

### E. 🟢 Sentry DSN 입력 (옵션 다 — pending)
mainnet 전환 직전 권장.

---

## 6. 트러블슈팅 (오늘 발견한 패턴)

### "no configuration file provided: not found"
→ 현재 폴더가 `binance-auto-trader\` 루트. `cd backend` 후 docker 명령.

### PowerShell 페이스트 사고 (명령 두 번 붙음)
→ 한 줄씩 따로 실행. 중간에 PowerShell 프롬프트 (`PS C:\... >`) 가 들어가지 않게 주의.

### 차트 라벨 timeframe 마다 다르게 보임
→ `Ctrl+Shift+R` 로 강력 새로고침. 캐시 헤더가 적용되었으니 이후엔 자동 갱신됨.

### ngrok URL 이 새 코드 안 보임
→ 다른 컴퓨터의 ngrok agent 가 같은 URL 점유 중. 사무실 ngrok 종료 또는 사무실 PC 도 git pull 해야 함.

### Stage 자동 진입 안 됨 (해결됨)
→ stage_trigger_worker 가 10초마다 감시. scheduler 가 안 돌면 진입 안 됨. `docker compose ps scheduler` 확인.

---

## 7. 파일 위치 빠른 참조

| 항목 | 경로 |
|------|------|
| 프로젝트 루트 | `C:\Users\user\바이낸스\binance-auto-trader\` |
| Stage 트리거 worker (NEW) | `backend\app\workers\stage_trigger_worker.py` |
| TP/SL 로직 | `backend\app\services\risk_service.py`, `backend\app\services\tp_sl_orchestrator.py` |
| 중복 검증 | `backend\app\services\strategy_service.py` |
| Scheduler 등록 | `backend\app\workers\scheduler_runner.py` |
| 대시보드 UI | `backend\app\static\index.html` |
| 알림 메시지 | `backend\app\services\notification_service.py` |
| Neon DB URL | `backend\.env` (DATABASE_URL) |
| 어제 인계서 | `HANDOFF-2026-04-29-OFFICE-TO-HOME-EVENING.md` |
| 이 인계서 | `HANDOFF-2026-04-30-HOME-EVENING.md` |

---

## 8. Cowork (Claude) 에게 보내는 메모

이 사용자는 회사↔집 양쪽에서 작업하는 1인 개발자, 한국어, 존댓말 선호.

**오늘 (2026-04-30) 작업 요약**:
- Critical bug fix (stage 2~N 자동 진입) 적용 → 마틴게일 정상 동작 시작
- TP/SL 룰 사용자 기획대로 4단계 (10/15/20/30% + qty 25/25/50/100), SL 모든 단계 후
- 크라이시스 모드 -30% 회복 시 4단계 TP (5/10/15/20%)
- 중복 전략 정리 + 재발 방지 검증
- 차트 평단/마크/청산 + RSI/MACD/OBV time-axis 양방향 sync
- Binance 스타일 테이블 (진입가/마크/청산 3줄 stack)

**작업 우선순위 (시점에 따라)**:
1. **활성 전략 모니터링**: BTC 변동성 타고 stage 2~5 자동 진입 + TP 발동 라이브 검증
2. **메인넷 전환**: testnet 풀 사이클 검증 완료 후 (옵션 ④)
3. **VPS 마이그레이션**: 메인넷 전환 시 동시 추진

**사용자 행동 패턴**:
- 한 줄씩 명령 받는 것 선호 (페이스트 사고 회피)
- 차트/UI 시각적 피드백 중요시
- 실시간 모니터링 + 텔레그램 알림으로 동작 확인

---

작성: 집 컴퓨터, 2026-04-30 저녁
