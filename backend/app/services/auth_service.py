import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.security import verify_password, create_access_token
from app.models.user import User

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def login(self, email: str, password: str) -> str:
        # 2026-11-20 모바일 로그인 401: 휴대폰 자판이 첫 글자를 대문자로 바꾸거나 앞뒤 공백을 넣으면
        #   이메일이 글자 그대로 비교돼 거절됐다 → 앞뒤 공백 제거 + 대소문자 무시.
        norm = (email or "").strip().lower()
        stmt = select(User).where(func.lower(User.email) == norm, User.is_active.is_(True))
        user = self.db.execute(stmt).scalar_one_or_none()
        if not user or not verify_password(password, user.password_hash):
            # 실패 사유만 남긴다 (이메일·비밀번호 값은 남기지 않음). 비ASCII 글자 = 한글 자판 입력 의심.
            pw = password or ""
            logger.warning(
                "login failed: reason=%s email_changed_by_norm=%s pw_len=%d pw_non_ascii=%d pw_edge_space=%s",
                "no_user" if not user else "bad_password",
                norm != (email or ""),
                len(pw),
                sum(1 for ch in pw if ord(ch) > 127),
                pw != pw.strip(),
            )
            raise ValueError("Invalid credentials")
        return create_access_token(subject=user.id)
