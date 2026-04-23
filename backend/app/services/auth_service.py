from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.security import verify_password, create_access_token
from app.models.user import User

class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def login(self, email: str, password: str) -> str:
        stmt = select(User).where(User.email == email, User.is_active.is_(True))
        user = self.db.execute(stmt).scalar_one_or_none()
        if not user or not verify_password(password, user.password_hash):
            raise ValueError("Invalid credentials")
        return create_access_token(subject=user.id)
