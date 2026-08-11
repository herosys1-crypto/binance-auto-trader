# C03. Silent bug 금지!

## 원칙
모든 차단/실패 = 사장님 즉시 인지!

## 사장님 사고
- Silent = 사장님이 모름!
- 진입 안 됨 = 이유 없이? = 사장님 답답!
- = 이유 명확 + 즉시 알림!

## 에이전트 적용
- 진입 차단 = Redis 기록 + 화면 표시 + Telegram!
- 알림 spam = dedup (1시간!)
- silent 시도 자체 = 금지!

## 알림 채널
- Telegram (즉시!)
- 대시보드 (실시간!)
- Redis (진단 endpoint!)

## 관련 fix
- v18 (자동 진입 silent 차단 영구!)
- v51 (mark_price 소스 불일치)
- v130 (SL 다음 단계 남으면 X = silent 아니라 = 사장님 사상!)

## 관련
- C01 (메인넷)
- C05 (대칭성)
