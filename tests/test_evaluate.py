from rag.evaluate import matches, score_case


def test_subsection_matches_parent_but_not_reverse() -> None:
    assert matches("2143.01", "2143")
    assert matches("2164.01(a)", "2164.01")
    assert matches("2143", "2143")
    assert not matches("2143", "2143.01")
    assert not matches("21430", "2143")


def test_recall_and_reciprocal_rank() -> None:
    recall, rr = score_case(["2143", "2141"], ["608.01", "2143.03", "1504"] + ["x"] * 20)
    assert recall[5] == 0.5
    assert rr == 0.5


def test_no_match_scores_zero() -> None:
    recall, rr = score_case(["2106"], ["2143"] * 25)
    assert recall == {5: 0.0, 10: 0.0, 20: 0.0}
    assert rr == 0.0


def test_identifier_pattern_finds_section_ids_not_years_or_noise() -> None:
    from rag.search import IDENTIFIER

    assert IDENTIFIER.findall("MPEP 2164.01(a) and 608.01(n)") == ["2164.01(a)", "608.01(n)"]
    assert IDENTIFIER.findall("see 2143 for KSR") == ["2143"]
    assert "35" in IDENTIFIER.findall("35 U.S.C. 103")  # harmless: no such MPEP section exists
