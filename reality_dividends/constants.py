"""Network, oracle, and RPC provider constants."""

from __future__ import annotations

from web3 import Web3

CHAIN_ID = 42161
ORACLE_ADDRESS = "0xd01f8aa971a3f4d13d52299bdd30225b1d7f40f1"
CREATION_BLOCK = 462_326_591

ALCHEMY_PROVIDER = "alchemy"
DRPC_PROVIDER = "drpc"
RPC_PROVIDERS = (ALCHEMY_PROVIDER, DRPC_PROVIDER)
RPC_URL_ENV = {
    ALCHEMY_PROVIDER: "ALCHEMY_RPC_URL",
    DRPC_PROVIDER: "DRPC_RPC_URL",
}

# Alchemy's free plan limits eth_getLogs to 10 blocks per request.
# dRPC has no documented block-range cap; 100 is a conservative window that
# reduces the risk of its free-tier two-second timeout.
RPC_BLOCK_WINDOWS = {
    ALCHEMY_PROVIDER: 10,
    DRPC_PROVIDER: 100,
}

# Maximum JSON-RPC calls per HTTP batch supported by each provider.
RPC_BATCH_LIMITS = {
    ALCHEMY_PROVIDER: 500,
    DRPC_PROVIDER: 3,
}

# Conservative pacing derived from documented free-tier throughput and
# per-request compute-unit costs.
RPC_REQUEST_INTERVALS = {
    ALCHEMY_PROVIDER: 0.2,
    DRPC_PROVIDER: 0.025,
}
RPC_LOG_LIMITS = {
    ALCHEMY_PROVIDER: None,
    DRPC_PROVIDER: 10_000,
}

EVENT_TYPES = (
    "bytes32",
    "address",
    "bytes32",
    "uint256",
    "bytes32",
    "string",
    "uint8",
    "uint8",
    "bytes",
)
ACTION_UPDATED_SIGNATURE = f"ActionUpdated({','.join(EVENT_TYPES)})"
ACTION_EXECUTED_SIGNATURE = f"ActionExecuted({','.join(EVENT_TYPES)})"


def event_topic(signature: str) -> str:
    return Web3.keccak(text=signature).to_0x_hex()


ACTION_UPDATED_TOPIC = event_topic(ACTION_UPDATED_SIGNATURE)
ACTION_EXECUTED_TOPIC = event_topic(ACTION_EXECUTED_SIGNATURE)
TOPIC_TO_EVENT = {
    ACTION_UPDATED_TOPIC: "ActionUpdated",
    ACTION_EXECUTED_TOPIC: "ActionExecuted",
}

STATUS_NAMES = {0: "Disclosed", 1: "Cancelled", 2: "Executed"}
DIVIDEND_ACTION_TYPE = 2
