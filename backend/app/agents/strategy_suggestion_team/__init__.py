"""🎯 Strategy Suggestion Team!

미션: 매일 학습 → 예측 → 신 전략 draft 자동 생성 → 사장님 수동/자동 결정!

사장님 요구 (2026-08-11):
"매일 학습하면서 급등과 급락이 예상되고 급락후 추가 지속적인 하락일경우
 새전략을 만들어 분석한 전략으로 만들어줘 그것을 보고 자동또는 수동으로
 매매를 할수 있게 해주고 기본은 수동으로 내가 실행할수 있게 해주고
 차후에 자동으로도 할수 있게 선택옵션을 넣어서 만들어주고 바로 사용하지
 않은 전략은 유지 삭제 관리 가능하게 만들어진 시간도 표기해서 해줘"

Agents:
- pump_dump_predictor           # 급등/급락 예상 분석!
- descent_pattern_detector      # 급락 후 지속 하락 감지!
- strategy_suggestion_generator # 신 전략 draft 자동 생성 ⭐ 핵심!
- suggestion_manager             # 유지/삭제 관리!
- auto_manual_executor          # 자동 or 수동 실행 (기본 수동!)

관련:
- spec: docs/STRATEGY_SUGGESTION_SPEC_v132.html
- alembic 0027: strategy_suggestions (다음 세션!)
- 헌법 C02 (사장님 사상 우선!) - 기본 수동!
"""
