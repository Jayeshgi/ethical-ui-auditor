from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.service import authenticate_user, create_access_token, get_current_user, normalize_email, password_hash
from app.database import UserRecord, get_database_session
from app.schemas import LoginRequest, RegisterRequest, TokenResponse, UserPublic


router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
def register(request: RegisterRequest, session: Session = Depends(get_database_session)) -> UserPublic:
    try:
        email = normalize_email(request.email)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if session.scalar(select(UserRecord.id).where(UserRecord.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = UserRecord(email=email, password_hash=password_hash.hash(request.password), role="reviewer")
    session.add(user)
    try:
        session.flush()
    except IntegrityError as error:
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from error
    return UserPublic(id=user.id, email=user.email, role=user.role, created_at=user.created_at)


@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, session: Session = Depends(get_database_session)) -> TokenResponse:
    user = authenticate_user(session, request.email, request.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    token, expires_at = create_access_token(user)
    return TokenResponse(access_token=token, expires_at=expires_at)


@router.get("/me", response_model=UserPublic)
def me(user: UserPublic = Depends(get_current_user)) -> UserPublic:
    return user
