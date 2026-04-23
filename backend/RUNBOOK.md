# Binance Futures Auto Trading Platform Runbook

## 기본 기동
1. `.env` 생성
2. `docker compose up -d db redis`
3. `make upgrade`
4. `make seed-templates`
5. `make run`
6. `make scheduler`
7. 별도 터미널에서 `make user-stream`

## 긴급 정지
1. 전략 정지 API 호출
2. 미체결 주문 취소
3. 필요 시 시장가 전량 종료
4. 전략 상태 `REENTRY_READY` 또는 `CLOSED` 전환
5. Telegram 경고 발송
