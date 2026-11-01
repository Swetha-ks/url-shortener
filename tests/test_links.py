from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.database import SessionLocal
from app.models import Link


def create(client, headers, **body):
    body.setdefault("url", "https://example.com/some/long/path")
    return client.post("/links", json=body, headers=headers)


# ---------- creating ----------
def test_create_link_requires_auth(client):
    assert client.post("/links", json={"url": "https://example.com"}).status_code == 401


def test_create_link_generates_code(client, auth_headers):
    response = create(client, auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert len(data["code"]) == get_settings().code_length
    assert data["short_url"].endswith("/" + data["code"])
    assert data["original_url"] == "https://example.com/some/long/path"


def test_custom_alias_and_duplicate(client, make_headers):
    first = make_headers("a@example.com")
    second = make_headers("b@example.com")
    assert create(client, first, custom_alias="my-link").status_code == 201
    assert create(client, second, custom_alias="my-link").status_code == 409


def test_invalid_input_is_rejected(client, auth_headers):
    assert create(client, auth_headers, url="not-a-url").status_code == 422
    assert create(client, auth_headers, url="javascript:alert(1)").status_code == 422
    assert create(client, auth_headers, custom_alias="a b").status_code == 422
    assert create(client, auth_headers, custom_alias="docs").status_code == 422  # reserved
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert create(client, auth_headers, expires_at=past).status_code == 422


def test_create_is_rate_limited(client, auth_headers):
    get_settings().create_limit_per_minute = 2
    assert create(client, auth_headers).status_code == 201
    assert create(client, auth_headers).status_code == 201
    assert create(client, auth_headers).status_code == 429


# ---------- redirecting ----------
def test_redirect_works_and_unknown_code_404(client, auth_headers):
    link = create(client, auth_headers, custom_alias="go-home").json()
    response = client.get("/go-home", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == link["original_url"]
    assert client.get("/does-not-exist", follow_redirects=False).status_code == 404


def test_expired_link_returns_410(client, auth_headers):
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    link = create(client, auth_headers, custom_alias="soon-gone", expires_at=future).json()

    with SessionLocal() as db:  # pretend time passed
        db.get(Link, link["id"]).expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

    assert client.get("/soon-gone", follow_redirects=False).status_code == 410


# ---------- analytics ----------
def test_stats_count_clicks(client, auth_headers):
    link = create(client, auth_headers, custom_alias="stats-demo").json()

    mobile = {"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)", "referer": "https://news.ycombinator.com/item?id=1"}
    client.get("/stats-demo", headers=mobile, follow_redirects=False)
    client.get("/stats-demo", headers=mobile, follow_redirects=False)
    client.get("/stats-demo", follow_redirects=False)  # second hit is served from cache

    stats = client.get(f"/links/{link['id']}/stats", headers=auth_headers).json()
    assert stats["total_clicks"] == 3
    assert stats["clicks_per_day"][0]["clicks"] == 3
    assert {"name": "news.ycombinator.com", "clicks": 2} in stats["top_referrers"]
    assert {"name": "direct", "clicks": 1} in stats["top_referrers"]
    assert {"name": "mobile", "clicks": 2} in stats["devices"]


# ---------- listing / deleting / ownership ----------
def test_list_links_with_pagination(client, auth_headers):
    for _ in range(3):
        create(client, auth_headers)
    page = client.get("/links?limit=2&offset=0", headers=auth_headers).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    rest = client.get("/links?limit=2&offset=2", headers=auth_headers).json()
    assert len(rest["items"]) == 1


def test_delete_link_also_clears_cache(client, auth_headers):
    link = create(client, auth_headers, custom_alias="delete-me").json()
    assert client.get("/delete-me", follow_redirects=False).status_code == 302  # fills the cache

    assert client.delete(f"/links/{link['id']}", headers=auth_headers).status_code == 204
    assert client.get("/delete-me", follow_redirects=False).status_code == 404


def test_users_cannot_touch_each_others_links(client, make_headers):
    owner = make_headers("owner@example.com")
    stranger = make_headers("stranger@example.com")
    link = create(client, owner).json()

    assert client.get(f"/links/{link['id']}/stats", headers=stranger).status_code == 404
    assert client.delete(f"/links/{link['id']}", headers=stranger).status_code == 404
    assert client.get("/links", headers=stranger).json()["total"] == 0


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
