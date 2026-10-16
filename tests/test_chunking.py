from rag.chunking import MAX_CHARS, SourceSection, chunk_section, split_paragraphs


def section(body: str) -> SourceSection:
    return SourceSection(
        "2143.01", "Suggestion or Motivation", "2143", "https://x/mpep-2100.pdf", body
    )


def test_short_section_is_one_chunk_with_header() -> None:
    chunks = chunk_section("mpep", "MPEP", section("First paragraph.\n\nSecond."))
    assert [c.chunk_id for c in chunks] == ["mpep:2143.01#0"]
    assert chunks[0].text.startswith("MPEP § 2143.01 Suggestion or Motivation (part of 2143)")
    assert "Second." in chunks[0].text


def test_long_section_splits_on_paragraphs_with_overlap() -> None:
    paras = [f"Paragraph {i} " + "x" * 900 for i in range(10)]
    windows = split_paragraphs("\n\n".join(paras))
    assert len(windows) > 1
    assert all(len(w) <= MAX_CHARS for w in windows)
    # One-paragraph overlap between consecutive windows.
    assert windows[0].split("\n\n")[-1] == windows[1].split("\n\n")[0]


def test_oversized_paragraph_is_wrapped_not_dropped() -> None:
    windows = split_paragraphs("y" * (MAX_CHARS * 2 + 10))
    assert sum(len(w.replace("\n", "")) for w in windows) >= MAX_CHARS * 2
    assert all(len(w) <= MAX_CHARS for w in windows)


def test_chunks_never_cross_sections() -> None:
    chunks = chunk_section("mpep", "MPEP", section("\n\n".join(["z" * 1000] * 12)))
    assert {c.section for c in chunks} == {"2143.01"}
    assert [c.index for c in chunks] == list(range(len(chunks)))
