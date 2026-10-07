"""Feature 1: deterministic source-quality intelligence."""

from src.models.research import Evidence, Source
from src.tools.quality import assess_source, quality_tier_distribution, with_quality
from src.tools.selection import select_evidence


def src(url, kind="web", domain=""):
    return Source(title=url, url=url, domain=domain, kind=kind)


class TestCategories:
    def test_academic_publisher(self):
        q = assess_source(src("https://www.nature.com/articles/s41586-x"))
        assert q.category == "peer-reviewed / academic"
        assert q.tier == "high"
        assert q.score >= 90
        assert any("nature.com" in s for s in q.signals)

    def test_government_domain(self):
        q = assess_source(src("https://www.energy.gov/report"))
        assert q.category == "government"
        assert q.tier == "high"

    def test_standards_org(self):
        assert assess_source(src("https://www.iso.org/standard/123")).category == \
            "standards organization"

    def test_university(self):
        q = assess_source(src("https://web.mit.edu/research/paper"))
        assert q.category == "university"
        assert q.warnings  # personal-pages caveat

    def test_community_platform(self):
        q = assess_source(src("https://www.reddit.com/r/batteries/comments/abc"))
        assert q.category == "community / user-generated"
        assert q.tier == "low"
        assert q.warnings

    def test_secondary_source(self):
        q = assess_source(src("https://en.wikipedia.org/wiki/Thermal_runaway"))
        assert q.category == "secondary informational source"
        assert q.tier == "medium"

    def test_unknown_domain_is_conservative_not_judged(self):
        q = assess_source(src("https://random-unknown-site-xyz.io/post"))
        assert q.tier == "low"
        assert 30 <= q.score <= 50
        assert any("known-publisher" in w for w in q.warnings)

    def test_document_source(self):
        q = assess_source(src("doc://abc#p3", kind="document"))
        assert q.category == "user document"
        assert q.tier == "high"

    def test_no_domain(self):
        q = assess_source(Source(title="x", url="not a url"))
        assert q.tier == "unknown"


class TestSignals:
    def test_doi_boosts_and_reclassifies(self):
        q = assess_source(src("https://doi.org/10.1000/xyz123"))
        assert q.category == "peer-reviewed / academic"
        assert any("DOI" in s for s in q.signals)

    def test_conflicting_signals_gov_blog(self):
        # .gov keeps authority but the blog path is flagged and penalized.
        q = assess_source(src("https://www.nist.gov/blog/some-post"))
        assert q.category == "standards organization"
        assert any("blog" in w.lower() for w in q.warnings)
        assert q.score < assess_source(src("https://www.nist.gov/report")).score

    def test_plain_http_penalized(self):
        secure = assess_source(src("https://example-site.com/a"))
        insecure = assess_source(src("http://example-site.com/a"))
        assert insecure.score < secure.score
        assert any("HTTP" in w for w in insecure.warnings)

    def test_not_a_truth_score(self):
        # Even top-tier sources stay below a "certainty" ceiling of 100 unless
        # independently boosted, and the model text never claims truth.
        q = assess_source(src("https://www.nature.com/articles/x"))
        assert q.score <= 100
        assert "truth" not in " ".join(q.signals).lower()


class TestDeterminismAndHelpers:
    def test_deterministic(self):
        url = "https://arxiv.org/abs/2401.0001"
        assert assess_source(src(url)) == assess_source(src(url))

    def test_with_quality_idempotent(self):
        s = with_quality(src("https://arxiv.org/abs/1"))
        again = with_quality(s)
        assert again.quality == s.quality

    def test_tier_distribution(self):
        sources = [
            with_quality(src("https://nature.com/a")),
            with_quality(src("https://reddit.com/r/x")),
            with_quality(src("https://nature.com/b")),
        ]
        dist = quality_tier_distribution(sources)
        assert dist == {"high": 2, "low": 1}


class TestSelectionIntegration:
    def _ev(self, url, rel, query="q"):
        return Evidence(source=with_quality(src(url)), content="c", query=query,
                        relevance_score=rel)

    def test_quality_breaks_relevance_ties(self):
        low_quality = self._ev("https://reddit.com/r/a/1", 0.8)
        high_quality = self._ev("https://nature.com/articles/1", 0.8)
        picked = select_evidence([low_quality, high_quality], 1)
        assert picked[0].source.url == "https://nature.com/articles/1"

    def test_relevance_still_dominates_quality(self):
        relevant_low_q = self._ev("https://reddit.com/r/a/1", 0.95)
        irrelevant_high_q = self._ev("https://nature.com/articles/1", 0.2)
        picked = select_evidence([irrelevant_high_q, relevant_low_q], 1)
        assert picked[0].source.url == "https://reddit.com/r/a/1"

    def test_low_quality_unique_evidence_not_discarded(self):
        # Round-robin coverage keeps the only source for query q2 even
        # though it is low quality.
        items = [
            self._ev("https://nature.com/a", 0.9, query="q1"),
            self._ev("https://nature.com/b", 0.8, query="q1"),
            self._ev("https://reddit.com/r/unique", 0.5, query="q2"),
        ]
        picked = select_evidence(items, 2)
        assert any(e.query == "q2" for e in picked)
