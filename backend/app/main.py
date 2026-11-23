"""The app factory. `uvicorn app.main:app` imports the module-level `app` below.

A factory (a function that builds the app) rather than a global built line by line, so
tests can build a fresh app with their own Settings and nothing leaks between tests.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import structlog
from fastapi import FastAPI

from app.api.router import build_api_router
from app.core.body_limit import BodySizeLimitMiddleware
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.engine import create_db_engine
from app.db.session import create_session_factory
from app.embed.model import FastEmbedder
from app.extract.taxonomy import SkillMatcher
from app.llm.chain import build_chain
from app.notify.email import BrevoEmailSender, EmailSender, InMemoryEmailSender
from app.search.config import load_ranking_config
from app.tracing.spans import DbSpanSink

log = structlog.get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info("app.startup", environment=settings.environment)
        yield
        app.state.http_client.close()
        app.state.engine.dispose()  # close pooled connections cleanly
        log.info("app.shutdown")

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    # app.state is where shared, process-wide objects live; dependencies read them from there.
    app.state.settings = settings
    app.state.engine = create_db_engine(settings)
    app.state.session_factory = create_session_factory(app.state.engine)  # used by get_db
    app.state.email_sender = create_email_sender(settings)
    app.state.http_client = httpx.Client()
    app.state.skill_matcher = SkillMatcher.from_yaml(settings.repo_path(settings.taxonomy_path))
    app.state.ranking_config = load_ranking_config(settings.repo_path(settings.ranking_config_path))
    # The model loads on the first query, not at startup; one thread fits Render's 0.1 CPU.
    app.state.embedder = FastEmbedder(settings.embed_model, settings.embed_cache_dir, threads=1)
    # Builds the résumé model chain per request, so its spans join the request's session.
    # Tests replace it with a fake.
    app.state.resume_llm_factory = lambda db: build_chain(
        [settings.resume_model], settings, app.state.http_client, DbSpanSink(db)
    )

    # Middleware added last runs first. The size limit sits inside the request context, so
    # even a refused upload gets a request ID and an access-log line.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(build_api_router(settings.api_prefix))
    return app


def create_email_sender(settings: Settings) -> EmailSender:
    if settings.brevo_api_key is None:
        return InMemoryEmailSender()
    return BrevoEmailSender(
        api_key=settings.brevo_api_key.get_secret_value(),
        sender_email=settings.email_from_address,
        sender_name=settings.email_from_name,
        client=httpx.Client(),
    )


app = create_app()
