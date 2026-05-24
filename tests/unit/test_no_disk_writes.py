"""D7: Roundtable-owned code writes nothing to disk during a round.

Scope is intentionally narrow: this test asserts no NEW files appear
under the repo root or the system temp dir during a FakeProvider
round. Provider SDK behavior (credential caches, telemetry files
written by openai/google-genai/httpx) is OUT OF SCOPE — those are
covered by FakeProvider not existing in the call path.

The stronger v0.2 test will assert that no prompt/answer CONTENT
lands on disk during a live round.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from roundtable.dispatcher import dispatch
from roundtable.providers.fake import FakeProvider
from roundtable.schemas import RoundInput


def _snapshot(paths: list[Path]) -> set[Path]:
    found: set[Path] = set()
    for root in paths:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            # Skip __pycache__ — interpreter-managed, not our writes.
            if "__pycache__" in p.parts:
                continue
            found.add(p)
    return found


@pytest.mark.asyncio
async def test_no_new_files_in_repo_or_tempdir() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    tmp_root = Path(tempfile.gettempdir())

    # Snapshot only stable subtrees of the repo we'd plausibly touch.
    # Whole-repo rglob is too slow and noisy (includes .venv).
    watched_repo_paths = [
        repo_root / "roundtable",
        repo_root / "tests",
        repo_root / "docs",
        repo_root / "mcpb",
        repo_root / "dist",
    ]

    before_repo = _snapshot(watched_repo_paths)
    # Tempdir snapshot is best-effort — other processes write here.
    # We compare only files whose names mention "roundtable".
    before_tmp = {
        p
        for p in tmp_root.glob("*roundtable*")
        if p.is_file()
    }

    providers = [
        FakeProvider(name="a", behavior="echo"),
        FakeProvider(name="b", behavior="echo"),
        FakeProvider(name="c", behavior="error"),
    ]
    await dispatch(
        RoundInput(prompt="hello", round=0),
        providers=providers,
    )

    after_repo = _snapshot(watched_repo_paths)
    after_tmp = {
        p
        for p in tmp_root.glob("*roundtable*")
        if p.is_file()
    }

    new_repo_files = after_repo - before_repo
    new_tmp_files = after_tmp - before_tmp

    assert new_repo_files == set(), (
        f"Roundtable wrote new files under the repo: {new_repo_files}"
    )
    assert new_tmp_files == set(), (
        f"Roundtable wrote roundtable-named files to tempdir: {new_tmp_files}"
    )


@pytest.mark.asyncio
async def test_round_1_plus_with_failures_also_writes_nothing() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    pkg_path = repo_root / "roundtable"
    before = _snapshot([pkg_path])

    from roundtable.schemas import PriorAnswer, Source

    providers = [
        FakeProvider(name="a", behavior="echo"),
        FakeProvider(name="b", behavior="timeout"),
    ]
    await dispatch(
        RoundInput(
            prompt="follow-up",
            round=2,
            per_call_timeout_seconds=1,
            prior_answers=[
                PriorAnswer(
                    model="claude",
                    source=Source.ORCHESTRATOR,
                    round=1,
                    answer="prior",
                ),
                PriorAnswer(
                    model="a",
                    source=Source.PANELIST,
                    round=1,
                    answer="prior a",
                ),
            ],
        ),
        providers=providers,
    )

    after = _snapshot([pkg_path])
    assert after == before


def test_roundtable_logger_has_no_file_handler() -> None:
    """If roundtable's own logger ever gets a file-backed handler,
    catch it. (D7 is about Roundtable-owned writes; the root logger
    can carry process-global handlers we don't control.)
    """
    import logging

    rt_logger = logging.getLogger("roundtable")
    for handler in rt_logger.handlers:
        # FileHandler is a subclass of StreamHandler with a baseFilename.
        assert not hasattr(handler, "baseFilename"), (
            f"roundtable logger has a file-backed handler: {handler}"
        )

    # Suppress unused-import warning for os; kept in case future expansion
    # needs it.
    assert os.name in {"posix", "nt"}
