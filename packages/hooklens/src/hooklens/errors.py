"""CLI error types. Each maps to a documented, stable process exit code.

Exit codes
    0  scan completed; no finding at or above the --fail-on threshold
    1  scan completed; at least one finding at or above the --fail-on threshold
    2  usage or configuration error (bad flag, invalid hooklens.toml, unknown contract)
    3  source acquisition error (path missing, invalid/inaccessible repository, rate limit, timeout)
    4  analysis error (no Solidity sources, unresolved imports, compiler unavailable or failing,
       requested contracts not analysed)
    5  report generation error (a requested report could not be written)

A security finding (exit 1) and a scanner failure (exit 2-5) are never conflated.
"""

from __future__ import annotations

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_CONFIG = 2
EXIT_SOURCE = 3
EXIT_ANALYSIS = 4
EXIT_REPORT = 5


class HookLensError(Exception):
    exit_code = EXIT_ANALYSIS
    kind = "analysis_error"

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def to_dict(self) -> dict[str, str | int | None]:
        return {"kind": self.kind, "message": self.message, "hint": self.hint, "exit_code": self.exit_code}


class ConfigError(HookLensError):
    exit_code = EXIT_CONFIG
    kind = "configuration_error"


class SourceError(HookLensError):
    exit_code = EXIT_SOURCE
    kind = "source_error"


class AnalysisError(HookLensError):
    exit_code = EXIT_ANALYSIS
    kind = "analysis_error"


class ReportError(HookLensError):
    exit_code = EXIT_REPORT
    kind = "report_error"
