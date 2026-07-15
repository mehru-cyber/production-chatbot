import datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import UsageLog

# Conservative estimate reserved atomically before each LLM call, then
# reconciled against the real token count afterward. Bounds how far
# concurrent requests can overshoot the daily cap to roughly
# (concurrent requests x this estimate) instead of being unbounded, without
# needing to hold a database lock for the multi-second duration of the
# actual LLM call.
_ESTIMATED_TOKENS_PER_REQUEST = 1500


def _today() -> str:
    return datetime.date.today().isoformat()


def get_today_usage(db: Session, user_id) -> int:
    row = (
        db.query(UsageLog)
        .filter(UsageLog.user_id == user_id, UsageLog.day == _today())
        .first()
    )
    return row.tokens_used if row else 0


def reserve_usage_or_raise(db: Session, user_id) -> int:
    """
    Atomically checks-and-reserves an estimated token cost against the
    daily cap in a single locked transaction, closing the race where many
    concurrent requests could each read a stale "under the cap" value
    before any of them commits. The row lock (SELECT ... FOR UPDATE) is
    held only for this brief check-and-increment, then released
    immediately on commit — not held across the slow LLM call itself.
    Call reconcile_usage() after the real call completes to correct the
    estimate to the actual token count.
    """
    today = _today()
    row = (
        db.query(UsageLog)
        .filter(UsageLog.user_id == user_id, UsageLog.day == today)
        .with_for_update()
        .first()
    )
    current = row.tokens_used if row else 0

    if current + _ESTIMATED_TOKENS_PER_REQUEST > settings.daily_token_cap:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Daily usage cap reached ({settings.daily_token_cap} tokens). "
                "Try again tomorrow."
            ),
        )

    if row:
        row.tokens_used = current + _ESTIMATED_TOKENS_PER_REQUEST
    else:
        row = UsageLog(user_id=user_id, day=today, tokens_used=_ESTIMATED_TOKENS_PER_REQUEST)
        db.add(row)
    db.commit()
    return _ESTIMATED_TOKENS_PER_REQUEST


def reconcile_usage(db: Session, user_id, reserved: int, actual: int) -> None:
    """Corrects the reserved estimate to the real token count once known."""
    delta = actual - reserved
    if delta == 0:
        return
    row = (
        db.query(UsageLog)
        .filter(UsageLog.user_id == user_id, UsageLog.day == _today())
        .first()
    )
    if row:
        row.tokens_used = max(0, row.tokens_used + delta)
        db.commit()


# ---------------------------------------------------------------------------
# Legacy names kept temporarily so nothing else breaks until routes/chat.py
# is updated to use reserve_usage_or_raise/reconcile_usage instead (next fix
# in this batch). Safe to delete once that change is applied.
# ---------------------------------------------------------------------------


def assert_within_daily_cap(db: Session, user_id) -> None:
    used = get_today_usage(db, user_id)
    if used >= settings.daily_token_cap:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Daily usage cap reached ({settings.daily_token_cap} tokens). "
                "Try again tomorrow."
            ),
        )


def record_usage(db: Session, user_id, tokens: int) -> None:
    if tokens <= 0:
        return
    row = (
        db.query(UsageLog)
        .filter(UsageLog.user_id == user_id, UsageLog.day == _today())
        .first()
    )
    if row:
        row.tokens_used += tokens
    else:
        row = UsageLog(user_id=user_id, day=_today(), tokens_used=tokens)
        db.add(row)
    db.commit()
