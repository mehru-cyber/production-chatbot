
import datetime
import uuid

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


def _sqlalchemy_url(raw_url: str) -> str:
    """
    SQLAlchemy defaults a bare postgresql:// URL to the psycopg2 driver,
    which this project doesn't install (it uses psycopg v3 instead, for
    compatibility with LangGraph's Postgres checkpointer/store). Rewrite the
    scheme so SQLAlchemy picks the driver that's actually installed. Users
    never need to touch DATABASE_URL themselves for this — the raw value in
    .env is still what LangGraph's connection pool uses directly.
    """
    if raw_url.startswith("postgresql://"):
        return raw_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw_url


engine = create_engine(_sqlalchemy_url(settings.database_url), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # account lockout (brute-force protection)
    failed_login_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True)

    # email verification — only enforced if SMTP is configured; otherwise
    # accounts are created already verified and this is unused.
    email_verified = Column(Boolean, nullable=False, default=False)
    verification_token = Column(String, nullable=True)


class RefreshToken(Base):
    """
    Long-lived tokens used to obtain new short-lived access tokens without
    re-entering a password. Stored hashed (never the raw token) so a
    database leak alone doesn't hand out valid refresh tokens. Revocable —
    logging out (or a suspected compromise) marks the row revoked instead of
    deleting it, preserving an audit trail.
    """

    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, nullable=False, default=False)


class ApprovalAuditLog(Base):
    """
    Immutable record of every HITL approval decision — who, what was asked,
    what they decided, and when. Kept separate from the general structured
    logs since this is the one thing a real trading product would need to
    be able to produce on demand (e.g. for a dispute or compliance review).
    """

    __tablename__ = "approval_audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    thread_id = Column(String, nullable=False, index=True)
    prompt = Column(Text, nullable=False)
    decision = Column(String, nullable=False)
    decided_at = Column(DateTime, default=datetime.datetime.utcnow)


class ChatThread(Base):
    """
    Tracks which user owns which LangGraph thread_id. LangGraph's Postgres
    checkpointer keys conversation state by thread_id alone, with no
    built-in per-user scoping — without this table, any user who learned or
    guessed another user's thread_id could send messages into that
    conversation. Every /chat and /chat/resume call checks this table
    before touching the graph.
    """

    __tablename__ = "chat_threads"

    thread_id = Column(String, primary_key=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class UsageLog(Base):
    """Per-user, per-day token usage — backs the daily cost cap."""

    __tablename__ = "usage_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    day = Column(String, nullable=False, index=True)  # "YYYY-MM-DD", simple + index-friendly
    tokens_used = Column(Integer, nullable=False, default=0)

class ChatThread(Base):
    """Binds a thread_id to the user who created it. Checked on every
    /chat and /chat/resume call so one user can't read or act on
    (e.g. approve a purchase in) another user's conversation."""

    __tablename__ = "chat_threads"

    thread_id = Column(String, primary_key=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()