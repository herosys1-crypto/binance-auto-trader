"""📊 Chart Pattern Learning Team (v152 신!)

배경 (사장님 요청 2026-08-16):
"심볼들의 1달 차트를 분석해서 이런 패턴을 학습해서 메모리해줘
 차트분석 에이전트가 없으면 차트분석 에이전트팀을 만들어줘"

3 Agents:
- PatternCollector: 심볼 1달 4H 캔들 수집!
- PatternDetector: v149/v150/v151 로직 = 과거 패턴 스캔!
- PatternMemory: DB 저장 + outcome tracking!

= 매일 자동 실행!
= 심볼별 패턴 성공률 = 학습!
"""
