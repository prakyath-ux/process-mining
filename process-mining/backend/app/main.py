from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .api import analytics, auth, ingest, insights, logs
from .config import get_settings
from .db import SessionLocal, init_db
from .models import User
from .security import hash_password


def _seed_admin() -> None:
    settings = get_settings()
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email == settings.seed_admin_email))
        if existing is None:
            db.add(
                User(
                    email=settings.seed_admin_email,
                    full_name="Default Admin",
                    hashed_password=hash_password(settings.seed_admin_password),
                    role="admin",
                )
            )
            db.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    _seed_admin()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth.router)
    app.include_router(logs.router)
    app.include_router(ingest.router)
    app.include_router(analytics.router)
    app.include_router(insights.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "app": settings.app_name}

    return app


app = create_app()
