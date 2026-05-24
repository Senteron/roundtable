"""Round-1+ framing template and bundle formatter.

This module's template constant is the single most load-bearing piece
of text in the system. Material changes require a minor version bump
in pyproject.toml AND mcpb/manifest.json, plus a CHANGELOG entry
(CLAUDE.md "Two strings get the version-bump discipline").

The golden snapshot test in tests/unit/test_framing.py pins the exact
text; intentional changes update the snapshot in the same commit.
"""

from __future__ import annotations

from .schemas import ErrorClass, PriorAnswer

# Header sent on round 1+ before the bundle. See docs/design.md §3.
# DO NOT silently edit. Changes require a version bump.
ROUND_1_PLUS_HEADER = """\
You are participating in a multi-model deliberation. Below is the
original question, followed by every participant's latest answer
(yours included).

Read all of them carefully. Then produce YOUR revised answer to the
original question. Integrate what is correct from the others. Reject
what is wrong, naming what specifically you reject and why. Defend
your distinctive choices when the others would smooth them away.

Do NOT produce a synthesis or summary of the panel. Produce your own
answer, as if you were the only respondent, but informed by what the
others have said. Keep your voice; do not adopt the panel's."""


def render_round_1_plus(
    prompt: str,
    successful: list[PriorAnswer],
    failed: list[tuple[str, ErrorClass]],
    current_round: int,
) -> str:
    """Render the round-1+ framing prompt.

    `successful` carries one PriorAnswer per non-empty prior response;
    `failed` carries (model, error_class) tuples for prior-round
    failures. The UNAVAILABLE PARTICIPANTS section is omitted entirely
    when `failed` is empty (D1).
    """
    if not successful and not failed:
        raise ValueError(
            "render_round_1_plus requires at least one prior-round "
            "entry (successful or failed); round 0 sends the raw prompt."
        )

    previous_round = (
        max(a.round for a in successful)
        if successful
        else current_round - 1
    )

    parts: list[str] = [ROUND_1_PLUS_HEADER, ""]
    parts.append("---")
    parts.append("ORIGINAL QUESTION:")
    parts.append(prompt)
    parts.append("")
    parts.append("---")
    parts.append(f"PANEL ANSWERS (round {previous_round}):")
    parts.append("")

    if successful:
        for i, a in enumerate(successful):
            parts.append(f"[{a.model}]")
            parts.append(a.answer)
            if i < len(successful) - 1:
                parts.append("")
    else:
        parts.append("(no successful answers from prior round)")

    if failed:
        parts.append("")
        parts.append("---")
        parts.append(f"UNAVAILABLE PARTICIPANTS (round {previous_round}):")
        parts.append("")
        for model, error_class in failed:
            parts.append(f"[{model}] {error_class.value}")

    parts.append("")
    parts.append("---")
    parts.append(f"This is round {current_round}.")

    return "\n".join(parts)
