"""The composite GitHub Action: structure, injection safety, and its scan/summary scripts run for real."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import REPO

ACTION = REPO / "action.yml"


@pytest.fixture(scope="module")
def action() -> dict[str, Any]:
    return yaml.safe_load(ACTION.read_text(encoding="utf-8"))


def _step(action: dict[str, Any], name: str) -> dict[str, Any]:
    return next(s for s in action["runs"]["steps"] if s.get("name") == name)


def test_inputs_and_outputs(action: dict[str, Any]) -> None:
    assert action["runs"]["using"] == "composite"
    for key in ("paths", "fail-on", "html-out", "json-out", "sarif-out", "comment-on-pr", "upload-sarif"):
        assert key in action["inputs"], key
    assert action["inputs"]["fail-on"]["default"] == "high"
    assert {"exit-code", "json-report", "sarif-report"} <= set(action["outputs"])


def test_installs_and_calls_the_real_cli(action: dict[str, Any]) -> None:
    assert "$GITHUB_ACTION_PATH/packages/hooklens" in _step(action, "Install HookLens CLI")["run"]
    assert 'hooklens "${args[@]}"' in _step(action, "Run hooklens scan")["run"]


def test_no_expression_interpolation_inside_scripts(action: dict[str, Any]) -> None:
    """User-controlled inputs reach shell scripts only through env vars (no `${{ }}` script injection)."""
    for step in action["runs"]["steps"]:
        if "run" in step:
            assert "${{" not in step["run"], step["name"]


def test_fork_pull_requests_skip_privileged_steps(action: dict[str, Any]) -> None:
    for name in ("Upload SARIF to Code Scanning", "Comment on pull request"):
        cond = _step(action, name)["if"]
        assert "github.event.pull_request.head.repo.full_name == github.repository" in cond
        assert _step(action, name).get("continue-on-error") is True
    text = ACTION.read_text(encoding="utf-8")
    assert not re.search(r"ghp_|github_pat_|gh[osu]_[A-Za-z0-9]|secrets\.", text)  # no hardcoded or implicit secrets
    assert text.count("github.token") == 1  # only the default of the github-token input


def _bash() -> str | None:
    found = shutil.which("bash")
    if found and sys.platform == "win32" and "system32" in found.lower():
        return None  # WSL launcher, not a POSIX bash for this filesystem
    return found


@pytest.mark.skipif(_bash() is None, reason="bash is not available")
@pytest.mark.parametrize(("fail_on", "expected"), [("high", "0"), ("medium", "1")])
def test_scan_and_summary_scripts_run(
    action: dict[str, Any], project: Path, tmp_path: Path, fail_on: str, expected: str
) -> None:
    exe = Path(sys.executable).parent
    if not (exe / "hooklens").exists() and not (exe / "hooklens.exe").exists():
        pytest.skip("hooklens executable is not installed next to the interpreter")
    out, summary = tmp_path / "out.txt", tmp_path / "summary.md"
    env = {
        **os.environ,
        "PATH": f"{exe}{os.pathsep}{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(out),
        "GITHUB_STEP_SUMMARY": str(summary),
        "HL_TARGET": str(project),
        "HL_PATHS": "src",
        "HL_CONTRACTS": "",
        "HL_EXCLUDE": "src/legacy/**",
        "HL_FAIL_ON": fail_on,
        "HL_THRESHOLD": "informational",
        "HL_HTML": str(tmp_path / "r.html"),
        "HL_JSON": str(tmp_path / "r.json"),
        "HL_SARIF": str(tmp_path / "r.sarif"),
        "HL_CONFIG": "",
        "HL_EXTRA": "-q",
    }
    scan = subprocess.run(
        [_bash(), "-c", _step(action, "Run hooklens scan")["run"]], env=env, capture_output=True, text=True, timeout=300
    )  # type: ignore[list-item]
    assert scan.returncode == 0, scan.stderr
    outputs = dict(line.split("=", 1) for line in out.read_text(encoding="utf-8").splitlines())
    assert outputs["exit-code"] == expected
    assert Path(outputs["sarif"]).is_file() and (tmp_path / "r.html").is_file()

    env |= {"HL_UPLOAD": "true", "HL_ARTIFACT": "hooklens-reports", "HL_SARIF": outputs["sarif"]}
    summ = subprocess.run(
        [_bash(), "-c", _step(action, "Job summary")["run"]], env=env, capture_output=True, text=True, timeout=120
    )  # type: ignore[list-item]
    assert summ.returncode == 0, summ.stderr
    md = summary.read_text(encoding="utf-8")
    assert "HookLens static scan" in md and "hooklens-reports" in md
    assert ("threshold reached" in md) == (expected == "1")

    final = subprocess.run(
        [_bash(), "-c", _step(action, "Apply fail-on result")["run"]],
        env=env | {"HL_CODE": expected},
        capture_output=True,
        text=True,
    )  # type: ignore[list-item]
    assert final.returncode == int(expected)


def test_example_workflow_uses_the_action() -> None:
    wf = yaml.safe_load((REPO / "examples" / "github-actions" / "hooklens.yml").read_text(encoding="utf-8"))
    steps = next(iter(wf["jobs"].values()))["steps"]
    assert any(re.match(r"vipinraj32/HookLens@", s.get("uses", "")) for s in steps)
    assert wf["permissions"]["contents"] == "read"
