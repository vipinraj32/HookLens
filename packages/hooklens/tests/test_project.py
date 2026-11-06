"""Project discovery, exclusions, remappings, import resolution, configuration and pragma handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from hooklens.config import ScanConfig, load_config
from hooklens.errors import ConfigError, SourceError
from hooklens.local import semver
from hooklens.local.project import _glob_re, discover_project, imports_of, list_sources, load_tree


@pytest.mark.parametrize(
    ("expr", "yes", "no"),
    [
        ("^0.8.24", ["0.8.24", "0.8.30"], ["0.8.23", "0.9.0"]),
        (">=0.8.0 <0.9.0", ["0.8.0", "0.8.26"], ["0.7.6", "0.9.0"]),
        ("0.8.26", ["0.8.26"], ["0.8.25", "0.8.27"]),
        ("=0.8.26", ["0.8.26"], ["0.8.27"]),
        ("~0.8.20", ["0.8.20", "0.8.29"], ["0.9.0", "0.8.19"]),
        ("^0.7.0 || ^0.8.0", ["0.7.6", "0.8.1"], ["0.6.12"]),
        (">0.8.20", ["0.8.21"], ["0.8.20"]),
    ],
)
def test_pragma_ranges(expr: str, yes: list[str], no: list[str]) -> None:
    for v in yes:
        assert semver.satisfies(semver.parse_version(v), expr), (expr, v)
    for v in no:
        assert not semver.satisfies(semver.parse_version(v), expr), (expr, v)


def test_best_version() -> None:
    cands = [semver.parse_version(v) for v in ("0.8.19", "0.8.24", "0.8.26", "0.8.30")]
    assert semver.fmt(semver.best_version(cands, ["^0.8.24", "<0.8.27"])) == "0.8.26"  # type: ignore[arg-type]
    assert semver.best_version(cands, ["^0.7.0"]) is None


def test_globs() -> None:
    assert _glob_re("**/test/**").match("test/A.sol")
    assert _glob_re("**/test/**").match("src/test/A.sol")
    assert not _glob_re("**/test/**").match("src/testing/A.sol")
    assert _glob_re("**/*.t.sol").match("a/b/C.t.sol")
    assert _glob_re("src/legacy/**").match("src/legacy/x/Y.sol")


def test_imports_parsing() -> None:
    src = """
    import "a.sol";
    import {X, Y} from "./b.sol";
    import * as Z from '../c.sol';
    // import "commented.sol";
    /* import "block.sol"; */
    import "d.sol" as D;
    """
    assert imports_of(src) == ["a.sol", "./b.sol", "../c.sol", "d.sol"]


def test_discovery_and_exclusions(project: Path) -> None:
    proj = discover_project(project, ScanConfig())
    assert proj.kind == "foundry" and proj.solc == "0.8.26" and proj.evm_version == "cancun"
    assert [proj.rel(p) for p in proj.scan_paths] == ["src"]
    assert any(r.prefix == "@uniswap/v4-core/" and r.origin == "remappings.txt" for r in proj.remappings)
    files, excluded = list_sources(proj, ScanConfig())
    assert "src/hooks/NormalHook.sol" in files and "src/mocks/MockHook.sol" not in files
    files2, _ = list_sources(proj, ScanConfig(exclude=["src/hooks/**"]))
    assert not any(f.startswith("src/hooks/") for f in files2)
    files3, _ = list_sources(proj, ScanConfig(default_excludes=False))
    assert "src/mocks/MockHook.sol" in files3


def test_subdirectory_target_keeps_project_root(project: Path) -> None:
    proj = discover_project(project / "src" / "hooks", ScanConfig())
    assert proj.root == project.resolve()
    assert [proj.rel(p) for p in proj.scan_paths] == ["src/hooks"]


def test_import_tree_and_remapping(project: Path) -> None:
    proj = discover_project(project, ScanConfig())
    tree = load_tree(proj, ["src/hooks/OracleHook.sol"])
    assert not tree.errors
    assert "lib/v4-core/src/interfaces/IHooks.sol" in tree.sources  # remapped unit name
    assert "src/interfaces/IPriceFeed.sol" in tree.sources  # relative import


def test_imports_cannot_escape_project_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "Secret.sol").write_text("pragma solidity ^0.8.0;\ncontract Secret {}\n")
    proj_dir = tmp_path / "proj"
    (proj_dir / "src").mkdir(parents=True)
    (proj_dir / "foundry.toml").write_text("[profile.default]\n")
    (proj_dir / "remappings.txt").write_text(f"evil/={outside.as_posix()}/\n")
    (proj_dir / "src" / "A.sol").write_text(
        'pragma solidity ^0.8.0;\nimport "evil/Secret.sol";\nimport "../../outside/Secret.sol";\ncontract A {}\n'
    )
    proj = discover_project(proj_dir, ScanConfig())
    tree = load_tree(proj, ["src/A.sol"])
    assert not any("Secret" in u for u in tree.sources)
    assert len(tree.errors) == 2
    # A remapping given explicitly by the user on the command line may point outside the project.
    proj2 = discover_project(proj_dir, ScanConfig(remappings=[f"evil/={outside.as_posix()}/"]))
    tree2 = load_tree(proj2, ["src/A.sol"])
    assert any(u.endswith("Secret.sol") for u in tree2.sources)


def test_missing_scan_path(project: Path) -> None:
    with pytest.raises(SourceError):
        discover_project(project, ScanConfig(paths=["nope"]))


def test_config_parsing(tmp_path: Path) -> None:
    f = tmp_path / "hooklens.toml"
    f.write_text(
        '[scan]\npaths = "src"\nexclude = ["src/x/**"]\n[compiler]\nsolc = "0.8.26"\nremappings = ["a/=b/"]\n'
        '[analysis]\ndisable = ["oracle"]\n[report]\nhtml = "out/r.html"\nseverity_threshold = "LOW"\n[ci]\nfail_on = "High"\n'
    )
    cfg = load_config(f)
    assert cfg.paths == ["src"] and cfg.solc == "0.8.26" and cfg.fail_on == "high"
    assert cfg.severity_threshold == "low"
    assert "oracle" not in cfg.effective_analyzers()
    assert Path(cfg.html or "") == (tmp_path / "out" / "r.html").resolve()


@pytest.mark.parametrize(
    "body",
    [
        "[nope]\nx = 1\n",
        "[ci]\nfail_on = 'extreme'\n",
        "[compiler]\nsolc = '^0.8.0'\n",
        "[analysis]\nanalyzers = ['made_up']\n",
        "[scan]\npaths = 3\n",
        "[report]\nhtml = '../../escape.html'\n",
        "not toml = = =",
    ],
)
def test_invalid_config(tmp_path: Path, body: str) -> None:
    f = tmp_path / "hooklens.toml"
    f.write_text(body)
    with pytest.raises(ConfigError):
        load_config(f)


def test_untrusted_config_ignores_outputs_and_gate(tmp_path: Path) -> None:
    f = tmp_path / "hooklens.toml"
    f.write_text('[report]\nhtml = "r.html"\n[ci]\nfail_on = "never"\n[scan]\npaths = ["src"]\n')
    cfg = load_config(f, trusted=False)
    assert cfg.html is None and cfg.fail_on == "never" and cfg.paths == ["src"]
    assert set(cfg.ignored_keys) == {"report.html", "ci.fail_on"}
