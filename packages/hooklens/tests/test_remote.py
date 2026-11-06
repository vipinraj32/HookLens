"""GitHub repository acquisition: URL validation, archive fallback, errors and cleanup."""

from __future__ import annotations

import io
import tarfile
import tempfile
from pathlib import Path

import httpx
import pytest

from hooklens import remote
from hooklens.errors import SourceError


def _leftovers() -> set[str]:
    return {p.name for p in Path(tempfile.gettempdir()).glob("hooklens-repo-*")}


@pytest.mark.parametrize(
    ("url", "owner", "repo", "ref", "sub"),
    [
        ("https://github.com/uniswapfoundation/v4-template", "uniswapfoundation", "v4-template", None, None),
        ("https://github.com/a/b.git", "a", "b", None, None),
        ("https://github.com/a/b/", "a", "b", None, None),
        ("https://github.com/a/b/tree/dev/contracts/src", "a", "b", "dev", "contracts/src"),
    ],
)
def test_parse_url(url: str, owner: str, repo: str, ref: str | None, sub: str | None) -> None:
    rr = remote.parse_github_url(url)
    assert (rr.owner, rr.repo, rr.ref, rr.subpath) == (owner, repo, ref, sub)


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/a/b",
        "https://gitlab.com/a/b",
        "https://github.com/a",
        "https://github.com/a/b/tree/main/../../etc",
        "git@github.com:a/b.git",
        "https://github.com/a/b?x=1",
        "https://github.com/-a/b",
    ],
)
def test_rejects_invalid_urls(url: str) -> None:
    with pytest.raises(SourceError):
        remote.parse_github_url(url)


def test_rejects_option_like_ref() -> None:
    with pytest.raises(SourceError):
        remote.parse_github_url("https://github.com/a/b", ref="--upload-pack=x")


def _tarball(files: dict[str, bytes], extra: list[tarfile.TarInfo] | None = None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            ti = tarfile.TarInfo(f"o-r-abc123/{name}")
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        for ti in extra or []:
            tf.addfile(ti, io.BytesIO(b"x" * ti.size) if ti.size else None)
    return buf.getvalue()


def _transport(tar: bytes, *, status: int = 200, headers: dict[str, str] | None = None) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, headers=headers or {}, json={"message": "x"})
        if "/commits/" in req.url.path:
            return httpx.Response(200, json={"sha": "a" * 40})
        return httpx.Response(200, content=tar)

    return httpx.MockTransport(handler)


def test_archive_fallback_and_cleanup() -> None:
    tar = _tarball({"src/H.sol": b"pragma solidity ^0.8.0; contract H {}", "foundry.toml": b"[profile.default]\n"})
    before = _leftovers()
    with remote.acquire("https://github.com/o/r", transport=_transport(tar), prefer_git=False) as ws:
        assert (ws.root / "src" / "H.sol").is_file()
        assert ws.commit == "a" * 40
        assert any("submodules are not included" in n for n in ws.notes)
        root = ws.root
    assert not root.exists() and _leftovers() == before


def test_archive_rejects_traversal_and_skips_links() -> None:
    evil = tarfile.TarInfo("o-r-abc123/../../escape.sol")
    evil.size = 1
    with pytest.raises(SourceError, match="Unsafe path"):
        with remote.acquire("https://github.com/o/r", transport=_transport(_tarball({}, [evil])), prefer_git=False):
            pass
    link = tarfile.TarInfo("o-r-abc123/link.sol")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    with remote.acquire(
        "https://github.com/o/r", transport=_transport(_tarball({"a.sol": b"x"}, [link])), prefer_git=False
    ) as ws:
        assert not (ws.root / "link.sol").exists()


def test_not_found_and_rate_limit_errors_clean_up() -> None:
    before = _leftovers()
    with pytest.raises(SourceError, match="not found or is private"):
        with remote.acquire("https://github.com/o/r", transport=_transport(b"", status=404), prefer_git=False):
            pass
    with (
        pytest.raises(SourceError, match="rate limit") as ei,
        remote.acquire(
            "https://github.com/o/r",
            transport=_transport(b"", status=403, headers={"x-ratelimit-remaining": "0"}),
            prefer_git=False,
        ),
    ):
        pass
    assert "GITHUB_TOKEN" in (ei.value.hint or "")
    assert _leftovers() == before


def test_timeout_is_source_error() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(SourceError, match="timed out"):
        with remote.acquire("https://github.com/o/r", transport=httpx.MockTransport(handler), prefer_git=False):
            pass


def test_missing_subpath() -> None:
    tar = _tarball({"src/H.sol": b"x"})
    with pytest.raises(SourceError, match="does not exist"):
        with remote.acquire("https://github.com/o/r/tree/main/contracts", transport=_transport(tar), prefer_git=False):
            pass


def test_interrupt_cleans_up() -> None:
    tar = _tarball({"src/H.sol": b"x"})
    before = _leftovers()
    with pytest.raises(KeyboardInterrupt):
        with remote.acquire("https://github.com/o/r", transport=_transport(tar), prefer_git=False):
            raise KeyboardInterrupt
    assert _leftovers() == before


def test_read_git_head(tmp_path: Path) -> None:
    g = tmp_path / ".git"
    (g / "refs" / "heads").mkdir(parents=True)
    (g / "HEAD").write_text("ref: refs/heads/main\n")
    (g / "refs" / "heads" / "main").write_text("b" * 40 + "\n")
    assert remote.read_git_head(tmp_path) == ("b" * 40, "main")
    (g / "refs" / "heads" / "main").unlink()
    (g / "packed-refs").write_text("# pack\n" + "c" * 40 + " refs/heads/main\n")
    assert remote.read_git_head(tmp_path) == ("c" * 40, "main")


@pytest.mark.network
def test_scan_real_github_repository(tmp_path: Path) -> None:
    """Uniswap Foundation's v4-template: cloned with submodules and scanned end to end."""
    import json

    from click.testing import CliRunner

    from hooklens.cli import main

    before = _leftovers()
    r = CliRunner().invoke(
        main,
        ["scan", "https://github.com/uniswapfoundation/v4-template", "--json", str(tmp_path / "t.json"), "-q"],
    )
    assert r.exit_code == 0, r.output
    doc = json.loads((tmp_path / "t.json").read_text(encoding="utf-8"))
    assert doc["scan"]["source"]["commit"] and doc["scan"]["status"] == "completed"
    counter = next(c for c in doc["contracts"] if c["name"] == "Counter")
    assert counter["kind"] == "hook" and counter["analyzed"]
    assert _leftovers() == before


def test_nested_submodule_path_limit_is_a_note_not_an_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Git for Windows cannot check out very deep test-only submodule chains; that must not fail the scan."""
    dest = tmp_path / "repo"
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], timeout: int, what: str, rr: remote.RepoRef) -> None:
        dest.mkdir()
        (dest / ".gitmodules").write_text('[submodule "lib/a"]\n')

    def fake_sub(cmd: list[str], timeout: int) -> tuple[int, str]:
        calls.append(cmd)
        deep = (dest / "lib/a/lib/b/lib/c").as_posix()
        return 1, f"fatal: '$GIT_DIR' too big\nfatal: clone of 'https://x/c' into submodule path '{deep}' failed\n"

    monkeypatch.setattr(remote, "_run", fake_run)
    monkeypatch.setattr(remote, "_run_submodules", fake_sub)
    monkeypatch.setattr(remote.shutil, "which", lambda _: "git")
    notes = remote._git_clone(remote.parse_github_url("https://github.com/o/r"), dest, 10, True)
    assert len(calls) == 1  # no pointless full-depth retry for a path-length failure
    assert notes == [
        "Some nested git submodules could not be fetched (path too long for git on this platform): lib/a/lib/b/lib/c. "
        "Imports that need them are reported as unresolved."
    ]
