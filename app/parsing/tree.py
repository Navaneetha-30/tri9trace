"""Node tree data structure produced by the parser (TRD section 2/4).

A ParseNode is an in-memory node: heading text, level, own body text,
parent/children links, a stable logical_key, and a content_hash. This is
the intermediate representation the ingestion pipeline turns into rows.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field


def _normalize(text: str) -> str:
    """Collapse internal whitespace and strip, for stable hashing."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _slug(text: str) -> str:
    """Slugify a heading for use in a path-based logical key."""
    s = text.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def content_hash(heading_text: str, body_text: str) -> str:
    return hashlib.sha256(_normalize(heading_text + "\n" + body_text).encode("utf-8")).hexdigest()


@dataclass
class ParseNode:
    heading_text: str
    level: int
    body_text: str = ""
    parent: "ParseNode | None" = None
    children: list["ParseNode"] = field(default_factory=list)
    logical_key: str = ""
    order_in_parent: int = 0

    def add_body(self, line: str) -> None:
        self.body_text = (self.body_text + "\n" + line).strip("\n") if self.body_text else line

    def finalize(self) -> None:
        self.body_text = self.body_text.strip()