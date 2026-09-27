"""Network, oracle, and event constants."""

from __future__ import annotations

from web3 import Web3

CHAIN_ID = 42161
ORACLE_ADDRESS = "0xd01f8aa971a3f4d13d52299bdd30225b1d7f40f1"
CREATION_BLOCK = 462_326_591

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
