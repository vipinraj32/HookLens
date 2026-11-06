"""CLI behaviour and exit codes (security finding vs. scanner failure are always distinct)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from hooklens import __version__
from hooklens.cli import main


def run(*args: str) -> tuple[int, str]:
    r = CliRunner().invoke(main, list(args))
    return r.exit_code, r.output


def test_help_and_version() -> None:
    code, out = run("--help")
    assert code == 0 and "scan" in out and "lab" in out
    code, out = run("version")
    assert code == 0 and f"hooklens {__version__}" in out
    code, out = run("--version")
    assert code == 0 and __version__ in out


def test_scan_writes_all_reports_and_gate(project: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    code, text = run(
        "scan", str(project), "--local",
        "--html", str(out / "r.html"), "--json", str(out / "r.json"), "--sarif", str(out / "r.sarif"),
        "--summary-md", str(out / "s.md"), "--fail-on", "HIGH",
    )  # fmt: skip
    assert code == 0, text  # highest finding is medium
    for name in ("r.html", "r.json", "r.sarif", "s.md"):
        assert (out / name).stat().st_size > 0
    doc = json.loads((out / "r.json").read_text(encoding="utf-8"))
    sar = json.loads((out / "r.sarif").read_text(encoding="utf-8"))
    # SARIF and JSON come from the same canonical findings
    ids = {f["id"] for f in doc["findings"] if f["severity"] != "informational"}
    assert {r["partialFingerprints"]["hooklensFindingId/v1"] for r in sar["runs"][0]["results"]} == ids


def test_fail_on_threshold_reached(project: Path) -> None:
    code, text = run("scan", str(project), "--fail-on", "medium", "-q")
    assert code == 1, text
    assert "Gate: findings at or above 'medium'" in text


def test_fail_on_never(project: Path) -> None:
    assert run("scan", str(project), "--fail-on", "never", "-q")[0] == 0


def test_contract_filter_and_unknown_contract(project: Path, tmp_path: Path) -> None:
    code, _ = run("scan", str(project), "--contract", "NormalHook", "--json", str(tmp_path / "n.json"), "-q")
    assert code == 0
    doc = json.loads((tmp_path / "n.json").read_text(encoding="utf-8"))
    assert {c["name"] for c in doc["contracts"] if c["analyzed"]} == {"NormalHook"}
    code, text = run("scan", str(project), "--contract", "NoSuchHook", "-q")
    assert code == 2 and "NoSuchHook" in text


def test_missing_path_is_source_error(tmp_path: Path) -> None:
    code, text = run("scan", str(tmp_path / "nope"))
    assert code == 3 and "does not exist" in text


def test_no_solidity_is_analysis_error(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("x")
    code, text = run("scan", str(tmp_path), "--local")
    assert code == 4 and "No Solidity source files" in text


def test_unresolved_import_is_analysis_error_with_failure_record(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "H.sol").write_text(
        'pragma solidity ^0.8.24;\nimport "@uniswap/v4-core/src/X.sol";\ncontract H {}\n'
    )
    code, text = run("scan", str(tmp_path), "--json", str(tmp_path / "f.json"))
    assert code == 4 and "could not be resolved" in text and "git submodule update" in text
    doc = json.loads((tmp_path / "f.json").read_text(encoding="utf-8"))
    assert doc["scan"]["status"] == "failed" and doc["scan"]["error"]["exit_code"] == 4


def test_partial_scan_exits_4(project: Path, tmp_path: Path) -> None:
    import shutil

    p = tmp_path / "p"
    shutil.copytree(project, p)
    (p / "src" / "Broken.sol").write_text(
        'pragma solidity ^0.8.24;\nimport "./nope/Missing.sol";\ncontract Broken {}\n'
    )
    code, text = run("scan", str(p), "--json", str(tmp_path / "p.json"), "-q")
    assert code == 4, text
    doc = json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))
    assert doc["scan"]["status"] == "partial"
    assert doc["summary"]["contracts_analyzed"] > 0  # the rest of the project was still analysed


def test_compile_error_is_reported(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Bad.sol").write_text("pragma solidity 0.8.26;\ncontract Bad { function f() { } }\n")
    code, text = run("scan", str(tmp_path), "--json", str(tmp_path / "b.json"), "-q")
    assert code == 4
    doc = json.loads((tmp_path / "b.json").read_text(encoding="utf-8"))
    assert doc["compilation"][0]["status"] == "failed" and doc["compilation"][0]["errors"]


def test_no_hooks_found(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Plain.sol").write_text("pragma solidity 0.8.26;\ncontract Plain { uint256 public x; }\n")
    code, text = run("scan", str(tmp_path), "--fail-on", "low")
    assert code == 0 and "no Uniswap v4 hook contracts were identified" in text


def test_report_write_failure(project: Path, tmp_path: Path) -> None:
    (tmp_path / "blocker").write_text("a file, not a directory")
    code, text = run(
        "scan", str(project), "--contract", "NormalHook", "--json", str(tmp_path / "blocker" / "r.json"), "-q"
    )
    assert code == 5 and "Cannot write report" in text


def test_invalid_config_and_precedence(project: Path, tmp_path: Path) -> None:
    import shutil

    p = tmp_path / "c"
    shutil.copytree(project, p)
    (p / "hooklens.toml").write_text("[scan]\nbogus = 1\n")
    code, text = run("scan", str(p), "-q")
    assert code == 2 and "unknown key 'bogus'" in text
    (p / "hooklens.toml").write_text('[scan]\ncontracts = ["OracleHook"]\n[ci]\nfail_on = "low"\n')
    assert run("scan", str(p), "-q")[0] == 1  # config fail_on=low applies
    assert run("scan", str(p), "-q", "--fail-on", "never")[0] == 0  # CLI overrides config
    assert run("scan", str(p), "-q", "--no-config")[0] == 0  # config ignored entirely


def test_init_creates_config_and_workflow(tmp_path: Path) -> None:
    (tmp_path / "foundry.toml").write_text('[profile.default]\nsrc = "src"\n')
    (tmp_path / "src").mkdir()
    code, text = run("init", str(tmp_path), "--github-action")
    assert code == 0, text
    cfg = (tmp_path / "hooklens.toml").read_text(encoding="utf-8")
    assert 'paths = ["src"]' in cfg and 'fail_on = "high"' in cfg
    wf = (tmp_path / ".github" / "workflows" / "hooklens.yml").read_text(encoding="utf-8")
    assert "vipinraj32/HookLens@" in wf and "fail-on: high" in wf
    from hooklens.config import load_config

    assert load_config(tmp_path / "hooklens.toml").fail_on == "high"  # the template is valid config
    assert run("init", str(tmp_path))[0] == 2  # refuses to overwrite


def test_summary_command(project: Path, tmp_path: Path) -> None:
    run("scan", str(project), "--json", str(tmp_path / "r.json"), "-q")
    code, md = run("summary", str(tmp_path / "r.json"), "--artifact", "HTML=r.html", "--fail-on", "medium")
    assert code == 0 and "HookLens static scan" in md and "threshold reached" in md
    (tmp_path / "x.json").write_text("{}")
    assert run("summary", str(tmp_path / "x.json"))[0] == 2


def test_local_flag_rejects_urls() -> None:
    code, text = run("scan", "https://github.com/a/b", "--local")
    assert code == 2


@pytest.mark.parametrize("bad", ["--fail-on=extreme", "--severity-threshold=huge"])
def test_invalid_choices(project: Path, bad: str) -> None:
    assert run("scan", str(project), bad)[0] == 2
