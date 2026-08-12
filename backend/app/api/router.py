from fastapi import APIRouter
from app.api.v1.auth import router as auth_router
from app.api.v1.strategies import router as strategies_router
from app.api.v1.orders import router as orders_router
from app.api.v1.positions import router as positions_router
from app.api.v1.events import router as events_router
from app.api.v1.admin import router as admin_router
from app.api.v1.exchange_accounts import router as exchange_accounts_router
from app.api.v1.symbols import router as symbols_router
from app.api.v1.market import router as market_router
from app.api.v1.reentry_alerts import router as reentry_alerts_router
from app.api.v1.pump_bb_alerts import router as pump_bb_alerts_router  # 🌟 v131 급등+BB중단!
from app.api.v1.strategy_suggestions import router as strategy_suggestions_router  # 🌟 v132 전략 제안!
from app.api.v1.suggestion_profiles import router as suggestion_profiles_router  # 🌟 v132 프로필!
from app.api.v1.analysis import router as analysis_router  # 🌟 v133c 심볼/전략 상세 분석!
from app.api.v1.live_pump_dump import router as live_pump_dump_router  # 🌟 v133d 급등락 실시간 진입!

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(strategies_router)
api_router.include_router(orders_router)
api_router.include_router(positions_router)
api_router.include_router(events_router)
api_router.include_router(admin_router)
api_router.include_router(exchange_accounts_router)
api_router.include_router(symbols_router)
api_router.include_router(market_router)
api_router.include_router(reentry_alerts_router)  # 🌟 v130 신 재진입 알람!
api_router.include_router(pump_bb_alerts_router)  # 🌟 v131 신 급등+BB중단 알람!
api_router.include_router(strategy_suggestions_router)  # 🌟 v132 전략 제안!
api_router.include_router(suggestion_profiles_router)  # 🌟 v132 제안 프로필!
api_router.include_router(analysis_router)  # 🌟 v133c 심볼/전략 상세 분석!
api_router.include_router(live_pump_dump_router)  # 🌟 v133d 급등락 실시간 진입!
