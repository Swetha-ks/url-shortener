import secrets
import string

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.cache import get_store, link_cache_key
from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models import Click, Link, User
from app.rate_limit import enforce_rate_limit
from app.schemas import DayCount, LinkCreate, LinkList, LinkOut, LinkStats, NameCount

router = APIRouter(prefix="/links", tags=["links"])

ALPHABET = string.ascii_letters + string.digits  # base62
MAX_CODE_ATTEMPTS = 5


def generate_code(length: int) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def to_out(link: Link) -> LinkOut:
    base = get_settings().base_url.rstrip("/")
    return LinkOut(
        id=link.id,
        code=link.code,
        short_url=f"{base}/{link.code}",
        original_url=link.original_url,
        created_at=link.created_at,
        expires_at=link.expires_at,
        is_active=link.is_active,
    )


def get_owned_link(db: Session, link_id: int, user: User) -> Link:
    link = db.scalar(select(Link).where(Link.id == link_id, Link.owner_id == user.id))
    if link is None:
        # 404 (not 403) so users cannot discover other people's link ids
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")
    return link


@router.post("", response_model=LinkOut, status_code=status.HTTP_201_CREATED)
def create_link(payload: LinkCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    settings = get_settings()
    enforce_rate_limit("create", str(user.id), settings.create_limit_per_minute)

    url = str(payload.url)

    if payload.custom_alias:
        link = Link(code=payload.custom_alias, original_url=url, owner_id=user.id, expires_at=payload.expires_at)
        db.add(link)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "Alias already taken")
    else:
        # Random codes can (rarely) collide; the unique index catches it and we retry.
        for _ in range(MAX_CODE_ATTEMPTS):
            link = Link(
                code=generate_code(settings.code_length),
                original_url=url,
                owner_id=user.id,
                expires_at=payload.expires_at,
            )
            db.add(link)
            try:
                db.commit()
                break
            except IntegrityError:
                db.rollback()
        else:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not generate a unique code")

    db.refresh(link)
    return to_out(link)


@router.get("", response_model=LinkList)
def list_links(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    total = db.scalar(select(func.count()).select_from(Link).where(Link.owner_id == user.id)) or 0
    links = db.scalars(
        select(Link)
        .where(Link.owner_id == user.id)
        .order_by(desc(Link.created_at), desc(Link.id))
        .limit(limit)
        .offset(offset)
    ).all()
    return LinkList(items=[to_out(link) for link in links], total=total, limit=limit, offset=offset)


@router.get("/{link_id}/stats", response_model=LinkStats)
def link_stats(link_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    link = get_owned_link(db, link_id, user)

    total = db.scalar(select(func.count()).select_from(Click).where(Click.link_id == link.id)) or 0

    day = func.date(Click.clicked_at)
    per_day = db.execute(
        select(day, func.count()).where(Click.link_id == link.id).group_by(day).order_by(day)
    ).all()

    referrers = db.execute(
        select(Click.referrer, func.count().label("n"))
        .where(Click.link_id == link.id)
        .group_by(Click.referrer)
        .order_by(desc("n"))
        .limit(5)
    ).all()

    devices = db.execute(
        select(Click.device, func.count().label("n"))
        .where(Click.link_id == link.id)
        .group_by(Click.device)
        .order_by(desc("n"))
    ).all()

    return LinkStats(
        link_id=link.id,
        code=link.code,
        total_clicks=total,
        clicks_per_day=[DayCount(date=str(d), clicks=n) for d, n in per_day],
        top_referrers=[NameCount(name=name, clicks=n) for name, n in referrers],
        devices=[NameCount(name=name, clicks=n) for name, n in devices],
    )


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_link(link_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    link = get_owned_link(db, link_id, user)
    get_store().delete(link_cache_key(link.code))  # stop serving it from cache immediately
    db.delete(link)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
