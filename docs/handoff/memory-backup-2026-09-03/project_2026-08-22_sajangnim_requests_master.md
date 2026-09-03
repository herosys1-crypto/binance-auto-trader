# 2026-08-22 사장님 요구 마스터 리스트 (Fix 1~25 + α)

## 목적
사장님 verbatim 각 요구 = 여기 영구 저장!
"완료" 마킹 = **사장님 실 UI 확인 후만!**
헌법 69/70/71 준수!

## Fix 1~25 요구 상태 (2026-08-23 재분류!)

### ✅ 실 검증 완료
- **Fix 1~19 (v218 9 Fix)**: PR #363 머지 + tag `v-2026-08-22-v218-9fixes-deployed`
  - STAGE_N_OPEN 오타 (사장님 지적!) → 활성 5건 100% 오분류 → ACTIVE_LIKE 재사용
  - daily 리셋 무시 → worker _count_used_slots 통일
  - auto_bb_breakdown 4h→1h
  - success_pyramiding_worker 신설
  - pending_hc_fast_worker 신설
  - realtime_reentry v202 마틴게일 완성
  - start_stage1 fail-open + 좀비 정리
  - _stop_price 청산가 우선
  - rsi=50 하드코딩 제거
  - **검증**: reset_at 03:57:47 KST 이후 HOODUSDT LONG STAGE1_OPEN 진입 확인!

- **Fix 20~21 (v219)**: PR = 7중 정점 SHORT + 신 마틴게일
  - 사장님 verbatim: "3단계까지 갈수 있다야 가능하면 가지않는 관리가 필요"
  - pump_top_detector + auto_short_at_top 신 워커!
  - **검증**: tag `v-2026-08-22-v219-final-confirmed` (사장님 UI 검증 = pending!)

### ⏳ Pending (사장님 실 검증 대기!)
- **Fix 22 = UI 배지 클릭!** 🚨 사장님 지금 지적!
  - **상태**: 코드 배포 마킹, 실 UI 미동작 or 반영 X!
  - **재확인 필요**:
    - 어떤 배지? (「🎯 정점」? 「📊 OBV」? 「🔄 재진입 대기중」?)
    - 클릭 = 무슨 동작 기대? (모달? 상세 창? 진입?)
    - 실 UI에서 발생하는 실제 동작?
  - **우선순위**: 최우선! 다음 세션 최상단!

- **Fix 23~25**: 사장님 verbatim 재확인 필요!
  - (구체 내용 = 세션 로그 or TaskList 재조회 필수!)

### 🚨 v219 검증 대기 항목 (pending!)
- [ ] 텔레그램 알림 실 도착 확인 (「🎯 정점 SHORT!」)
- [ ] pump_top_detector 5분 주기 실행 확인 (docker logs!)
- [ ] auto_short_at_top 30초 주기 실행 확인
- [ ] 실 SHORT 진입 시 = 사장님 검증
- [ ] 300 USDT default = 조정 여부 (사장님 결정!)
- [ ] daily_limit 공유 = 실 카운트 확인

## 헌법 신 3개 (2026-08-23)
- 헌법 69: 사장님 요구 = 즉시 메모리 저장!
- 헌법 70: 완료 = 실 검증 3단계 후만! (VPS+API+UI!)
- 헌법 71: 사장님 verbatim 통과까지 = "pending"!

## 다음 세션 우선순위 (재정렬!)
1. **Fix 22 UI 배지 = 사장님 재현 요청 + 실 fix!**
2. Fix 23~25 = 사장님 verbatim 재확인!
3. v219 검증 5개 항목!
4. 롤백 재발 방지 = 헌법 69/70/71 실 적용!

## 세션 인수인계 규칙
매 세션 종료 = MEMORY.md 인덱스 = 이 파일 링크 + "pending N개" 마킹!
다음 세션 = 이 파일 = **첫 번째 읽기!**
