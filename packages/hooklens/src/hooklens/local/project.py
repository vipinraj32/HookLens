"""Local Solidity project discovery: root, layout, remappings, source files, import graph.

Nothing in a scanned project is executed. Configuration files (foundry.toml, remappings.txt)
are parsed as data, imports are resolved in Python, and every file that is read must live inside
the project root unless the *user* supplied a remapping that points elsewhere on the command line.
"""

from __future__ import annotations

import posixpath
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from hooklens.config import DEFAULT_EXCLUDES, ScanConfig
from hooklens.errors import AnalysisError, SourceError

MAX_FILES = 6000
MAX_FILE_BYTES = 3 * 1024 * 1024
PROJECT_MARKERS = ("foundry.toml", "remappings.txt", "hardhat.config.ts", "hardhat.config.js")

_COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_IMPORT_RE = re.compile(r"\bimport\s+(?:[^;\"']*?\bfrom\s+)?[\"']([^\"']+)[\"']")


@dataclass
class Remapping:
    context: str
    prefix: str
    target: str
    origin: str  # cli | hooklens.toml | remappings.txt | foundry.toml | lib:<name> | auto

    @classmethod
    def parse(cls, text: str, origin: str) -> Remapping:
        ctx = ""
        body = text.strip()
        if ":" in body.split("=", 1)[0]:
            ctx, body = body.split(":", 1)
        prefix, target = body.split("=", 1)
        return cls(ctx.strip(), prefix.strip(), target.strip(), origin)

    @property
    def trusted(self) -> bool:
        return self.origin == "cli"

    def solc(self) -> str:
        return (f"{self.context}:" if self.context else "") + f"{self.prefix}={self.target}"

    def to_dict(self) -> dict[str, str]:
        return {"context": self.context, "prefix": self.prefix, "target": self.target, "origin": self.origin}


@dataclass
class Project:
    root: Path
    repo_root: Path
    kind: str  # foundry | hardhat | plain
    scan_paths: list[Path]
    remappings: list[Remapping]
    solc: str | None = None
    evm_version: str | None = None
    optimizer: bool = False
    optimizer_runs: int = 200
    via_ir: bool = False
    notes: list[str] = field(default_factory=list)

    def rel(self, p: Path) -> str:
        return p.resolve().relative_to(self.root).as_posix()

    def repo_path(self, unit: str) -> str | None:
        """Repository-relative path of a source unit, or None when it lies outside the repository."""
        p = Path(unit) if Path(unit).is_absolute() else self.root / unit
        try:
            return p.resolve().relative_to(self.repo_root).as_posix()
        except ValueError:
            return None


# ====================================================================== discovery


def _find_up(start: Path, stop: Path | None) -> Path | None:
    cur = start
    while True:
        if any((cur / m).is_file() for m in PROJECT_MARKERS):
            return cur
        if (stop is not None and cur == stop) or (cur / ".git").exists() or cur.parent == cur:
            return None
        cur = cur.parent


def find_repo_root(start: Path) -> Path | None:
    cur = start
    while True:
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            return None
        cur = cur.parent


def _foundry_profile(root: Path) -> dict[str, object]:
    f = root / "foundry.toml"
    if not f.is_file():
        return {}
    try:
        data = tomllib.loads(f.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise AnalysisError(f"foundry.toml could not be parsed: {e}") from e
    prof = (data.get("profile") or {}).get("default") or {}
    return prof if isinstance(prof, dict) else {}


def discover_project(target: Path, cfg: ScanConfig, *, boundary: Path | None = None) -> Project:
    """`boundary` stops the upward search for a project root (used for cloned repositories)."""
    target = target.resolve()
    if not target.exists():
        raise SourceError(f"Path does not exist: {target}")
    start = target if target.is_dir() else target.parent
    root = _find_up(start, boundary) or start
    repo_root = boundary.resolve() if boundary else (find_repo_root(root) or root)
    prof = _foundry_profile(root)
    kind = (
        "foundry"
        if (root / "foundry.toml").is_file()
        else ("hardhat" if any((root / m).is_file() for m in PROJECT_MARKERS[2:]) else "plain")
    )
    notes: list[str] = []

    # ---------------------------------------------------------------- scan paths
    if cfg.paths:
        scan_paths = [(root / p).resolve() for p in cfg.paths]
    elif target != root:
        scan_paths = [target]
    else:
        src = prof.get("src")
        cands = [str(src)] if isinstance(src, str) else ["src", "contracts"]
        scan_paths = [root / c for c in cands if (root / c).is_dir()] or [root]
    for p in scan_paths:
        if not p.exists():
            raise SourceError(f"Scan path does not exist: {p}")
        if not p.resolve().is_relative_to(root):
            raise SourceError(f"Scan path {p} is outside the project root {root}.")

    # ---------------------------------------------------------------- remappings
    remaps: list[Remapping] = [Remapping.parse(r, "cli") for r in cfg.remappings]
    rfile = root / "remappings.txt"
    if rfile.is_file():
        for line in rfile.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                remaps.append(Remapping.parse(line, "remappings.txt"))
    raw_remaps = prof.get("remappings")
    for r in raw_remaps if isinstance(raw_remaps, list) else []:
        if isinstance(r, str) and "=" in r:
            remaps.append(Remapping.parse(r, "foundry.toml"))
    raw_libs = prof.get("libs")
    libs: list[object] = raw_libs if isinstance(raw_libs, list) else ["lib"]
    for lib in libs:
        _lib_remappings(root, Path(str(lib)), remaps, depth=0)
    seen: set[tuple[str, str]] = set()
    uniq = []
    for r in remaps:  # earlier sources win for identical (context, prefix)
        key = (r.context, r.prefix)
        if key not in seen:
            seen.add(key)
            uniq.append(r)

    solc = cfg.solc or _str(prof.get("solc_version") or prof.get("solc"))
    if solc and not re.fullmatch(r"\d+\.\d+\.\d+", solc):
        notes.append(f"foundry.toml solc setting '{solc}' is not an exact version; using pragma-based selection.")
        solc = None
    return Project(
        root=root,
        repo_root=repo_root,
        kind=kind,
        scan_paths=scan_paths,
        remappings=uniq,
        solc=solc,
        evm_version=cfg.evm_version or _str(prof.get("evm_version")),
        optimizer=bool(prof.get("optimizer", False)),
        optimizer_runs=int(prof.get("optimizer_runs", 200) or 200),  # type: ignore[call-overload]
        via_ir=bool(prof.get("via_ir", False)),
        notes=notes,
    )


def _str(v: object) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


def _lib_remappings(root: Path, lib: Path, out: list[Remapping], depth: int) -> None:
    """Foundry-style automatic remappings for dependencies vendored under lib/ (git submodules)."""
    base = root / lib
    if not base.is_dir() or depth > 2:
        return
    for d in sorted(p for p in base.iterdir() if p.is_dir()):
        rel = (lib / d.name).as_posix()
        nested = d / "remappings.txt"
        if nested.is_file():
            for line in nested.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    r = Remapping.parse(line, f"lib:{d.name}")
                    if not r.target.startswith("/") and not re.match(r"^[A-Za-z]:", r.target):
                        r.target = posixpath.join(rel, r.target)
                        out.append(r)
        target = f"{rel}/src/" if (d / "src").is_dir() else f"{rel}/"
        out.append(Remapping("", f"{d.name}/", target, "auto"))
        _lib_remappings(root, lib / d.name / "lib", out, depth + 1)


# ====================================================================== source files


def _glob_re(pattern: str) -> re.Pattern[str]:
    i, out = 0, ""
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


def exclusion_patterns(cfg: ScanConfig) -> list[str]:
    return (list(DEFAULT_EXCLUDES) if cfg.default_excludes else []) + list(cfg.exclude)


def list_sources(project: Project, cfg: ScanConfig) -> tuple[list[str], list[dict[str, str]]]:
    """Solidity files to analyse (root-relative), plus the excluded ones with the matching pattern."""
    pats = [(p, _glob_re(p)) for p in exclusion_patterns(cfg)]
    included: list[str] = []
    excluded: list[dict[str, str]] = []
    for sp in project.scan_paths:
        files = [sp] if sp.is_file() else sorted(sp.rglob("*.sol"))
        for f in files:
            if f.is_symlink() or not f.is_file():
                continue
            rel = project.rel(f)
            hit = next((p for p, rx in pats if rx.match(rel)), None)
            # A file named explicitly on the command line is never excluded by pattern.
            if hit and not sp.is_file():
                excluded.append({"file": rel, "pattern": hit})
            elif rel not in included:
                included.append(rel)
            if len(included) > MAX_FILES:
                raise AnalysisError(f"More than {MAX_FILES} Solidity files under the scan paths.")
    return included, excluded


# ====================================================================== imports


@dataclass
class SourceTree:
    sources: dict[str, str]  # source unit name -> content
    imports: dict[str, list[str]]  # unit -> imported units
    disk: dict[str, Path]
    errors: list[dict[str, str]]


def imports_of(content: str) -> list[str]:
    return _IMPORT_RE.findall(_COMMENT_RE.sub("", content))


def _remap(project: Project, importer: str, path: str) -> tuple[str, Remapping | None]:
    best: Remapping | None = None
    for r in project.remappings:
        if r.context and not importer.startswith(r.context):
            continue
        if path.startswith(r.prefix) and (
            best is None or (len(r.context), len(r.prefix)) > (len(best.context), len(best.prefix))
        ):
            best = r
    if best is None:
        return path, None
    return best.target + path[len(best.prefix) :], best


def resolve_import(project: Project, importer: str, path: str) -> tuple[str, Remapping | None]:
    if path.startswith(("./", "../")):
        path = posixpath.normpath(posixpath.join(posixpath.dirname(importer), path))
    return _remap(project, importer, path)


def _locate(project: Project, unit: str, trusted: bool) -> tuple[Path | None, str | None]:
    candidates = (
        [Path(unit)] if Path(unit).is_absolute() else [project.root / unit, project.root / "node_modules" / unit]
    )
    for c in candidates:
        if c.is_file():
            real = c.resolve()
            if not trusted and not real.is_relative_to(project.root):
                return None, f"resolves outside the project root ({unit})"
            if real.stat().st_size > MAX_FILE_BYTES:
                return None, f"file larger than {MAX_FILE_BYTES // (1024 * 1024)} MiB"
            return real, None
    return None, None


def load_tree(project: Project, roots: list[str]) -> SourceTree:
    tree = SourceTree({}, {}, {}, [])
    # (unit, importer, may_leave_root): only files reached through a remapping given on the command
    # line (and relative imports between such files) may live outside the project root.
    stack: list[tuple[str, str | None, bool]] = [(u, None, False) for u in roots]
    while stack:
        unit, importer, trusted = stack.pop()
        if unit in tree.sources or any(e["unit"] == unit for e in tree.errors):
            continue
        disk, why = _locate(project, unit, trusted)
        if disk is None:
            tree.errors.append(
                {
                    "unit": unit,
                    "imported_by": importer or "",
                    "reason": why or "file not found",
                }
            )
            continue
        content = disk.read_text(encoding="utf-8", errors="replace")
        tree.sources[unit] = content
        tree.disk[unit] = disk
        deps = []
        for imp in imports_of(content):
            dep, remap = resolve_import(project, unit, imp)
            deps.append(dep)
            outside_ok = remap.trusted if remap is not None else (trusted and imp.startswith(("./", "../")))
            stack.append((dep, unit, outside_ok))
        tree.imports[unit] = deps
        if len(tree.sources) > MAX_FILES:
            raise AnalysisError(f"The import graph exceeds {MAX_FILES} files.")
    return tree


def closure(tree: SourceTree, unit: str) -> set[str]:
    seen: set[str] = set()
    stack = [unit]
    while stack:
        u = stack.pop()
        if u in seen:
            continue
        seen.add(u)
        stack.extend(tree.imports.get(u, []))
    return seen
