from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.dependencies import SESSION_COOKIE, get_current_user
from app.api.schemas import AuthResponse, LoginRequest, OrganizationOut, RegisterRequest, UserOut
from app.core.config import get_settings
from app.domain.errors import AppError, UnauthorizedError
from app.infrastructure.db.models import Organization, User
from app.infrastructure.db.session import get_db
from app.infrastructure.security.passwords import hash_password, verify_password
from app.infrastructure.security.session import create_session_token

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


def _set_session_cookie(response: Response, user: User) -> None:
    token = create_session_token(user.id)
    # When frontend and backend are on different origins (e.g. ngrok), browsers will only send
    # cookies on cross-site requests if SameSite=None + Secure is set.
    cross_site = not settings.frontend_base_url.startswith("http://localhost")
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=(settings.app_env == "production") or cross_site,
        samesite="none" if cross_site else "lax",
        max_age=settings.access_token_ttl_seconds,
        path="/",
    )


@router.post("/register", response_model=AuthResponse)
def register(body: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    if body.password != body.confirm_password:
        raise AppError("VALIDATION_ERROR", "Passwords do not match.", 400)
    if db.query(User).filter(User.email == body.email).first():
        raise AppError("VALIDATION_ERROR", "Email already registered.", 400)

    org = Organization(name=body.organization_name)
    db.add(org)
    db.flush()

    user = User(
        organization_id=org.id,
        email=body.email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role="owner",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.refresh(org)

    _set_session_cookie(response, user)
    return AuthResponse(user=UserOut.model_validate(user), organization=OrganizationOut.model_validate(org))


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise UnauthorizedError(message="Invalid email or password.")
    org = db.query(Organization).filter(Organization.id == user.organization_id).first()
    _set_session_cookie(response, user)
    return AuthResponse(
        user=UserOut.model_validate(user),
        organization=OrganizationOut.model_validate(org),
    )


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=AuthResponse)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    org = db.query(Organization).filter(Organization.id == user.organization_id).first()
    return AuthResponse(
        user=UserOut.model_validate(user),
        organization=OrganizationOut.model_validate(org),
    )
