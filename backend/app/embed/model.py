"""Embeddings: one small model (bge-small, 384-d) in both the batch worker and the API.

fastembed runs the quantized ONNX model without PyTorch, so the API image stays small and
fits Render Free's 512 MB. The API embeds one query at a time on one thread (Phase 0 check).
"""

from typing import Protocol

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
MAX_SKILLS = 12


class Embedder(Protocol):
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def document_text(
    *,
    title: str,
    company: str,
    city: str | None,
    remote_scope: str,
    summary: str | None,
    skills: list[str],
) -> str:
    parts = [title, company, city or remote_scope, summary or "", ", ".join(skills[:MAX_SKILLS])]
    return " | ".join(p for p in parts if p)


class FastEmbedder:
    """Loads the model on first use, so importing the app costs nothing."""

    dim = 384

    def __init__(
        self, model_name: str, cache_dir: str | None = None, threads: int | None = 1
    ) -> None:
        self._model_name, self._cache_dir, self._threads = model_name, cache_dir, threads
        self._model = None

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(
                self._model_name, cache_dir=self._cache_dir, threads=self._threads
            )
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._load().embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._load().embed([QUERY_PREFIX + text]))).tolist()
