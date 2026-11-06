"""Supported chain registry.

The registry is server configuration. Users select a chain by ID; they never provide RPC
endpoints, which removes the SSRF surface of user-controlled URLs entirely.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.config import Settings, get_settings
from app.errors import AppError

# Uniswap v4 PoolManager on Ethereum mainnet (Uniswap v4 deployments documentation).
MAINNET_POOL_MANAGER = "0x000000000004444c5dc75cB358380D2e3dE08A90"
# Conservative lower bound for the mainnet PoolManager deployment (Uniswap v4 launched on
# mainnet in January 2025). Initialize logs cannot predate it; starting slightly earlier only
# costs a few extra log queries, starting later could miss pools.
MAINNET_POOL_MANAGER_DEPLOY_BLOCK = 21_600_000

# Uniswap v4 PoolManager on Sepolia, from the Uniswap v4 deployments documentation. Its creation
# transaction (0xdb2321e6dd8e0147066338043ab05d34f3b3d5cba9104c4e3286ebfd73399b8f) was mined in
# block 7_258_946, so pool discovery starts there.
SEPOLIA_POOL_MANAGER = "0xE03A1074c86CFeDd5C142C4F04F1a1536e203543"
SEPOLIA_POOL_MANAGER_DEPLOY_BLOCK = 7_258_946


@dataclass(frozen=True)
class ChainConfig:
    chain_id: int
    name: str
    short_name: str
    native_symbol: str
    pool_manager: str | None
    pool_manager_deploy_block: int
    explorer_name: str | None
    explorer_url: str | None
    is_local: bool = False
    rpc_url: str | None = field(default=None, repr=False)  # secret; never serialise
    notes: list[str] = field(default_factory=list)

    @property
    def rpc_configured(self) -> bool:
        return bool(self.rpc_url)

    def public_dict(self) -> dict[str, object]:
        return {
            "chain_id": self.chain_id,
            "name": self.name,
            "short_name": self.short_name,
            "native_symbol": self.native_symbol,
            "pool_manager": self.pool_manager,
            "explorer_name": self.explorer_name,
            "explorer_url": self.explorer_url,
            "is_local": self.is_local,
            "rpc_configured": self.rpc_configured,
            "source_verification": "etherscan" if not self.is_local else "local-artifacts",
            "notes": self.notes,
        }


def _local_pool_manager(settings: Settings) -> str | None:
    path = settings.deployments_file
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pm = data.get("pool_manager")
        return str(pm) if pm else None
    except (OSError, json.JSONDecodeError):
        return None


def load_chains(settings: Settings | None = None) -> dict[int, ChainConfig]:
    s = settings or get_settings()
    chains: dict[int, ChainConfig] = {
        1: ChainConfig(
            chain_id=1,
            name="Ethereum Mainnet",
            short_name="ethereum",
            native_symbol="ETH",
            pool_manager=MAINNET_POOL_MANAGER,
            pool_manager_deploy_block=MAINNET_POOL_MANAGER_DEPLOY_BLOCK,
            explorer_name="Etherscan",
            explorer_url="https://etherscan.io",
            rpc_url=s.mainnet_rpc_url.get_secret_value() if s.mainnet_rpc_url else None,
            notes=[] if s.mainnet_rpc_url else ["HOOKLENS_MAINNET_RPC_URL is not configured on this server."],
        ),
        11155111: ChainConfig(
            chain_id=11155111,
            name="Sepolia Testnet",
            short_name="sepolia",
            native_symbol="ETH",
            pool_manager=SEPOLIA_POOL_MANAGER,
            pool_manager_deploy_block=SEPOLIA_POOL_MANAGER_DEPLOY_BLOCK,
            explorer_name="Etherscan (Sepolia)",
            explorer_url="https://sepolia.etherscan.io",
            rpc_url=s.sepolia_rpc_url.get_secret_value() if s.sepolia_rpc_url else None,
            notes=[] if s.sepolia_rpc_url else ["HOOKLENS_SEPOLIA_RPC_URL is not configured on this server."],
        ),
    }
    if s.enable_local_chain:
        pm = _local_pool_manager(s)
        chains[31337] = ChainConfig(
            chain_id=31337,
            name="Local Anvil (HookLens fixtures)",
            short_name="anvil",
            native_symbol="ETH",
            pool_manager=pm,
            pool_manager_deploy_block=0,
            explorer_name=None,
            explorer_url=None,
            is_local=True,
            rpc_url=s.local_rpc_url,
            notes=[
                "Development chain with deliberately designed HookLens fixture hooks.",
                *([] if pm else ["Fixtures are not deployed: run scripts/dev-chain.sh."]),
            ],
        )
    return chains


def get_chain(chain_id: int, settings: Settings | None = None) -> ChainConfig:
    chains = load_chains(settings)
    if chain_id not in chains:
        raise AppError(
            "unsupported_chain",
            f"Chain {chain_id} is not supported. Supported chains: {sorted(chains)}.",
            status_code=422,
        )
    return chains[chain_id]
