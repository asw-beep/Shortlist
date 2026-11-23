"""Phase 0: does the query embedder fit Render Free (512 MB RAM, 0.1 CPU)?

Standalone (fastembed + stdlib) so it runs in a bare python:3.12-slim container:

    python embed_memory.py [model]

Prints JSON: peak resident memory after loading the model and embedding 50 short queries,
and the median and 95th-percentile latency of a single query embedding.
Pass: peak_rss_mb <= 420 and p50_ms <= 500 under --memory=512m --cpus=0.1.
"""

import json
import resource
import statistics
import sys
import time

from fastembed import TextEmbedding

PREFIX = "Represent this sentence for searching relevant passages: "
QUERIES = [
    "python backend internship bengaluru",
    "machine learning intern remote india",
    "data engineer new grad hyderabad",
    "react frontend developer fresher",
    "golang distributed systems entry level",
]


def main() -> None:
    model_name = sys.argv[1] if len(sys.argv) > 1 else "BAAI/bge-small-en-v1.5"
    started = time.perf_counter()
    model = TextEmbedding(model_name)
    list(model.embed([PREFIX + "warm up"]))
    load_s = time.perf_counter() - started
    latencies = []
    for i in range(50):
        t0 = time.perf_counter()
        vector = next(iter(model.embed([PREFIX + QUERIES[i % len(QUERIES)]])))
        latencies.append((time.perf_counter() - t0) * 1000)
    peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(
        json.dumps(
            {
                "model": model_name,
                "dim": len(vector),
                "load_s": round(load_s, 1),
                "peak_rss_mb": round(peak_kb / 1024),
                "p50_ms": round(statistics.median(latencies), 1),
                "p95_ms": round(statistics.quantiles(latencies, n=20)[18], 1),
            }
        )
    )


if __name__ == "__main__":
    main()
