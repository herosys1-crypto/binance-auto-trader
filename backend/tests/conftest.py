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
