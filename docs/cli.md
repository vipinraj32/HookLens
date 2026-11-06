# HookLens CLI

`hooklens` is a local-first static scanner for Uniswap v4 hook contracts. It uses the **same
analysis engine as the HookLens web app**: the analyzers live in the `hooklens` Python package
(`packages/hooklens/src/hooklens/analyzers`), and the backend imports that package. The CLI is not a
second scanner.

A static scan needs no Anthropic key, database, HookLens server, Foundry, Node.js or RPC endpoint.
The only thing that may be downloaded is a `solc` binary, and only if the right version is not
already installed (`--offline` turns that off).

- [Installation](#installation)
- [Scanning](#scanning)
- [Reports](#reports)
- [Configuration](#configuration)
- [GitHub Actions](#github-actions)
- [Execution testing: `hooklens lab`](#execution-testing-hooklens-lab)
- [How a scan works](#how-a-scan-works)
- [Exit codes](#exit-codes)
- [Limitations](#limitations)

## Installation

Python 3.11 or newer is required.

```bash
# From this repository (works today)
pip install "hooklens @ git+https://github.com/vipinraj32/HookLens#subdirectory=packages/hooklens"

# From a checkout
pip install ./packages/hooklens

# From a release wheel (built by .github/workflows/release-cli.yml and attached to cli-v* releases)
pip install hooklens-0.2.0-py3-none-any.whl
```

> **PyPI name conflict.** The PyPI project name `hooklens` is already used by an unrelated project
> (a coding-agent monitoring tool, unrelated to Uniswap). Until that is resolved, `pip install
> hooklens` installs **that other package, not this one**. Use one of the commands above. The
> product name, the import package and the `hooklens` executable stay the same. The release
> workflow publishes to PyPI only when the repository variable `PYPI_PUBLISH=true` is set, and
> it refuses to run at all until a LICENSE file has been added.

The core install pulls in only `click`, `httpx`, `py-solc-x`, `eth-utils` and `pycryptodome`. The
optional extra `hooklens[schema]` adds `jsonschema`, for validating JSON reports.

Check the install:

```bash
hooklens --help
hooklens version      # HookLens, analyzer, Python and solc versions
hooklens rules        # every stable rule id, e.g. HL.WDR.withdrawal_revert_conditions
```

## Scanning

```bash
# A local Foundry/Hardhat project or a subdirectory of one
hooklens scan ./my-hook-project --local --html report.html

# A public GitHub repository (cloned shallowly into a temp dir, then deleted)
hooklens scan https://github.com/uniswapfoundation/v4-template --html report.html

# A branch / tag / subdirectory
hooklens scan https://github.com/owner/repo/tree/dev/contracts
hooklens scan https://github.com/owner/repo --ref v1.2.0

# CI style: machine-readable reports plus a gate
hooklens scan . --json hooklens-report.json --sarif hooklens.sarif --fail-on high
```

Useful options (`hooklens scan --help` lists them all):

| Option | Meaning |
|---|---|
| `--local` | Treat TARGET as a path and never fetch anything. A URL given with `--local` is a usage error |
| `--path DIR` | Source directory relative to the project root (repeatable). The default is `src` from foundry.toml, else `src/`, else `contracts/` |
| `--contract NAME` | Analyse only these contracts (repeatable). An unknown name exits 2 |
| `--exclude GLOB` | Extra exclusions, e.g. `'src/legacy/**'` |
| `--no-default-excludes` | Do not skip `test/`, `tests/`, `script/`, `lib/`, `node_modules/`, `mocks/`, `*.t.sol`, `*.s.sol` … |
| `--include-mocks` | Analyse contracts classified as mocks too |
| `--remapping a/=path/` | Extra import remapping. remappings.txt, foundry.toml and `lib/*` remappings are read automatically |
| `--solc 0.8.26`, `--evm-version cancun`, `--offline` | Compiler selection |
| `--analyzer ID` / `--disable-analyzer ID` | Run only, or skip, specific analyzers |
| `--severity-threshold LEVEL` | Lowest severity included in the reports (default `informational`) |
| `--sarif-min-severity LEVEL` | Lowest severity sent to SARIF (default `low`, so Code Scanning is not flooded with informational notes) |
| `--fail-on LEVEL\|never` | Exit 1 when a finding at or above LEVEL exists (default `never`) |
| `--summary-md FILE` | Also write the Markdown summary used for CI job summaries |
| `-v` / `-q` | List every finding / print only errors and the status line |

### What gets analysed

Each compiled contract is classified, and the reason is recorded in the report:

| Kind | Meaning | Analysed by default |
|---|---|---|
| `hook` | Implements v4 hook callbacks and declares or derives permissions (high confidence) | yes |
| `candidate` | Hook-shaped (callbacks, PoolManager references) but incomplete evidence (medium confidence) | yes |
| `abstract-hook` | Abstract base hook (e.g. a `BaseHook`) | no (analysed through the contracts that inherit it) |
| `mock` | Name or path looks like a mock or test double | no (`--include-mocks`) |
| `interface`, `library` | Not deployable | no |
| `not-a-hook` | No hook callbacks | no |

Scanning a project with **no hooks** is not an error. The scan exits 0 and says no Uniswap v4 hook
contracts were identified.

### GitHub repositories

- Only `https://github.com/<owner>/<repo>` URLs are accepted (optionally with `/tree/<ref>/<path>`).
  Other hosts, `http://`, SSH URLs, query strings, `..` path segments and option-like refs are
  rejected.
- The repository goes into a fresh temporary directory with a shallow `git clone`. Submodules are
  fetched shallowly, with a full-depth fallback for pinned commits a shallow fetch can't reach. The
  temporary directory is deleted after the scan, including on errors and Ctrl-C.
- **Nothing from the repository is executed.** Git runs with hooks disabled, a system and global
  config that are ignored, HTTPS-only protocols, symlinks off, no fsmonitor and LFS smudging
  skipped. HookLens never runs `forge`, `npm`, Makefiles or scripts. Compilation is plain `solc
  --standard-json` with the sources passed in memory. A `hooklens.toml` in a remote repository is
  **untrusted**: its report paths and `fail_on` are ignored.
- Without `git`, HookLens downloads the GitHub tarball instead. Archive members are checked for
  path traversal; links and devices are skipped; submodules are not included, and the report says
  so. Set `GITHUB_TOKEN` (or `GH_TOKEN`) to raise the API rate limit. It is sent only to the GitHub API and never
  printed.
- Errors are clear and exit 3: repository not found or private, rate limited (with a reset time),
  timeout (`--timeout`, default 300 s), or invalid URL.

## Reports

All formats are rendered from one canonical report, so the same finding has the same id
everywhere.

| Format | Flag | Notes |
|---|---|---|
| Console | (always) | Contracts, findings by severity, gate result |
| HTML | `--html FILE` | One standalone file that works offline: no external requests, and a CSP that allows only its own inline style and script (pinned by hash). Includes severity filters, search, grouping by contract or rule, expandable findings with evidence and source excerpts, source navigation, the compilation details, and scope and limitations. Light and dark themes follow the OS. Untrusted text is HTML-escaped |
| JSON | `--json FILE` | Versioned schema (`schema_version` 1.x), [`report-v1.schema.json`](../packages/hooklens/src/hooklens/schema/report-v1.schema.json). On a failed scan, a JSON failure record with `scan.status = "failed"` and the error is still written |
| SARIF 2.1.0 | `--sarif FILE` | Validates against the OASIS schema. Rule ids are `HL.<CODE>.<rule>`; the stable fingerprint is `partialFingerprints["hooklensFindingId/v1"]`. Locations are repository-relative (`%SRCROOT%`). A finding with no location in the scanned project gets **no** location; HookLens does not invent one. Levels: critical/high → error, medium → warning, low/informational → note, plus `security-severity` |
| Markdown | `--summary-md FILE`, `hooklens summary report.json` | For `$GITHUB_STEP_SUMMARY` and PR comments (`--compact`) |

Each finding has a stable id (`HL-…`), a rule id, analyzer, severity, confidence and confidence
basis, the contract and function, file and line, evidence (source excerpts with line ranges),
LP implications, mitigations and limitations. Findings are **static indicators that need review,
never confirmed exploits**. A report with no findings does not mean the hook is safe, and HookLens
never says it is.

`execution_results` is always `null` in a static scan. Execution-tested results come only from
`hooklens lab` or the web app, and are labelled as such.

## Configuration

`hooklens init` writes a commented `hooklens.toml`. `hooklens init --github-action` also writes
`.github/workflows/hooklens.yml`. Precedence: **command-line flags > `hooklens.toml` > defaults**.
`--config FILE` picks a file explicitly; `--no-config` ignores config files.

```toml
[scan]
paths = ["src"]
exclude = []                 # added to the default excludes
contracts = []
include_mocks = false

[compiler]
# solc = "0.8.26"
# evm_version = "cancun"
remappings = []
allow_download = true

[analysis]
analyzers = []               # empty = all; ids: source_integrity, permissions, bytecode_heuristics,
disable = []                 # access_control, upgradeability, external_calls, oracle, dynamic_fee,
                             # withdrawal, accounting

[report]
html = "hooklens-report.html"
json = "hooklens-report.json"
sarif = "hooklens.sarif"
severity_threshold = "informational"
sarif_min_severity = "low"

[ci]
fail_on = "high"
```

Unknown sections or keys, wrong types and invalid values are errors (exit 2), so typos are not
silently ignored. Report paths are resolved relative to the config file and must stay inside its
directory.

## GitHub Actions

The repository root is a composite action that installs this package and runs the real CLI.

```yaml
name: HookLens
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
  security-events: write   # SARIF upload
  pull-requests: write     # only if comment-on-pr is true
jobs:
  hooklens:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { submodules: recursive }   # Foundry dependencies in lib/
      - uses: vipinraj32/HookLens@main    # pin a release tag or commit SHA once one exists
        with:
          paths: src
          fail-on: high
          html-out: hooklens-report.html
          json-out: hooklens-report.json
          sarif-out: hooklens.sarif
          comment-on-pr: false
```

A copy lives at [`examples/github-actions/hooklens.yml`](../examples/github-actions/hooklens.yml).
No `v1` tag has been published yet, so reference `@main` or a commit SHA for now.

What the action does:

1. Installs the CLI from the action's own checkout into an isolated venv.
2. Runs `hooklens scan --local` on the checked-out code. Inputs reach the shell only through
   environment variables, never `${{ }}` interpolation into scripts.
3. Writes the Markdown summary to the job summary.
4. Uploads SARIF to Code Scanning (category `hooklens`).
5. Uploads the reports as an artifact.
6. If `comment-on-pr: true`, creates or updates a single PR comment, found by a hidden marker.
7. Exits with the scan's exit code: 1 means the gate was reached, 2–5 mean scanner errors. The
   two are reported differently.

For **fork pull requests**, the SARIF upload and the PR comment are skipped, because the token is
read-only. The scan, summary and artifact still run. No secrets are needed.

Inputs: `target`, `paths`, `contracts`, `exclude`, `fail-on` (default `high`),
`severity-threshold`, `html-out`, `json-out`, `sarif-out`, `upload-sarif`, `upload-artifact`,
`artifact-name`, `comment-on-pr`, `config`, `extra-args`, `python-version`, `github-token`.
Outputs: `exit-code`, `json-report`, `sarif-report`.

Using the CLI directly in a workflow works the same way:

```yaml
      - run: pip install "hooklens @ git+https://github.com/vipinraj32/HookLens#subdirectory=packages/hooklens"
      - run: hooklens scan . --local --sarif hooklens.sarif --fail-on high
```

## Execution testing: `hooklens lab`

Static scans read code. `hooklens lab` *executes* a **deployed** hook on a forked chain through
the HookLens simulation engine (Foundry + Anvil):

```bash
hooklens lab --chain 31337 --hook 0x... --api http://127.0.0.1:8000 --json lab.json
hooklens lab --chain 1 --hook 0x... --pool-id 0x... --scenario withdrawal_failure --fail-on-failed
```

It needs a running HookLens server: the API plus a simulation worker with `forge`, and an RPC
endpoint configured server-side for the chain. Before starting, it checks `/v1/health/worker` and
`/v1/chains`, and exits 4 with an explanation if either is missing. Results are the server's run
statuses (passed, failed, expected/unexpected revert, unsupported, …), reported verbatim, for
one fork at one block. They are kept separate from static findings.

## How a scan works

1. **Project discovery.** Finds the project root (`foundry.toml`, `hardhat.config.*`,
   `remappings.txt`), the source paths, the remappings and the solc settings.
2. **Source tree.** Imports are resolved in Python with solc's semantics: relative paths, then
   remappings with longest-prefix and context matching. Only files inside the project root are
   read, unless a remapping given on the command line points elsewhere. Unresolved imports are
   reported with a hint (e.g. `git submodule update --init --recursive`).
3. **Compilation.** Sources are grouped by compatible pragma. The solc version comes from
   foundry.toml or `--solc`, else the highest available version that satisfies the pragmas. EVM
   `cancun` is the default for solc ≥ 0.8.24. Runtime bytecode is generated only for the analysed
   contracts.
4. **Hook detection.** Each contract is classified as in the table above, with a confidence level
   and its reasons.
5. **Analysis.** The shared analyzers run in *source mode*. Permissions come from the parsed
   `getHookPermissions()`, or from the implemented callbacks if none are declared. There is no
   deployed address, so address-bit and on-chain checks are reported as not applicable rather
   than guessed. Internal calls resolve to the most-derived override, so logic in
   `_beforeRemoveLiquidity` behind a `BaseHook` dispatcher is found.
6. **Reports.** A failure in one compilation group or analyzer gives a `partial` scan (exit 4),
   and the rest is still reported.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Scan completed; no finding at or above `--fail-on` (or `--fail-on never`) |
| 1 | Scan completed; at least one finding at or above `--fail-on` |
| 2 | Usage or configuration error (bad flag, invalid `hooklens.toml`, unknown `--contract`) |
| 3 | Source error (path missing, invalid URL, repository not found or private, rate limit, timeout) |
| 4 | Analysis error (no Solidity files, unresolved imports, compiler failure, partial scan) |
| 5 | Report error (an output file could not be written) |
| 130 | Interrupted |

A finding is never reported as a scanner error, and a scanner error never looks like a clean
scan.

## Limitations

- Static analysis of source code at one commit. It does not know the deployed address (so it
  cannot check permission bits), the on-chain owner, proxy implementation or oracle state.
- Heuristic analyzers produce false positives and false negatives. Severity is a deterministic
  rule-based label, not a risk score. See [analyzers.md](analyzers.md).
- Only Solidity sources that compile with an available solc are analysed. Vyper is not supported.
- A Hardhat project's `node_modules` dependencies must be installed for their imports to resolve.
  HookLens does not run a package manager.
- Tarball fallback scans do not include git submodules.
- On Windows, git cannot check out very deeply nested submodule chains. These are usually
  test-only dependencies of dependencies. The scan continues, and the report notes lists the
  missing paths. If a hook actually imports from one of them, the import is reported as
  unresolved (exit 4). Scanning in CI (Linux) avoids this.
- Results apply to the scanned commit only. See also [limitations.md](limitations.md).
