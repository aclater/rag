from rag.answers import score_answer

ABSTAIN_CASE = {"id": "x", "type": "abstain", "expected_sources": [], "expect_abstain": True}


def test_abstention_phrasings() -> None:
    for answer in (
        "The collections I have access to do not include any information on that.",
        "The indexed collections do not contain information on that.",
        "I couldn't find anything relevant.",
    ):
        assert score_answer(ABSTAIN_CASE, answer, set())["abstained"], answer


def test_citations_grounded_against_returned_ids() -> None:
    case = {"id": "y", "type": "lookup", "expected_sources": ["2143"]}
    scored = score_answer(case, "Rationales [mpep:2143#1] and [mpep:9.02#0].", {"mpep:2143#1"})
    assert scored["citation_grounded"] == 0.5
    assert scored["citation_coverage"] == 1.0


def test_native_gpt_oss_citation_brackets() -> None:
    case = {"id": "z", "type": "exact_match", "expected_sources": ["608.01(n)"]}
    scored = score_answer(
        case, "In the alternative only【mpep:608.01(n)#0】.", {"mpep:608.01(n)#0"}
    )
    assert scored["citation_coverage"] == 1.0


def test_grouped_citations_and_non_citation_brackets() -> None:
    from rag.answers import citations

    text = "Rules [mpep:608.01(n)#0, mpep:608.01(n)#1]; see [1] and [mpep:2143#1]."
    assert citations(text) == ["mpep:608.01(n)#0", "mpep:608.01(n)#1", "mpep:2143#1"]
