"""Decode oracle events with Web3.py."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from web3 import Web3

from .constants import (
    DIVIDEND_ACTION_TYPE,
    ORACLE_ADDRESS,
    STATUS_NAMES,
    TOPIC_TO_EVENT,
)


class DecodeError(ValueError):
    """Raised when a log does not match the oracle ABI."""


CSV_FIELDS = (
    "event_type",
    "corporate_action_id",
    "block_number",
    "transaction_hash",
    "log_index",
    "rtoken_address",
    "status",
    "payload_rtoken",
    "payout_token",
    "dividend_per_share_raw",
    "dividend_per_share_scaled",
    "source_provider",
)

_ABI_PATH = Path(__file__).with_name("abi") / "reality_oracle_events.json"
ORACLE_ABI = json.loads(_ABI_PATH.read_text(encoding="utf-8"))
_WEB3 = Web3()
_CONTRACT = _WEB3.eth.contract(
    address=Web3.to_checksum_address(ORACLE_ADDRESS), abi=ORACLE_ABI
)
_EVENTS = {
    topic: getattr(_CONTRACT.events, name)()
    for topic, name in TOPIC_TO_EVENT.items()
}


def scale_1e18(value: int) -> str:
    whole, fraction = divmod(value, 10**18)
    if not fraction:
        return str(whole)
    return f"{whole}.{fraction:018d}".rstrip("0")


@dataclass(frozen=True)
class DecodedAction:
    event_type: str
    corporate_action_id: str
    token: str
    reference: str
    effective_at: int
    document_hash: str
    ticker: str
    action_type: int
    status: int
    payload: bytes
    block_number: int
    transaction_hash: str
    log_index: int


def decode_action_log(log: Mapping[str, Any]) -> DecodedAction:
    try:
        emitter = str(log["address"]).lower()
        if emitter != ORACLE_ADDRESS:
            raise DecodeError(
                f"log emitter is {emitter}; expected oracle {ORACLE_ADDRESS}"
            )
        topic0 = Web3.to_hex(log["topics"][0]).lower()
        event = _EVENTS[topic0]
        decoded = event.process_log(log)
        args = decoded["args"]
        return DecodedAction(
            event_type=str(decoded["event"]),
            corporate_action_id=Web3.to_hex(args["id"]).lower(),
            token=str(args["token"]).lower(),
            reference=Web3.to_hex(args["reference"]).lower(),
            effective_at=int(args["effectiveAt"]),
            document_hash=Web3.to_hex(args["documentHash"]).lower(),
            ticker=str(args["ticker"]),
            action_type=int(args["actionType"]),
            status=int(args["status"]),
            payload=bytes(args["payload"]),
            block_number=int(decoded["blockNumber"]),
            transaction_hash=Web3.to_hex(decoded["transactionHash"]).lower(),
            log_index=int(decoded["logIndex"]),
        )
    except DecodeError:
        raise
    except Exception as exc:
        raise DecodeError(f"invalid oracle event: {exc}") from exc


def dividend_record(log: Mapping[str, Any], provider: str) -> dict[str, Any] | None:
    action = decode_action_log(log)
    if action.action_type != DIVIDEND_ACTION_TYPE:
        return None
    if len(action.payload) != 96:
        raise DecodeError(
            "dividend payload must encode (address,address,uint256) in 96 bytes"
        )
    try:
        payload_rtoken, payout_token, dividend = _WEB3.codec.decode(
            ["address", "address", "uint256"], action.payload
        )
    except Exception as exc:
        raise DecodeError("invalid dividend payload") from exc

    return {
        "event_type": action.event_type,
        "corporate_action_id": action.corporate_action_id,
        "block_number": action.block_number,
        "transaction_hash": action.transaction_hash,
        "log_index": action.log_index,
        "rtoken_address": action.token,
        "status": STATUS_NAMES.get(action.status, f"Unknown({action.status})"),
        "payload_rtoken": str(payload_rtoken).lower(),
        "payout_token": str(payout_token).lower(),
        "dividend_per_share_raw": str(dividend),
        "dividend_per_share_scaled": scale_1e18(dividend),
        "source_provider": provider,
    }


def deduplicate_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate exact logs while retaining updates to the same action."""

    unique = {
        (str(record["transaction_hash"]).lower(), int(record["log_index"])): dict(record)
        for record in records
    }
    return sorted(
        unique.values(),
        key=lambda record: (
            int(record["block_number"]),
            int(record["log_index"]),
            str(record["transaction_hash"]),
        ),
    )
