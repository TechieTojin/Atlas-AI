import pytest
from pydantic import ValidationError

from src.models.research import Critique, CriticDecision, normalize_url
from src.tools.search import dedupe_evidence, result_to_evidence, run_searches
from tests.conftest import make_evidence, make_search_fn


class TestNormalizeUrl:
    def test_strips_fragment_and_trailing_slash(self):
        assert normalize_url("https://Example.com/Path/#frag") == "https://example.com/Path"

    def test_strips_tracking_params_keeps_real_ones(self):
        url = "https://example.com/a?utm_source=x&id=5&fbclid=y"
        assert normalize_url(url) == "https://example.com/a?id=5"

    def test_unparseable_url_returned_as_is(self):
        assert normalize_url("not a url") == "not a url"


class TestDedup:
    def test_duplicate_urls_dropped(self):
        items = [
            make_evidence("https://example.com/a"),
            make_evidence("https://example.com/a/"),
            make_evidence("https://example.com/b"),
        ]
        unique, seen = dedupe_evidence(items)
        assert [e.source.url for e in unique] == [
            "https://example.com/a",
            "https://example.com/b",
        ]
        assert len(seen) == 2

    def test_respects_previously_seen_urls(self):
        prior = {normalize_url("https://example.com/a")}
        unique, seen = dedupe_evidence([make_evidence("https://example.com/a")], prior)
        assert unique == []
        assert seen == prior


class TestResultNormalization:
    def test_valid_result(self):
        ev = result_to_evidence(
            {"url": "https://x.com/p", "title": "T", "content": "C", "score": 0.9},
            query="q1",
        )
        assert ev is not None
        assert ev.source.domain == "x.com"
        assert ev.query == "q1"
        assert ev.relevance_score == 0.9

    def test_missing_url_or_content_rejected(self):
        assert result_to_evidence({"title": "T", "content": "C"}, "q") is None
        assert result_to_evidence({"url": "https://x.com"}, "q") is None


class TestRunSearches:
    def test_search_failure_is_isolated(self):
        def flaky(query, max_results):
            if query == "bad":
                raise RuntimeError("network down")
            return [{"url": "https://x.com/a", "title": "T", "content": "C"}]

        evidence = run_searches(flaky, ["bad", "good"], 5)
        assert len(evidence) == 1
        assert evidence[0].query == "good"

    def test_empty_results_handled(self):
        evidence = run_searches(make_search_fn(default=[]), ["q1", "q2"], 5)
        assert evidence == []

    def test_max_results_respected(self):
        rows = [{"url": f"https://x.com/{i}", "title": "T", "content": "C"} for i in range(10)]
        evidence = run_searches(make_search_fn(default=rows), ["q"], 3)
        assert len(evidence) == 3


class TestCritiqueModel:
    def test_score_bounds_enforced(self):
        with pytest.raises(ValidationError):
            Critique(
                overall_score=11,
                coverage_assessment="x",
                decision=CriticDecision.SYNTHESIZE,
                reasoning="r",
            )
