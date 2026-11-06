#!/usr/bin/env bash
# Start a local Anvil chain and deploy the HookLens fixture hooks.
#
#   scripts/dev-chain.sh            # start anvil on :8545 (foreground) and deploy
#   ANVIL_PORT=8546 scripts/dev-chain.sh
#   scripts/dev-chain.sh --deploy-only   # deploy to an already-running anvil
#
# The deployer key is Anvil's well-known PUBLIC development key; it controls nothing of value
# and is only accepted by the deploy script on chain 31337. Never put a real key here.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${ANVIL_PORT:-8545}"
RPC="http://127.0.0.1:${PORT}"
export PATH="$PATH:$HOME/.foundry/bin"
DEV_KEY="0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"

command -v anvil >/dev/null || { echo "anvil not found: install Foundry (https://getfoundry.sh)" >&2; exit 1; }

ANVIL_PID=""
if [[ "${1:-}" != "--deploy-only" ]]; then
  anvil --port "$PORT" --code-size-limit 50000 --silent &
  ANVIL_PID=$!
  trap '[[ -n "$ANVIL_PID" ]] && kill "$ANVIL_PID" 2>/dev/null || true' EXIT INT TERM
fi

for _ in $(seq 1 50); do
  cast chain-id --rpc-url "$RPC" >/dev/null 2>&1 && break
  sleep 0.2
done
[[ "$(cast chain-id --rpc-url "$RPC")" == "31337" ]] || { echo "chain at $RPC is not 31337" >&2; exit 1; }

DEPLOYER="$(cast wallet address --private-key "$DEV_KEY")"
# Make sure the deployer has gas regardless of how this anvil was started.
cast rpc --rpc-url "$RPC" anvil_setBalance "$DEPLOYER" 0x3635C9ADC5DEA00000 >/dev/null

cd "$ROOT/contracts"
HL_DEPLOYER_KEY="$DEV_KEY" forge script script/DeployFixtures.s.sol:DeployFixtures \
  --rpc-url "$RPC" --broadcast --start-fresh --slow -q
echo "Fixtures deployed; addresses in contracts/deployments/31337.json"

if [[ -n "$ANVIL_PID" ]]; then
  echo "Anvil running on $RPC (Ctrl+C to stop)"
  wait "$ANVIL_PID"
fi
