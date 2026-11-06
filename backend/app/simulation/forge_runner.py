"""Runs Foundry scenario tests as isolated subprocesses.

Security properties:
  * argument lists only (no shell), fixed executable from server config;
  * the environment is an allowlist: OS essentials + HL_* scenario variables + the fork URL;
  * the fork RPC URL is passed via HOOKLENS_FORK_RPC_URL and referenced through the
    `hooklens_fork` alias in foundry.toml, never on the command line (it can contain an API
    key, and argv is visible to other local processes);
  * FFI is forced off; the harness can only write inside contracts/sim-out (foundry.toml);
  * per-scenario wall-clock timeout and cooperative cancellation (process is killed).
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.observability import redact

_ESSENTIAL_ENV = (
    "PATH",
    "SYSTEMROOT",
    "SystemRoot",
    "WINDIR",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "COMSPEC",
    "PATHEXT",
    "LANG",
    "LC_ALL",
)
FORK_ALIAS = "hooklens_fork"
FORK_ENV = "HOOKLENS_FORK_RPC_URL"
_build_lock = threading.Lock()
_built_digest: str | None = None


@dataclass
class ForgeRun:
    status: str  # completed | timed_out | cancelled | spawn_error
    exit_code: int | None
    duration_ms: int
    output: dict[str, Any] | None
    stderr_tail: str
    parse_error: str | None = None
    argv: list[str] = field(default_factory=list)


def forge_path() -> str | None:
    s = get_settings()
    found = shutil.which(s.forge_bin)
    if found:
        return found
    for cand in (Path.home() / ".foundry" / "bin" / "forge.exe", Path.home() / ".foundry" / "bin" / "forge"):
        if cand.exists():
            return str(cand)
    return None


def _base_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _ESSENTIAL_ENV}
    fp = forge_path()
    if fp:
        env["PATH"] = str(Path(fp).parent) + os.pathsep + env.get("PATH", "")
    env["NO_COLOR"] = "1"
    env["FOUNDRY_FFI"] = "false"
    env["FOUNDRY_DISABLE_NIGHTLY_WARNING"] = "1"
    return env


def ensure_built(digest: str, timeout_s: int = 600) -> tuple[bool, str]:
    """Compile once per harness digest so concurrent scenario runs never race the compiler."""
    global _built_digest
    with _build_lock:
        if _built_digest == digest:
            return True, ""
        fp = forge_path()
        if not fp:
            return False, "forge executable not found (install Foundry: https://getfoundry.sh)"
        try:
            p = subprocess.run(
                [fp, "build"],
                cwd=get_settings().contracts_dir,
                env=_base_env(),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, "forge build timed out"
        if p.returncode != 0:
            return False, redact((p.stderr or p.stdout)[-2000:])
        _built_digest = digest
        return True, ""


def scenario_argv(contract: str, fork_block: int | None, *, fork_url_placeholder: str | None = None) -> list[str]:
    argv = ["test", "--match-contract", f"^{contract}$", "--json", "-vvvv"]
    if fork_url_placeholder is not None:
        argv += ["--fork-url", fork_url_placeholder]
    if fork_block is not None:
        argv += ["--fork-block-number", str(fork_block)]
    return argv


def repro_command(contract: str, fork_block: int | None, env: dict[str, str]) -> str:
    exports = " ".join(f"{k}={shlex.quote(v)}" for k, v in sorted(env.items()) if k.startswith("HL_"))
    cmd = " ".join(["forge", *scenario_argv(contract, fork_block, fork_url_placeholder='"$ETH_RPC_URL"')])
    cmd = cmd.replace("--json ", "")
    return f"cd contracts && export ETH_RPC_URL=<archive RPC URL for this chain> && {exports} {cmd}"


def run_scenario(
    contract: str,
    *,
    fork_url: str,
    fork_block: int | None,
    scenario_env: dict[str, str],
    log_path: Path,
    timeout_s: int,
    should_cancel: Callable[[], bool],
    heartbeat: Callable[[], None] | None = None,
) -> ForgeRun:
    fp = forge_path()
    if not fp:
        return ForgeRun("spawn_error", None, 0, None, "forge executable not found")
    # `hooklens_fork` is an [rpc_endpoints] alias in foundry.toml resolved from
    # HOOKLENS_FORK_RPC_URL, so the URL (which may embed an API key) never appears in argv.
    argv = [fp, *scenario_argv(contract, fork_block, fork_url_placeholder=FORK_ALIAS)]
    env = _base_env()
    env.update({k: v for k, v in scenario_env.items() if k.startswith("HL_")})
    env[FORK_ENV] = fork_url

    log_path.parent.mkdir(parents=True, exist_ok=True)
    out_path = log_path.with_suffix(".stdout.json")
    err_path = log_path.with_suffix(".stderr.txt")
    t0 = time.monotonic()
    status = "completed"
    with open(out_path, "wb") as out_f, open(err_path, "wb") as err_f:
        try:
            proc = subprocess.Popen(
                argv, cwd=get_settings().contracts_dir, env=env, stdout=out_f, stderr=err_f, stdin=subprocess.DEVNULL
            )
        except OSError as e:
            return ForgeRun("spawn_error", None, 0, None, str(e))
        last_hb = t0
        while proc.poll() is None:
            now = time.monotonic()
            if now - t0 > timeout_s:
                status = "timed_out"
                proc.kill()
                break
            if should_cancel():
                status = "cancelled"
                proc.kill()
                break
            if heartbeat and now - last_hb > 10:
                heartbeat()
                last_hb = now
            time.sleep(0.25)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    duration = int((time.monotonic() - t0) * 1000)
    stderr_tail = redact(err_path.read_text(encoding="utf-8", errors="replace")[-4000:]).replace(fork_url, "[RPC]")
    output, parse_error = None, None
    if status == "completed":
        raw = out_path.read_text(encoding="utf-8", errors="replace").strip()
        if raw:
            try:
                output = json.loads(raw)
            except json.JSONDecodeError as e:
                parse_error = f"forge JSON output could not be parsed: {e}"
        else:
            parse_error = "forge produced no JSON output"
    return ForgeRun(
        status, proc.returncode, duration, output, stderr_tail, parse_error, argv=[os.path.basename(argv[0]), *argv[1:]]
    )
