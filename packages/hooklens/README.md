# hooklens

A local-first static scanner for **Uniswap v4 hook** contracts. It scans a Foundry or Hardhat
project, or a public GitHub repository, and writes HTML, JSON and SARIF reports. It can also gate
CI on finding severity.

This is the same analysis engine that powers the HookLens web app, packaged as a CLI. No API key,
database or server is needed.

```bash
pip install "hooklens @ git+https://github.com/vipinraj32/HookLens#subdirectory=packages/hooklens"

hooklens scan ./my-hook-project --local --html report.html
hooklens scan https://github.com/uniswapfoundation/v4-template --html report.html
hooklens scan . --json report.json --sarif report.sarif --fail-on high
hooklens init --github-action
```

> The PyPI name `hooklens` currently belongs to an unrelated project, so `pip install hooklens`
> does **not** install this tool. Install it from the Git URL above or from a release wheel.

Findings are static indicators that need review, not confirmed exploits. A report with no
findings does not mean a hook is safe.

| Exit code | Meaning |
|---|---|
| 0 | OK |
| 1 | Findings at or above `--fail-on` |
| 2 | Usage or config error |
| 3 | Source error |
| 4 | Analysis error |
| 5 | Report error |

Full documentation is in [docs/cli.md](https://github.com/vipinraj32/HookLens/blob/main/docs/cli.md).
It covers configuration, GitHub Actions, report formats, `hooklens lab` execution testing, and
the methodology and limitations.
