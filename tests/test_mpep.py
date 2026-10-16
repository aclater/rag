from rag.connectors.mpep import parent_of, split_sections

ITEMS = [
    ("section_header", "Chapter 2100 Patentability"),
    ("section_header", "2141 Examination Guidelines 2143 Examples of Basic Requirements"),
    ("section_header", "2141 Examination Guidelines for Determining Obviousness [R-01.2024]"),
    ("text", "Graham v. John Deere sets out the factual inquiries."),
    ("page_footer", "Rev. 01.2024, November 2024 2100-1"),
    ("section_header", "2142-2142.99 [Reserved]"),
    ("section_header", "2143 Examples of Basic Requirements of a Prima Facie Case [R-01.2024]"),
    ("section_header", "I. EXEMPLARY RATIONALES"),
    ("list_item", "(A) Combining prior art elements according to known methods."),
    ("section_header", "35 U.S.C. 103 Conditions for patentability; non-obvious subject matter."),
    ("section_header", "2143.01 Suggestion or Motivation To Modify the References [R-07.2022]"),
    ("text", "Text of 2143.01."),
    ("section_header", "2164.01(a) Undue Experimentation Factors [R-08.2017]"),
    ("text", "The Wands factors."),
]


def test_split_sections_uses_revision_tagged_headings() -> None:
    secs = split_sections(ITEMS, "https://x/mpep-2100.pdf")
    assert [s["section"] for s in secs] == ["2141", "2143", "2143.01", "2164.01(a)"]
    assert secs[1]["title"] == "Examples of Basic Requirements of a Prima Facie Case"
    assert secs[1]["revision"] == "01.2024"


def test_bodies_keep_subheadings_and_statutes_but_drop_page_furniture() -> None:
    secs = {s["section"]: s for s in split_sections(ITEMS, "u")}
    assert "Rev. 01.2024" not in secs["2141"]["body"]
    body = secs["2143"]["body"]
    assert "## I. EXEMPLARY RATIONALES" in body
    assert "(A) Combining prior art elements" in body
    assert "## 35 U.S.C. 103" in body


def test_table_of_contents_and_reserved_ranges_are_not_sections() -> None:
    ids = [s["section"] for s in split_sections(ITEMS, "u")]
    assert "2142-2142.99" not in ids
    assert ids.count("2141") == 1


def test_parent_of() -> None:
    assert parent_of("2164.01(a)") == "2164.01"
    assert parent_of("2143.01") == "2143"
    assert parent_of("2143") is None
