import os
import sys
from pathlib import Path

import numpy as np
import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Must be set before app.config is imported anywhere.
os.environ.update(
    VECTOR_BACKEND="memory",
    DATABASE_URL="sqlite+aiosqlite:///:memory:",
    LLM_PROVIDER="echo",
    FALLBACK_PROVIDER="none",
    LOG_JSON="false",
    LOG_LEVEL="WARNING",
)

from app.rag.store import MemoryStore, StoredChunk, set_store  # noqa: E402

pytest_plugins = ["pytest_asyncio"]


def fake_embed(texts):
    """Deterministic bag-of-words embeddings.

    The real model is a 130MB download and ~1s of CPU per call; that turns a
    2-second test suite into a 3-minute one. These vectors preserve the property
    the code under test actually depends on — shared vocabulary means higher
    cosine — which is enough for retrieval ordering and the grounding gate.
    Real-model behaviour is covered by `make eval`, not by unit tests.
    """
    dim = 384
    out = np.zeros((len(texts), dim), dtype=np.float32)
    for i, t in enumerate(texts):
        for w in set(t.lower().split()):
            out[i, hash(w) % dim] += 1.0
    n = np.linalg.norm(out, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return out / n


CORPUS = [
    ("chesky-1", "Brian Chesky", "Founder Mode at Airbnb", "00:14:32",
     "Brian Chesky: I review every detail of the product every week. "
     "We cut 200 projects down to 20 and I personally sign off on each one."),
    ("chesky-2", "Brian Chesky", "Founder Mode at Airbnb", "00:22:10",
     "Brian Chesky: The 11 star experience exercise forces you past incremental "
     "thinking. A 5 star checkin is fine. An 11 star checkin is absurd on purpose."),
    ("ravi-1", "Ravi Mehta", "Product market fit signals", "00:08:00",
     "Ravi Mehta: Retention curves that flatten are the clearest product market "
     "fit signal. If week 8 retention is flat you have something real."),
    ("lenny-1", "Casey Winters", "Growth loops", "00:31:45",
     "Casey Winters: Growth loops compound where funnels leak. Every output of "
     "the loop feeds the next input, so the channel gets cheaper over time."),
]


def build_store() -> MemoryStore:
    st = MemoryStore()
    chunks, texts = [], []
    for i, (cid, guest, title, ts, text) in enumerate(CORPUS):
        chunks.append(StoredChunk(id=cid, document_id=guest.lower().replace(" ", "-"),
                                  ordinal=i, text=text, speakers=[guest], start_ts=ts,
                                  end_ts=ts, guest=guest, title=title,
                                  youtube_url="https://www.youtube.com/watch?v=abc123"))
        texts.append(text)
    import asyncio
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        st.upsert(chunks, fake_embed(texts))
    )
    return st


@pytest.fixture(autouse=True)
def patch_embedder(monkeypatch):
    import app.grounding.faithfulness as f
    import app.rag.embedder as emb
    import app.rag.retriever as ret

    monkeypatch.setattr(emb, "embed_texts", fake_embed)
    monkeypatch.setattr(emb, "embed_query", lambda t: fake_embed([t])[0])
    monkeypatch.setattr(ret, "embed_query", lambda t: fake_embed([t])[0])
    monkeypatch.setattr(f, "embed_texts", fake_embed, raising=False)
    yield


@pytest.fixture(autouse=True)
def seeded_store():
    st = build_store()
    set_store(st)
    import app.rag.retriever as ret
    ret._GUEST_CACHE = None  # rebuilt per test; guests differ between fixtures
    yield st
    set_store(None)


@pytest_asyncio.fixture
async def client():
    from httpx import ASGITransport, AsyncClient

    from app.db import dispose, init_models
    from app.main import app

    await init_models()
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as c:
        yield c
    await dispose()
