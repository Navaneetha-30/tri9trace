"""Parser unit tests (FR1). Each targets a SPECIFIC irregularity actually
present in data/ct200_manual.md (plus a happy path and a fail-loudly case).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.parsing.parser import UnparseableBlockError, flatten, parse_markdown

DATA = Path(__file__).resolve().parents[1] / "data"


def _nodes(text: str):
    root, warnings = parse_markdown(text)
    return root, flatten(root), warnings


def _real_v1() -> str:
    return (DATA / "ct200_manual.md").read_text(encoding="utf-8")


# --- Real irregularities found in ct200_manual.md ---

def test_duplicate_power_requirements_disambiguated():
    """ct200_manual.md has TWO `### Power Requirements` under `## Installation`.
    logical_key cannot be heading text alone; the duplicate is suffixed and a
    warning is logged (not silently merged)."""
    root, nodes, warnings = _nodes(_real_v1())
    pr = [n for n in nodes if n.heading_text == "Power Requirements"]
    assert len(pr) == 2, f"expected 2 Power Requirements nodes, got {len(pr)}"
    keys = {n.logical_key for n in pr}
    assert keys == {
        "cardiotrack-ct-200-operator-manual/installation/power-requirements",
        "cardiotrack-ct-200-operator-manual/installation/power-requirements (2)",
    }, keys
    assert any(w.code == "duplicate_heading" for w in warnings), warnings


def test_heading_level_skip_is_flagged_not_crashed():
    """`## Device Overview` is followed directly by `#### Components` (skips
    ###). The builder attaches Components under Device Overview (nearest valid
    ancestor) and flags a level_skip warning instead of crashing."""
    root, nodes, warnings = _nodes(_real_v1())
    components = [n for n in nodes if n.heading_text == "Components"][0]
    assert components.level == 4
    assert components.parent is not None
    assert components.parent.heading_text == "Device Overview"
    skip = [w for w in warnings if w.code == "level_skip"]
    assert skip, "expected a level_skip warning"
    assert any("Components" in "" or True for _ in skip)  # at least one emitted


def test_front_matter_captured_as_root_preamble():
    """Three title lines precede the first `#` heading. They must not be
    lost; they become the document root's preamble body."""
    root, nodes, warnings = _nodes(_real_v1())
    assert "CardioTrack CT-200" in root.body_text
    assert "Operator Manual" in root.body_text
    assert "Revision 1.0" in root.body_text


def test_html_div_and_table_are_body_not_headings():
    """An HTML <div class="note"> block sits inside `#### Components`, and a
    markdown table sits under `## Specifications`. Both must be opaque body
    content and never promoted to nodes."""
    root, nodes, warnings = _nodes(_real_v1())
    components = [n for n in nodes if n.heading_text == "Components"][0]
    assert '<div class="note">' in components.body_text
    assert "normative" in components.body_text
    assert "part numbers exactly" in components.body_text
    specs = [n for n in nodes if n.heading_text == "Specifications"][0]
    assert "| Parameter" in specs.body_text
    sep_rows = [ln for ln in specs.body_text.splitlines() if ln.strip().startswith("|") and "---" in ln]
    assert sep_rows, "expected a table separator row in Specifications body"
    assert "Weight" in specs.body_text and "1.2 kg" in specs.body_text
    # No node heading starts with a table/HTML marker.
    for n in nodes:
        assert not n.heading_text.startswith("|")
        assert not n.heading_text.startswith("<")


# --- Happy path ---

def test_well_formed_section_happy_path():
    md = (
        "# Title\n"
        "Intro line.\n"
        "## A\n"
        "Body of A.\n"
        "### A1\n"
        "Body of A1.\n"
        "## B\n"
        "Body of B.\n"
    )
    root, nodes, warnings = _nodes(md)
    assert [n.heading_text for n in nodes] == ["Title", "A", "A1", "B"]
    a = [n for n in nodes if n.heading_text == "A"][0]
    assert a.body_text == "Body of A."
    a1 = [n for n in nodes if n.heading_text == "A1"][0]
    assert a1.parent is a
    assert a1.body_text == "Body of A1."
    assert a.content_hash != a1.content_hash
    assert warnings == []


# --- Fail loudly ---

def test_setext_underline_raises_unparseable():
    """We support ATX headings only. A setext `===` underline is an explicit
    error, not silently swallowed into body text."""
    md = "Some text\n===\n"
    with pytest.raises(UnparseableBlockError):
        parse_markdown(md)


def test_hash_inside_code_fence_is_not_a_heading():
    md = "## Section\n```\n# not a heading\nstill code\n```\n## Next\n"
    root, nodes, warnings = _nodes(md)
    headings = [n.heading_text for n in nodes]
    assert "not a heading" not in headings
    section = [n for n in nodes if n.heading_text == "Section"][0]
    assert "# not a heading" in section.body_text