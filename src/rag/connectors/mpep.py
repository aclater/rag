"""USPTO Manual of Patent Examining Procedure connector.

Source: the official chapter PDFs from https://www.uspto.gov/web/offices/pac/mpep/
(the e9r-01-2024.zip archive for the Ninth Edition, Revision 01.2024), parsed
with Docling. Section boundaries come from the MPEP's own heading format: every
section heading ends with a revision tag, e.g.
"2143.01 Suggestion or Motivation To Modify the References [R-01.2024]".
Statute and rule headers (35 U.S.C., 37 CFR) and Roman-numeral subheadings stay
inside their section. "[Reserved]" ranges are skipped.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from rag.chunking import SourceSection
from rag.ingest import CollectionSpec

log = logging.getLogger(__name__)

CORPUS_VERSION = "Ninth Edition, Revision 01.2024"
BASE_URL = "https://www.uspto.gov/web/offices/pac/mpep"
SPEC = CollectionSpec(
    name="mpep",
    label="MPEP",
    source=f"{BASE_URL}/e9r-01-2024.zip",
    corpus_version=CORPUS_VERSION,
    description="USPTO Manual of Patent Examining Procedure (public).",
)

HEADING = re.compile(
    r"^(?P<id>\d{3,4}(?:\.\d{1,2})?(?:\([a-z0-9]+\))*)\s+(?P<title>.+?)\s*"
    r"\[R-(?P<rev>\d{2}\.\d{4})\]\s*$"
)
SKIP_LABELS = {"page_header", "page_footer", "picture", "caption", "footnote"}
CHAPTER_FILE = re.compile(r"^mpep-(\d{4})\.pdf$")


def parent_of(section: str) -> str | None:
    """'2164.01(a)' -> '2164.01'; '2143.01' -> '2143'; '2143' -> None."""
    m = re.match(r"^(.*)\([a-z0-9]+\)$", section)
    if m:
        return m.group(1)
    if "." in section:
        return section.rsplit(".", 1)[0]
    return None


def split_sections(items: Sequence[tuple[str, str]], source_url: str) -> list[dict[str, Any]]:
    """Group (label, text) items into sections at revision-tagged headings."""
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for label, raw in items:
        text = " ".join(raw.split())
        if not text or label in SKIP_LABELS:
            continue
        m = HEADING.match(text)
        if m and m.group("title").strip().lower() != "[reserved]":
            current = {
                "section": m.group("id"),
                "title": m.group("title").strip(),
                "revision": m.group("rev"),
                "source_url": source_url,
                "parts": [],
            }
            sections.append(current)
            continue
        if current is None:
            continue  # chapter title and table of contents precede the first section
        current["parts"].append(f"## {text}" if label == "section_header" else text)
    for s in sections:
        s["body"] = "\n\n".join(s.pop("parts"))
    return sections


def _parse_chapter(pdf: str) -> list[dict[str, Any]]:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions(do_ocr=False, do_table_structure=False)
    artifacts = os.environ.get("DOCLING_ARTIFACTS_PATH")
    if artifacts:
        opts.artifacts_path = artifacts
    conv = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )
    doc = conv.convert(pdf).document
    items = [
        (str(getattr(it, "label", "")).rsplit(".", 1)[-1].lower(), getattr(it, "text", "") or "")
        for it, _ in doc.iterate_items()
    ]
    return split_sections(items, f"{BASE_URL}/{Path(pdf).name}")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load(
    pdf_dir: Path, *, parse_cache: Path | None = None, workers: int | None = None
) -> tuple[CollectionSpec, list[SourceSection]]:
    """Parse every chapter PDF in pdf_dir (cached by file hash) into sections."""
    chapters = sorted(p for p in pdf_dir.iterdir() if CHAPTER_FILE.match(p.name))
    if not chapters:
        raise FileNotFoundError(f"no mpep-NNNN.pdf chapter files in {pdf_dir}")
    if parse_cache:
        parse_cache.mkdir(parents=True, exist_ok=True)
    parsed: dict[str, list[dict[str, Any]]] = {}
    todo: list[Path] = []
    for p in chapters:
        cached = parse_cache / f"{p.stem}-{_sha256(p)[:16]}.json" if parse_cache else None
        if cached and cached.exists():
            parsed[p.name] = json.loads(cached.read_text())
        else:
            todo.append(p)
    n = workers or int(os.environ.get("RAG_INGEST_WORKERS", "3"))
    if todo:
        log.info("parsing %d chapter(s) with %d worker(s)", len(todo), n)
        with ProcessPoolExecutor(max_workers=n) as pool:
            futures = {pool.submit(_parse_chapter, str(p)): p for p in todo}
            # Cache each chapter as soon as it's parsed, so an interrupted run
            # (e.g. a worker killed for memory) loses nothing already done. A
            # failed chapter doesn't stop the others; the run fails at the end
            # rather than index a collection with chapters missing.
            failed: list[str] = []
            for fut in as_completed(futures):
                p = futures[fut]
                try:
                    secs = fut.result()
                except Exception:
                    log.exception("%s: parse failed", p.name)
                    failed.append(p.name)
                    continue
                parsed[p.name] = secs
                log.info("%s: %d sections", p.name, len(secs))
                if parse_cache:
                    out = parse_cache / f"{p.stem}-{_sha256(p)[:16]}.json"
                    out.write_text(json.dumps(secs))
        if failed:
            raise RuntimeError(
                f"could not parse {', '.join(sorted(failed))}; the other chapters are "
                "cached, so a rerun only retries these"
            )
    sections: list[SourceSection] = []
    seen: set[str] = set()
    for p in chapters:
        for s in parsed[p.name]:
            if s["section"] in seen:
                log.warning("duplicate section %s in %s; keeping the first", s["section"], p.name)
                continue
            seen.add(s["section"])
            sections.append(
                SourceSection(
                    section=s["section"],
                    title=s["title"],
                    parent=parent_of(s["section"]),
                    source_url=s["source_url"],
                    body=s["body"],
                )
            )
    return SPEC, sections
