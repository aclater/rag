# Evaluation case schema

Each collection's golden set is one YAML file: a header plus a list of cases.

```yaml
collection: mpep                   # collection name in the knowledge base
corpus_version: "Ninth Edition, Revision 01.2024"   # what the expected sources were verified against
verified_on: 2026-10-15            # date the sources were checked against the authoritative text
source_url: https://www.uspto.gov/web/offices/pac/mpep/

cases:
  - id: mpep-001                   # stable, never reused
    type: lookup                   # lookup | exact_match | multi_hop | abstain | edition
    difficulty: easy               # easy | medium | hard
    question: "…"                  # phrased the way a user would actually ask
    expected_answer: >-            # what a correct answer must convey (not the exact wording)
      …
    expected_sources:              # sections that must be retrieved and cited; empty for abstain
      - "2143"
    must_mention: ["obvious to try"]   # optional: terms the answer must contain (case-insensitive)
    must_not_mention: []           # optional: terms indicating a wrong or hallucinated answer
    expect_abstain: false          # true when the correct behaviour is "the corpus doesn't say"
    notes: "…"                     # optional: why the case exists, caveats, confidence
    confidence: high               # high | medium | low: how sure the drafter is about the expected answer
```

## Types

| Type | Tests |
| --- | --- |
| `lookup` | Finding and summarising the right section for a natural-language question. |
| `exact_match` | Queries that hinge on an identifier: a section number, a statute (35 U.S.C. §), a rule (37 CFR §). Dense retrieval alone tends to miss these; the keyword half of hybrid search should catch them. |
| `multi_hop` | Answers that need two or more sections combined. |
| `abstain` | Questions the corpus doesn't answer. The correct answer says so and cites nothing. |
| `edition` | Answers that depend on which revision of the corpus is indexed. They detect a stale corpus and test that the system doesn't present newer outside knowledge as the corpus's position. |

## Section identifiers

Sources are MPEP section identifiers as strings (`"2143"`, `"2164.01(a)"`,
`"706.07(d)"`). A retrieved chunk counts as a hit for an expected source if its
`section` metadata equals the expected identifier **or is a subsection of it**
(`"2143.01"` satisfies `"2143"`, but `"2143"` doesn't satisfy `"2143.01"`).
