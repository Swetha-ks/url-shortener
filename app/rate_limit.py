from fastapi import HTTPException, Request, status

from app.cache import get_store


def client_ip(request: Request) -> str:
    # Behind a proxy, run uvicorn with --proxy-headers so this is the real client IP.
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(scope: str, identifier: str, limit: int, window_seconds: int = 60) -> None:
    """Fixed-window rate limiter. Raises HTTP 429 when the limit is exceeded."""
    count = get_store().incr(f"rl:{scope}:{identifier}", window_seconds)
    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please slow down.",
            headers={"Retry-After": str(window_seconds)},
        )
