"""Prompt construction for QA test-case generation (TRD section 7)."""
from __future__ import annotations

PROMPT_VERSION = "tc-v1"

SYSTEM_PROMPT = (
    "You are generating QA test-case drafts for a medical-device requirements "
    "section. Output ONLY a valid JSON object matching the given schema, no "
    "prose, no markdown fences. Each test case must be concrete and executable: "
    "a specific trigger (steps) and a specific, checkable expected_result. "
    'Use source_node_ids to cite which node(s) each case came from. Schema: '
    '{"test_cases":[{"title":str,"steps":[str],"expected_result":str,'
    '"rationale":str,"source_node_ids":[int]}]}. Generate 3 to 5 test cases.'
)


def reconstruct_selection_text(nodes: list[dict]) -> str:
    """Build the user prompt payload: each node's heading + body, with an
    explicit numeric boundary so the model can cite source_node_ids back."""
    parts = []
    for n in nodes:
        parts.append(f"[NODE {n['node_id']}] {n['heading_text']}\n{n['body_text']}")
    return "\n\n".join(parts).strip()


def build_user_prompt(nodes: list[dict]) -> str:
    return (
        "Selected requirements text (headings and bodies in document order):\n\n"
        f"{reconstruct_selection_text(nodes)}\n\n"
        "Generate 3 to 5 QA test-case drafts from the text above. Respond with "
        "ONLY the JSON object matching the schema."
    )


def build_retry_prompt(nodes: list[dict], validation_error: str) -> str:
    return (
        build_user_prompt(nodes)
        + f"\n\nYour previous response failed validation: {validation_error}\n"
        "Return ONLY corrected valid JSON matching the schema."
    )