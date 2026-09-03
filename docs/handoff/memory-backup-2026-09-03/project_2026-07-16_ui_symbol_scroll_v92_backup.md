---
name: project-2026-07-16-ui-symbol-scroll-v95-backup
description: 2026-07-16 최종 백업 = UI fix 12개 (v83~v95) + backend fix + v95 = 진짜 root cause fix (v117 overflow:hidden 완전 제거!). tag=v-2026-07-16-v95-root-cause-fix
metadata:
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
---

# 2026-07-16 최종 백업 = v95 진짜 root cause 발견!

## 🌟 오늘 최종 = 사장님 UI critical fix 12개 + backend fix 1개!

### UI 모바일/템플릿 fix (v83~v95):
- **v83**: 모바일 심볼 선택 = readonly 강제 keyboard 닫기
- **v84**: 저장된 전략 클릭 = 값 직접 반영 (endpoint 없음 우회)
- **v85**: 저장된 전략 hot-fix = 전체 조회 후 filter (GET /{id} X)
- **v86**: 저장된 전략 = 「직접 입력」 tab 자동 (radio 대신 값 표시)
- **v87**: **critical 영구 fix** = _quick_* 정리 = 옵션 3 (force) 영구 제거! (사장님 12건 강제 청산 사건 재발 방지!)
- **v88**: 심볼 재선택 가능 (readonly 제거 + activeElement blur)
- **v89**: 미체결 아이콘 항상 표시 (canTriggerNext 조건 제거) — AKEUSDT #467 3/3 이지만 6 pending LIMIT 있음!
- **v90**: 심볼 선택 = 자동 위로 스크롤 (modal.scrollTop = 0)
- **v91**: scrollIntoView 접근 (iOS Safari scrollTop 무시 대응)
- **v92**: 「⬆ 심볼로」 fixed 버튼 (viewport 우하단 파란 원형, 백업 유지!)
- **v93**: 완전 전체 화면 (사장님 원하지 않음 → v94 revert!)
- **v94 critical fix ⭐**: 심볼 한 글자 silent bug fix (내가 v92에서 추가한 oninput 제거!) + v93 revert!
- **v95 진짜 root cause fix ⭐**: v117 「overflow: hidden」 완전 제거! (심볼 스크롤 근본 원인!)

### Backend critical fix:
- **decrypt_text import 오타 수정**: `app.core.security` → `app.core.crypto` (LABUSDT 개별 취소 502 원인!)

## 🚨 v94 = 내가 만든 silent bug 자백:
- v92에서 `oninput="_cmSymbolFullBlur"` 추가
- = 매 키 입력마다 blur() = keyboard 닫힘 = 한 글자만 입력!
- 사장님 = "심볼을 입력하면 한글자만 입력되는 문제" = 발견!
- v94 fix = oninput 즉시 제거!

## 🚨 v95 = 진짜 root cause 발견!

### 「모바일 UI v2」 (v117, 2026-06-20) = overflow: hidden 규칙!
```css
@media (max-width: 767px) {
  #create-modal > div {
    max-height: 100vh !important;
    height: 100vh !important;
    overflow: hidden !important;  ← 진짜 원인!
    display: flex !important;
    flex-direction: column !important;
  }
}
```

### 영향:
- 사장님 스크롤 완전 차단!
- 심볼 sticky top도 무효 (부모 = overflow hidden!)
- 데스크탑 요소들 (레버리지/전략구성/저장된 전략/수량 table) = 심볼 아래 = 안 보임!

### v83~v92 (10번 fix) = 모두 이 옛 CSS 우회 시도!
v95 = 옛 CSS 완전 제거 = 근본 해결!

## 🚨 사장님 12건 강제 청산 사건 (v87 원인):
- 사장님 = 「_quick_ 정리」 옵션 3 (force) 선택 = 활성 strategy 12건 emergency_close!
- 사장님 명시: "이 메뉴는 현재 진행중인 전략에 영향을 주지 않고 임시 저장과 종료된 전략을 삭제하는 메뉴가 되어야 해!"
- fix: 2중 방어 = frontend (옵션 3 제거 + toast) + backend (400 error)

## 📌 미배포 PR (사장님 = 머지 필수!)
- 브랜치: `fix/pin-fastapi-prometheus-incompat-2026-06-24`
- 최신 commit: `0f7aa9b v95 진짜 root cause fix`
- v84~v95 = 모두 누적!
- URL: https://github.com/herosys1-crypto/binance-auto-trader/compare/main...fix/pin-fastapi-prometheus-incompat-2026-06-24

## 🏷 Git Tags:
- **`v-2026-07-16-v95-root-cause-fix`** (최종 백업 - v95!)
- `v-2026-07-16-symbol-scroll-v92` (중간 백업 - v92)
- `v-2026-07-01-end-of-day` (이전 - 헌법 51)

## 다음 세션 우선순위:
1. **PR 머지** (GitHub web UI)
2. **VPS 배포**: `ssh root@159.65.137.250` → `cd ~/binance-auto-trader/backend` → `git pull` → `docker compose restart api`
3. **사장님 모바일 검증**:
   - ✅ 심볼 정상 타이핑 (한 글자 X)!
   - ✅ 데스크탑 요소 모두 표시 (레버리지/전략구성/저장된 전략/수량 table)!
   - ✅ 스크롤 정상!
4. v95 성공 시 = 헌법 46 추가 후보: **"모달 CSS = overflow: hidden 금지! (= 사장님 스크롤 근본 차단!)"**

## 관련 메모리:
- [[project-2026-06-22-mobile-scroll-lessons]] — 옛 모바일 스크롤 6번 fix 메타 학습 (헌법 42~45)
- [[project-2026-07-01-constitution51-add-position-mode]] — 헌법 51 (「💉 포지션 추가」 2 모드)
- [[reference-vps]] — VPS 배포 경로/서비스명
