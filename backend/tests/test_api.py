"""API contract and session isolation.

Session isolation gets the most attention here because it's the requirement
most likely to look fine in a demo and be wrong in production — one shared
history variable and nobody notices until two people use it at once.
"""
import pytest


async def new_session(client, title=None):
    r = await client.post("/api/sessions", json={"title": title} if title else {})
    assert r.status_code == 201
    return r.json()["id"]


@pytest.mark.asyncio
async def test_health_reports_each_subsystem(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    b = r.json()
    assert b["database"]["ok"] is True
    assert b["index"]["chunks"] == 4
    assert {p["provider"] for p in b["providers"]} >= {"ollama", "anthropic", "echo"}


@pytest.mark.asyncio
async def test_liveness_does_not_touch_the_database(client):
    assert (await client.get("/api/health/live")).json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_config_never_leaks_keys(client):
    body = (await client.get("/api/config")).json()
    assert set(body["keys_present"]) == {"anthropic", "openai"}
    assert "sk-" not in str(body)


@pytest.mark.asyncio
async def test_sessions_keep_independent_context(client):
    a, b = await new_session(client, "A"), await new_session(client, "B")

    await client.post("/api/chat", json={"session_id": a,
                                         "message": "What is the 11 star experience?"})
    msgs_a = (await client.get(f"/api/sessions/{a}/messages")).json()
    msgs_b = (await client.get(f"/api/sessions/{b}/messages")).json()

    assert len(msgs_a) == 2 and msgs_b == []


@pytest.mark.asyncio
async def test_chat_returns_the_full_contract(client):
    sid = await new_session(client)
    r = await client.post("/api/chat",
                          json={"session_id": sid, "message": "What is founder mode?"})
    assert r.status_code == 200
    b = r.json()
    assert b["route"] == "answer"
    assert b["provider"] == "echo"
    assert b["citations"] and b["citations"][0]["marker"] == 1
    assert b["grounding"]["total_claims"] >= 1
    assert b["timings"]["total_ms"] >= 0


@pytest.mark.asyncio
async def test_citation_deep_links_to_the_timestamp(client):
    sid = await new_session(client)
    b = (await client.post("/api/chat",
                           json={"session_id": sid,
                                 "message": "What did Chesky do with projects?"})).json()
    url = b["citations"][0]["youtube_url"]
    assert url and "t=" in url  # ?t=<seconds> is what makes a citation checkable


@pytest.mark.asyncio
async def test_unknown_session_is_404_with_error_contract(client):
    r = await client.post("/api/chat", json={"session_id": "nope", "message": "hi"})
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"
    assert r.json()["trace_id"]


@pytest.mark.asyncio
async def test_blank_message_is_422(client):
    sid = await new_session(client)
    r = await client.post("/api/chat", json={"session_id": sid, "message": "   "})
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


@pytest.mark.asyncio
async def test_session_title_is_backfilled_from_first_message(client):
    sid = await new_session(client)
    await client.post("/api/chat",
                      json={"session_id": sid, "message": "How do growth loops work?"})
    listed = {s["id"]: s for s in (await client.get("/api/sessions")).json()}
    assert listed[sid]["title"].startswith("How do growth loops")


@pytest.mark.asyncio
async def test_artifact_is_persisted_and_sanitised(client):
    sid = await new_session(client)
    b = (await client.post("/api/chat",
                           json={"session_id": sid,
                                 "message": "make me an HTML one-pager on growth loops"})).json()
    assert b["route"] == "artifact"
    art = b["artifact"]
    assert art["kind"] == "html"
    assert "Content-Security-Policy" in art["content"]

    fetched = await client.get(f"/api/artifacts/{art['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["content"] == art["content"]


@pytest.mark.asyncio
async def test_artifact_policy_is_exposed(client):
    p = (await client.get("/api/artifacts/policy")).json()
    assert "allow-same-origin" not in p["sandbox"]
    assert "default-src 'none'" in p["csp"]
    assert p["permitted"] and p["blocked"]


@pytest.mark.asyncio
async def test_traces_are_written_per_turn(client):
    sid = await new_session(client)
    await client.post("/api/chat", json={"session_id": sid, "message": "What is PMF?"})
    traces = (await client.get("/api/admin/traces")).json()
    assert traces and traces[0]["route"] == "answer"
    assert traces[0]["retrieved_n"] > 0


@pytest.mark.asyncio
async def test_deleting_a_session_removes_its_messages(client):
    sid = await new_session(client)
    await client.post("/api/chat", json={"session_id": sid, "message": "What is PMF?"})
    assert (await client.delete(f"/api/sessions/{sid}")).status_code == 204
    assert (await client.get(f"/api/sessions/{sid}/messages")).status_code == 404
