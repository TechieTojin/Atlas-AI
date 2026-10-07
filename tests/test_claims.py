"""Feature 5: deterministic claim-level citation mapping."""

from src.evaluation.claims import claims_for_source, extract_claims

REPORT = """\
## Technical Barriers

Sensors degrade badly in heavy rain [1]. LiDAR and cameras both struggle,
and redundancy helps only partially [2][4].

- Separator failure cascades quickly [3].
- Costs remain high with no citation here.

## Regulation

Rules differ across states [2]. Invalid marker [9] should be ignored.

## Sources

1. [A](https://a.com)
"""


class TestExtraction:
    def test_claims_extracted_with_sections(self):
        claims = extract_claims(REPORT, valid_max=4)
        texts = [c.text for c in claims]
        assert any("Sensors degrade" in t for t in texts)
        first = next(c for c in claims if "Sensors degrade" in c.text)
        assert first.citations == [1]
        assert first.section == "Technical Barriers"

    def test_multi_citation_claim_lists_all_sources(self):
        claims = extract_claims(REPORT, valid_max=4)
        multi = next(c for c in claims if "redundancy" in c.text)
        assert multi.citations == [2, 4]

    def test_list_items_are_claims(self):
        claims = extract_claims(REPORT, valid_max=4)
        assert any(c.citations == [3] and "Separator" in c.text for c in claims)

    def test_uncited_sentences_are_not_claims(self):
        claims = extract_claims(REPORT, valid_max=4)
        assert not any("Costs remain high" in c.text for c in claims)

    def test_invalid_markers_ignored(self):
        claims = extract_claims(REPORT, valid_max=4)
        regulation = next(c for c in claims if "Invalid marker" in c.text or "Rules differ" in c.text)
        assert 9 not in regulation.citations

    def test_sources_section_excluded(self):
        claims = extract_claims(REPORT, valid_max=4)
        assert not any("a.com" in c.text for c in claims)

    def test_malformed_citations_ignored(self):
        claims = extract_claims("Claim [abc] and [1.5] and [] here.", valid_max=4)
        assert claims == []

    def test_repeated_citation_supports_multiple_claims(self):
        claims = extract_claims(REPORT, valid_max=4)
        supported = claims_for_source(claims, 2)
        assert len(supported) == 2  # redundancy claim + regulation claim

    def test_empty_report(self):
        assert extract_claims("", valid_max=4) == []

    def test_deterministic(self):
        assert extract_claims(REPORT, 4) == extract_claims(REPORT, 4)
