from __future__ import annotations

"""Tests for agent/profile/store.py — user profile persistence."""


async def test_has_profile_false_initially(profile_store):
    assert await profile_store.has_profile() is False


async def test_set_and_get_profile_text(profile_store):
    await profile_store.set_profile_from_text("Senior ML Engineer with 5 years experience.")
    text = await profile_store.get_profile_summary()
    assert "ML Engineer" in text


async def test_has_profile_true_after_set(profile_store):
    await profile_store.set_profile_from_text("Some profile.")
    assert await profile_store.has_profile() is True


async def test_set_and_get_card_url(profile_store):
    await profile_store.set_profile_card_url("https://navox.tech/card/jsmith")
    url = await profile_store.get_profile_card_url()
    assert url == "https://navox.tech/card/jsmith"


async def test_job_preferences_json_roundtrip(profile_store):
    prefs = {
        "target_roles": ["ML Engineer", "Data Scientist"],
        "locations": ["Toronto", "Remote"],
    }
    await profile_store.set_job_preferences(prefs)
    loaded = await profile_store.get_job_preferences()
    assert loaded == prefs


async def test_get_full_context(profile_store):
    await profile_store.set_profile_from_text("My profile text.")
    await profile_store.set_profile_card_url("https://navox.tech/card/test")
    await profile_store.set_job_preferences({"target_roles": ["Engineer"]})

    ctx = await profile_store.get_full_context()
    assert ctx["profile_text"] == "My profile text."
    assert ctx["profile_card_url"] == "https://navox.tech/card/test"
    assert ctx["job_preferences"]["target_roles"] == ["Engineer"]
    assert "resume_path" in ctx  # Key exists even if None
