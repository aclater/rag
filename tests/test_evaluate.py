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
