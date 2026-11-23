"""The real embedding model. Slow (downloads ~70 MB once): RUN_MODEL_TESTS=1 to run."""

import os

import pytest

from app.embed.model import FastEmbedder

pytestmark = [
    pytest.mark.model,
    pytest.mark.skipif(os.environ.get("RUN_MODEL_TESTS") != "1", reason="RUN_MODEL_TESTS=1"),
]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_fastembed_similarity_order() -> None:
    embedder = FastEmbedder("BAAI/bge-small-en-v1.5")
    backend, sales = embedder.embed_documents(
        [
            "Backend Engineer Intern | Acme | Bengaluru | Build Python APIs | Python, PostgreSQL",
            "Account Executive | Acme | Mumbai | Sell enterprise software | Salesforce",
        ]
    )
    query = embedder.embed_query("python backend internship")
    assert len(query) == embedder.dim == 384
    assert cosine(query, backend) > cosine(query, sales)
