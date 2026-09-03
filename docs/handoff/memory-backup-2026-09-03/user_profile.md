---
name: 사용자 프로필
description: 사용자 역할/언어/협업 방식 + 검증된 워크플로우 패턴
type: user
originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
---
- **이름**: 이규수 (git author)
- **역할**: Binance Futures 자동매매 1인 개발자 + 운영자 (실전 자본 투입 직전)
- **언어**: 한국어. 코드/문서/commit/PR 모두 한국어 위주
- **개발 환경**: Windows 11, bash + PowerShell. 사무실 PC ↔ 집 PC 동기화 (HANDOFF-* + sync 배치)
- **운영 인프라**: Docker Compose (Windows Docker Desktop) — api/scheduler/user-stream/db/redis/grafana 구성
- **GitHub workflow**: PR 생성/머지는 **GitHub 웹 UI** 만 사용 (`gh` CLI 없음). 어시스턴트가 push 후 compare URL 만 제공, 사용자가 웹에서 PR 만들고 「Squash and merge」 → 「Delete branch」
- **작업 스타일**:
  - mainnet 직전이라 안정성/감사가능성/회귀 방지 매우 중시
  - 핸드오프 문서를 세션마다 업데이트
  - 「추천으로 진행해줘」 패턴 — 어시스턴트가 우선순위 옵션 제시 후 1번 추천 항목으로 자동 진행. 매 단계 재확인 X
  - PR 단위로 작은 커밋 묶음 선호 — 7 커밋이 누적되면 한 PR 로 묶어 머지 (squash)
- **선호**:
  - 정밀 spec 우선, audit 결과 정량화
  - commit 메시지 상세 (배경/원인/조치/테스트 결과)
  - 파괴적 작업 (머지/푸시/재시작) 은 사용자 명시 승인 후 실행 — `docker compose restart` 도 「응」 답변 받고 실행
  - 코드 변경 후 pytest 회귀 + 새 기능엔 통합 테스트 (간혹 단위 테스트도) 같이 작성
