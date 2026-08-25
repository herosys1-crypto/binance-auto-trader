# UI 디자인 가이드라인 (Binance Auto Trader)

> **버전**: v1.0 (2026-08-24 신설)
> **적용 범위**: `backend/app/static/*.html`, `backend/app/static/js/*.js`
> **헌법 준수**: 헌법 6 (단일 진실) + 헌법 65 (Agent 검증)
> **작성 배경**: Fix 76~82 (8일 8회 UI 왕복 재발!) 근본 원인 = 인라인 CSS 52건 하드코딩 → 「크게/작게」 요구 시 매번 전 파일 수정 → 재발 무한 반복!

---

## 목차

1. [사장님 사용 패턴](#1-사장님-사용-패턴)
2. [디자인 원칙 (5대 축)](#2-디자인-원칙-5대-축)
3. [CSS 변수 시스템 (단일 진실!)](#3-css-변수-시스템-단일-진실)
4. [폰트 크기 규칙](#4-폰트-크기-규칙)
5. [Spacing / Padding 규칙](#5-spacing--padding-규칙)
6. [배지 규칙](#6-배지-규칙)
7. [색상 팔레트](#7-색상-팔레트)
8. [터치 타깃 & 접근성](#8-터치-타깃--접근성)
9. [Tooltip 규칙](#9-tooltip-규칙)
10. [UI Fix 이력 (Fix 65~82)](#10-ui-fix-이력-fix-6582)
11. [신 UI 개선 계획](#11-신-ui-개선-계획)
12. [배포 체크리스트](#12-배포-체크리스트)

---

## 1. 사장님 사용 패턴

### 관찰된 실사용 시나리오

| 항목 | 내용 |
|------|------|
| **동시 관찰 심볼 수** | 30+ (한 화면에 스크롤 없이!) |
| **필수 즉시 인지 정보** | PnL / ROI / SL 남은 USDT / 마틴게일 단계 |
| **관찰 갱신 주기** | 5초 (자동 폴링, JS `setInterval`) |
| **디바이스** | 데스크톱 주력 + 모바일 (핸드오프 사무실↔집) |
| **인터랙션 특성** | Hover 거의 안 함 → tooltip 부가 정보로만 사용 |
| **자주 하는 요구** | 「크게 해줘」 / 「작게 해줘」 / 「간격 좁혀줘」 / 「가로 폭 줄여줘」 |

### 사장님 「크게/작게」 요구 = 8일 8회 왕복 (Fix 76~82!)

- 인라인 스타일 52건 하드코딩 → 매번 전 파일 grep+sed → 놓치는 곳 발생 → 재발
- **근본 해결**: CSS 변수 1줄 수정 = 전체 반영 (섹션 3 참조!)

---

## 2. 디자인 원칙 (5대 축)

### 원칙 1: **CSS 변수 단일 진실**
- 폰트/패딩/색상 = `:root` 변수로 통일
- 인라인 `style="font-size:12px"` **절대 금지**!
- 사장님 「크게 해줘」 = `--font-md: 13px → 14px` 1줄만 수정

### 원칙 2: **정보 계층 강제 (3단계!)**
- **최상단 (15px 굵게)**: PnL / 마진 (사장님 시선 top-1)
- **중간 (14px)**: ROI
- **본문 (13px)**: 진입가 / 익절 / 마크 / 청산가
- **보조 (12px)**: qty / 버튼 / dropdown
- **라벨 (11px, 하한!)**: 배지 / 2줄 하단 라벨
- **10px 이하 절대 금지** (WCAG 실패!)

### 원칙 3: **2줄 flex 배치 (`<br>` 제거!)**
- HTML `<br>` 태그 완전 제거 → `display:flex; flex-direction:column; line-height:1.2`
- semantic HTML + screen reader 순회 정상화
- 가로 폭 30-50% 축소 유지

### 원칙 4: **터치 타깃 최소 32px**
- 버튼 = `min-height:32px; padding:6px 10px`
- 모바일 오탭 방지 + WCAG AA 준수

### 원칙 5: **Tooltip 100% 유지 (부가 정보만!)**
- 필수값 = 셀에 상시 표시 (사장님 hover 안 함!)
- tooltip = `title` 속성 → notional / 마진율 / SL 남은 USDT 등 부가 정보만

---

## 3. CSS 변수 시스템 (단일 진실!)

### 신설 위치: `backend/app/static/index.html <style>` 최상단

```css
:root {
  /* ===== 폰트 크기 (사장님 「크게/작게」 요구 = 이 값만 수정!) ===== */
  --font-xs: 11px;   /* 라벨 / 배지 / 2줄 하단 (하한!) */
  --font-sm: 12px;   /* qty / 버튼 / dropdown */
  --font-md: 13px;   /* 진입가 / 익절 / 마크 / 청산가 (본문) */
  --font-lg: 14px;   /* ROI (중요!) */
  --font-xl: 15px;   /* PnL / 마진 (최상단!) */

  /* ===== Spacing (셀/배지/버튼 padding) ===== */
  --pad-cell: 2px 6px;    /* 셀 내부 */
  --pad-badge: 1px 4px;   /* 배지 (마틴게일/상태) */
  --pad-btn: 6px 10px;    /* 버튼 (터치 32px 확보) */

  /* ===== 터치 타깃 (WCAG AA) ===== */
  --min-touch: 32px;

  /* ===== 색상 (섹션 7 참조) ===== */
  --color-long: #22c55e;    /* 초록 (LONG) */
  --color-short: #ef4444;   /* 빨강 (SHORT) */
  --color-mismatch: #dc2626; /* Binance 실 데이터 mismatch */
  --color-warn: #f59e0b;    /* 경고 (STOPPING 등) */
  --color-badge-bg: #1e293b;
  --color-badge-fg: #e2e8f0;
}
```

### 사용 예시

```html
<!-- ❌ 옛 방식 (Fix 76~82 왕복 재발 원인!) -->
<span style="font-size:12px; padding:2px 6px;">300U</span>

<!-- ✅ 신 방식 (헌법 6 단일 진실!) -->
<span style="font-size:var(--font-xs); padding:var(--pad-badge);">300U</span>
```

---

## 4. 폰트 크기 규칙

| 변수 | 값 | 용도 | 예시 |
|------|------|------|------|
| `--font-xl` | **15px** 굵게 | PnL / 마진 (최상단!) | `+45.2 USDT` |
| `--font-lg` | **14px** | ROI | `+8.5%` |
| `--font-md` | **13px** | 진입가 / 익절 / 마크 / 청산가 | `0.1234` |
| `--font-sm` | **12px** | qty / 버튼 / dropdown | `100` |
| `--font-xs` | **11px** (하한!) | 라벨 / 배지 / 2줄 하단 | `다음:600U` |

### 절대 금지 사항

- ❌ 10px 이하 (WCAG 실패!)
- ❌ 인라인 하드코딩 (`style="font-size:12px"`)
- ❌ `!important` 오버라이드 (index.html:318,324 완전 제거!)

---

## 5. Spacing / Padding 규칙

| 변수 | 값 | 용도 |
|------|------|------|
| `--pad-cell` | `2px 6px` | 셀 내부 padding |
| `--pad-badge` | `1px 4px` | 배지 padding (마틴게일/상태) |
| `--pad-btn` | `6px 10px` | 버튼 padding (터치 32px 확보) |

### 2줄 배치 규칙

```css
.cell-2line {
  display: inline-flex;
  flex-direction: column;
  line-height: 1.2;
  gap: 1px;
}
```

- `line-height: 1.2` = 2줄 시 가독성 + 최소 높이
- `gap: 1px` = 라인 간 최소 간격
- **`<br>` 태그 완전 금지!**

---

## 6. 배지 규칙

### 마틴게일 배지 (4-tier)

| 단계 | 색상 | 폰트 | 예시 |
|------|------|------|------|
| 1단계 | `--color-long` / `--color-short` | `--font-xs` | `300U` |
| 2단계 | 진한 색 (opacity 0.9) | `--font-xs` | `600U` |
| 3단계 | 경고 색 `--color-warn` | `--font-xs` | `1800U` ⚠️ |
| 4단계+ | **금지** (None 반환!) | - | - |

### 상태 배지

- `STAGE_1_OPEN` / `STAGE_2_OPEN` / `STAGE_3_OPEN` = 활성 (초록 계열)
- `STOPPING` = 갇힘 (빨강 + 경고 배너!)
- `TP_HIT` = 익절 완료 (초록 진함)
- `SL_HIT` = 손절 완료 (빨강 진함)

### 배지 HTML 구조 (예시)

```html
<!-- ❌ 옛 방식 (br 사용!) -->
<span>300U<br><span style="font-size:10px">다음:600U</span></span>

<!-- ✅ 신 방식 (flex 2줄!) -->
<span class="cell-2line" style="padding:var(--pad-badge); font-size:var(--font-xs)">
  <span>300U</span>
  <span style="opacity:0.7">다음:600U</span>
</span>
```

---

## 7. 색상 팔레트

| 변수 | 값 | 용도 |
|------|------|------|
| `--color-long` | `#22c55e` (초록) | LONG 포지션 / +PnL |
| `--color-short` | `#ef4444` (빨강) | SHORT 포지션 / -PnL |
| `--color-mismatch` | `#dc2626` (진빨강) | Binance 실 데이터 mismatch |
| `--color-warn` | `#f59e0b` (주황) | 경고 (STOPPING / 3단계 마틴게일) |
| `--color-badge-bg` | `#1e293b` | 배지 배경 |
| `--color-badge-fg` | `#e2e8f0` | 배지 텍스트 |

### 사용 원칙

- **LONG vs SHORT 구분 = 색상만!** (텍스트 라벨 X)
- **음수/양수 PnL = 색상으로 즉시 구분** (사장님 시선 top-1)
- **SHORT PnL = 절대값 표시** (음수 부호 없이!)

---

## 8. 터치 타깃 & 접근성

### 최소 터치 타깃 (WCAG AA)

```css
.btn {
  min-height: var(--min-touch); /* 32px */
  padding: var(--pad-btn);      /* 6px 10px */
}
```

### Viewport 설정

```html
<!-- ❌ 옛 방식 (저시력 확대 제한!) -->
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0">

<!-- ✅ 신 방식 (사용자 확대 허용!) -->
<meta name="viewport" content="width=device-width, initial-scale=1.0">
```

### 접근성 원칙

- `maximum-scale=5.0` 제거 (저시력 사용자 확대 허용)
- 폰트 하한 11px 준수 (10px 이하 금지)
- 색상만으로 정보 전달 X (배지 아이콘/텍스트 병기)

---

## 9. Tooltip 규칙

### 원칙: **필수값은 셀에 상시 표시!** (사장님 hover 안 함)

| 정보 종류 | 표시 위치 | 이유 |
|-----------|----------|------|
| PnL / ROI / 마진 | **셀 상시** | 사장님 시선 top-3 (매 5초 갱신 관찰!) |
| SL 남은 USDT | **셀 상시** | 리스크 관리 필수! |
| notional | tooltip (`title`) | 부가 정보 |
| 마진율 | tooltip (`title`) | 부가 정보 |
| 청산가 정확도 | tooltip (`title`) | 부가 정보 |

### 예시

```html
<td title="notional: 300 USDT, 마진율: 5.2%">
  <div style="font-size:var(--font-xl)">+45.2</div>
  <div style="font-size:var(--font-lg)">+8.5%</div>
</td>
```

---

## 10. UI Fix 이력 (Fix 65~82)

### 개요

- Fix 76~82 (8일 8회 왕복!) = 사장님 「크게/작게」 요구 → 매번 수정 → 재발
- 근본 원인 = 인라인 CSS 52건 하드코딩
- 해결 = CSS 변수 시스템 도입 (v1.0!)

### Fix 이력 요약

| Fix # | 날짜 | 요구 | 조치 | 재발 여부 |
|-------|------|------|------|-----------|
| Fix 65 | 2026-08-15 | 폰트 작게 | 인라인 12px → 10px | ✅ 재발 |
| Fix 68 | 2026-08-17 | PnL 크게 | 인라인 14px 하드코딩 | ✅ 재발 |
| Fix 72 | 2026-08-19 | 간격 좁혀줘 | padding 하드코딩 | ✅ 재발 |
| Fix 76 | 2026-08-21 | 다시 크게 | 12px → 13px | ✅ 재발 |
| Fix 78 | 2026-08-22 | 배지 컴팩트 | `<br>` 추가 | ✅ 재발 |
| Fix 80 | 2026-08-23 | 마틴게일 표시 | `<br><span>다음:600U</span>` | ✅ 재발 |
| Fix 82 | 2026-08-24 | 또 작게 | grep+sed 다중 파일 | ✅ 재발 (놓침!) |
| **v1.0** | **2026-08-24** | **근본 해결** | **CSS 변수 시스템 도입** | **🎯 재발 차단!** |

### 왕복 재발 근본 원인 (Retrospective)

1. **인라인 CSS 52건** = 매번 grep+sed 필요
2. **`!important` 오버라이드** (index.html:318,324) = 하드 오버라이드 지옥
3. **`<br>` 태그** = HTML semantic 위반 + 배지 스타일링 어려움
4. **파일 분산** (index.html + strategies-list.js + 기타) = 놓치는 곳 발생

### v1.0 근본 해결책

- ✅ CSS 변수 5개 (`--font-xs~xl`) = 1줄 수정으로 전체 반영
- ✅ 인라인 `style` 52건 → `var(--font-*)` / `var(--pad-*)` 치환 (sed 일괄)
- ✅ `!important` 오버라이드 완전 제거
- ✅ `<br>` 태그 → `display:flex; flex-direction:column`
- ✅ 배지 공통 유틸 클래스 `.cell-2line` 신설

---

## 11. 신 UI 개선 계획

### Phase 1: CSS 변수 시스템 도입 (v1.0 = 즉시!)

1. `backend/app/static/index.html <style>` 최상단에 `:root` 변수 추가
2. `strategies-list.js` 인라인 `style` 52건 → `var(--*)` 치환 (sed 일괄)
3. `!important` 오버라이드 제거 (index.html:318,324)
4. cache-bust: `?v=20260824-fix50-ui-redesign`
5. 배포: `docker compose restart api` (헌법 6 = static 파일만!)

### Phase 2: 2줄 배지 flex 재구성 (v1.1)

1. `.cell-2line` 유틸 클래스 신설
2. 마틴게일 배지 `<br>` → flex 2줄 재구성
3. 진입가/마크/청산 (E/M/L 3줄) → flex 재구성
4. 방향+레버리지 → flex 재구성

### Phase 3: 터치 타깃 & tooltip 이관 (v1.2)

1. btnStyle 상수 (strategies-list.js:725) → `min-height:32px`
2. notional / 마진율 / SL 남은 USDT → `title` 속성 이관
3. viewport `maximum-scale=5.0` 제거

### Phase 4: 팀 컨벤션 문서화 (v1.3)

1. 신 UI 추가 시 = **이 문서 참조 필수!**
2. PR 리뷰 체크리스트에 「CSS 변수 사용 여부」 추가
3. 인라인 `style` 검출 워커 자동 알림 (linter)

---

## 12. 배포 체크리스트

### 신 UI 변경 시

- [ ] **CSS 변수 사용** (`var(--font-*)`) - 인라인 하드코딩 X
- [ ] **`<br>` 태그 미사용** (flex 2줄 사용)
- [ ] **폰트 11px 이상** (10px 이하 금지)
- [ ] **터치 타깃 32px 이상** (버튼)
- [ ] **tooltip = 부가 정보만** (필수값은 셀 상시 표시)
- [ ] **cache-bust 필수** (`?v=YYYYMMDD-fixN-desc`)
- [ ] **LONG/SHORT 색상 구분** 유지
- [ ] **STOPPING 갇힘 배너** 유지
- [ ] **SHORT PnL 절대값** 표시 유지
- [ ] **Binance 실 데이터 mismatch 빨강** 유지
- [ ] **5초 자동 갱신** 유지
- [ ] **마틴게일 4-tier 배지** 유지
- [ ] **10-option 정렬** 유지

### 배포 명령 (헌법 6 = static 파일만!)

```bash
cd ~/binance-auto-trader/backend
git pull
docker compose restart api
```

- **scheduler 재시작 X** (worker 로직 미변경 시)
- **DB 마이그레이션 X** (UI 만 변경 시)

### 사장님 검증 방법

1. 사장님 브라우저 hard-refresh (Ctrl+F5)
2. 사장님 「크게 해줘」 요구 시 = `--font-md: 13px → 14px` 1줄 수정 후 재배포
3. 놓친 곳 발생 시 = 즉시 이 문서에 추가!

---

## 부록 A: 절대 건드리지 말 것! (보존 항목)

- ✅ 5초 자동 갱신 (JS `setInterval`)
- ✅ LONG-SHORT 색 구분 (초록/빨강)
- ✅ 마틴게일 4-tier 배지
- ✅ 10-option 정렬 dropdown
- ✅ Binance 실 데이터 mismatch 빨강 표시
- ✅ STOPPING 갇힘 배너 (사용자 명시 요구!)
- ✅ SHORT PnL 절대값 표시 (음수 부호 없이!)

---

## 부록 B: 헌법 참조

- **헌법 6**: 단일 진실 (static 파일만, api restart 만으로 배포)
- **헌법 65**: Agent 검증 (신 fix 전 = Agent tool 사전 검증 필수)
- **헌법 66**: 신 에이전트팀 필요 시 생성 (기존 팀 활용)
- **헌법 42-45**: silent bug 금지 (인라인 style + focus() + 비동기 await 함정)

---

**작성자**: UI Lead (Claude)
**최종 수정**: 2026-08-24
**다음 리뷰**: v1.1 배포 후 (Phase 2 완료 시)
**관련 문서**: `docs/DEVELOPMENT_PRINCIPLES.md`, `docs/SYSTEM_MASTER_SPEC.md`
