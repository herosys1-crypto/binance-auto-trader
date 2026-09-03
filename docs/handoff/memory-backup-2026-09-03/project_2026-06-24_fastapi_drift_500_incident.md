---
name: project-2026-06-24-fastapi-drift-500-incident
description: 전 대시보드 500 사고 = fastapi 핀 없음 → _IncludedRouter ↔ prometheus 7.1.0 비호환. 핀 고정으로 fix
metadata: 
  node_type: memory
  type: project
  originSessionId: 3a7c8fc6-6afa-4af2-8926-abe6b890367e
---

🚨 2026-06-24 mainnet 사고: force-sl 배포 후 **전 API 500** ("전략 조회 실패: 500: Internal Server Error", 대시보드 전체 다운).

**진짜 원인 (DB/마이그레이션 아님!)**: `backend/requirements.txt` 의 `fastapi` 가 핀 없음 → 재빌드 시 신버전 드리프트. 신 FastAPI 는 `include_router` 시 `app.routes` 에 `.path` 없는 `fastapi.routing._IncludedRouter` (API 라우트들을 중첩 보관) 추가. `prometheus-fastapi-instrumentator` 7.1.0 (`<8` 핀) 이 `routing.py:55 route.path` 접근 → `AttributeError` → 매 요청 500.
- 진단 핵심: `top routes: 10` (= 라우트가 _IncludedRouter 안에 중첩 = 제거하면 전 엔드포인트 사라짐 → 제거 금지!).
- 로컬 fastapi 0.135.3 = `_IncludedRouter` 없음 (정상). 프로덕션만 드리프트.

**거래 영향 0**: scheduler(자동 진입/TP/SL) 는 별도 컨테이너 = prometheus 미들웨어 안 거침. 화면(API)만 다운.

**즉시 복구**: `.env` 에 `ENABLE_METRICS=false` + `docker compose restart api` (= Instrumentator 비활성 = 크래시 제거, Grafana만 잠시 손실).

**근본 fix (PR, 브랜치 `fix/pin-fastapi-prometheus-incompat-2026-06-24`, 커밋 `9e74478`)**: `fastapi==0.135.3` + `starlette==0.52.1` 핀 고정 (= 코드/단위테스트 385 검증된 조합). requirements 변경 = pip 레이어 캐시 자동 무효 → `--build` 만으로 재설치. 배포 후 `ENABLE_METRICS=true` 복구.

**교훈 (영구)**: **mainnet 배포 의존성은 핀 고정 필수.** 핀 없는 패키지 = 재빌드 때 silent 드리프트 = 운영 사고. fastapi/starlette 외 다른 핵심 deps 도 핀 검토 필요 (후속). 마이그레이션은 정상이었는데 컬럼 에러로 오인하기 쉬움 → **실제 traceback 확인이 진단의 핵심** (`docker compose logs api --tail`).

**진단 절차 (재사용)**: alembic current/heads → 컬럼 존재 SQL 확인 → `docker compose logs api --tail=40` 실제 traceback → `app.routes` 중 `.path` 없는 객체 walk. 관련: [[project_2026-06-24_force_sl_loss_limit_spec]].
