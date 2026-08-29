from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.routes import login, register
from app.auth.service import get_current_user
from app.database import Base
from app.schemas import LoginRequest, RegisterRequest


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_register_login_and_authenticated_identity(session: Session) -> None:
    registered = register(RegisterRequest(email="Reviewer@Example.com", password="strong-password-123"), session)
    session.commit()

    token = login(LoginRequest(email="reviewer@example.com", password="strong-password-123"), session)
    current = get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token.access_token), session)

    assert registered.email == "reviewer@example.com"
    assert current.id == registered.id
    assert current.role == "reviewer"


def test_duplicate_account_is_rejected(session: Session) -> None:
    request = RegisterRequest(email="same@example.com", password="strong-password-123")
    register(request, session)
    session.commit()

    with pytest.raises(HTTPException) as error:
        register(request, session)

    assert error.value.status_code == 409


def test_incorrect_password_is_rejected(session: Session) -> None:
    register(RegisterRequest(email="reviewer@example.com", password="strong-password-123"), session)
    session.commit()

    with pytest.raises(HTTPException) as error:
        login(LoginRequest(email="reviewer@example.com", password="wrong"), session)

    assert error.value.status_code == 401
