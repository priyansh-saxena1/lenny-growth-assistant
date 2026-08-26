"""Local embeddings.

Deliberately not an API embedding model. Ingesting 300 episodes against a hosted
embedder means the evaluator needs a paid key before they can see anything work.
bge-small runs on CPU, is 384-dim, and downloads once (~130MB).
"""

from __future__ import annotations

import threading

import numpy as np

from ..config import get_settings
from ..logging_setup import get_logger

log = get_logger(__name__)

_model = None
_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from fastembed import TextEmbedding

                import os

                name = get_settings().embed_model
                threads = int(os.environ.get("ONNX_NUM_THREADS", "4"))
                log.info("embedder.load", model=name, threads=threads)
                _model = TextEmbedding(name, threads=threads)
    return _model


def embed_texts(texts: list[str], batch_size: int = 256) -> np.ndarray:
    if not texts:
        return np.zeros((0, get_settings().embed_dim), dtype=np.float32)
    vecs = list(_get_model().embed(texts, batch_size=batch_size))
    arr = np.asarray(vecs, dtype=np.float32)
    return _l2(arr)


def embed_query(text: str) -> np.ndarray:
    # bge wants this prefix on the query side only; skipping it costs a few
    # points of recall@8 on the golden set.
    return embed_texts([f"Represent this sentence for searching relevant passages: {text}"])[0]


def _l2(a: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(a, axis=-1, keepdims=True)
    n[n == 0] = 1.0
    return a / n
