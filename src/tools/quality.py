"""Deterministic, explainable source-quality assessment.

This module classifies the *publisher class/authority* of a source — it is
not a truth score, and it is intentionally conservative: unknown domains get
a neutral score with a warning rather than a judgment. Relevance is a
separate concept handled by search scoring and evidence selection.

Pure functions, no LLM, no network: fully deterministic and unit-testable.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from src.models.research import Source, SourceQuality

# Explicit domain knowledge. Suffix matching includes subdomains.
_ACADEMIC = {
    "nature.com", "science.org", "sciencedirect.com", "springer.com",
    "link.springer.com", "wiley.com", "onlinelibrary.wiley.com", "ieee.org",
    "ieeexplore.ieee.org", "acm.org", "dl.acm.org", "arxiv.org", "doi.org",
    "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov", "plos.org", "cell.com",
    "thelancet.com", "nejm.org", "pnas.org", "sagepub.com", "tandfonline.com",
    "mdpi.com", "frontiersin.org", "semanticscholar.org",
}
_STANDARDS = {
    "iso.org", "nist.gov", "ietf.org", "w3.org", "iec.ch", "ansi.org",
    "astm.org", "sae.org", "ul.com", "etsi.org", "bsigroup.com",
}
_RESEARCH_INSTITUTIONS = {
    "rand.org", "brookings.edu", "pewresearch.org", "nber.org", "cern.ch",
    "nrel.gov", "ornl.gov", "anl.gov", "pnnl.gov", "sandia.gov", "llnl.gov",
    "iea.org", "irena.org", "worldbank.org", "oecd.org", "un.org", "who.int",
    "ipcc.ch", "esa.int", "nasa.gov", "noaa.gov",
}
_REPUTABLE_TECH = {
    "spectrum.ieee.org", "arstechnica.com", "technologyreview.com",
    "anandtech.com", "phoronix.com", "lwn.net", "acm.org",
}
_MAINSTREAM_NEWS = {
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "nytimes.com",
    "wsj.com", "ft.com", "economist.com", "theguardian.com",
    "washingtonpost.com", "bloomberg.com", "cnbc.com", "npr.org", "axios.com",
}
_COMMUNITY = {
    "reddit.com", "quora.com", "medium.com", "stackexchange.com",
    "stackoverflow.com", "news.ycombinator.com", "substack.com", "x.com",
    "twitter.com", "facebook.com", "linkedin.com", "youtube.com", "tiktok.com",
    "blogspot.com", "wordpress.com", "tumblr.com", "fandom.com",
}
_SECONDARY_INFO = {
    "wikipedia.org", "britannica.com", "investopedia.com", "howstuffworks.com",
    "sciencedaily.com", "phys.org",
}

_TIER_BY_SCORE = ((80, "high"), (60, "medium"), (0, "low"))


def _domain_of(source: Source) -> str:
    if source.domain:
        return source.domain.lower()
    try:
        return urlsplit(source.url).netloc.lower()
    except ValueError:
        return ""


def _matches(domain: str, known: set[str]) -> str | None:
    for candidate in known:
        if domain == candidate or domain.endswith("." + candidate):
            return candidate
    return None


def _tier(score: int) -> str:
    for floor, tier in _TIER_BY_SCORE:
        if score >= floor:
            return tier
    return "unknown"


def assess_source(source: Source) -> SourceQuality:
    """Classify one source. Deterministic; same input, same output."""
    if source.kind == "document":
        return SourceQuality(
            category="user document",
            tier="high",
            score=85,
            signals=["Private document supplied directly by the user."],
        )

    domain = _domain_of(source)
    url = source.url.lower()
    signals: list[str] = []
    warnings: list[str] = []

    if not domain:
        return SourceQuality(
            category="unknown",
            tier="unknown",
            score=30,
            warnings=["Source has no parseable domain."],
        )

    category, score = "unknown", 40

    if match := _matches(domain, _ACADEMIC):
        category, score = "peer-reviewed / academic", 92
        signals.append(f"Recognized academic/scholarly publisher ({match}).")
    elif match := _matches(domain, _STANDARDS):
        category, score = "standards organization", 90
        signals.append(f"Recognized standards body ({match}).")
    elif match := _matches(domain, _RESEARCH_INSTITUTIONS):
        category, score = "research institution", 88
        signals.append(f"Recognized research institution ({match}).")
    elif domain.endswith(".gov") or ".gov." in domain:
        category, score = "government", 86
        signals.append("Government domain (.gov).")
    elif domain.endswith(".mil"):
        category, score = "government", 84
        signals.append("Military/government domain (.mil).")
    elif domain.endswith(".edu") or ".ac." in domain:
        category, score = "university", 80
        signals.append("University domain (.edu/.ac).")
        warnings.append("University domains also host personal/student pages.")
    elif match := _matches(domain, _REPUTABLE_TECH):
        category, score = "reputable technical publication", 72
        signals.append(f"Established technical publication ({match}).")
    elif match := _matches(domain, _MAINSTREAM_NEWS):
        category, score = "mainstream publication", 68
        signals.append(f"Established news organization ({match}).")
    elif match := _matches(domain, _SECONDARY_INFO):
        category, score = "secondary informational source", 60
        signals.append(f"Secondary/tertiary reference ({match}).")
        warnings.append("Summarizes other sources; verify against primary sources.")
    elif match := _matches(domain, _COMMUNITY):
        category, score = "community / user-generated", 35
        signals.append(f"Community or user-generated platform ({match}).")
        warnings.append("Content is user-generated and not editorially reviewed.")
    elif domain.endswith(".int"):
        category, score = "official organization", 82
        signals.append("International organization domain (.int).")
    elif domain.endswith(".org"):
        category, score = "official organization", 55
        signals.append("Organization domain (.org).")
        warnings.append(".org registration proves nothing by itself.")
    else:
        category, score = "secondary informational source", 45
        warnings.append("Domain not in Atlas's known-publisher lists.")

    # URL-level signals refine the domain class conservatively.
    if "doi.org/" in url or "/doi/" in url:
        signals.append("URL carries a DOI (persistent scholarly identifier).")
        score = min(100, score + 5)
        if category in ("secondary informational source", "unknown"):
            category = "peer-reviewed / academic"
    if url.startswith("http://"):
        warnings.append("Served over plain HTTP (no TLS).")
        score = max(0, score - 5)
    if any(seg in url for seg in ("/blog/", "/forum/", "/comments/")):
        warnings.append("URL path suggests blog/forum content.")
        score = max(0, score - 10)

    return SourceQuality(
        category=category,
        tier=_tier(score),
        score=score,
        signals=signals,
        warnings=warnings,
    )


def with_quality(source: Source) -> Source:
    """Return the source with quality attached (idempotent)."""
    if source.quality is not None:
        return source
    return source.model_copy(update={"quality": assess_source(source)})


def quality_tier_distribution(sources: list[Source]) -> dict[str, int]:
    """Tier counts for metrics (unknown-quality sources counted as unknown)."""
    distribution: dict[str, int] = {}
    for source in sources:
        tier = source.quality.tier if source.quality else "unknown"
        distribution[tier] = distribution.get(tier, 0) + 1
    return distribution
