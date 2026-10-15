# Evaluation

The golden sets here define what "better" means. Every change to models,
chunking, retrieval or prompts reports these numbers, before and after.

| File | What |
| --- | --- |
| [`schema.md`](schema.md) | The case format |
| [`mpep.yaml`](mpep.yaml) | The MPEP golden set (public corpus) |
| [`private-templates.md`](private-templates.md) | Templates for private collections; fill them in `eval/private/`, which is gitignored |

**Status: draft for maintainer review.** The MPEP cases were drafted by an
agent, and every expected source was checked against the live USPTO MPEP
(Ninth Edition, Revision 01.2024) on 2026-10-15. Cases marked
`confidence: medium` or `low` need a human look.

## Metrics

Computed per case, then averaged per collection and per case type.

### Retrieval (no LLM involved)

Run against the `search` tool's ranked results.

- **recall@k** (k = 5, 10, 20): the fraction of a case's `expected_sources`
  that appear among the top k results. A result matches an expected source if
  its section equals it or is a subsection of it (see `schema.md`). Cases with
  no expected sources (`abstain`) are excluded.
- **MRR** (mean reciprocal rank): `1 / rank` of the first result that matches
  any expected source; 0 if none in the top 20. Rewards putting the right
  section first.
- **exact-match recall@5**: recall@5 restricted to `exact_match` cases. This
  watches the keyword half of hybrid search specifically.

### Answers (LLM in the loop)

Run against a full chat turn, with the model calling the tools.

- **citation accuracy:** of the citations in the answer, the fraction that
  (a) were actually returned by a tool call in that turn, and (b) match an
  expected source. Part (a) catches fabricated citations; the citation
  validator should make it 1.0 by construction.
- **citation coverage:** the fraction of `expected_sources` that the answer cites.
- **abstention correctness:** for `expect_abstain: true` cases, did the answer
  say the corpus doesn't cover it, and cite nothing? For all other cases, did it
  *not* abstain? Reported as both a false-abstention rate and a missed-abstention
  rate, since the two failure modes matter differently.
- **content checks:** `must_mention` terms present, `must_not_mention` absent
  (case-insensitive). A cheap, deterministic proxy, not a full grade.
- **graded correctness (nightly):** an LLM judge compares the answer with
  `expected_answer` on a 0–2 scale (wrong, partial, right), with its reasoning
  stored next to the score. Run with a different model from the one under test.

## How it runs

The walking skeleton provides the search tool (`search(query, collections, k)`
returning ranked chunks with `section` metadata) and a chat endpoint. The
harness (to be added with the skeleton) will:

1. Load `eval/*.yaml` and any `eval/private/*.yaml`.
2. For retrieval metrics, call `search` directly for each case. These are fast,
   deterministic and cheap enough for CI.
3. For answer metrics, send each question as a chat turn, record the tool calls
   and citations, then score. These run nightly or on demand, per model profile
   (`home`, `laptop`).
4. Write a JSON report (per case and aggregate, with the model, embedding model,
   corpus version and git revision) and compare it with the last stored
   baseline. A drop beyond a set tolerance fails the run.

## Adding cases

- Phrase questions the way you'd really ask them.
- Verify `expected_sources` against the authoritative text and update
  `verified_on`; never guess a section number.
- Give each case a new `id`; never renumber or reuse one.
- When the indexed corpus moves to a new revision, re-verify the `edition`
  cases first; they're designed to change.
