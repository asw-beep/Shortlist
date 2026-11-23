"""The database layer: pgvector is installed, tests are isolated, pooled URLs skip prepares."""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.engine import engine_connect_args

pytestmark = pytest.mark.integration


def test_vector_extension_installed(db: Session) -> None:
    version = db.execute(
        text("select extversion from pg_extension where extname = 'vector'")
    ).scalar()
    assert version


def test_probe_1_commit_inside_test(db: Session) -> None:
    db.execute(text("create table t_probe(x int)"))
    db.commit()
    assert db.execute(text("select to_regclass('t_probe')")).scalar() is not None


def test_probe_2_previous_commit_was_rolled_back(db: Session) -> None:
    # pytest runs a file's tests in order, so this proves the per-test rollback.
    assert db.execute(text("select to_regclass('t_probe')")).scalar() is None


def test_pooled_settings_disable_prepared_statements() -> None:
    pooled = Settings(_env_file=None, environment="test", database_pooled=True)
    direct = Settings(_env_file=None, environment="test")
    assert engine_connect_args(pooled)["prepare_threshold"] is None
    assert "prepare_threshold" not in engine_connect_args(direct)
