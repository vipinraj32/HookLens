"""SARIF 2.1.0 output for GitHub Code Scanning and other SARIF consumers.

* `ruleId` is the stable HookLens rule key (``HL.<CODE>.<rule_id>``).
* Locations are repository-relative (``uriBaseId: %SRCROOT%``). A finding without a real
  source location is reported without a physical location; no line number is invented.
* `partialFingerprints.hooklensFindingId/v1` is the HookLens finding id, which is derived from the
  contract, rule and code location (not line numbers), so alerts survive unrelated edits.
* Severity: critical/high -> error, medium -> warning, low/unknown/informational -> note, plus
  GitHub's numeric `security-severity` on rules (informational rules carry none).
"""

from __future__ import annotations

from typing import Any

from hooklens.rules_catalog import rule_info
from hooklens.scanner import SEVERITY_RANK

LEVEL = {
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "low": "note",
    "unknown": "note",
    "informational": "note",
}
SECURITY_SEVERITY = {"critical": "9.5", "high": "8.0", "medium": "5.5", "low": "3.0", "unknown": "3.0"}
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"


def render(report: dict[str, Any]) -> dict[str, Any]:
    min_rank = SEVERITY_RANK[report["scan"]["configuration"].get("sarif_min_severity", "low")]
    findings = [f for f in report["findings"] if SEVERITY_RANK[f["severity"]] <= min_rank]
    rules: dict[str, dict[str, Any]] = {}
    results = []
    for f in findings:
        rid = f["rule"]
        code = rid.split(".")[1]
        if rid not in rules:
            info = rule_info(code, f["rule_id"])
            props: dict[str, Any] = {"tags": ["security", "uniswap-v4", f["category"]], "precision": "medium"}
            if f["severity"] in SECURITY_SEVERITY:
                props["security-severity"] = SECURITY_SEVERITY[f["severity"]]
            rules[rid] = {
                "id": rid,
                "name": info.name,
                "shortDescription": {"text": info.short},
                "fullDescription": {"text": info.help},
                "help": {
                    "text": info.help + " HookLens findings are static patterns, not confirmed exploits.",
                    "markdown": f"**{info.short}**\n\n{info.help}\n\nHookLens findings are static patterns, "
                    "not confirmed exploits.",
                },
                "defaultConfiguration": {"level": LEVEL[f["severity"]]},
                "properties": props,
            }
        else:
            # A rule can produce different severities; keep the highest for the rule's metadata.
            cur = rules[rid]["properties"].get("security-severity")
            new = SECURITY_SEVERITY.get(f["severity"])
            if new and (cur is None or float(new) > float(cur)):
                rules[rid]["properties"]["security-severity"] = new
                rules[rid]["defaultConfiguration"]["level"] = LEVEL[f["severity"]]
        msg = f"{f['title']} ({f['contract']}). {f['description']}"
        if f.get("remediation"):
            msg += f" Investigate: {f['remediation']}"
        result: dict[str, Any] = {
            "ruleId": rid,
            "level": LEVEL[f["severity"]],
            "message": {"text": msg[:4000]},
            "partialFingerprints": {"hooklensFindingId/v1": f["fingerprint"]},
            "properties": {
                "hooklens-id": f["id"],
                "severity": f["severity"],
                "confidence-basis": f["confidence_basis"],
                "status": f["status"],
                "contract": f["contract"],
            },
        }
        loc = f.get("location")
        if (
            loc
            and loc.get("in_project") is not False
            and not loc["file"].startswith(("/", "\\"))
            and ":" not in loc["file"]
        ):
            result["locations"] = [_location(loc)]
            related = [
                _location(x) | {"id": i, "message": {"text": x.get("function") or "related code"}}
                for i, x in enumerate(f.get("locations") or [])
                if x is not loc and x.get("in_project") and x != loc
            ]
            if related:
                result["relatedLocations"] = related[:10]
        else:
            result["properties"]["location"] = "no in-repository source location for this finding"
        results.append(result)

    src = report["scan"]["source"]
    run: dict[str, Any] = {
        "tool": {
            "driver": {
                "name": "HookLens",
                "semanticVersion": report["tool"]["version"],
                "version": report["tool"]["version"],
                "informationUri": report["tool"].get("information_uri"),
                "rules": list(rules.values()),
            }
        },
        "automationDetails": {"id": "hooklens/static-source/"},
        "originalUriBaseIds": {"%SRCROOT%": {"description": {"text": "Repository root"}}},
        "results": results,
        "invocations": [
            {
                "executionSuccessful": report["scan"]["status"] in ("completed", "no-hooks"),
                "startTimeUtc": report["scan"]["started_at"],
                "endTimeUtc": report["scan"]["finished_at"],
                "toolExecutionNotifications": [
                    {"level": "warning", "message": {"text": p}} for p in report["scan"].get("problems") or []
                ],
            }
        ],
        "properties": {
            "hooklens-scan-status": report["scan"]["status"],
            "scope": report["scope"],
        },
    }
    # repositoryUri is required by SARIF; without a known remote URL the provenance block is omitted.
    if src.get("commit") and src.get("url"):
        vcp = {"repositoryUri": src["url"], "revisionId": src["commit"]}
        if src.get("branch"):
            vcp["branch"] = src["branch"]
        run["versionControlProvenance"] = [vcp]
    return {"$schema": SARIF_SCHEMA, "version": "2.1.0", "runs": [run]}


def _location(loc: dict[str, Any]) -> dict[str, Any]:
    region: dict[str, Any] = {"startLine": int(loc["start_line"])}
    if loc.get("end_line") and int(loc["end_line"]) >= int(loc["start_line"]):
        region["endLine"] = int(loc["end_line"])
    return {"physicalLocation": {"artifactLocation": {"uri": loc["file"], "uriBaseId": "%SRCROOT%"}, "region": region}}
