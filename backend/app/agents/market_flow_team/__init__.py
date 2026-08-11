"""📊 Market Flow Learning Team!

미션: 매일 자동 = top 50 급등/급락 흐름 학습 → 유사 패턴 감지!

Agents:
- daily_pump_dump_scanner     # 매일 top 50 자동 조회!
- flow_analyzer                # 4H 흐름 분석 (higher low, EMA, 지지/저항!)
- pivot_point_detector         # 급등/급락 시점 감지 (volume 3x + price ±5%!)
- pattern_similarity_matcher   # 실시간 유사도 (cosine similarity!)
- pattern_alert_generator      # 유사도 > 0.80 = 알림!

DB:
- alembic 0025: market_flow_records + flow_pattern_matches
- features JSONB (4h_flow / support_resistance / pivots / indicators!)

관련:
- spec: docs/MARKET_FLOW_TIMEZONE_SPEC_v132.html
- 헌법 C03 (Silent bug 금지!)
- 헌법 C02 (사장님 사상 우선!)
"""
