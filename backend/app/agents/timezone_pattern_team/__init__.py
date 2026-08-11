"""🌏 Timezone Pattern Team!

미션: 한국 시간 급등락 통계 → 심볼별 시간대 패턴 → 매매 참고!

사장님 사고:
「미국 외 지역 = 가격 조작 의심!」
「한국 시간 = 급등락 시간대 통계 필요!」
「예: BTCUSDT = 새벽 03시 KST = 45% 급등 빈번!」

Agents:
- kst_pivot_recorder           # 한국 시간 급등락 기록!
- timezone_stats_calculator    # 시간대 통계 (%)!
- symbol_pattern_analyzer      # 심볼별 패턴!
- heatmap_generator             # heatmap 시각화!
- regional_alert_agent          # 예상 시간대 도래 알림!

DB:
- alembic 0026: timezone_pivots + timezone_stats

관련:
- spec: docs/MARKET_FLOW_TIMEZONE_SPEC_v132.html
- 헌법 C02 (사장님 사상 우선!)
"""
