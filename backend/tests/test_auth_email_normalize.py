"""2026-11-20 모바일 로그인 401 — 이메일 앞뒤 공백·대문자는 같은 계정으로 본다. 비밀번호는 그대로 비교."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.security import hash_password
from app.models.user import User
from app.services.auth_service import AuthService


@pytest.fixture()
def db():
    eng = create_engine("sqlite://")
    User.__table__.create(eng)
    s = sessionmaker(bind=eng)()
    s.add(User(email="owner@example.com", password_hash=hash_password("pw-Test1"), is_active=True))
    s.commit()
    yield s
    s.close()


@pytest.mark.parametrize("email", ["owner@example.com", "Owner@example.com", " owner@EXAMPLE.com "])
def test_email_case_and_space_ok(db, email):
    assert AuthService(db).login(email, "pw-Test1")


@pytest.mark.parametrize("pw", ["pw-test1", " pw-Test1", "ㅔㅈ-Test1", ""])
def test_password_still_exact(db, pw):
    with pytest.raises(ValueError):
        AuthService(db).login("owner@example.com", pw)


def test_unknown_email_rejected(db):
    with pytest.raises(ValueError):
        AuthService(db).login("other@example.com", "pw-Test1")
