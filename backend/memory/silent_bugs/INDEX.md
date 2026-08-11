# 🐛 Silent Bugs = fix 기록 (25+!)

**발견된 silent bug + fix + 재발 방지!**

---

## 🚨 v131~v132 신 (최신!)

| # | 심볼/사고 | 원인 | Fix commit |
|---|-----------|-----|-----------|
| SB023 | #838 BMTUSDT TP4 초과 청산 | TP1_override = 모든 TP 상향 | 3497d25 |
| SB024 | #836 CYSUSDT false positive | title 검색 잘못 | 5ab2600 |
| SB025 | #828 TSTUSDT retry 병렬 진입 | retry ON + 옛 stage_trigger 병행 | 4bb9054 |
| SB026 | 레버리지 5x stuck | fix branch만 push (main X!) | 3e319d8 |
| SB027 | 강제 SL "on:30" 오류 | JS 검증 = 4개 값만 | 909563b |

---

## 🚨 v127 대감사 (17건!)

| # | 사고 | 원인 |
|---|------|-----|
| SB018 | #505 DEXEUSDT TP10 조기 청산 | qty 계산 잘못 |
| SB019 | mark_price 소스 불일치 | Redis vs DB snapshot |
| SB020 | leverage 불완전 | 신규 진입 시 미설정 |
| SB021 | Redis peak 리셋 | 청산 후 안 지움 |
| SB022 | 좀비 방지 | STOPPING race |

---

## 🚨 v106 이전 (핵심!)

| # | 사고 | 참조 |
|---|------|-----|
| SB001 | BEATUSDT #110 SL critical | [project_2026-06-13](../../..) |
| SB002 | 모바일 스크롤 6번 | v1~v6 = 같은 root cause! |
| SB003 | 자동 2단계 mark_price silent | fix v51 |
| SB004 | fastapi drift 500 사고 | fix pin |
| SB005~017 | 기타 v43~v127 | 프로젝트 memory 참조 |

---

## 🎯 Silent Bug 원칙 (헌법 C03!)

1. **모든 차단 = 사장님 인지!**
2. **Redis 기록 + 화면 표시 + Telegram!**
3. **1시간 dedup (spam 방지!)**
4. **원인 분석 → memory에 저장!**
5. **재발 방지 로직 추가!**
