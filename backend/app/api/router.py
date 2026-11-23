"""Assembles the versioned API. Every module's router is mounted under /api/v1 here."""

from fastapi import APIRouter

from app.api import health


def build_api_router(prefix: str) -> APIRouter:
    router = APIRouter(prefix=prefix)
    router.include_router(health.router)
    return router
