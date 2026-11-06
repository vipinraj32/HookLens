"""JSON schema validity, SARIF structure and HTML safety, all rendered from one canonical report."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

import jsonschema
import pytest

from hooklens.reports import html, load_schema, markdown, sarif
from hooklens.scanner import public


def test_json_report_matches_schema(report: dict[str, Any]) -> None:
    schema = load_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    doc = json.loads(json.dumps(public(report)))
    jsonschema.validate(doc, schema, cls=jsonschema.Draft202012Validator)
    assert "_all_findings" not in doc
    assert doc["schema_version"].startswith("1.")


def test_sarif_structure(report: dict[str, Any]) -> None:
    doc = sarif.render(public(report))
    assert doc["version"] == "2.1.0"
    run = doc["runs"][0]
    rules = {r["id"] for r in run["tool"]["driver"]["rules"]}
    reported = [f for f in report["findings"] if f["severity"] not in ("informational",)]
    assert len(run["results"]) == len(reported)  # sarif_min_severity defaults to low
    for res in run["results"]:
        assert res["ruleId"] in rules
        assert re.fullmatch(r"HL\.[A-Z]+\.[a-z0-9_]+", res["ruleId"])
        assert res["level"] in ("error", "warning", "note")
        assert res["partialFingerprints"]["hooklensFindingId/v1"].startswith("HL-")
        for loc in res.get("locations", []):
            art = loc["physicalLocation"]["artifactLocation"]
            assert art["uriBaseId"] == "%SRCROOT%"
            assert not art["uri"].startswith("/") and ":" not in art["uri"]  # repository-relative
            assert loc["physicalLocation"]["region"]["startLine"] >= 1
    for r in run["tool"]["driver"]["rules"]:
        sev = r["properties"].get("security-severity")
        assert sev is None or 0 < float(sev) <= 10


def test_sarif_never_invents_locations(report: dict[str, Any]) -> None:
    doc = copy.deepcopy(public(report))
    for f in doc["findings"]:
        f["location"] = None
        f["locations"] = []
    run = sarif.render(doc)["runs"][0]
    assert run["results"] and all("locations" not in r for r in run["results"])


def test_sarif_severity_mapping() -> None:
    assert sarif.LEVEL["critical"] == sarif.LEVEL["high"] == "error"
    assert sarif.LEVEL["medium"] == "warning"
    assert sarif.LEVEL["low"] == sarif.LEVEL["informational"] == "note"


def test_html_is_standalone_and_escaped(report: dict[str, Any]) -> None:
    doc = copy.deepcopy(public(report))
    evil = '</script><script>alert("x")</script><img src=x onerror=alert(1)>'
    doc["findings"][0]["description"] = evil
    doc["findings"][0]["evidence"][0]["excerpt"] = evil
    doc["scan"]["source"]["display_name"] = evil
    out = html.render(doc)
    assert evil not in out
    assert "&lt;/script&gt;&lt;script&gt;" in out
    assert out.count("<script>") == 1  # only HookLens' own script
    csp = re.search(r'Content-Security-Policy" content="([^"]+)"', out).group(1)  # type: ignore[union-attr]
    assert "default-src 'none'" in csp and "unsafe-inline" not in csp
    assert not re.search(
        r'(src|href)="https?://', out.split("</header>", 1)[1].replace(str(doc["scan"]["source"].get("url")), "")
    )
    assert ' style="' not in out  # inline style attributes would violate the CSP


def test_html_content(report: dict[str, Any]) -> None:
    out = html.render(public(report))
    for text in ("Static analysis, not execution-tested", "Contract discovery", "Source navigation",
                 "Scope and limitations", "WithdrawalLockHook", "HL.WDR.withdrawal_revert_conditions"):  # fmt: skip
        assert text in out
    assert out.count("<details class='f'") == len(report["findings"])


def test_html_empty_report(report: dict[str, Any]) -> None:
    doc = copy.deepcopy(public(report))
    doc["findings"] = []
    out = html.render(doc)
    assert "does not mean the analysed contracts are safe" in out


def test_markdown_summary(report: dict[str, Any]) -> None:
    md = markdown.render(public(report), artifacts={"HTML": "r.html"}, fail_on="medium")
    assert md.startswith(markdown.COMMENT_MARKER)
    assert "threshold reached" in md
    assert "Highest-severity findings" in md and "`r.html`" in md
    assert "passed" in markdown.render(public(report), fail_on="critical")


@pytest.mark.parametrize("bad", ["a|b", "<b>x</b>"])
def test_markdown_escapes_table_text(report: dict[str, Any], bad: str) -> None:
    doc = copy.deepcopy(public(report))
    doc["findings"][0]["title"] = bad
    doc["findings"][0]["severity"] = "critical"
    md = markdown.render(doc)
    assert bad not in md
