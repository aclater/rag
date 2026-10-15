# Private collection templates

Your Drive documents, git repositories, web sources and any personal or
work collections can't go in this public repo. Fill these templates **locally**
in `eval/private/<collection>.yaml`, which is gitignored, using the same schema
as `mpep.yaml` (see `schema.md`). The harness picks those files up automatically.

How to fill one:

1. Copy a template block into `eval/private/<collection>.yaml`.
2. Replace each `<placeholder>` with something real from that collection, phrased
   the way you'd actually ask.
3. Set `expected_sources` to the document identifiers the knowledge base stores
   (file path, Drive file name, URL), which you can find with the `search` tool.
4. Aim for 10–15 cases per collection, covering every `type`, including at least
   two `abstain` cases (things the collection doesn't contain).

## Documents (Google Drive)

| # | Type | Template |
| --- | --- | --- |
| 1 | lookup | "What does `<document title>` say about `<topic>`?" |
| 2 | lookup | "Summarise the main recommendations in `<report>`." |
| 3 | exact_match | "Which document mentions `<exact identifier: contract number, ticket ID, part number>`?" |
| 4 | exact_match | "What was decided about `<project codename>` on `<date>`?" |
| 5 | multi_hop | "How does the plan in `<doc A>` compare with the budget in `<doc B>`?" |
| 6 | multi_hop | "Which `<items>` in `<doc A>` are also listed in `<doc B>`?" |
| 7 | lookup | "Who is responsible for `<task>` according to `<doc>`?" |
| 8 | edition | "What is the latest version of `<living document>` and what changed in it?" (tests freshness after re-ingest) |
| 9 | abstain | "What does `<a document you know isn't in the folder>` say?" |
| 10 | abstain | "What's the `<figure>` for `<year the documents don't cover>`?" |
| 11 | lookup | A question in Dutch about an English document, or the reverse (multilingual retrieval). |
| 12 | lookup | A question about a table or figure in a PDF or slide deck (tests parsing). |

## Git repositories

| # | Type | Template |
| --- | --- | --- |
| 1 | lookup | "How does `<repo>` handle `<concern, e.g. configuration, retries, auth>`?" |
| 2 | exact_match | "Where is `<function or class name>` defined?" |
| 3 | exact_match | "What does the `<CLI flag or env var>` option do?" |
| 4 | lookup | "What are the setup steps in `<repo>`'s README?" |
| 5 | multi_hop | "Which repos depend on `<library>`, and at what versions?" |
| 6 | multi_hop | "How does `<component A>` call `<component B>`?" |
| 7 | lookup | "Why was `<design decision>` made?" (answer should come from an ADR or design doc) |
| 8 | edition | "What changed in `<file>` in the last ingested revision?" (freshness) |
| 9 | abstain | "How does `<repo>` implement `<feature it doesn't have>`?" |
| 10 | abstain | "What's in `<repo that isn't indexed>`?" |
| 11 | exact_match | A query containing an error message string verbatim. |

## Web sources

| # | Type | Template |
| --- | --- | --- |
| 1 | lookup | "What does `<site/page>` say about `<topic>`?" |
| 2 | exact_match | "What is `<standard/spec identifier, e.g. RFC or NIST SP number>` about?" |
| 3 | multi_hop | "Do `<source A>` and `<source B>` agree on `<claim>`?" |
| 4 | edition | "When was `<page>` last updated, and what's the current guidance?" |
| 5 | abstain | "What does `<source not ingested>` say about `<topic>`?" |
| 6 | lookup | A question whose answer sits deep in a long page (tests chunking). |
| 7 | lookup | "List the `<items>` described on `<page>`." (tests completeness) |
| 8 | abstain | A question about events after the last crawl date. |
| 9 | exact_match | A query with a product or version string, e.g. "`<tool> <version>` release notes". |
| 10 | multi_hop | "Summarise what `<three pages>` say about `<topic>`." |

## Personal and work collections

The old suite also had collections about people and organisations (an org chart
and professional backgrounds) and policy documents. If you keep such
collections, add their golden sets here locally too, with extra cases for:

- **abstain on personal data that isn't there:** e.g. "What is `<person>`'s home
  address?" must abstain even if the model could guess;
- **no cross-collection leakage:** a question scoped to one collection mustn't
  cite another;
- **injection resistance:** a document containing instructions ("ignore previous
  instructions…") must be treated as content, not followed. The old ragprobe
  suite had good cases for this (`tests/injection.yaml`, `context_poisoning.yaml`
  in the archived aclater/ragprobe repo); port the relevant ones.
