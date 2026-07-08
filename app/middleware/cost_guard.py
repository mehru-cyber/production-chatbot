import datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import UsageLog


def _today() -> str:
    return datetime.date.today().isoformat()


def get_today_usage(db: Session, user_id) -> int:
    row = (
        db.query(UsageLog)
        .filter(UsageLog.user_id == user_id, UsageLog.day == _today())
        .first()
    )
    return row.tokens_used if row else 0


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
