from __future__ import annotations

import json
import unittest
from pathlib import Path

from hexbytes import HexBytes

from reality_dividends.constants import (
    ACTION_EXECUTED_SIGNATURE,
    ACTION_EXECUTED_TOPIC,
    ACTION_UPDATED_SIGNATURE,
    ACTION_UPDATED_TOPIC,
    event_topic,
)
from reality_dividends.decode import (
    DecodeError,
    decode_action_log,
    deduplicate_records,
    dividend_record,
    scale_1e18,
)
from tests.fixtures import EXECUTED_LOG, UPDATED_LOG, copy_log


class TopicAndAbiTests(unittest.TestCase):
    def test_generated_topics(self):
        self.assertEqual(event_topic(ACTION_UPDATED_SIGNATURE), ACTION_UPDATED_TOPIC)
        self.assertEqual(event_topic(ACTION_EXECUTED_SIGNATURE), ACTION_EXECUTED_TOPIC)

    def test_corrected_minimal_abi_layout(self):
        path = (
            Path(__file__).parents[1]
            / "reality_dividends"
            / "abi"
            / "reality_oracle_events.json"
        )
        abi = json.loads(path.read_text())
        self.assertEqual([event["name"] for event in abi], ["ActionUpdated", "ActionExecuted"])
        for event in abi:
            self.assertEqual(
                [item["type"] for item in event["inputs"]],
                ["bytes32", "address", "bytes32", "uint256", "bytes32", "string", "uint8", "uint8", "bytes"],
            )
            self.assertEqual(
                [item["name"] for item in event["inputs"] if item["indexed"]],
                ["id", "token"],
            )
            ticker = next(item for item in event["inputs"] if item["name"] == "ticker")
            self.assertFalse(ticker["indexed"])


class DecodeTests(unittest.TestCase):
    def test_real_updated_fixture_and_dividend_payload(self):
        action = decode_action_log(UPDATED_LOG)
        self.assertEqual(action.event_type, "ActionUpdated")
        self.assertEqual(action.ticker, "Distribution")
        self.assertEqual(action.action_type, 2)
        self.assertEqual(action.status, 0)
        record = dividend_record(UPDATED_LOG, "alchemy")
        assert record is not None
        self.assertEqual(record["status"], "Disclosed")
        self.assertEqual(record["rtoken_address"], "0xd5bc195a8f19cf12f59c05fd3266cf39a3306706")
        self.assertEqual(record["payload_rtoken"], record["rtoken_address"])
        self.assertEqual(record["payout_token"], "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9")
        self.assertEqual(record["dividend_per_share_raw"], str(int("6092fb1de1b2000", 16)))
        self.assertEqual(
            record["dividend_per_share_scaled"],
            scale_1e18(int("6092fb1de1b2000", 16)),
        )

    def test_real_executed_fixture(self):
        record = dividend_record(EXECUTED_LOG, "alchemy")
        assert record is not None
        self.assertEqual(record["event_type"], "ActionExecuted")
        self.assertEqual(record["status"], "Executed")
        self.assertEqual(record["source_provider"], "alchemy")
        self.assertEqual(record["log_index"], 6)

    def test_filters_non_dividend_locally(self):
        log = copy_log(UPDATED_LOG)
        raw = bytearray(log["data"])
        raw[4 * 32 : 5 * 32] = (1).to_bytes(32, "big")
        log["data"] = HexBytes(raw)
        self.assertIsNone(dividend_record(log, "alchemy"))

    def test_rejects_wrong_oracle_emitter(self):
        log = copy_log(UPDATED_LOG)
        log["address"] = "0x" + "11" * 20
        with self.assertRaisesRegex(DecodeError, "expected oracle"):
            decode_action_log(log)

    def test_wraps_web3_decode_errors(self):
        log = copy_log(UPDATED_LOG)
        log["data"] = HexBytes("0x")
        with self.assertRaisesRegex(DecodeError, "invalid oracle event"):
            decode_action_log(log)

    def test_status_cancelled(self):
        log = copy_log(UPDATED_LOG)
        raw = bytearray(log["data"])
        raw[5 * 32 : 6 * 32] = (1).to_bytes(32, "big")
        log["data"] = HexBytes(raw)
        self.assertEqual(dividend_record(log, "alchemy")["status"], "Cancelled")

    def test_scaling_is_exact(self):
        self.assertEqual(scale_1e18(1), "0.000000000000000001")
        self.assertEqual(scale_1e18(10**18), "1")
        self.assertEqual(scale_1e18(1_250_000_000_000_000_000), "1.25")

    def test_only_exact_logs_are_deduplicated(self):
        first = dividend_record(UPDATED_LOG, "alchemy")
        assert first is not None
        repeated_action = dict(first)
        repeated_action["transaction_hash"] = "0x" + "11" * 32
        repeated_action["log_index"] = 7
        rows = deduplicate_records([first, dict(first), repeated_action])
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["corporate_action_id"] for row in rows}, {first["corporate_action_id"]})


if __name__ == "__main__":
    unittest.main()
