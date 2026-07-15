import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status

from app.auth.dependencies import get_current_user
from app.config import settings
from app.db.session import User

# NOTE: in-memory, per-process. Fine for a single instance. If you run more
# than one app instance behind a load balancer, replace these dicts with
# Redis (e.g. a sorted set per key, ZADD/ZREMRANGEBYSCORE) so all instances
# share the same counters.
_request_log: dict[str, deque] = defaultdict(deque)
_ip_log: dict[str, deque] = defaultdict(deque)

WINDOW_SECONDS = 60
IP_LIMIT_PER_MINUTE = 10  # deliberately stricter than the per-user limit — these guard unauthenticated endpoints


def check_rate_limit(current_user: User = Depends(get_current_user)) -> User:
    key = str(current_user.id)
    now = time.time()
    window = _request_log[key]

    while window and now - window[0] > WINDOW_SECONDS:
        window.popleft()

    if len(window) >= settings.rate_limit_per_minute:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: {settings.rate_limit_per_minute} requests/minute.",
        )

    window.append(now)
    return current_user


def check_ip_rate_limit(request: Request) -> None:
    """
    Guards endpoints that run before any user is authenticated — register,
    login, refresh — where check_rate_limit (which requires a logged-in
    user) doesn't apply. Without this, an attacker gets unlimited attempts
    against these endpoints regardless of the per-account lockout, since a
    lockout only protects one specific account, not the endpoint itself.
    """
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = _ip_log[client_ip]

    while window and now - window[0] > WINDOW_SECONDS:
        window.popleft()

    if len(window) >= IP_LIMIT_PER_MINUTE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many requests from this address. Try again shortly.",
        )

    window.append(now)
