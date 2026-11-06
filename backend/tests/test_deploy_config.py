"""Deployment config stays consistent with the repository."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _gitlinks() -> dict[str, str]:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("needs the git checkout")
    out = subprocess.run(
        ["git", "ls-files", "-s", "contracts/lib"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return {line.split("\t")[1]: line.split()[1] for line in out.splitlines() if line.startswith("160000")}


def test_dockerfile_submodule_pins_match_the_gitlinks() -> None:
    dockerfile = (ROOT / "docker" / "backend.Dockerfile").read_text(encoding="utf-8")
    pins = dict(re.findall(r"^ARG (FORGE_STD_REV|V4_PERIPHERY_REV)=([0-9a-f]{40})$", dockerfile, re.M))
    links = _gitlinks()
    assert pins["FORGE_STD_REV"] == links["contracts/lib/forge-std"]
    assert pins["V4_PERIPHERY_REV"] == links["contracts/lib/v4-periphery"]
