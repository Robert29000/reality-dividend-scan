from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reality_dividends.constants import (
    ACTION_EXECUTED_TOPIC,
    ACTION_UPDATED_TOPIC,
    ALCHEMY_PROVIDER,
    CHAIN_ID,
    DRPC_PROVIDER,
    ORACLE_ADDRESS,
    RPC_BATCH_LIMITS,
    RPC_BLOCK_WINDOWS,
    RPC_LOG_LIMITS,
    RPC_REQUEST_INTERVALS,
)
from reality_dividends.rpc import (
    CollectionError,
    RpcCollector,
    block_windows,
    window_batches,
)
from reality_dividends.state import ScanState
from tests.fixtures import UPDATED_LOG


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeEth:
    def __init__(self, handler, chain_id=CHAIN_ID, block_number=100):
        self.handler = handler
        self.chain_id = chain_id
        self.block_number = block_number
        self.calls = []

    def get_logs(self, params):
        return dict(params)


class FakeBatch:
    def __init__(self, web3):
        self.web3 = web3
        self.requests = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    def add(self, request):
        self.requests.append(request)

    def execute(self):
        self.web3.batch_sizes.append(len(self.requests))
        responses = []
        for request in self.requests:
            self.web3.eth.calls.append(request)
            responses.append(self.web3.eth.handler(request))
        return responses


class FakeWeb3:
    def __init__(self, eth):
        self.eth = eth
        self.batch_sizes = []

    def batch_requests(self):
        return FakeBatch(self)


class RpcTests(unittest.TestCase):
    def make_state(self, directory, provider, start=1, end=100):
        return ScanState(Path(directory) / "state.json", provider, start, end)

    def make_collector(self, directory, provider, handler, fake_time=None):
        clock = fake_time or FakeTime()
        eth = FakeEth(handler)
        state = self.make_state(directory, provider)
        collector = RpcCollector(
            provider,
            "unused",
            state,
            web3=FakeWeb3(eth),
            sleeper=clock.sleep,
            clock=clock.clock,
        )
        return collector, eth, state, clock

    def test_provider_settings_are_selected_by_name(self):
        self.assertEqual(RPC_BLOCK_WINDOWS[ALCHEMY_PROVIDER], 10)
        self.assertEqual(RPC_BATCH_LIMITS[ALCHEMY_PROVIDER], 1_000)
        self.assertEqual(RPC_REQUEST_INTERVALS[ALCHEMY_PROVIDER], 0.2)
        self.assertEqual(RPC_BLOCK_WINDOWS[DRPC_PROVIDER], 100)
        self.assertEqual(RPC_BATCH_LIMITS[DRPC_PROVIDER], 3)
        self.assertEqual(RPC_REQUEST_INTERVALS[DRPC_PROVIDER], 0.025)
        self.assertEqual(RPC_LOG_LIMITS[DRPC_PROVIDER], 10_000)

    def test_each_provider_uses_its_window_and_combined_topics(self):
        cases = ((ALCHEMY_PROVIDER, 21), (DRPC_PROVIDER, 2_001))
        for provider, end in cases:
            with (
                self.subTest(provider=provider),
                tempfile.TemporaryDirectory() as directory,
            ):
                collector, eth, state, fake_time = self.make_collector(
                    directory, provider, lambda params: []
                )
                collector.validate_chain()
                self.assertEqual(collector.head_block(), 100)
                collector.collect(1, end)

                expected = block_windows(1, end, RPC_BLOCK_WINDOWS[provider])
                self.assertEqual(
                    [(call["fromBlock"], call["toBlock"]) for call in eth.calls],
                    expected,
                )
                self.assertEqual(
                    eth.calls[0]["topics"],
                    [[ACTION_UPDATED_TOPIC, ACTION_EXECUTED_TOPIC]],
                )
                self.assertEqual(eth.calls[0]["address"].lower(), ORACLE_ADDRESS)
                self.assertEqual(state.completed_ranges, [[1, end]])
                self.assertEqual(
                    collector.web3.batch_sizes,
                    [
                        len(batch)
                        for batch in window_batches(
                            expected, RPC_BATCH_LIMITS[provider]
                        )
                    ],
                )
                expected_waited_requests = max(
                    0, len(expected) - collector.web3.batch_sizes[-1]
                )
                self.assertGreaterEqual(
                    sum(fake_time.sleeps),
                    expected_waited_requests * RPC_REQUEST_INTERVALS[provider],
                )

    def test_window_batches_rejects_invalid_size(self):
        with self.assertRaisesRegex(ValueError, "batch size must be positive"):
            window_batches([(1, 2)], 0)

    def test_selected_provider_is_written_to_decoded_records(self):
        with tempfile.TemporaryDirectory() as directory:
            collector, _eth, state, _time = self.make_collector(
                directory, DRPC_PROVIDER, lambda params: [UPDATED_LOG]
            )
            collector.collect(1, 1)
            self.assertEqual(state.records[0]["source_provider"], DRPC_PROVIDER)

    def test_drpc_splits_at_log_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            def handler(params):
                if (params["fromBlock"], params["toBlock"]) == (1, 4):
                    return [{}] * 10_000
                return []

            collector, eth, state, _time = self.make_collector(
                directory, DRPC_PROVIDER, handler
            )
            collector._collect_window(1, 4)
            self.assertEqual(
                [(call["fromBlock"], call["toBlock"]) for call in eth.calls],
                [(1, 4), (1, 2), (3, 4)],
            )
            self.assertEqual(collector.web3.batch_sizes, [1, 2])
            self.assertEqual(state.completed_ranges, [[1, 4]])

    def test_drpc_single_block_log_cap_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            collector, _eth, _state, _time = self.make_collector(
                directory, DRPC_PROVIDER, lambda params: [{}] * 10_000
            )
            with self.assertRaisesRegex(CollectionError, "10,000-log limit"):
                collector._collect_window(9, 9)

    def test_resume_only_requests_uncovered_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self.make_state(directory, ALCHEMY_PROVIDER, 1, 20)
            state.complete(1, 10)
            state.save()
            eth = FakeEth(lambda params: [])
            collector = RpcCollector(
                ALCHEMY_PROVIDER,
                "unused",
                state,
                web3=FakeWeb3(eth),
                sleeper=lambda _: None,
            )
            collector.collect(1, 20)
            self.assertEqual(
                (eth.calls[0]["fromBlock"], eth.calls[0]["toBlock"]), (11, 20)
            )
            self.assertEqual(state.completed_ranges, [[1, 20]])


if __name__ == "__main__":
    unittest.main()
