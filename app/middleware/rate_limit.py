import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, status

from app.auth.dependencies import get_current_user
from app.config import settings
from app.db.session import User

# NOTE: in-memory, per-process. Fine for a single instance. If you run more
# than one app instance behind a load balancer, replace this dict with
# Redis (e.g. a sorted set per user, ZADD/ZREMRANGEBYSCORE) so all instances
# share the same counters.
_request_log: dict[str, deque] = defaultdict(deque)

WINDOW_SECONDS = 60


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
