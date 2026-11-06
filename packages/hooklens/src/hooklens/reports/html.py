"""Standalone HTML report.

* One self-contained file: CSS and JavaScript are inline, no fonts, images or network requests.
  A Content-Security-Policy pins the inline style and script by SHA-256 and blocks everything else.
* Every string from the scanned project (paths, names, code, messages) is HTML-escaped; the
  report is safe to open even when the scanned repository is hostile.
* Fully readable without JavaScript (findings are server-rendered, expandable via <details>);
  JavaScript adds search, severity filters and grouping by contract or rule.
"""

from __future__ import annotations

import base64
import hashlib
import html
from collections import Counter, defaultdict
from typing import Any

from hooklens.scanner import SEVERITY_RANK

SEVERITIES = ("critical", "high", "medium", "low", "informational", "unknown")
KIND_LABEL = {
    "hook": "Hook",
    "candidate": "Candidate",
    "abstract-hook": "Abstract base",
    "mock": "Mock",
    "interface": "Interface",
    "library": "Library",
    "not-a-hook": "Not a hook",
}
STATUS_LABEL = {
    "completed": "Completed",
    "partial": "Partial",
    "failed": "Failed",
    "no-hooks": "No hooks found",
}


def e(v: Any) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def _anchor(*parts: Any) -> str:
    return "x" + hashlib.sha1("|".join(str(p) for p in parts).encode(), usedforsecurity=False).hexdigest()[:12]


CSS = r"""
:root{--bg:#f6f7f9;--panel:#fff;--panel2:#f0f2f5;--ink:#14171c;--ink2:#4a5260;--muted:#6b7480;--line:#e2e5ea;
--accent:#5b4bdb;--code:#0f1115;--codeink:#e6e8ec;--codeln:#6b7480;--hl:#2a2f3a;
--critical:#c92a2a;--high:#d9480f;--medium:#b08800;--low:#1c6fd1;--informational:#6b7480;--unknown:#7048e8;
--shadow:0 1px 2px rgba(16,24,40,.06),0 1px 3px rgba(16,24,40,.08);color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#0d0f13;--panel:#151821;--panel2:#1b1f2a;--ink:#e8eaee;--ink2:#b6bcc6;
--muted:#8a919c;--line:#262b36;--accent:#9d8cff;--code:#0a0c10;--codeink:#e6e8ec;--hl:#232838;
--critical:#ff6b6b;--high:#ff922b;--medium:#fcc419;--low:#4dabf7;--informational:#9aa1ab;--unknown:#9775fa;--shadow:none}}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:16px}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;-webkit-font-smoothing:antialiased}
code,pre,.mono{font-family:ui-monospace,"SF Mono","Cascadia Code","JetBrains Mono",Menlo,Consolas,monospace;font-size:12.5px}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.layout{display:grid;grid-template-columns:232px minmax(0,1fr);min-height:100vh}
nav.side{position:sticky;top:0;height:100vh;overflow:auto;padding:22px 16px;border-right:1px solid var(--line);background:var(--panel)}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:16px;letter-spacing:-.01em;margin-bottom:22px}
.logo{width:26px;height:26px;border-radius:8px;background:linear-gradient(135deg,var(--accent),#2bb3a3);display:grid;place-items:center;color:#fff;font-size:13px}
nav.side a{display:flex;justify-content:space-between;padding:7px 10px;border-radius:8px;color:var(--ink2);font-weight:500}
nav.side a:hover{background:var(--panel2);text-decoration:none;color:var(--ink)}
nav.side .count{color:var(--muted);font-variant-numeric:tabular-nums}
nav.side .meta{margin-top:24px;padding-top:16px;border-top:1px solid var(--line);color:var(--muted);font-size:12px;line-height:1.7}
main{padding:28px 36px 64px;max-width:1240px;width:100%}
header.top{display:flex;flex-wrap:wrap;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:18px}
h1{font-size:24px;letter-spacing:-.02em;margin:0 0 4px}h2{font-size:17px;margin:0 0 14px;letter-spacing:-.01em}
h3{font-size:14px;margin:0 0 8px}.sub{color:var(--muted)}
.badge{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;font-weight:600;font-size:12px;border:1px solid var(--line);background:var(--panel)}
.badge.completed{color:#2f9e44;border-color:currentColor}.badge.partial{color:var(--high);border-color:currentColor}
.badge.failed{color:var(--critical);border-color:currentColor}.badge.no-hooks{color:var(--muted)}
.callout{border:1px solid var(--line);border-left:4px solid var(--accent);background:var(--panel);border-radius:10px;padding:12px 16px;margin:0 0 18px;color:var(--ink2)}
.callout.warn{border-left-color:var(--high)}
section.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px 22px;margin:0 0 18px;box-shadow:var(--shadow)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:18px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px;box-shadow:var(--shadow)}
.kpi .v{font-size:28px;font-weight:700;letter-spacing:-.02em;font-variant-numeric:tabular-nums}.kpi .l{color:var(--muted);font-size:12.5px;font-weight:500}
.dist{display:block;width:100%;height:14px;margin:6px 0 12px}
.dist rect{rx:4px}.f-critical{fill:var(--critical)}.f-high{fill:var(--high)}.f-medium{fill:var(--medium)}.f-low{fill:var(--low)}.f-informational{fill:var(--informational)}.f-unknown{fill:var(--unknown)}
.mt{margin-top:14px}.m0{margin:0}.small{font-size:16px}
.legend{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:12.5px;color:var(--ink2)}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.sev{display:inline-flex;align-items:center;gap:6px;font-weight:650;font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;padding:2px 9px;border-radius:999px;border:1px solid currentColor;white-space:nowrap}
.sev::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}
.s-critical{color:var(--critical)}.s-high{color:var(--high)}.s-medium{color:var(--medium)}.s-low{color:var(--low)}.s-informational{color:var(--informational)}.s-unknown{color:var(--unknown)}
.bg-critical{background:var(--critical)}.bg-high{background:var(--high)}.bg-medium{background:var(--medium)}.bg-low{background:var(--low)}.bg-informational{background:var(--informational)}.bg-unknown{background:var(--unknown)}
.toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:14px}
.toolbar input[type=search]{flex:1 1 260px;min-width:200px;padding:9px 12px;border-radius:10px;border:1px solid var(--line);background:var(--panel2);color:var(--ink);font:inherit}
.chip{display:inline-flex;align-items:center;gap:6px;padding:6px 11px;border-radius:999px;border:1px solid var(--line);background:var(--panel);color:var(--ink2);font:inherit;font-size:12.5px;cursor:pointer}
.chip[aria-pressed=false]{opacity:.45}.chip:focus-visible,.seg button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:10px;overflow:hidden}
.seg button{border:0;background:var(--panel);color:var(--ink2);padding:7px 12px;font:inherit;font-size:12.5px;cursor:pointer}
.seg button[aria-pressed=true]{background:var(--panel2);color:var(--ink);font-weight:600}
.group{margin:18px 0 6px}.group h3{display:flex;gap:10px;align-items:baseline}.group h3 .sub{font-weight:400;font-size:12.5px}
details.f{border:1px solid var(--line);border-radius:12px;background:var(--panel);margin:8px 0;overflow:hidden}
details.f>summary{list-style:none;cursor:pointer;display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:12px;align-items:center;padding:12px 14px}
details.f>summary::-webkit-details-marker{display:none}
details.f>summary:hover{background:var(--panel2)}details.f[open]>summary{border-bottom:1px solid var(--line)}
.ft{font-weight:600}.fm{color:var(--muted);font-size:12px;margin-top:2px;overflow-wrap:anywhere}
.fbody{padding:16px 18px 18px;display:grid;gap:14px}
.kv{display:grid;grid-template-columns:170px minmax(0,1fr);gap:6px 14px}.kv dt{color:var(--muted);font-weight:500}.kv dd{margin:0}
.tags{display:flex;flex-wrap:wrap;gap:6px}.tag{font-size:11.5px;padding:2px 8px;border-radius:6px;background:var(--panel2);color:var(--ink2)}
.ev{border:1px solid var(--line);border-radius:10px;overflow:hidden}
.ev .eh{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;padding:8px 12px;background:var(--panel2);font-size:12.5px}
pre.code{margin:0;background:var(--code);color:var(--codeink);padding:10px 0;overflow:auto;max-height:420px;counter-reset:none}
pre.code span.ln{display:block;padding:0 14px;white-space:pre}pre.code span.ln::before{content:attr(data-n);display:inline-block;width:3.2em;margin-right:14px;color:var(--codeln);text-align:right;user-select:none}
pre.code span.ln:target{background:var(--hl)}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.empty{padding:22px;text-align:center;color:var(--muted);border:1px dashed var(--line);border-radius:12px}
ul.plain{margin:0;padding-left:18px}ul.plain li{margin:3px 0}
.hidden{display:none!important}
footer{color:var(--muted);font-size:12px;margin-top:28px}
@media (max-width:900px){.layout{grid-template-columns:1fr}nav.side{position:static;height:auto;border-right:0;border-bottom:1px solid var(--line)}
nav.side .links{display:flex;flex-wrap:wrap;gap:4px}nav.side .meta{display:none}main{padding:20px 16px 48px}.kv{grid-template-columns:1fr}
details.f>summary{grid-template-columns:1fr}}
@media print{nav.side,.toolbar{display:none}.layout{display:block}details.f{break-inside:avoid}details.f:not([open])>.fbody{display:block}}
"""

JS = r"""
(function(){
  var q=document.getElementById('q'),list=document.getElementById('findings-list'),
      chips=[].slice.call(document.querySelectorAll('[data-sev-toggle]')),
      groupBtns=[].slice.call(document.querySelectorAll('[data-group]')),
      items=[].slice.call(document.querySelectorAll('details.f')),counter=document.getElementById('shown');
  if(!list){return;}
  var active={};chips.forEach(function(c){active[c.getAttribute('data-sev-toggle')]=true;});
  function apply(){var t=(q&&q.value||'').toLowerCase().trim(),n=0;
    items.forEach(function(it){var ok=active[it.getAttribute('data-sev')]&&(!t||it.getAttribute('data-text').indexOf(t)>=0);
      it.classList.toggle('hidden',!ok);if(ok){n++;}});
    [].slice.call(list.querySelectorAll('.group')).forEach(function(g){
      g.classList.toggle('hidden',!g.querySelector('details.f:not(.hidden)'));});
    if(counter){counter.textContent=n+' of '+items.length+' shown';}}
  function regroup(by){var groups={},order=[];
    items.forEach(function(it){var k=it.getAttribute('data-'+by),label=it.getAttribute('data-'+by+'-label')||k;
      if(!groups[k]){groups[k]={label:label,els:[]};order.push(k);}groups[k].els.push(it);});
    order.sort(function(a,b){return groups[a].label.localeCompare(groups[b].label);});
    while(list.firstChild){list.removeChild(list.firstChild);}
    order.forEach(function(k){var sec=document.createElement('div');sec.className='group';
      var h=document.createElement('h3');h.textContent=groups[k].label;var s=document.createElement('span');
      s.className='sub';s.textContent=groups[k].els.length+' finding(s)';h.appendChild(s);sec.appendChild(h);
      groups[k].els.forEach(function(el){sec.appendChild(el);});list.appendChild(sec);});
    groupBtns.forEach(function(b){b.setAttribute('aria-pressed',String(b.getAttribute('data-group')===by));});apply();}
  chips.forEach(function(c){c.addEventListener('click',function(){var s=c.getAttribute('data-sev-toggle');
    active[s]=!active[s];c.setAttribute('aria-pressed',String(active[s]));apply();});});
  groupBtns.forEach(function(b){b.addEventListener('click',function(){regroup(b.getAttribute('data-group'));});});
  if(q){q.addEventListener('input',apply);}
  function openTarget(){var h=location.hash.slice(1);if(!h){return;}var el=document.getElementById(h);
    var d=el&&(el.tagName==='DETAILS'?el:el.closest('details'));if(d){d.open=true;el.scrollIntoView();}}
  window.addEventListener('hashchange',openTarget);openTarget();apply();
})();
"""


def _sha(s: str) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode()


def _code(code: str | None, start: int | None, anchor_prefix: str, focus: tuple[int, int] | None = None) -> str:
    if not code:
        return '<div class="empty">No source excerpt for this evidence item.</div>'
    n0 = int(start or 1)
    rows = []
    for i, line in enumerate(code.splitlines()):
        n = n0 + i
        rows.append(f'<span class="ln" id="{anchor_prefix}-L{n}" data-n="{n}">{e(line) or " "}</span>')
    return f'<pre class="code" tabindex="0">{"".join(rows)}</pre>'


def _sev(s: str) -> str:
    return f'<span class="sev s-{e(s)}">{e(s)}</span>'


def render(report: dict[str, Any]) -> str:
    s = report["summary"]
    scan = report["scan"]
    src = scan["source"]
    cfg = scan["configuration"]
    findings = report["findings"]
    contracts = report["contracts"]
    title = src.get("display_name") or src.get("target") or "Scan"
    counts = s["by_severity"]
    total = sum(counts.values())

    # ------------------------------------------------------------------ header + KPIs
    parts: list[str] = []
    commit = src.get("commit")
    meta_bits = [f"Scanned {e(scan['finished_at'])}", f"HookLens {e(report['tool']['version'])}"]
    if src.get("url"):
        meta_bits.insert(0, f'<a href="{e(src["url"])}" rel="noreferrer noopener">{e(src["url"])}</a>')
    if commit:
        meta_bits.append(
            f"commit <code>{e(commit[:12])}</code>" + (f" ({e(src['branch'])})" if src.get("branch") else "")
        )
    parts.append(
        f'<header class="top" id="overview"><div><h1>{e(title)}</h1><div class="sub">{" · ".join(meta_bits)}</div></div>'
        f'<span class="badge {e(scan["status"])}">{e(STATUS_LABEL.get(scan["status"], scan["status"]))}</span></header>'
    )
    parts.append(
        '<div class="callout"><strong>Static analysis, not execution-tested.</strong> ' + e(report["scope"]) + "</div>"
    )
    if scan.get("problems") or scan.get("error"):
        items = "".join(f"<li>{e(p)}</li>" for p in scan.get("problems") or [])
        if scan.get("error"):
            items += (
                f"<li>{e(scan['error'].get('message'))}"
                + (f" — {e(scan['error'].get('hint'))}" if scan["error"].get("hint") else "")
                + "</li>"
            )
        parts.append(f'<div class="callout warn"><strong>Scan incomplete.</strong><ul class="plain">{items}</ul></div>')
    highest = s.get("highest_severity")
    parts.append(
        '<div class="kpis">'
        f'<div class="kpi"><div class="v">{s["contracts_analyzed"]}</div><div class="l">Contracts analysed</div></div>'
        f'<div class="kpi"><div class="v">{s["hooks"]}<span class="sub small"> + {s["candidates"]}</span></div><div class="l">Hooks + candidates detected</div></div>'
        f'<div class="kpi"><div class="v">{s["findings_total"]}</div><div class="l">Findings ({s["suppressed_below_threshold"]} below report threshold)</div></div>'
        f'<div class="kpi"><div class="v">{_sev(highest) if highest else "—"}</div><div class="l">Highest severity</div></div>'
        "</div>"
    )
    bar, x = [], 0.0
    nonzero = [sv for sv in SEVERITIES if counts.get(sv)]
    gap = 4.0
    width = 1000.0 - gap * max(len(nonzero) - 1, 0)
    for sv in nonzero:
        w = width * counts[sv] / total
        bar.append(
            f'<rect class="f-{sv}" x="{x:.1f}" y="0" width="{w:.1f}" height="14"><title>{sv}: {counts[sv]}</title></rect>'
        )
        x += w + gap
    legend = "".join(
        f'<span><i class="bg-{sv}"></i>{sv} <strong>{counts.get(sv, 0)}</strong></span>' for sv in SEVERITIES
    )
    parts.append(
        '<section class="card"><h2>Severity distribution</h2>'
        + (
            f'<svg class="dist" viewBox="0 0 1000 14" preserveAspectRatio="none" role="img" aria-label="Findings by severity">{"".join(bar)}</svg>'
            if total
            else '<div class="empty">No findings.</div>'
        )
        + f'<div class="legend">{legend}</div></section>'
    )

    # ------------------------------------------------------------------ contracts
    rows: list[str] = []
    skipped_rows: list[str] = []
    for c in contracts:
        perms = c.get("permissions") or {}
        state = "Analysed" if c["analyzed"] else f'<span class="sub">Skipped: {e(c.get("skip_reason"))}</span>'
        cbs = ", ".join(perms.get("callbacks") or []) or ("—" if c["analyzed"] else "")
        reasons = "; ".join(c.get("reasons") or []) or "—"
        n_find = len(c.get("finding_ids") or [])
        (rows if c["analyzed"] else skipped_rows).append(
            f"<tr><td><strong>{e(c['name'])}</strong><div class='fm mono'>{e(c.get('repo_path') or c['file'])}:{e(c.get('line'))}</div></td>"
            f"<td>{e(KIND_LABEL.get(c['kind'], c['kind']))}"
            + (f"<div class='fm'>confidence: {e(c['confidence'])}</div>" if c.get("confidence") else "")
            + "</td>"
            f"<td>{state}<div class='fm'>{e(reasons)}</div></td><td>{e(cbs)}"
            + (f"<div class='fm'>permissions: {e(perms.get('source'))}</div>" if perms else "")
            + f"</td><td class='num'>{n_find if c['analyzed'] else ''}</td></tr>"
        )
    thead = "<table><thead><tr><th>Contract</th><th>Classification</th><th>Analysis</th><th>Callbacks</th><th class='num'>Findings</th></tr></thead><tbody>"
    parts.append(
        '<section class="card" id="contracts"><h2>Contract discovery</h2>'
        + (thead + "".join(rows) + "</tbody></table>" if rows else '<div class="empty">No contract was analysed.</div>')
        + (
            f"<details class='mt'><summary>{len(skipped_rows)} other contract(s) not analysed, with the reason</summary>"
            + thead
            + "".join(skipped_rows)
            + "</tbody></table></details>"
            if skipped_rows
            else ""
        )
        + "</section>"
    )

    # ------------------------------------------------------------------ findings
    sev_chips = "".join(
        f'<button type="button" class="chip" data-sev-toggle="{sv}" aria-pressed="true"><span class="sev s-{sv}">{sv}</span>{counts_r}</button>'
        for sv, counts_r in ((sv, sum(1 for f in findings if f["severity"] == sv)) for sv in SEVERITIES)
        if counts_r
    )
    by_contract: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in sorted(findings, key=lambda f: (SEVERITY_RANK[f["severity"]], f["rule"])):
        by_contract[f"{f['contract']} — {f['contract_file']}"].append(f)
    groups_html = []
    for label, fs in sorted(by_contract.items()):
        groups_html.append(
            f'<div class="group"><h3>{e(label)} <span class="sub">{len(fs)} finding(s)</span></h3>'
            + "".join(_finding(f) for f in fs)
            + "</div>"
        )
    parts.append(
        '<section class="card" id="findings"><h2>Findings</h2>'
        + (
            '<div class="toolbar"><input type="search" id="q" placeholder="Search title, rule, contract, file, function…" aria-label="Search findings">'
            + sev_chips
            + '<div class="seg" role="group" aria-label="Group findings by"><button type="button" data-group="contract" aria-pressed="true">By contract</button>'
            '<button type="button" data-group="rule" aria-pressed="false">By rule</button></div>'
            '<span class="sub" id="shown" aria-live="polite"></span></div>'
            f'<div id="findings-list">{"".join(groups_html)}</div>'
            if findings
            else '<div class="empty">No findings at or above the report threshold ('
            + e(cfg.get("severity_threshold"))
            + "). This does not mean the analysed contracts are safe.</div>"
        )
        + "</section>"
    )

    # ------------------------------------------------------------------ source navigation
    refs: dict[str, list[tuple[int, int, str, str]]] = defaultdict(list)
    for f in findings:
        for ev in f.get("evidence") or []:
            loc = ev.get("location")
            if loc:
                refs[loc["file"]].append((loc["start_line"], loc["end_line"], _anchor(f["id"], ev["id"]), f["title"]))
    src_rows = []
    for file in sorted(refs):
        file_refs = sorted(set(refs[file]))
        links = "".join(
            f'<li><a href="#{a}-L{a0}">lines {a0}–{a1}</a> <span class="sub">— {e(t)}</span></li>'
            for a0, a1, a, t in file_refs
        )
        src_rows.append(
            f"<details><summary class='mono'>{e(file)} <span class='sub'>({len(file_refs)} reference(s))</span></summary><ul class='plain'>{links}</ul></details>"
        )
    parts.append(
        '<section class="card" id="sources"><h2>Source navigation</h2>'
        + ("".join(src_rows) if src_rows else '<div class="empty">No source locations referenced.</div>')
        + "</section>"
    )

    # ------------------------------------------------------------------ configuration & compilation
    comp_rows = "".join(
        f"<tr><td class='mono'>solc {e(g['solc_version'])}</td><td>{e(g.get('evm_version') or 'default')}</td><td>{e(g['status'])}</td>"
        f"<td>{e(g.get('bytecode'))}</td><td class='num'>{len(g['targets'])}</td></tr>"
        + "".join(
            f"<tr><td colspan='5'><pre class='code'><span class='ln' data-n='!'>{e(er.get('formatted') or er.get('message'))}</span></pre></td></tr>"
            for er in g.get("errors") or []
        )
        for g in report["compilation"]
    )
    files = report["files"]
    excluded = "".join(
        f"<li class='mono'>{e(x['file'])} <span class='sub'>({e(x['pattern'])})</span></li>"
        for x in files.get("excluded") or []
    )
    unresolved = "".join(
        f"<li class='mono'>{e(x['unit'])} <span class='sub'>imported by {e(x.get('imported_by'))}: {e(x['reason'])}</span></li>"
        for x in files.get("unresolved_imports") or []
    )
    conf_kv = "".join(
        f"<dt>{e(k)}</dt><dd class='mono'>{e(', '.join(map(str, v)) if isinstance(v, list) else v)}</dd>"
        for k, v in cfg.items()
        if v not in (None, [], "")
    )
    parts.append(
        '<section class="card" id="configuration"><h2>Analysis configuration</h2>'
        f"<dl class='kv'><dt>Source</dt><dd class='mono'>{e(src.get('kind'))}: {e(src.get('url') or src.get('target'))}"
        + (f" @ {e(src.get('ref'))}" if src.get("ref") else "")
        + f"</dd><dt>Project root</dt><dd class='mono'>{e(scan['project']['root'])} ({e(scan['project']['kind'])})</dd>"
        f"<dt>Scan paths</dt><dd class='mono'>{e(', '.join(scan['project']['scan_paths']))}</dd>{conf_kv}"
        f"<dt>Files</dt><dd>{len(files.get('selected') or [])} selected, {len(files.get('excluded') or [])} excluded, "
        f"{len(files.get('unresolved_imports') or [])} unresolved import(s)</dd></dl>"
        + "<h3 class='mt'>Compilation</h3><table><thead><tr><th>Compiler</th><th>EVM</th><th>Status</th><th>Bytecode</th><th class='num'>Files</th></tr></thead><tbody>"
        + comp_rows
        + "</tbody></table>"
        + (
            f"<details class='mt'><summary>Unresolved imports</summary><ul class='plain'>{unresolved}</ul></details>"
            if unresolved
            else ""
        )
        + (
            f"<details class='mt'><summary>Excluded files ({len(files.get('excluded') or [])})</summary><ul class='plain'>{excluded}</ul></details>"
            if excluded
            else ""
        )
        + "</section>"
    )

    lim = "".join(f"<li>{e(x)}</li>" for x in report["limitations"])
    parts.append(
        '<section class="card" id="limitations"><h2>Scope and limitations</h2>'
        f"<p>{e(report['scope'])}</p><ul class='plain'>{lim}</ul>"
        "<h3 class='mt'>Execution-tested results</h3><p class='sub'>None. This report contains static "
        "findings only. To execute controlled scenarios against a deployed hook on a pinned fork, use "
        "<code>hooklens lab</code> with a HookLens server; those results are reported separately and marked as "
        "execution-tested.</p></section>"
    )
    parts.append(
        f"<footer>Generated by HookLens {e(report['tool']['version'])} ({e(report['tool']['analyzer_version'])}) · "
        f"report schema {e(report['schema_version'])} · scan id <span class='mono'>{e(scan['id'])}</span></footer>"
    )

    nav_counts = Counter(f["severity"] for f in findings)
    nav = (
        '<nav class="side" aria-label="Report sections"><div class="brand"><span class="logo" aria-hidden="true">HL</span>HookLens</div>'
        '<div class="links"><a href="#overview">Overview</a>'
        f'<a href="#contracts">Contracts <span class="count">{len(contracts)}</span></a>'
        f'<a href="#findings">Findings <span class="count">{len(findings)}</span></a>'
        '<a href="#sources">Sources</a><a href="#configuration">Configuration</a><a href="#limitations">Limitations</a></div>'
        '<div class="meta">'
        + "".join(f"<div>{_sev(sv)} {nav_counts[sv]}</div>" for sv in SEVERITIES if nav_counts.get(sv))
        + f"<div class='mt'>{e(STATUS_LABEL.get(scan['status'], scan['status']))}</div></div></nav>"
    )
    csp = f"default-src 'none'; style-src '{_sha(CSS)}'; script-src '{_sha(JS)}'; img-src 'none'; base-uri 'none'; form-action 'none'"
    return (
        "<!DOCTYPE html>\n<html lang='en'><head><meta charset='utf-8'>"
        f'<meta http-equiv="Content-Security-Policy" content="{csp}">'
        "<meta name='viewport' content='width=device-width,initial-scale=1'><meta name='referrer' content='no-referrer'>"
        f"<title>HookLens report — {e(title)}</title><style>{CSS}</style></head>"
        f"<body><div class='layout'>{nav}<main>{''.join(parts)}</main></div><script>{JS}</script></body></html>\n"
    )


def _finding(f: dict[str, Any]) -> str:
    loc = f.get("location")
    where = f"{loc['file']}:{loc['start_line']}" if loc else "no source location"
    text = " ".join(
        str(x)
        for x in (
            f["title"],
            f["rule"],
            f["contract"],
            f["category"],
            where,
            " ".join(f.get("affected_functions") or []),
            f["description"],
        )
    ).lower()
    fns = "".join(f"<span class='tag mono'>{e(x)}</span>" for x in f.get("affected_functions") or [])
    lims = "".join(f"<li>{e(x)}</li>" for x in f.get("limitations") or [])
    scen = ", ".join(f.get("related_scenarios") or [])
    evid = []
    for ev in f.get("evidence") or []:
        a = _anchor(f["id"], ev["id"])
        el = ev.get("location")
        head = f"<span><strong>{e(ev['title'])}</strong> <span class='sub'>({e(ev['kind'])}, {e(ev['basis'])})</span></span>"
        if el:
            head += f"<span class='mono'>{e(el['file'])}:{el['start_line']}–{el['end_line']}</span>"
        body = _code(ev.get("excerpt"), ev.get("excerpt_start_line"), a) if ev.get("excerpt") else ""
        if not body and ev.get("data"):
            body = (
                "<pre class='code'>"
                + "".join(
                    f"<span class='ln' data-n='·'>{e(k)}: {e(', '.join(map(str, v)) if isinstance(v, list) else v)}</span>"
                    for k, v in ev["data"].items()
                )
                + "</pre>"
            )
        evid.append(f"<div class='ev' id='{a}'><div class='eh'>{head}</div>{body}</div>")
    return (
        f"<details class='f' id='{e(f['id'])}' data-sev='{e(f['severity'])}' data-text='{e(text)}' "
        f"data-contract='{e(f['contract'] + '|' + f['contract_file'])}' data-contract-label='{e(f['contract'] + ' — ' + f['contract_file'])}' "
        f"data-rule='{e(f['rule'])}' data-rule-label='{e(f['rule'] + ' — ' + (f.get('rule_name') or ''))}'>"
        f"<summary>{_sev(f['severity'])}<div><div class='ft'>{e(f['title'])}</div>"
        f"<div class='fm'><span class='mono'>{e(f['rule'])}</span> · {e(f['contract'])} · <span class='mono'>{e(where)}</span></div></div>"
        f"<span class='sub mono'>{e(f['id'])}</span></summary><div class='fbody'>"
        f"<p class='m0'>{e(f['description'])}</p>"
        "<dl class='kv'>"
        f"<dt>Why it may matter</dt><dd>{e(f['severity_rationale'])}</dd>"
        + (f"<dt>LP implications</dt><dd>{e(f['lp_implications'])}</dd>" if f.get("lp_implications") else "")
        + (f"<dt>What to investigate</dt><dd>{e(f['remediation'])}</dd>" if f.get("remediation") else "")
        + f"<dt>Confidence basis</dt><dd>{e(f['confidence_basis'])} · status {e(f['status'])} (static inference, not execution-tested)</dd>"
        + (f"<dt>Affected functions</dt><dd class='tags'>{fns}</dd>" if fns else "")
        + (
            f"<dt>Fork scenarios</dt><dd>{e(scen)} <span class='sub'>(run with <code>hooklens lab</code> on a deployed hook)</span></dd>"
            if scen
            else ""
        )
        + (f"<dt>Limitations</dt><dd><ul class='plain'>{lims}</ul></dd>" if lims else "")
        + f"<dt>Category</dt><dd>{e(f['category'])} · analyzer {e(f['analyzer'])}</dd></dl>"
        + (f"<div><h3>Evidence</h3>{''.join(evid)}</div>" if evid else "")
        + "</div></details>"
    )
