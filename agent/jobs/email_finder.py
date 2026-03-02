from __future__ import annotations

"""
Email Finder — discover hiring manager emails from job postings.

After finding a job on LinkedIn, this module tries to identify
the hiring manager or recruiter and guess their email address
using common corporate email patterns.

Strategy:
1. Extract the recruiter/poster name from the LinkedIn job page
   (LinkedIn shows "Posted by [Name]" on many listings)
2. Look up the company's email domain from common patterns
3. Generate likely email addresses using standard formats:
   - first.last@company.com
   - first@company.com
   - flast@company.com
"""

import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Common corporate email patterns (ordered by likelihood)
EMAIL_PATTERNS = [
    "{first}.{last}@{domain}",       # john.doe@company.com
    "{first}@{domain}",              # john@company.com
    "{first}{last}@{domain}",        # johndoe@company.com
    "{f}{last}@{domain}",            # jdoe@company.com
    "{first}_{last}@{domain}",       # john_doe@company.com
    "{first}.{last[0]}@{domain}",    # john.d@company.com
]

# Well-known company domains (saves a lookup)
KNOWN_DOMAINS = {
    "google": "google.com",
    "meta": "meta.com",
    "facebook": "meta.com",
    "amazon": "amazon.com",
    "apple": "apple.com",
    "microsoft": "microsoft.com",
    "netflix": "netflix.com",
    "spotify": "spotify.com",
    "shopify": "shopify.com",
    "stripe": "stripe.com",
    "airbnb": "airbnb.com",
    "uber": "uber.com",
    "lyft": "lyft.com",
    "twitter": "x.com",
    "x": "x.com",
    "salesforce": "salesforce.com",
    "adobe": "adobe.com",
    "ibm": "ibm.com",
    "oracle": "oracle.com",
    "nvidia": "nvidia.com",
    "intel": "intel.com",
    "tesla": "tesla.com",
    "cohere": "cohere.com",
    "openai": "openai.com",
    "anthropic": "anthropic.com",
    "databricks": "databricks.com",
    "snowflake": "snowflake.com",
    "palantir": "palantir.com",
    "datadog": "datadoghq.com",
    "twilio": "twilio.com",
    "square": "squareup.com",
    "block": "block.xyz",
    "coinbase": "coinbase.com",
    "robinhood": "robinhood.com",
    "plaid": "plaid.com",
}


def guess_company_domain(company: str, job_url: str = "") -> str | None:
    """
    Guess the company's email domain.

    Strategy:
    1. Check known domains map
    2. Extract from job URL if it's a company career page
    3. Fall back to company-name.com pattern
    """
    if not company or company == "Unknown":
        return None

    # Normalize company name
    company_lower = company.lower().strip()

    # Remove common suffixes
    for suffix in [" inc", " inc.", " ltd", " ltd.", " corp", " corp.",
                   " llc", " co.", " company", " technologies", " technology",
                   " labs", " group", " solutions"]:
        company_lower = company_lower.replace(suffix, "")
    company_lower = company_lower.strip()

    # Check known domains
    if company_lower in KNOWN_DOMAINS:
        return KNOWN_DOMAINS[company_lower]

    # Try to extract domain from job URL
    if job_url:
        try:
            parsed = urlparse(job_url)
            host = parsed.hostname or ""
            # If it's a company career page (not linkedin/indeed)
            if host and not any(
                s in host for s in ["linkedin.com", "indeed.com", "glassdoor.com", "google.com"]
            ):
                # Strip www prefix
                if host.startswith("www."):
                    host = host[4:]
                return host
        except Exception:
            pass

    # Fall back: company-name.com (remove spaces, keep simple)
    domain = re.sub(r"[^a-z0-9]", "", company_lower)
    if domain:
        return f"{domain}.com"

    return None


def parse_name(full_name: str) -> dict | None:
    """
    Parse a full name into first/last components.

    Returns dict with 'first', 'last', 'f' (first initial).
    Returns None if the name can't be parsed.
    """
    if not full_name:
        return None

    # Clean up the name
    name = full_name.strip()
    # Remove common prefixes/suffixes
    for prefix in ["dr.", "mr.", "ms.", "mrs.", "prof."]:
        if name.lower().startswith(prefix):
            name = name[len(prefix):].strip()

    parts = name.split()
    if len(parts) < 2:
        return None

    first = parts[0].lower()
    last = parts[-1].lower()

    # Skip if names contain non-alpha characters (likely not a real name)
    if not first.isalpha() or not last.isalpha():
        return None

    return {
        "first": first,
        "last": last,
        "f": first[0],
    }


def guess_emails(name: str, company: str, job_url: str = "") -> list[str]:
    """
    Generate likely email addresses for a person at a company.

    Args:
        name: Full name (e.g., "Sarah Chen")
        company: Company name (e.g., "Shopify")
        job_url: Optional job URL for domain extraction

    Returns:
        List of likely email addresses, ordered by probability.
        Returns empty list if name/company can't be parsed.
    """
    parsed = parse_name(name)
    if not parsed:
        return []

    domain = guess_company_domain(company, job_url)
    if not domain:
        return []

    emails = []
    for pattern in EMAIL_PATTERNS:
        try:
            email = pattern.format(
                first=parsed["first"],
                last=parsed["last"],
                f=parsed["f"],
                domain=domain,
            )
            emails.append(email)
        except (KeyError, IndexError):
            continue

    return emails


def extract_hiring_info(
    hiring_manager_name: str | None = None,
    company: str = "",
    job_url: str = "",
) -> dict:
    """
    Build a hiring info dict with name and guessed emails.

    This is the main entry point called by the scanner after
    extracting poster info from a LinkedIn job page.
    """
    result = {
        "hiring_manager_name": hiring_manager_name,
        "hiring_manager_emails": [],
    }

    if hiring_manager_name and company:
        result["hiring_manager_emails"] = guess_emails(
            name=hiring_manager_name,
            company=company,
            job_url=job_url,
        )

    return result
