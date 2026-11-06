from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "sample-hooks"
REPO = HERE.parents[2]
V4_CORE_SRC = (
    Path(os.environ.get("HOOKLENS_V4_CORE", REPO / "contracts" / "lib" / "v4-periphery" / "lib" / "v4-core")) / "src"
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("HOOKLENS_TEST_NETWORK") == "1":
        return
    skip = pytest.mark.skip(reason="network test; set HOOKLENS_TEST_NETWORK=1")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


def make_project(dest: Path) -> Path:
    """The sample-hooks fixture as a real Foundry layout, with Uniswap v4-core vendored under lib/."""
    if not V4_CORE_SRC.is_dir():
        pytest.skip(f"Uniswap v4-core sources not found at {V4_CORE_SRC} (git submodule update --init --recursive)")
    proj = dest / "sample-hooks"
    shutil.copytree(FIXTURE, proj)
    shutil.copytree(V4_CORE_SRC, proj / "lib" / "v4-core" / "src")
    return proj


@pytest.fixture(scope="session")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_project(tmp_path_factory.mktemp("proj"))


@pytest.fixture(scope="session")
def report(project: Path) -> dict[str, Any]:
    from hooklens.config import ScanConfig
    from hooklens.scanner import SourceInfo, run_scan

    return run_scan(project, ScanConfig(), SourceInfo("local", str(project)))


def by_contract(report: dict[str, Any]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in report["_all_findings"]:
        out.setdefault(f["contract"], set()).add(f["rule_id"])
    return out
