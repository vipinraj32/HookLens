"""Obtain a GitHub repository into an isolated temporary workspace.

Safety rules:
* Only ``https://github.com/<owner>/<repo>`` URLs are accepted (optionally ``/tree/<ref>[/<path>]``).
* Nothing from the repository is executed. git runs with hooks disabled, HTTPS-only protocols
  (also for submodules), no credential prompts, no LFS smudge and no symlink checkout; the tarball
  fallback rejects links, absolute paths and path traversal.
* The workspace is deleted when the scan finishes, fails, times out or is interrupted.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from hooklens.errors import SourceError

_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/(?P<repo>[A-Za-z0-9._-]{1,100}?)(?:\.git)?"
    r"(?:/tree/(?P<rest>[^?#]+))?/?$"
)
MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_MEMBERS = 50_000
API = "https://api.github.com"


@dataclass
class RepoRef:
    owner: str
    repo: str
    ref: str | None
    subpath: str | None

    @property
    def url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}"

    @property
    def name(self) -> str:
        return f"{self.owner}/{self.repo}"


def is_remote(target: str) -> bool:
    return target.startswith(("http://", "https://", "git@", "ssh://", "git://"))


def parse_github_url(url: str, ref: str | None = None) -> RepoRef:
    u = url.strip()
    if u.startswith("http://"):
        raise SourceError("Only https:// GitHub URLs are supported.")
    m = _URL_RE.match(u)
    if not m:
        raise SourceError(
            f"Not a supported GitHub repository URL: {url}",
            hint="Use https://github.com/<owner>/<repo> (optionally /tree/<branch>/<path>).",
        )
    owner, repo = m["owner"], m["repo"]
    if repo in (".", "..") or repo.startswith("."):
        raise SourceError(f"Invalid repository name in URL: {url}")
    subpath = None
    tree_ref = None
    if m["rest"]:
        # /tree/<ref>/<path>: the ref cannot contain '/' here (ambiguous); use --ref for such refs.
        bits = m["rest"].strip("/").split("/", 1)
        tree_ref = bits[0]
        subpath = bits[1] if len(bits) > 1 else None
    if subpath and (".." in subpath.split("/") or subpath.startswith("/")):
        raise SourceError("The path inside the repository may not contain '..'.")
    r = ref or tree_ref
    if r is not None and not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", r):
        raise SourceError(f"Invalid git ref: {r}")
    if r is not None and (r.startswith("-") or ".." in r):
        raise SourceError(f"Invalid git ref: {r}")
    return RepoRef(owner, repo, r, subpath)


def _rmtree(path: Path) -> None:
    """Remove a workspace, including read-only git object files (Windows)."""

    def retry(func: Any, p: Any, _exc: Any) -> None:
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    if not path.exists():
        return
    # Nested submodules can exceed MAX_PATH (git runs with core.longpaths); the extended-length prefix lets
    # Windows delete them.
    target = "\\\\?\\" + str(path.resolve()) if os.name == "nt" else str(path)
    if sys.version_info >= (3, 12):
        shutil.rmtree(target, onexc=retry)
    else:  # pragma: no cover - Python 3.11
        shutil.rmtree(target, onerror=retry)


def _git_env() -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "HOME", "USERPROFILE", "TEMP", "TMP", "LANG")
    }
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "",
            "SSH_ASKPASS": "",
            "GIT_LFS_SKIP_SMUDGE": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
    )
    return env


GIT_SAFE = [
    "-c", "core.hooksPath=" + os.devnull,
    "-c", "core.symlinks=false",
    "-c", "core.fsmonitor=false",
    "-c", "core.longpaths=true",  # Windows: deeply nested Foundry submodules exceed MAX_PATH
    "-c", "protocol.allow=never",
    "-c", "protocol.https.allow=always",
    "-c", "submodule.recurse=false",
    "-c", "advice.detachedHead=false",
]  # fmt: skip


def _git_clone(rr: RepoRef, dest: Path, timeout: int, submodules: bool) -> list[str]:
    git = shutil.which("git")
    if git is None:
        raise FileNotFoundError("git")
    notes: list[str] = []
    cmd = [git, *GIT_SAFE, "clone", "--depth", "1", "--no-tags", "--quiet"]
    if rr.ref:
        cmd += ["--branch", rr.ref]
    cmd += ["--", rr.url + ".git", str(dest)]
    _run(cmd, timeout, "clone", rr)
    if submodules and (dest / ".gitmodules").is_file():
        sub = [
            git,
            *GIT_SAFE,
            "-C",
            str(dest),
            "submodule",
            "update",
            "--init",
            "--recursive",
            "--depth",
            "1",
            "--jobs",
            "4",
        ]
        rc, err = _run_submodules(sub, timeout)
        if rc != 0 and not _PATH_LIMIT.search(err):
            # A pinned submodule commit that is not a branch tip cannot be fetched at depth 1; retry with
            # full history for the submodules only.
            rc, err = _run_submodules([x for x in sub if x not in ("--depth", "1")], timeout)
            if rc == 0:
                notes.append("git submodules were fetched (full depth; shallow fetch was not possible).")
        elif rc == 0:
            notes.append("git submodules were fetched (shallow).")
        if rc != 0:
            failed = sorted({_rel_sub(m, dest) for m in _FAILED_SUB.findall(err)})
            if failed:
                why = " (path too long for git on this platform)" if _PATH_LIMIT.search(err) else ""
                shown = ", ".join(failed[:3]) + (f" and {len(failed) - 3} more" if len(failed) > 3 else "")
                notes.append(
                    f"Some nested git submodules could not be fetched{why}: {shown}. Imports that need them are "
                    "reported as unresolved."
                )
            else:
                last = err.strip().splitlines()[-1] if err.strip() else f"exit code {rc}"
                notes.append(
                    f"git submodules could not be fetched ({last[:200]}); dependency imports may be unresolved."
                )
    return notes


_PATH_LIMIT = re.compile(r"filename too long|'\$GIT_DIR' too big|path too long", re.IGNORECASE)
_FAILED_SUB = re.compile(r"into submodule path '([^']+)' failed")


def _rel_sub(path: str, dest: Path) -> str:
    norm = path.replace("\\", "/")
    root = str(dest).replace("\\", "/").rstrip("/") + "/"
    return norm[len(root) :] if norm.lower().startswith(root.lower()) else norm


def _run_submodules(cmd: list[str], timeout: int) -> tuple[int, str]:
    """Submodule failures are reported as notes (the main checkout succeeded), never as a source error."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=_git_env(), check=False)
    except subprocess.TimeoutExpired:
        return 124, f"git submodule update did not finish within {timeout}s"
    return proc.returncode, proc.stderr or ""


def _run(cmd: list[str], timeout: int, what: str, rr: RepoRef) -> None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=_git_env(), check=False)
    except subprocess.TimeoutExpired as e:
        raise SourceError(f"git {what} of {rr.name} did not finish within {timeout}s.", hint="Raise --timeout.") from e
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()
        tail = err[-1] if err else f"exit code {proc.returncode}"
        low = (proc.stderr or "").lower()
        if "not found" in low or "could not read username" in low or "authentication" in low:
            raise SourceError(
                f"Repository {rr.name} was not found or is not publicly accessible.",
                hint="Check the URL. Private repositories must be cloned locally and scanned as a path.",
            )
        if "remote branch" in low and "not found" in low:
            raise SourceError(f"Ref '{rr.ref}' does not exist in {rr.name}.")
        raise SourceError(f"git {what} failed for {rr.name}: {tail[:300]}")


def _api_headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "hooklens-cli", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _check_api(r: httpx.Response, rr: RepoRef) -> None:
    if r.status_code == 404:
        raise SourceError(
            f"Repository {rr.name}" + (f" at ref '{rr.ref}'" if rr.ref else "") + " was not found or is private.",
            hint="Private repositories must be cloned locally and scanned as a path.",
        )
    if r.status_code in (403, 429) and (r.headers.get("x-ratelimit-remaining") == "0" or r.status_code == 429):
        reset = r.headers.get("x-ratelimit-reset")
        when = ""
        if reset and reset.isdigit():
            when = f" (resets in {max(0, int(reset) - int(time.time())) // 60} min)"
        raise SourceError(
            "GitHub API rate limit exceeded" + when + ".",
            hint="Set GITHUB_TOKEN to raise the limit, or install git so HookLens can clone instead.",
        )
    if r.status_code >= 400:
        raise SourceError(f"GitHub returned HTTP {r.status_code} for {rr.name}.")


def _tarball(
    rr: RepoRef, dest: Path, timeout: int, transport: httpx.BaseTransport | None = None
) -> tuple[str | None, list[str]]:
    notes = ["git is not installed: downloaded a source archive instead; git submodules are not included."]
    ref = rr.ref or "HEAD"
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=_api_headers(), transport=transport) as c:
        try:
            meta = c.get(f"{API}/repos/{rr.owner}/{rr.repo}/commits/{ref}")
            _check_api(meta, rr)
            commit = meta.json().get("sha")
            buf = io.BytesIO()
            with c.stream("GET", f"{API}/repos/{rr.owner}/{rr.repo}/tarball/{commit or ref}") as resp:
                _check_api(resp, rr)
                for chunk in resp.iter_bytes():
                    buf.write(chunk)
                    if buf.tell() > MAX_ARCHIVE_BYTES:
                        raise SourceError(f"Repository archive exceeds {MAX_ARCHIVE_BYTES // (1024 * 1024)} MiB.")
        except httpx.TimeoutException as e:
            raise SourceError(f"Downloading {rr.name} timed out after {timeout}s.") from e
        except httpx.HTTPError as e:
            raise SourceError(f"Could not reach GitHub: {type(e).__name__}.") from e
    buf.seek(0)
    _safe_extract(buf, dest)
    return commit, notes


def _safe_extract(buf: io.BytesIO, dest: Path) -> None:
    dest = dest.resolve()
    try:
        with tarfile.open(fileobj=buf, mode="r:gz") as tf:
            members = tf.getmembers()
            if len(members) > MAX_MEMBERS:
                raise SourceError("Repository archive has too many files.")
            for m in members:
                parts = m.name.split("/", 1)  # strip the <owner>-<repo>-<sha>/ prefix
                if len(parts) < 2 or not parts[1]:
                    continue
                rel = parts[1]
                if m.issym() or m.islnk() or m.isdev() or m.isfifo():
                    continue
                target = (dest / rel).resolve()
                if not target.is_relative_to(dest) or rel.startswith("/") or ".." in Path(rel).parts:
                    raise SourceError(f"Unsafe path in repository archive: {m.name}")
                if m.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif m.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    src = tf.extractfile(m)
                    if src is None:
                        continue
                    with open(target, "wb") as out:
                        shutil.copyfileobj(src, out)
    except tarfile.TarError as e:
        raise SourceError(f"Repository archive could not be read: {e}") from e


def read_git_head(root: Path) -> tuple[str | None, str | None]:
    """(commit, branch) read from .git files directly: no git process runs in the scanned repository."""
    gitdir = root / ".git"
    try:
        if gitdir.is_file():  # worktree / submodule: "gitdir: <path>"
            line = gitdir.read_text(encoding="utf-8").strip()
            if line.startswith("gitdir:"):
                gitdir = (root / line.split(":", 1)[1].strip()).resolve()
        head = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None, None
    if not head.startswith("ref:"):
        return (head if re.fullmatch(r"[0-9a-f]{40}", head) else None), None
    ref = head.split(":", 1)[1].strip()
    branch = ref.removeprefix("refs/heads/")
    try:
        return (gitdir / ref).read_text(encoding="utf-8").strip(), branch
    except OSError:
        pass
    try:
        for line in (gitdir / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref):
                return line.split(" ", 1)[0], branch
    except OSError:
        pass
    return None, branch


@dataclass
class Workspace:
    root: Path
    scan_target: Path
    repo: RepoRef
    commit: str | None
    branch: str | None
    notes: list[str]


@contextmanager
def acquire(
    url: str,
    *,
    ref: str | None = None,
    timeout: int = 300,
    submodules: bool = True,
    transport: httpx.BaseTransport | None = None,
    prefer_git: bool = True,
) -> Iterator[Workspace]:
    rr = parse_github_url(url, ref)
    tmp = Path(tempfile.mkdtemp(prefix="hooklens-repo-"))
    try:
        dest = tmp / rr.repo
        notes: list[str] = []
        commit = branch = None
        try:
            if not prefer_git:
                raise FileNotFoundError("git")
            notes += _git_clone(rr, dest, timeout, submodules)
            commit, branch = read_git_head(dest)
            branch = branch or rr.ref
        except FileNotFoundError:
            _rmtree(dest)
            dest.mkdir(parents=True)
            commit, more = _tarball(rr, dest, timeout, transport)
            notes += more
            branch = rr.ref
        target = dest / rr.subpath if rr.subpath else dest
        if not target.resolve().is_relative_to(dest.resolve()) or not target.exists():
            raise SourceError(f"Path '{rr.subpath}' does not exist in {rr.name}.")
        yield Workspace(dest, target, rr, commit, branch, notes)
    finally:
        _rmtree(tmp)
