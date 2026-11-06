"""`hooklens.toml` configuration.

Precedence (lowest to highest): built-in defaults < hooklens.toml < explicit CLI arguments.

Security: a configuration file found inside a scanned *remote* repository is untrusted. Its scan
preferences (paths, exclusions, compiler settings) are honoured, but its report destinations and
CI threshold are ignored; those come only from the command line of the person running the scan.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from hooklens.errors import ConfigError

CONFIG_NAME = "hooklens.toml"
SEVERITIES = ("critical", "high", "medium", "low", "informational")
FAIL_ON_CHOICES = (*SEVERITIES, "never")

# Directories and files that are not part of the deployable contract surface.
DEFAULT_EXCLUDES = (
    "**/test/**",
    "**/tests/**",
    "**/script/**",
    "**/scripts/**",
    "**/lib/**",
    "**/node_modules/**",
    "**/out/**",
    "**/cache/**",
    "**/broadcast/**",
    "**/artifacts/**",
    "**/typechain/**",
    "**/typechain-types/**",
    "**/mocks/**",
    "**/mock/**",
    "**/*.t.sol",
    "**/*.s.sol",
)

ANALYZER_IDS = (
    "source_integrity",
    "permissions",
    "bytecode_heuristics",
    "access_control",
    "upgradeability",
    "external_calls",
    "oracle",
    "dynamic_fee",
    "withdrawal",
    "accounting",
)


@dataclass
class ScanConfig:
    paths: list[str] = field(default_factory=list)  # relative to the project root; empty = auto
    exclude: list[str] = field(default_factory=list)
    default_excludes: bool = True
    contracts: list[str] = field(default_factory=list)  # restrict analysis to these contract names
    include_mocks: bool = False
    # compiler / import handling
    solc: str | None = None
    evm_version: str | None = None
    remappings: list[str] = field(default_factory=list)
    allow_solc_download: bool = True
    compile_timeout_s: int = 300
    # analysis
    analyzers: list[str] = field(default_factory=list)  # empty = all
    disable_analyzers: list[str] = field(default_factory=list)
    # reports
    html: str | None = None
    json: str | None = None
    sarif: str | None = None
    severity_threshold: str = "informational"  # minimum severity included in reports
    sarif_min_severity: str = "low"  # code-scanning alerts below this are omitted from SARIF
    # CI
    fail_on: str = "never"
    # provenance (not user-settable)
    config_file: str | None = None
    ignored_keys: list[str] = field(default_factory=list)

    def effective_analyzers(self) -> list[str]:
        chosen = list(self.analyzers) or list(ANALYZER_IDS)
        return [a for a in ANALYZER_IDS if a in chosen and a not in self.disable_analyzers]

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


_SECTIONS: dict[str, dict[str, str]] = {
    "scan": {
        "paths": "paths",
        "exclude": "exclude",
        "default_excludes": "default_excludes",
        "contracts": "contracts",
        "include_mocks": "include_mocks",
    },
    "compiler": {
        "solc": "solc",
        "evm_version": "evm_version",
        "remappings": "remappings",
        "allow_download": "allow_solc_download",
        "timeout_s": "compile_timeout_s",
    },
    "analysis": {"analyzers": "analyzers", "disable": "disable_analyzers"},
    "report": {
        "html": "html",
        "json": "json",
        "sarif": "sarif",
        "severity_threshold": "severity_threshold",
        "sarif_min_severity": "sarif_min_severity",
    },
    "ci": {"fail_on": "fail_on"},
}
_UNTRUSTED_KEYS = {"html", "json", "sarif", "fail_on"}
_LIST_KEYS = {"paths", "exclude", "contracts", "remappings", "analyzers", "disable_analyzers"}
_BOOL_KEYS = {"default_excludes", "include_mocks", "allow_solc_download"}


def find_config(root: Path) -> Path | None:
    p = root / CONFIG_NAME
    return p if p.is_file() else None


def load_config(path: Path | None, *, trusted: bool = True) -> ScanConfig:
    cfg = ScanConfig()
    if path is None:
        return cfg
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(f"Configuration file not found: {path}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path.name} is not valid TOML: {e}") from e
    except OSError as e:
        raise ConfigError(f"Cannot read {path}: {e.strerror}") from e
    cfg.config_file = str(path)
    for section, body in data.items():
        if section not in _SECTIONS:
            raise ConfigError(
                f"{path.name}: unknown section [{section}]", hint=f"Valid sections: {', '.join(_SECTIONS)}."
            )
        if not isinstance(body, dict):
            raise ConfigError(f"{path.name}: [{section}] must be a table.")
        for key, value in body.items():
            attr = _SECTIONS[section].get(key)
            if attr is None:
                raise ConfigError(
                    f"{path.name}: unknown key '{key}' in [{section}]",
                    hint=f"Valid keys: {', '.join(_SECTIONS[section])}.",
                )
            if attr in _UNTRUSTED_KEYS and not trusted:
                cfg.ignored_keys.append(f"{section}.{key}")
                continue
            setattr(cfg, attr, _coerce(path.name, f"{section}.{key}", attr, value))
    if cfg.html or cfg.json or cfg.sarif:
        base = path.parent
        for attr in ("html", "json", "sarif"):
            v = getattr(cfg, attr)
            if v:
                setattr(cfg, attr, str(_inside(base, v, f"{path.name}: report.{attr}")))
    validate(cfg)
    return cfg


def _inside(base: Path, value: str, label: str) -> Path:
    """Report paths from a config file must stay inside the directory holding that file."""
    target = (base / value).resolve()
    if not target.is_relative_to(base.resolve()):
        raise ConfigError(f"{label} points outside the project directory: {value}")
    return target


def _coerce(fname: str, key: str, attr: str, value: Any) -> Any:
    if attr in _LIST_KEYS:
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ConfigError(f"{fname}: {key} must be a string or a list of strings.")
        return list(value)
    if attr in _BOOL_KEYS:
        if not isinstance(value, bool):
            raise ConfigError(f"{fname}: {key} must be true or false.")
        return value
    if attr == "compile_timeout_s":
        if not isinstance(value, int) or value <= 0:
            raise ConfigError(f"{fname}: {key} must be a positive integer (seconds).")
        return value
    if not isinstance(value, str):
        raise ConfigError(f"{fname}: {key} must be a string.")
    return value.strip().lower() if attr in ("severity_threshold", "sarif_min_severity", "fail_on") else value


def validate(cfg: ScanConfig) -> None:
    if cfg.severity_threshold not in SEVERITIES:
        raise ConfigError(
            f"severity threshold must be one of {', '.join(SEVERITIES)} (got '{cfg.severity_threshold}')."
        )
    if cfg.sarif_min_severity not in SEVERITIES:
        raise ConfigError(f"SARIF minimum severity must be one of {', '.join(SEVERITIES)}.")
    if cfg.fail_on not in FAIL_ON_CHOICES:
        raise ConfigError(f"fail-on must be one of {', '.join(FAIL_ON_CHOICES)} (got '{cfg.fail_on}').")
    unknown = [a for a in cfg.analyzers + cfg.disable_analyzers if a not in ANALYZER_IDS]
    if unknown:
        raise ConfigError(f"Unknown analyzer(s): {', '.join(unknown)}", hint=f"Valid: {', '.join(ANALYZER_IDS)}.")
    for r in cfg.remappings:
        if "=" not in r:
            raise ConfigError(f"Invalid remapping '{r}': expected 'prefix=target'.")
    if cfg.solc is not None and not _is_version(cfg.solc):
        raise ConfigError(f"compiler.solc must be an exact version such as 0.8.26 (got '{cfg.solc}').")


def _is_version(v: str) -> bool:
    parts = v.split(".")
    return len(parts) == 3 and all(p.isdigit() for p in parts)


def render_default(paths: list[str], fail_on: str = "high") -> str:
    paths_toml = ", ".join(f'"{p}"' for p in paths) or '"src"'
    return f"""# HookLens configuration. Explicit command-line flags override these values.
# Reference: https://github.com/vipinraj32/HookLens/blob/main/docs/cli.md#configuration

[scan]
# Directories (relative to this file) that contain the hook contracts to analyse.
paths = [{paths_toml}]
# Extra glob patterns to skip, in addition to the defaults (test/, script/, lib/, mocks/, *.t.sol ...).
exclude = []
# Restrict analysis to specific contract names (empty = every detected hook).
contracts = []
include_mocks = false

[compiler]
# Exact solc version; leave unset to use foundry.toml or the highest version allowed by the pragmas.
# solc = "0.8.26"
# evm_version = "cancun"
# Extra import remappings (Foundry syntax). remappings.txt and foundry.toml are read automatically.
remappings = []
# Allow downloading the required solc binary (from binaries.soliditylang.org) when it is not installed.
allow_download = true

[analysis]
# Empty = all analyzers. Valid ids: {", ".join(ANALYZER_IDS)}
analyzers = []
disable = []

[report]
html = "hooklens-report.html"
json = "hooklens-report.json"
sarif = "hooklens.sarif"
severity_threshold = "informational"
sarif_min_severity = "low"

[ci]
# Exit with code 1 when a finding at or above this severity is present ("never" to only report).
fail_on = "{fail_on}"
"""
