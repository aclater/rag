"""Structure-aware chunking: one source section yields one or more chunks.

Chunks never cross a section boundary, so every chunk carries exactly one
section id. Long sections are split on paragraph boundaries with a one-paragraph
overlap. Each chunk starts with a short contextual header (collection, section
id, title, parent) that is embedded and keyword-indexed with the text, which
keeps exact identifiers like "2143.01" searchable inside every chunk.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_CHARS = 3600  # about 900 tokens: well inside the embedder's 8192-token window


@dataclass(frozen=True)
class SourceSection:
    section: str
    title: str
    parent: str | None
    source_url: str
    body: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    section: str
    index: int
    text: str


def header(collection_label: str, s: SourceSection) -> str:
    parent = f" (part of {s.parent})" if s.parent else ""
    return f"{collection_label} § {s.section} {s.title}{parent}"


def split_paragraphs(body: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Group paragraphs into windows of at most max_chars, overlapping by one paragraph."""
    paras = [p.strip() for p in body.split("\n\n") if p.strip()]
    if not paras:
        return []
    windows: list[str] = []
    current: list[str] = []
    size = 0
    for p in paras:
        # A single oversized paragraph is hard-wrapped rather than dropped.
        pieces = [p[i : i + max_chars] for i in range(0, len(p), max_chars)] or [p]
        for piece in pieces:
            if current and size + len(piece) + 2 > max_chars:
                windows.append("\n\n".join(current))
                current = [current[-1]] if len(current[-1]) < max_chars // 2 else []
                size = sum(len(x) + 2 for x in current)
            current.append(piece)
            size += len(piece) + 2
    if current:
        windows.append("\n\n".join(current))
    return windows


def chunk_section(collection: str, collection_label: str, s: SourceSection) -> list[Chunk]:
    head = header(collection_label, s)
    windows = split_paragraphs(s.body) or [""]
    return [
        Chunk(
            chunk_id=f"{collection}:{s.section}#{i}",
            section=s.section,
            index=i,
            text=f"{head}\n\n{w}".strip(),
        )
        for i, w in enumerate(windows)
    ]
