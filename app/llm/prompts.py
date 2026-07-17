"""Prompt construction for QA test-case generation (TRD section 7)."""
from __future__ import annotations

PROMPT_VERSION = "tc-v1"

SYSTEM_PROMPT = (
    "You are generating QA test-case drafts for a medical-device requirements "
    "section. Output ONLY a valid JSON object matching the schema, no prose, "
    "no markdown fences. Generate 3 to 5 test cases.\n\n"
    "Schema: {\"test_cases\":[{\"title\":string,\"steps\":[string],"
    "\"expected_result\":string,\"rationale\":string,\"source_node_ids\":[int]}]}\n\n"
    'IMPORTANT: "steps" MUST be a JSON ARRAY of strings, e.g. '
    '"steps": ["do action A","observe result B"]. Never write "steps" = [...] '
    "with an equals sign; JSON keys use a colon.\n\n"
    "Example output:\n"
    '{"test_cases":[{"title":"Threshold alarm","steps":["Set HR to 161 bpm",'
    '"Observe alarm"],"expected_result":"Alarm triggers","rationale":"tests the '
    'hard threshold","source_node_ids":[1]}]}'
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
        "ONLY the JSON object matching the schema in the system prompt."
    )


def build_retry_prompt(nodes: list[dict], validation_error: str) -> str:
    return (
        build_user_prompt(nodes)
        + f"\n\nYour previous response failed validation: {validation_error}\n"
        "Return ONLY corrected valid JSON matching the schema. Remember steps "
        "is an array of strings and keys use colons, not equals signs."
    )