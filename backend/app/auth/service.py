from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import ACCESS_TOKEN_EXPIRE_MINUTES, JWT_ALGORITHM, JWT_SECRET_KEY
from app.database import UserRecord, get_database_session
from app.schemas import UserPublic


password_hash = PasswordHash.recommended()
bearer_scheme = HTTPBearer(auto_error=False)


def normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if "@" not in normalized or len(normalized) > 320:
        raise ValueError("A valid email address is required.")
    return normalized


def create_access_token(user: UserRecord) -> tuple[str, datetime]:
    expires_at = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    token = jwt.encode({"sub": user.id, "role": user.role, "exp": expires_at}, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token, expires_at


def authenticate_user(session: Session, email: str, password: str) -> UserRecord | None:
    user = session.scalar(select(UserRecord).where(UserRecord.email == normalize_email(email)))
    if user is None or not password_hash.verify(password, user.password_hash):
        return None
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_database_session),
) -> UserPublic:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Valid bearer authentication is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = str(payload["sub"])
    except (jwt.InvalidTokenError, KeyError):
        raise unauthorized
    user = session.get(UserRecord, user_id)
    if user is None:
        raise unauthorized
    return UserPublic(id=user.id, email=user.email, role=user.role, created_at=user.created_at)
