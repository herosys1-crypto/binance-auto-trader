# C06. 단일 진실 (Single Source of Truth!)

## 원칙
같은 데이터/설정 = 단 하나만!
- 코드 중복 = drift 위험!
- Constant/Config = 한 곳에!

## 사장님 사고
- 하나만 = 변경 시 = 한 곳만!
- 여러 곳 = 하나 놓치면 = silent bug!

## 예시
- FORCE_SL_ALLOWED_ROI = risk_constants.py 한 곳!
- STATUS_MAP = constants.js 한 곳!
- 헌법 = memory/constitution/ 한 곳!

## 에이전트 적용
- 모든 에이전트 = memory 참조 (중복 X!)
- 상수 = risk_constants.py, strategy_status.py에서!
- UI JS = constants.js에서!

## 관련
- C05 (대칭성)
- capital_calculator.calc_reserved_for_account() = 화면과 100% 동일!
