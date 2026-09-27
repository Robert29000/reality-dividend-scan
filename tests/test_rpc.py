from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reality_dividends.config import (
    ALCHEMY_PROVIDER,
    DRPC_PROVIDER,
    REMAINING_THROUGHPUT_THRESHOLD,
    RPC_PROVIDER_CONFIGS,
    RPC_PROVIDER_CONFIG_PATHS,
)
from reality_dividends.constants import (
    ACTION_EXECUTED_TOPIC,
    ACTION_UPDATED_TOPIC,
    CHAIN_ID,
    ORACLE_ADDRESS,
)
from reality_dividends.rpc import (
    CollectionError,
    RateLimiter,
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
    def make_collector(
        self, directory, provider, handler, fake_time=None, start=1, end=100
    ):
        clock = fake_time or FakeTime()
        eth = FakeEth(handler)
        collector = RpcCollector(
            provider,
            "unused",
            web3=FakeWeb3(eth),
            sleeper=clock.sleep,
            clock=clock.clock,
        )
        state = collector.initialize_state(
            Path(directory) / "state.json", start, end
        )
        return collector, eth, state, clock

    def test_provider_settings_are_selected_by_name(self):
        alchemy_config = RPC_PROVIDER_CONFIGS[ALCHEMY_PROVIDER]
        drpc_config = RPC_PROVIDER_CONFIGS[DRPC_PROVIDER]
        self.assertEqual(
            RPC_PROVIDER_CONFIG_PATHS[ALCHEMY_PROVIDER].name, "alchemy.json"
        )
        self.assertEqual(RPC_PROVIDER_CONFIG_PATHS[DRPC_PROVIDER].name, "drpc.json")
        self.assertTrue(
            all(
                path.parent.name == "configs"
                for path in RPC_PROVIDER_CONFIG_PATHS.values()
            )
        )
        self.assertEqual(REMAINING_THROUGHPUT_THRESHOLD, 0.10)
        self.assertFalse(hasattr(alchemy_config, "remaining_threshold"))
        self.assertFalse(hasattr(drpc_config, "remaining_threshold"))
        self.assertEqual(alchemy_config.block_window, 10)
        self.assertEqual(alchemy_config.batch_limit, 500)
        self.assertEqual(alchemy_config.get_logs_cu_cost, 60)
        self.assertEqual(alchemy_config.throughput, 300)
        self.assertEqual(alchemy_config.throughput_rate_period_seconds, 1.0)
        self.assertEqual(alchemy_config.rate_limit_window_seconds, 10.0)
        self.assertEqual(alchemy_config.throttle_wait_seconds, 1.0)
        self.assertEqual(alchemy_config.get_logs_batch_cu_cost(3), 180)

        self.assertEqual(drpc_config.block_window, 100)
        self.assertEqual(drpc_config.batch_limit, 3)
        self.assertEqual(drpc_config.log_limit, 10_000)
        self.assertEqual(drpc_config.get_logs_cu_cost, 20)
        self.assertEqual(drpc_config.throughput, 50_400)
        self.assertEqual(drpc_config.throughput_rate_period_seconds, 60.0)
        self.assertEqual(drpc_config.rate_limit_window_seconds, 60.0)
        self.assertEqual(drpc_config.throttle_wait_seconds, 1.0)
        self.assertEqual(drpc_config.get_logs_batch_cu_cost(3), 60)

    def test_http_provider_uses_web3_default_retries(self):
        collector = RpcCollector(ALCHEMY_PROVIDER, "https://example.invalid")
        self.assertIsNotNone(
            collector.web3.provider.exception_retry_configuration
        )

    def test_each_provider_uses_its_window_and_combined_topics(self):
        cases = ((ALCHEMY_PROVIDER, 81), (DRPC_PROVIDER, 2_001))
        for provider, end in cases:
            with (
                self.subTest(provider=provider),
                tempfile.TemporaryDirectory() as directory,
            ):
                collector, eth, state, fake_time = self.make_collector(
                    directory, provider, lambda params: [], end=end
                )
                collector.validate_chain()
                self.assertEqual(collector.head_block(), 100)
                collector.collect(1, end)

                expected = block_windows(1, end, collector.block_window)
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
                            expected, collector.batch_limit
                        )
                    ],
                )
                self.assertEqual(fake_time.sleeps, [])
                expected_consumed = 555 if provider == ALCHEMY_PROVIDER else 450
                self.assertEqual(
                    collector.limiter.consumed_units, expected_consumed
                )

    def test_throttle_wait_is_independent_from_throughput_period(self):
        for period in (1.0, 60.0):
            with self.subTest(period=period):
                fake_time = FakeTime()
                limiter = RateLimiter(
                    throughput=100,
                    throughput_rate_period_seconds=period,
                    rate_limit_window_seconds=period,
                    wait_seconds=0.25,
                    sleeper=fake_time.sleep,
                    clock=fake_time.clock,
                )
                limiter.wait(40)
                limiter.wait(40)
                self.assertEqual(limiter.consumed_units, 80)
                self.assertEqual(limiter.remaining_units, 20)

                fake_time.now = period - 0.1
                limiter.wait(10)
                self.assertEqual(fake_time.sleeps, [0.25])
                self.assertEqual(limiter.consumed_units, 10)
                self.assertEqual(limiter.remaining_units, 90)

    def test_consumption_expires_only_after_leaving_rolling_window(self):
        fake_time = FakeTime()
        limiter = RateLimiter(
            throughput=100,
            throughput_rate_period_seconds=1,
            rate_limit_window_seconds=10,
            wait_seconds=0.25,
            sleeper=fake_time.sleep,
            clock=fake_time.clock,
        )
        limiter.wait(800)
        self.assertEqual(limiter.consumed_units, 800)

        fake_time.sleep(2)
        self.assertEqual(limiter.consumed_units, 800)
        self.assertEqual(limiter.remaining_units, 200)

        fake_time.sleep(8)
        self.assertEqual(limiter.consumed_units, 0)
        self.assertEqual(limiter.remaining_units, 1_000)

    def test_rolling_window_does_not_refill_after_initial_drpc_burst(self):
        fake_time = FakeTime()
        limiter = RateLimiter(
            throughput=50_400,
            throughput_rate_period_seconds=60,
            rate_limit_window_seconds=60,
            wait_seconds=1,
            sleeper=fake_time.sleep,
            clock=fake_time.clock,
        )
        limiter.wait(45_300)

        fake_time.now = 7
        limiter.wait(840)

        self.assertEqual(fake_time.sleeps, [53])
        self.assertEqual(limiter.consumed_units, 840)

    def test_throughput_limiter_rejects_request_larger_than_usable_budget(self):
        limiter = RateLimiter(
            throughput=100,
            throughput_rate_period_seconds=1,
            rate_limit_window_seconds=1,
            wait_seconds=1,
        )
        with self.assertRaisesRegex(ValueError, "exceeds usable throughput 89"):
            limiter.wait(90)

    def test_block_windows_cover_inclusive_range_without_gaps(self):
        for start, end, size in ((5, 5, 10), (5, 14, 10), (5, 15, 10)):
            with self.subTest(start=start, end=end, size=size):
                windows = block_windows(start, end, size)
                covered = [
                    block
                    for window_start, window_end in windows
                    for block in range(window_start, window_end + 1)
                ]
                self.assertEqual(covered, list(range(start, end + 1)))

    def test_window_batches_rejects_invalid_size(self):
        with self.assertRaisesRegex(ValueError, "batch size must be positive"):
            window_batches([(1, 2)], 0)

    def test_state_is_checkpointed_once_per_batch(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "reality_dividends.state.atomic_json"
        ) as atomic_json:
            collector, _eth, _state, _time = self.make_collector(
                directory, DRPC_PROVIDER, lambda params: [], end=401
            )
            collector.collect(1, 401)

            self.assertEqual(collector.web3.batch_sizes, [3, 2])
            self.assertEqual(atomic_json.call_count, 2)

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
            path = Path(directory) / "state.json"
            state = ScanState(path, ALCHEMY_PROVIDER, 1, 20)
            state.complete(1, 10)
            state.save()
            eth = FakeEth(lambda params: [])
            collector = RpcCollector(
                ALCHEMY_PROVIDER,
                "unused",
                web3=FakeWeb3(eth),
                sleeper=lambda _: None,
            )
            state = collector.initialize_state(path, 1, 20)
            collector.collect(1, 20)
            self.assertEqual(
                (eth.calls[0]["fromBlock"], eth.calls[0]["toBlock"]), (11, 20)
            )
            self.assertEqual(state.completed_ranges, [[1, 20]])

    def test_collection_requires_state_but_rpc_lookups_do_not(self):
        eth = FakeEth(lambda params: [], block_number=321)
        collector = RpcCollector(
            ALCHEMY_PROVIDER,
            "unused",
            web3=FakeWeb3(eth),
        )
        collector.validate_chain()
        self.assertEqual(collector.head_block(), 321)
        with self.assertRaisesRegex(CollectionError, "state is not configured"):
            collector.collect(1, 1)


if __name__ == "__main__":
    unittest.main()
