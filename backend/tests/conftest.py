import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.base import Base

TEST_DATABASE_URL = "sqlite+pysqlite:///:memory:"

@pytest.fixture
def db_session():
    engine = create_engine(TEST_DATABASE_URL, future=True)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)

@pytest.fixture(autouse=True)
def _fix371_halt_off_for_tests():
    """Fix 371: production treats a missing auto_trading_halt row as HALTED; unit DBs have no row.
    Other guard tests run with the halt forced off. tests/test_fix371_* reset FORCE_HALT themselves."""
    from app.services import auto_trading_halt as _h
    _prev = _h.FORCE_HALT
    _h.FORCE_HALT = False
    yield
    _h.FORCE_HALT = _prev


@pytest.fixture(autouse=True)
def _fix376_chart_gate_off_for_tests():
    """Fix 376: 자동 전략 생성 시 차트 게이트가 바이낸스 봉을 조회한다 — 단위·통합 DB 테스트에서는 끈다.
    tests/test_fix376_* 는 FORCE_MODE 를 None 으로 되돌려 실제 판정을 본다."""
    from app.services import chart_gate_live as _g
    from app.services import force_cci_gate as _f          # 📊 Fix 380 도 같은 자리에서 봉을 조회한다
    from app.services import family_loss_breaker as _b     # ⛔ Fix 384 도 같은 자리에서 DB 손익을 조회한다
    _prev, _prev_f, _prev_b = _g.FORCE_MODE, _f.FORCE_MODE, _b.FORCE_OFF
    _g.FORCE_MODE = "off"
    _f.FORCE_MODE = "off"
    _b.FORCE_OFF = True
    from app.services import strategy_list_cache as _lc   # ⚡ Fix 386: 테스트끼리 목록 캐시가 섞이지 않게
    _lc.invalidate()
    yield
    _lc.invalidate()
    _g.FORCE_MODE = _prev
    _f.FORCE_MODE = _prev_f
    _b.FORCE_OFF = _prev_b
