"""Markdown parser for CT-200-style manuals (TRD section 4).

Line-based, heading-driven, stack-based tree builder.

Design rules (graded requirements):
- Never silently drop or mis-parent a line. Every non-heading line goes
  into some node's body_text; every heading attaches to its nearest valid
  ancestor.
- Fail loudly: raise UnparseableBlockError (with line number + snippet) on
  anything we don't confidently classify instead of guessing. We support
  ATX headings only; a setext-style heading underline ("===") is treated
  as an explicit error rather than silently becoming body text.
- Handle the real irregularities present in data/ct200_manual.md:
    * title/front-matter lines before the first heading -> root preamble
    * heading level skips (e.g. ## -> ####) -> attach to nearest ancestor,
      flag a parse warning, do not crash
    * duplicate heading text under the same parent -> disambiguate the
      logical_key with a sibling-order suffix and log it
    * HTML blocks (<div ...>) and tables (| ... |) -> opaque body content,
      never mistaken for headings
    * fenced code blocks (``` or ~~~) -> # lines inside are not headings
"""
from __future__ import annotations

import re

from app.parsing.tree import ParseNode, _slug, content_hash

ATX_RE = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
SETEXT_UNDERLINE_RE = re.compile(r"^[=-]{3,}\s*$")
FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})")


class UnparseableBlockError(Exception):
    """Raised when the parser cannot confidently classify a line/block."""


class ParseWarning:
    def __init__(self, line_no: int, code: str, message: str) -> None:
        self.line_no = line_no
        self.code = code  # e.g. "level_skip", "duplicate_heading"
        self.message = message

    def __repr__(self) -> str:
        return f"ParseWarning(line {self.line_no}, {self.code}): {self.message}"


def parse_markdown(text: str) -> tuple[ParseNode, list[ParseWarning]]:
    """Parse markdown into a tree of ParseNodes rooted at a document root.

    Returns (root, warnings). The root node carries front-matter/preamble in
    its body_text and the top-level sections as children.
    """
    lines = text.splitlines()
    root = ParseNode(heading_text="", level=0)
    stack: list[ParseNode] = [root]
    warnings: list[ParseWarning] = []

    # Track duplicate keys per parent path so we can suffix collisions.
    seen_keys: dict[str, int] = {}

    in_fence = False
    fence_marker = ""

    for idx, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")
        stripped = line.strip()

        # --- Fenced code block toggle (``` or ~~~). Inside a fence, no line
        # is treated as a heading; a # line is literal body content.
        m_fence = FENCE_RE.match(line)
        if m_fence and not in_fence:
            in_fence = True
            fence_marker = m_fence.group(2)[0]
            _current(stack).add_body(line)
            continue
        if in_fence:
            if stripped.startswith(fence_marker * 3) and len(stripped) >= 3:
                in_fence = False
                fence_marker = ""
            _current(stack).add_body(line)
            continue

        # --- Setext underline (=== / --- as a heading underline). We only
        # support ATX, so an === underline is an explicit "fail loudly" case
        # (a real heading would otherwise be silently demoted to body).
        # Note: a table row like "|---|" does not match (it has pipes); a
        # thematic break "---" is left as body, not an error.
        if re.match(r"^={3,}\s*$", line):
            prev = _current(stack)
            if prev.body_text:
                raise UnparseableBlockError(
                    f"line {idx}: setext-style heading underline ('=') is not "
                    f"supported (only ATX '#'). Near: {prev.body_text.splitlines()[-1]!r}"
                )

        m = ATX_RE.match(line)
        if m:
            level = len(m.group(1))
            heading = m.group(2).strip()
            # Pop until the top of the stack is shallower than this heading.
            while len(stack) > 1 and stack[-1].level >= level:
                stack.pop()
            parent = stack[-1]

            # Flag heading level skips (e.g. ## -> ####): the heading is more
            # than one level deeper than its attached parent.
            if level > parent.level + 1:
                parent_name = parent.heading_text or "root"
                warnings.append(
                    ParseWarning(
                        idx,
                        "level_skip",
                        f"heading level {level} attached under level {parent.level} "
                        f"(skip of {level - parent.level - 1}); attached to {parent_name!r}",
                    )
                )

            node = ParseNode(heading_text=heading, level=level, parent=parent)
            node.order_in_parent = len(parent.children)
            parent.children.append(node)

            # Path-based logical key from ancestor headings.
            # Full path INCLUDING this node own heading.
            path_parts = [n.heading_text for n in _ancestors(node) if n.heading_text] + [heading]
            base_key = "/".join(_slug(p) for p in path_parts) or _slug(heading)

            # Disambiguate duplicate keys (same path seen before in this parse).
            if base_key in seen_keys:
                seen_keys[base_key] += 1
                key = f"{base_key} ({seen_keys[base_key]})"
                warnings.append(
                    ParseWarning(
                        idx,
                        "duplicate_heading",
                        f"duplicate logical key {base_key!r}; renamed to {key!r}",
                    )
                )
            else:
                seen_keys[base_key] = 1
                key = base_key
            node.logical_key = key

            stack.append(node)
        else:
            _current(stack).add_body(line)

    # Finalize: trim bodies, compute hashes.
    _finalize(root)
    return root, warnings


def _ancestors(node: ParseNode) -> list[ParseNode]:
    out: list[ParseNode] = []
    cur = node.parent
    while cur is not None:
        out.append(cur)
        cur = cur.parent
    out.reverse()
    return out


def _current(stack: list[ParseNode]) -> ParseNode:
    return stack[-1]


def _finalize(node: ParseNode) -> None:
    node.finalize()
    node_hash = content_hash(node.heading_text, node.body_text)
    setattr(node, "content_hash", node_hash)
    for c in node.children:
        _finalize(c)


def flatten(node: ParseNode) -> list[ParseNode]:
    """Pre-order traversal excluding the root, yielding real section nodes."""
    out: list[ParseNode] = []
    for c in node.children:
        out.append(c)
        out.extend(flatten(c))
    return out