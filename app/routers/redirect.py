import json
import logging
from datetime import timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cache import get_store, link_cache_key
from app.config import get_settings
from app.database import SessionLocal, get_db
from app.models import Click, Link
from app.utils import as_utc, utcnow

router = APIRouter(tags=["redirect"])
logger = logging.getLogger("uvicorn.error")


def detect_device(user_agent: str | None) -> str:
    if not user_agent:
        return "unknown"
    ua = user_agent.lower()
    if any(word in ua for word in ("bot", "crawler", "spider")):
        return "bot"
    if any(word in ua for word in ("mobile", "android", "iphone", "ipad")):
        return "mobile"
    return "desktop"


def referrer_host(referer: str | None) -> str:
    """Store only the referring site's host, e.g. 'news.ycombinator.com'."""
    if not referer:
        return "direct"
    return urlparse(referer).netloc[:255] or "direct"


def record_click(link_id: int, referer: str | None, user_agent: str | None) -> None:
    """Runs after the redirect response is sent, so analytics never slow the user down."""
    try:
        with SessionLocal() as db:
            db.add(
                Click(
                    link_id=link_id,
                    referrer=referrer_host(referer),
                    user_agent=(user_agent or "")[:512] or None,
                    device=detect_device(user_agent),
                )
            )
            db.commit()
    except Exception:  # analytics must never break a redirect
        logger.exception("Failed to record click for link %s", link_id)


@router.get("/{code}", include_in_schema=False)
def redirect_to_original(
    code: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    settings = get_settings()
    store = get_store()
    key = link_cache_key(code)

    cached = store.get(key)
    if cached:  # fast path: no database query
        data = json.loads(cached)
        link_id, url = data["id"], data["url"]
    else:
        link = db.scalar(select(Link).where(Link.code == code))
        if link is None or not link.is_active:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Short link not found")

        now = utcnow()
        expires_at = as_utc(link.expires_at)
        if expires_at is not None and expires_at <= now:
            raise HTTPException(status.HTTP_410_GONE, "This link has expired")

        # Never cache longer than the link lives, so expiry is respected.
        ttl = settings.cache_ttl_seconds
        if expires_at is not None:
            ttl = max(1, min(ttl, int((expires_at - now).total_seconds())))
        store.set(key, json.dumps({"id": link.id, "url": link.original_url}), ttl)
        link_id, url = link.id, link.original_url

    background_tasks.add_task(
        record_click, link_id, request.headers.get("referer"), request.headers.get("user-agent")
    )
    # 302 (not 301) so browsers don't cache the redirect and every click is counted.
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)
