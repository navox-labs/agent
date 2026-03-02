from __future__ import annotations

"""
Job Matching Engine — scores jobs against the user's profile.

This is ported from Navox's job-match API:
  /Users/nahrin/reflexive.ai/src/app/api/job-match/route.ts

The logic:
1. Send the user's profile + job description to GPT-4o
2. LLM returns: matchedSkills, missingSkills, gapAnalysis, resumeTailoring
3. We recalculate the score server-side (LLM scores are unreliable)
4. Formula: (matched / total) * 100, capped at 50% if missing > matched

Why recalculate? LLMs tend to inflate match scores. A candidate with
2 matching skills and 8 missing skills should not score 70%. The
server-side formula gives an honest, comparable score.
"""

import json
import logging
from dataclasses import dataclass, field

from agent.llm.base import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class JobAnalysis:
    """
    Result of analyzing a job against the user's profile.

    Mirrors Navox's JobAnalysis interface from job-match/route.ts.
    """
    match_score: int = 0
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    gap_analysis: str = ""
    resume_tailoring: dict | None = None


@dataclass
class JobDetails:
    """Extracted job details from a raw description."""
    title: str = "Unknown Position"
    location: str | None = None
    company: str | None = None


class JobMatcher:
    """
    Scores job descriptions against a user's profile.

    Uses the same GPT-4o prompts that power Navox's recruiter matching,
    but runs locally through the agent's existing OpenAI provider.
    """

    def __init__(self, llm_provider: LLMProvider):
        self.llm = llm_provider

    async def analyze_match(
        self, job_description: str, profile_text: str
    ) -> JobAnalysis:
        """
        Analyze how well a job matches the user's profile.

        This is the core matching function, ported from Navox's
        analyzeJobMatch() in job-match/route.ts.

        Args:
            job_description: The full job posting text
            profile_text: The user's profile summary (from ProfileStore)

        Returns:
            JobAnalysis with score, matched/missing skills, and gap analysis
        """
        # The matching prompt — ported verbatim from Navox
        analysis_prompt = f"""You are a senior Recruiter with expertise in talent acquisition and resume optimization. Analyze the candidate's information against the job description.

Candidate Profile:
{profile_text}

Job Description:
{job_description}

Your task:
1. Calculate a match score (0-100) based on how well the candidate's qualifications align with the job requirements
2. Identify matched skills and missing skills
3. Identify the top 5 missing keywords/skills that would improve the candidate's match
4. Provide a gap analysis
5. Suggest resume tailoring recommendations

Return JSON format:
{{
  "matchScore": 85,
  "matchedSkills": ["Python", "Machine Learning", "Docker"],
  "missingSkills": ["Kubernetes", "AWS", "Spark"],
  "top5MissingKeywords": ["Kubernetes", "AWS", "Spark", "Airflow", "MLOps"],
  "gapAnalysis": "Strong match in core ML skills...",
  "resumeTailoring": {{
    "relevantExperiences": [{{"experience": "...", "relevance": "..."}}],
    "applicableSkills": ["..."],
    "recommendedKeywords": ["..."],
    "atsOptimization": "...",
    "qualificationHighlights": "..."
  }}
}}"""

        try:
            response = await self.llm.generate(
                system=(
                    "You are a senior Recruiter with 15+ years of experience in "
                    "talent acquisition, resume optimization, and ATS compliance. "
                    "Return only valid JSON."
                ),
                messages=[{"role": "user", "content": analysis_prompt}],
            )

            parsed = json.loads(response.text)

            matched_skills = parsed.get("matchedSkills", [])
            missing_skills = parsed.get("missingSkills", [])

            # Server-side score recalculation (ported from Navox)
            # The AI score is unreliable — it inflates matches
            score = self.calculate_score(matched_skills, missing_skills)

            return JobAnalysis(
                match_score=score,
                matched_skills=matched_skills,
                missing_skills=missing_skills,
                gap_analysis=parsed.get("gapAnalysis", ""),
                resume_tailoring=parsed.get("resumeTailoring"),
            )

        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to parse match analysis: %s", e)
            return JobAnalysis(
                gap_analysis="Unable to perform detailed analysis. Please review manually."
            )
        except Exception as e:
            logger.exception("Job matching error")
            return JobAnalysis(gap_analysis=f"Matching error: {e}")

    def calculate_score(self, matched: list, missing: list) -> int:
        """
        Calculate match score server-side.

        Ported from Navox's job-match/route.ts — the exact same formula:
        - score = (matched / total) * 100
        - Cap at 50% if missing skills outnumber matched
        - Floor at 5% if zero matched skills
        - Floor at 5% if no skills identified at all

        This prevents LLM score inflation and gives honest, comparable scores.
        """
        matched_count = len(matched)
        missing_count = len(missing)
        total = matched_count + missing_count

        if total == 0:
            return 5  # No skills identified — near-zero match

        score = round((matched_count / total) * 100)

        # Cap: if missing > matched, never exceed 50%.
        # Note: mathematically, when missing > matched, matched/total < 0.5
        # so score is already ≤50. Kept for Navox parity as a safety net.
        if missing_count > matched_count:
            score = min(score, 50)

        # Floor: zero matched skills = near-zero match (not exactly 0)
        if matched_count == 0:
            score = 5

        return score

    async def extract_job_details(self, description: str) -> JobDetails:
        """
        Extract title, location, and company from a raw job description.

        Ported from Navox's extractJobDetails() — uses GPT-4o-mini for speed.
        """
        try:
            response = await self.llm.generate(
                system=(
                    "You are a job description parser. Extract job title, location, "
                    "and company from job descriptions. Return only valid JSON."
                ),
                messages=[{
                    "role": "user",
                    "content": (
                        f"Extract the job title, location, and company name from this "
                        f"job description. If not found, use \"Unknown Position\" for "
                        f"title and null for location/company.\n\n"
                        f"Job Description:\n{description[:3000]}\n\n"
                        f"Return JSON format:\n"
                        f'{{"jobTitle": "...", "jobLocation": "..." or null, "company": "..." or null}}'
                    ),
                }],
            )

            parsed = json.loads(response.text)
            return JobDetails(
                title=parsed.get("jobTitle", "Unknown Position"),
                location=parsed.get("jobLocation"),
                company=parsed.get("company"),
            )

        except Exception as e:
            logger.error("Failed to extract job details: %s", e)
            return JobDetails()
