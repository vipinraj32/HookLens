"""Shared fixtures: an isolated SQLite database per test session, the in-process job dispatcher,
and an API client. Integration tests against Anvil/forge are opt-in via markers."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="hooklens-test-"))
os.environ["HOOKLENS_DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["HOOKLENS_REPORTS_DIR"] = str(_TMP / "reports")
os.environ["HOOKLENS_ENVIRONMENT"] = "test"
os.environ["HOOKLENS_ANTHROPIC_API_KEY"] = ""
os.environ["HOOKLENS_MAINNET_RPC_URL"] = ""
os.environ["HOOKLENS_RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["HOOKLENS_RATE_LIMIT_JOBS_PER_MINUTE"] = "100000"

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.db.migrate import upgrade_head  # noqa: E402
from app.jobs.dispatch import LocalDispatcher, set_dispatcher  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_sessionstart(session: pytest.Session) -> None:
    upgrade_head()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    from app.db.base import get_engine

    get_engine().dispose()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(scope="session")
def dispatcher() -> Iterator[LocalDispatcher]:
    d = LocalDispatcher(2)
    set_dispatcher(d)
    yield d
    set_dispatcher(None)


@pytest.fixture()
def client(dispatcher: LocalDispatcher) -> Iterator[object]:
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def _anvil_ready() -> bool:
    import httpx

    s = get_settings()
    if not s.deployments_file.exists():
        return False
    try:
        r = httpx.post(
            s.local_rpc_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_getCode",
                "params": [json.loads(s.deployments_file.read_text())["pool_manager"], "latest"],
            },
            timeout=2,
        )
        return len(r.json().get("result", "0x")) > 2
    except Exception:
        return False


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    anvil_ok = _anvil_ready()
    from app.simulation.forge_runner import forge_path

    forge_ok = forge_path() is not None
    # In CI the integration job sets HL_TEST_ANVIL=1 so a missing chain fails loudly instead of skipping.
    if os.environ.get("HL_TEST_ANVIL") == "1" and not (anvil_ok and forge_ok):
        raise pytest.UsageError(
            f"HL_TEST_ANVIL=1 but anvil_ready={anvil_ok} forge_available={forge_ok}; run scripts/dev-chain.sh first"
        )
    for item in items:
        if "anvil" in item.keywords and not anvil_ok:
            item.add_marker(
                pytest.mark.skip(reason="Anvil with HookLens fixtures is not running (scripts/dev-chain.sh)")
            )
        if "forge" in item.keywords and not forge_ok:
            item.add_marker(pytest.mark.skip(reason="forge is not installed"))


@pytest.fixture(scope="session")
def deployments() -> dict:
    return json.loads(get_settings().deployments_file.read_text())
