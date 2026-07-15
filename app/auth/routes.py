import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import PlainTextResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.email import send_verification_email
from app.auth.security import (
    create_access_token,
    generate_refresh_token,
    generate_verification_token,
    hash_password,
    hash_refresh_token,
    refresh_token_expiry,
    verify_password,
)
from app.config import settings
from app.db.session import RefreshToken, User, get_db
from app.middleware.rate_limit import check_ip_rate_limit
from app.observability.logging_config import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# Precomputed once at import time. Used to run a real bcrypt verification
# even when no matching user exists, so a login attempt against a
# nonexistent account takes the same amount of time as one against a real
# account with a wrong password — otherwise the response-time difference
# (bcrypt runs vs. doesn't run) leaks which emails have accounts, even
# though the error *message* is already identical either way.
_DUMMY_PASSWORD_HASH = hash_password("this-is-not-a-real-account-timing-safety-only")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"


class RegisterResponse(BaseModel):
    status: str
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    email_verified: bool


def _issue_tokens(db: Session, user: User) -> tuple[str, str]:
    access_token = create_access_token(subject=user.email)
    raw_refresh = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(raw_refresh),
            expires_at=refresh_token_expiry(),
        )
    )
    db.commit()
    return access_token, raw_refresh


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(check_ip_rate_limit)],
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    # Normalize case so "Alice@Example.com" and "alice@example.com" can't
    # both register as distinct accounts.
    normalized_email = payload.email.lower()

    existing = db.query(User).filter(User.email == normalized_email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    require_verification = settings.smtp_configured
    user = User(
        email=normalized_email,
        hashed_password=hash_password(payload.password),
        email_verified=not require_verification,
        verification_token=generate_verification_token() if require_verification else None,
    )
    db.add(user)
    db.commit()

    if require_verification:
        send_verification_email(user.email, user.verification_token)
        return RegisterResponse(status="verification_sent")

    access_token, refresh_token = _issue_tokens(db, user)
    return RegisterResponse(status="ok", access_token=access_token, refresh_token=refresh_token)


@router.get("/verify-email", response_class=PlainTextResponse)
def verify_email(token: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.verification_token == token).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link")
    user.email_verified = True
    user.verification_token = None
    db.commit()
    return "Email verified — you can now log in."

@router.post("/login", response_model=TokenResponse, dependencies=[Depends(check_ip_rate_limit)])
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # form_data.username carries the email — this is OAuth2 form spec, not a naming choice
    normalized_email = form_data.username.lower()
    user = db.query(User).filter(User.email == normalized_email).first()

    # Same error message whether the email doesn't exist or the password is
    # wrong — don't leak which one it was, that's an account-enumeration risk.
    generic_error = HTTPException(status_code=401, detail="Incorrect email or password")

    if not user:
        # Run a real bcrypt verification against a dummy hash anyway, so
        # this path takes the same time as a real "wrong password" attempt
        # — otherwise the *absence* of that delay leaks that the email
        # doesn't exist, even with an identical error message.
        verify_password(form_data.password, _DUMMY_PASSWORD_HASH)
        raise generic_error

    if user.locked_until and user.locked_until > datetime.datetime.utcnow():
        remaining = int((user.locked_until - datetime.datetime.utcnow()).total_seconds() // 60) + 1
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Too many failed attempts. Try again in {remaining} minute(s).",
        )

    if not verify_password(form_data.password, user.hashed_password):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.max_failed_login_attempts:
            user.locked_until = datetime.datetime.utcnow() + datetime.timedelta(
                minutes=settings.lockout_minutes
            )
            log.warning("account_locked", email=user.email)
        db.commit()
        raise generic_error

    if settings.smtp_configured and not user.email_verified:
        raise HTTPException(status_code=403, detail="Please verify your email before logging in.")

    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()

    access_token, refresh_token = _issue_tokens(db, user)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse, dependencies=[Depends(check_ip_rate_limit)])
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    token_hash = hash_refresh_token(payload.refresh_token)
    stored = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    invalid = HTTPException(status_code=401, detail="Invalid or expired refresh token")
    if not stored or stored.revoked or stored.expires_at < datetime.datetime.utcnow():
        raise invalid

    user = db.query(User).filter(User.id == stored.user_id).first()
    if not user:
        raise invalid

    # Rotate: revoke the used refresh token, issue a fresh pair. Limits how
    # long a stolen refresh token stays useful if it's ever intercepted.
    stored.revoked = True
    db.commit()

    access_token, new_refresh_token = _issue_tokens(db, user)
    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: LogoutRequest, db: Session = Depends(get_db)):
    token_hash = hash_refresh_token(payload.refresh_token)
    stored = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if stored:
        stored.revoked = True
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=str(current_user.id), email=current_user.email, email_verified=current_user.email_verified
    )