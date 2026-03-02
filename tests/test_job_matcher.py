from __future__ import annotations

"""Tests for agent/jobs/matcher.py — job scoring and LLM-based matching."""

import json

from agent.models import LLMResponse
from agent.jobs.matcher import JobMatcher


# ── calculate_score() — pure function tests ───────────────────────

def test_score_all_matched():
    matcher = JobMatcher(llm_provider=None)  # No LLM needed for pure function
    assert matcher.calculate_score(["Python", "ML", "Docker"], []) == 100


def test_score_all_missing():
    matcher = JobMatcher(llm_provider=None)
    assert matcher.calculate_score([], ["K8s", "AWS", "Spark"]) == 5


def test_score_equal_split():
    matcher = JobMatcher(llm_provider=None)
    assert matcher.calculate_score(["Python", "ML"], ["K8s", "AWS"]) == 50


def test_score_both_empty():
    matcher = JobMatcher(llm_provider=None)
    assert matcher.calculate_score([], []) == 5


def test_score_one_matched_many_missing():
    matcher = JobMatcher(llm_provider=None)
    # 1 / (1 + 10) * 100 = 9.09 → rounds to 9
    assert matcher.calculate_score(["Python"], ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]) == 9


# ── analyze_match() — mock LLM tests ─────────────────────────────

async def test_analyze_match_recalculates_score(mock_llm):
    """The server-side score should override the LLM's reported score."""
    # LLM says 90%, but only 3 matched / 3 missing → real score is 50
    mock_llm.generate.return_value = LLMResponse(
        text=json.dumps({
            "matchScore": 90,
            "matchedSkills": ["Python", "ML", "Docker"],
            "missingSkills": ["K8s", "AWS", "Spark"],
            "gapAnalysis": "Good match but missing cloud skills.",
            "resumeTailoring": {"applicableSkills": ["Python"]},
        })
    )

    matcher = JobMatcher(llm_provider=mock_llm)
    result = await matcher.analyze_match("Job description here", "Profile text here")

    # Server-side recalculation: 3/(3+3)*100 = 50
    assert result.match_score == 50
    assert result.matched_skills == ["Python", "ML", "Docker"]
    assert result.missing_skills == ["K8s", "AWS", "Spark"]
    assert "cloud" in result.gap_analysis.lower()


async def test_analyze_match_invalid_json(mock_llm):
    """When the LLM returns invalid JSON, we get a fallback analysis."""
    mock_llm.generate.return_value = LLMResponse(text="This is not JSON at all.")

    matcher = JobMatcher(llm_provider=mock_llm)
    result = await matcher.analyze_match("Job desc", "Profile text")

    assert result.match_score == 0
    assert "Unable to perform" in result.gap_analysis or "error" in result.gap_analysis.lower()
