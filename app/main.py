import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import models  # noqa: F401  (registers tables on Base.metadata)
from app.config import get_settings
from app.database import Base, engine
from app.routers import auth, links, redirect

settings = get_settings()
logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.secret_key == "change-me":
        logger.warning("SECRET_KEY is the insecure default. Set a real one in your environment.")
    # Simple setup for a small project. For schema changes over time, use Alembic migrations.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Create short links, redirect fast with caching, and track click analytics. "
        "Register, log in with the Authorize button, then try the /links endpoints."
    ),
    lifespan=lifespan,
)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(links.router)
app.include_router(redirect.router)  # keep last: its /{code} route matches anything
