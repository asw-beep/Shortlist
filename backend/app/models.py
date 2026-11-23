"""Imports every module that defines tables, so Base.metadata knows them all (Alembic, tests)."""

import app.catalog.models  # noqa: F401
import app.feedback.models  # noqa: F401
import app.identity.models  # noqa: F401
import app.profiles.models  # noqa: F401
import app.tracing.models  # noqa: F401
