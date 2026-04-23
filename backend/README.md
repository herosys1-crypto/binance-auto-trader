# Binance Futures Auto Trading Platform

자동매매 운영 플랫폼 골격입니다.

## 포함 범위
- 전략 계산 / 전략 생성 / 전략 조회 API
- Binance Futures 주문 어댑터(plain + algo adapter 골격)
- Redis 락 / idempotency middleware / kill-switch / daily loss limiter
- Binance user stream consumer / keepalive / reconcile / scheduler
- Prometheus metrics / Grafana / Sentry / Nginx / CI / runbook
- Alembic 마이그레이션 / seed SQL / pytest 골격

## 빠른 시작
1. `.env` 생성 (`.env.example` 복사)
2. `docker compose up -d db redis`
3. `make upgrade`
4. `make seed-templates`
5. `make run`
6. `make scheduler`
7. 별도 터미널에서 `make user-stream`
