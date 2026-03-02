from __future__ import annotations

"""Tests for agent/memory/store.py — persistent conversation memory."""


async def test_save_and_get_messages(memory_store):
    await memory_store.save_message("s1", "user", "hello")
    await memory_store.save_message("s1", "assistant", "hi there")
    messages = await memory_store.get_recent_messages(limit=10)
    assert len(messages) == 2
    roles = {m["role"] for m in messages}
    assert roles == {"user", "assistant"}


async def test_get_recent_messages_limit(memory_store):
    for i in range(10):
        await memory_store.save_message("s1", "user", f"msg {i}")
    messages = await memory_store.get_recent_messages(limit=3)
    assert len(messages) == 3


async def test_get_session_messages(memory_store):
    await memory_store.save_message("session_a", "user", "msg A")
    await memory_store.save_message("session_b", "user", "msg B")
    messages = await memory_store.get_session_messages("session_a")
    assert len(messages) == 1
    assert messages[0]["content"] == "msg A"


async def test_preference_set_and_get(memory_store):
    await memory_store.set_preference("user_name", "Nahrin")
    value = await memory_store.get_preference("user_name")
    assert value == "Nahrin"


async def test_preference_upsert(memory_store):
    await memory_store.set_preference("color", "blue")
    await memory_store.set_preference("color", "red")
    value = await memory_store.get_preference("color")
    assert value == "red"


async def test_get_all_preferences(memory_store):
    await memory_store.set_preference("name", "Test")
    await memory_store.set_preference("tz", "UTC")
    prefs = await memory_store.get_all_preferences()
    assert prefs == {"name": "Test", "tz": "UTC"}


async def test_save_and_get_summaries(memory_store):
    await memory_store.save_summary("s1", "User asked about weather", 5)
    summaries = await memory_store.get_recent_summaries(limit=5)
    assert len(summaries) == 1
    assert "weather" in summaries[0]


async def test_build_context(memory_store):
    await memory_store.save_message("s1", "user", "hello")
    await memory_store.set_preference("name", "Test")
    await memory_store.save_summary("s1", "Greeted the user", 1)

    ctx = await memory_store.build_context(limit=20)
    assert len(ctx["messages"]) == 1
    assert ctx["preferences"]["name"] == "Test"
    assert len(ctx["summaries"]) == 1
