"""Assembles the versioned API. Every module's router is mounted under /api/v1 here."""

from fastapi import APIRouter

from app.api import health, status
from app.feedback.router import router as feedback_router
from app.identity.router import auth_router, users_router
from app.profiles.router import router as profile_router
from app.search.router import router as search_router


def build_api_router(prefix: str) -> APIRouter:
    router = APIRouter(prefix=prefix)
    router.include_router(health.router)
    router.include_router(status.router)
    router.include_router(auth_router)
    router.include_router(users_router)
    router.include_router(profile_router)
    router.include_router(search_router)
    router.include_router(feedback_router)
    return router
