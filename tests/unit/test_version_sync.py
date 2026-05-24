"""Version sync across the three places version lives.

`pyproject.toml`, `mcpb/manifest.json`, and `roundtable/__init__.py`
must agree. If they drift, the released bundle has one version but
the running server reports another — a class of release bug that
hit Senteron at least once before this rule existed.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

import roundtable


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_pyproject_matches_manifest_matches_init() -> None:
    root = _repo_root()

    with (root / "pyproject.toml").open("rb") as f:
        pyproject_version = tomllib.load(f)["project"]["version"]

    with (root / "mcpb" / "manifest.json").open() as f:
        manifest_version = json.load(f)["version"]

    init_version = roundtable.__version__

    assert pyproject_version == manifest_version == init_version, (
        f"version drift: pyproject={pyproject_version!r}, "
        f"manifest={manifest_version!r}, __version__={init_version!r}"
    )


def test_bundle_pyproject_matches_root_pyproject() -> None:
    """The bundle's mcpb/pyproject.toml carries its own version field
    so it can be installed standalone via `uv pip install`. It must
    match the root pyproject's version too — otherwise the bundle
    on disk advertises one version while the server reports another.
    """
    root = _repo_root()

    with (root / "pyproject.toml").open("rb") as f:
        root_version = tomllib.load(f)["project"]["version"]

    with (root / "mcpb" / "pyproject.toml").open("rb") as f:
        bundle_version = tomllib.load(f)["project"]["version"]

    assert root_version == bundle_version, (
        f"bundle pyproject.toml version {bundle_version!r} != "
        f"root pyproject.toml version {root_version!r}"
    )


# tomllib is stdlib in 3.11+. Sanity check we're not running on an old
# interpreter where this whole test file would silently fail to import.
def test_python_version_supports_tomllib() -> None:
    assert sys.version_info >= (3, 11), (
        f"tomllib requires Python >= 3.11; running {sys.version}"
    )
