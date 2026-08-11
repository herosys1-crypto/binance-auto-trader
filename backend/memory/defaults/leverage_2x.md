# 신 default: 레버리지 2x

## 값
**2x** (모든 사이드! LONG/SHORT!)

## 히스토리
| 날짜 | 값 | 이유 |
|------|-----|------|
| 2026-08-08 | 2x | 사장님 요구 (원 default!) |
| 2026-08-09 | 5x | 사장님 재요구! |
| 2026-08-11 | **2x** | 사장님 재재요구 (v132 최종!) |

## 적용 파일
- `backend/app/static/index.html` line 1628: value="2"
- `backend/app/static/js/cm-open-modal.js` line 80, 185: value = 2
- `backend/app/static/js/cm-collectors.js` line 115: return 2

## 사장님 override
- 「↺ 기본값」 = 2x 복원!
- 직접 입력 = 1~125 자유!

## 관련
- C12 (레버리지 자율)
- SB026 (레버리지 5x stuck!)
