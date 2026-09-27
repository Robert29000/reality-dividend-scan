"""JSON-RPC event collection utilities."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests
from web3 import Web3
from web3.exceptions import Web3Exception

from .config import (
    REMAINING_THROUGHPUT_THRESHOLD,
    RPC_PROVIDER_CONFIGS,
    RpcProviderConfig,
    ThroughputMode,
)
from .constants import (
    ACTION_EXECUTED_TOPIC,
    ACTION_UPDATED_TOPIC,
    CHAIN_ID,
    ORACLE_ADDRESS,
)
from .decode import DecodeError, dividend_record
from .state import ScanState, subtract_ranges


class CollectionError(RuntimeError):
    pass


class RateLimiter:
    def __init__(
        self,
        throughput: int,
        mode: ThroughputMode,
        wait_seconds: float,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if throughput <= 0:
            raise ValueError("throughput must be positive")
        if not 0 <= REMAINING_THROUGHPUT_THRESHOLD < 1:
            raise ValueError("remaining threshold must be between zero and one")
        if wait_seconds <= 0:
            raise ValueError("wait seconds must be positive")

        self.throughput = throughput
        self.period_seconds = mode.period_seconds
        self.wait_seconds = wait_seconds
        self.sleeper = sleeper
        self.clock = clock
        self.window_started = self.clock()
        self._consumed_units = 0

    @property
    def reserve_units(self) -> float:
        return self.throughput * REMAINING_THROUGHPUT_THRESHOLD

    @property
    def max_request_units(self) -> int:
        return max(0, math.ceil(self.throughput - self.reserve_units) - 1)

    def _refresh(self, now: float) -> None:
        if now - self.window_started >= self.period_seconds:
            self.window_started = now
            self._consumed_units = 0

    @property
    def consumed_units(self) -> int:
        self._refresh(self.clock())
        return self._consumed_units

    @property
    def remaining_units(self) -> int:
        return self.throughput - self.consumed_units

    def wait(self, cost: int) -> None:
        if cost < 0:
            raise ValueError("request cost must be non-negative")
        if cost == 0:
            return
        if cost > self.max_request_units:
            raise ValueError(
                f"request cost {cost} exceeds usable throughput "
                f"{self.max_request_units}"
            )

        while True:
            now = self.clock()
            self._refresh(now)
            remaining_after_request = self.remaining_units - cost
            if remaining_after_request > self.reserve_units:
                self._consumed_units += cost
                return

            until_reset = max(
                0.0, self.period_seconds - (now - self.window_started)
            )
            self.sleeper(min(self.wait_seconds, until_reset))


def block_windows(start: int, end: int, size: int) -> list[tuple[int, int]]:
    if size <= 0:
        raise ValueError("window size must be positive")
    return [
        (block, min(end, block + size - 1))
        for block in range(start, end + 1, size)
    ]


def window_batches(
    windows: list[tuple[int, int]], size: int
) -> list[list[tuple[int, int]]]:
    if size <= 0:
        raise ValueError("batch size must be positive")
    return [windows[index : index + size] for index in range(0, len(windows), size)]


class RpcCollector:
    def __init__(
        self,
        provider: str,
        rpc_url: str,
        web3: Web3 | Any | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if provider not in RPC_PROVIDER_CONFIGS:
            raise ValueError(f"unsupported RPC provider: {provider}")
        self.provider = provider
        self.config: RpcProviderConfig = RPC_PROVIDER_CONFIGS[provider]
        self._state: ScanState | None = None
        self.block_window = self.config.block_window
        self.log_limit = self.config.log_limit
        self.web3 = web3 or Web3(
            Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30})
        )
        self.limiter = RateLimiter(
            throughput=self.config.throughput,
            mode=self.config.throughput_mode,
            wait_seconds=self.config.throttle_wait_seconds,
            sleeper=sleeper,
            clock=clock,
        )
        max_batch_calls = (
            self.limiter.max_request_units - self.config.batch_base_cu_cost
        ) // self.config.get_logs_cu_cost
        if max_batch_calls <= 0:
            raise ValueError(
                f"{provider} throughput cannot accommodate one eth_getLogs call"
            )
        self.batch_limit = min(self.config.batch_limit, max_batch_calls)

    def initialize_state(
        self, path: Path, requested_from: int, requested_to: int
    ) -> ScanState:
        self._state = ScanState(
            path, self.provider, requested_from, requested_to
        )
        return self._state

    def _require_state(self) -> ScanState:
        if self._state is None:
            raise CollectionError("scan state is not configured")
        return self._state

    def validate_chain(self) -> None:
        self.limiter.wait(self.config.chain_id_cu_cost)
        try:
            chain_id = int(self.web3.eth.chain_id)
        except (
            Web3Exception,
            requests.RequestException,
            TypeError,
            ValueError,
        ) as exc:
            raise CollectionError(f"{self.provider} chain lookup failed: {exc}") from exc
        if chain_id != CHAIN_ID:
            raise CollectionError(
                f"{self.provider} chain ID is {chain_id}; expected {CHAIN_ID}"
            )

    def head_block(self) -> int:
        self.limiter.wait(self.config.block_number_cu_cost)
        try:
            return int(self.web3.eth.block_number)
        except (
            Web3Exception,
            requests.RequestException,
            TypeError,
            ValueError,
        ) as exc:
            raise CollectionError(f"{self.provider} head lookup failed: {exc}") from exc

    @staticmethod
    def _log_filter(start: int, end: int) -> dict[str, Any]:
        return {
            "fromBlock": start,
            "toBlock": end,
            "address": Web3.to_checksum_address(ORACLE_ADDRESS),
            "topics": [[ACTION_UPDATED_TOPIC, ACTION_EXECUTED_TOPIC]],
        }

    def _get_logs_batch(
        self, windows: list[tuple[int, int]]
    ) -> list[list[Any]]:
        if not windows:
            return []
        if len(windows) > self.batch_limit:
            raise ValueError(
                f"batch contains {len(windows)} requests; limit is {self.batch_limit}"
            )

        self.limiter.wait(self.config.get_logs_batch_cu_cost(len(windows)))
        try:
            with self.web3.batch_requests() as batch:
                for start, end in windows:
                    batch.add(self.web3.eth.get_logs(self._log_filter(start, end)))
                responses = batch.execute()
        except (
            Web3Exception,
            requests.RequestException,
            TypeError,
            ValueError,
        ) as exc:
            first_start, first_end = windows[0]
            last_start, last_end = windows[-1]
            raise CollectionError(
                f"{self.provider} log batch failed for "
                f"{first_start}..{first_end} through {last_start}..{last_end}: {exc}"
            ) from exc

        if len(responses) != len(windows):
            raise CollectionError(
                f"{self.provider} returned {len(responses)} responses for "
                f"{len(windows)} batched log requests"
            )
        return [list(logs) for logs in responses]

    def _store(self, start: int, end: int, logs: list[Any]) -> None:
        state = self._require_state()
        records = []
        for log in logs:
            try:
                record = dividend_record(log, self.provider)
            except DecodeError as exc:
                raise CollectionError(
                    f"cannot decode {self.provider} log at {start}..{end}: {exc}"
                ) from exc
            if record is not None:
                records.append(record)
        state.add_records(records)
        state.complete(start, end)

    def _process_window(self, start: int, end: int, logs: list[Any]) -> None:
        if self.log_limit is not None and len(logs) >= self.log_limit:
            if start == end:
                raise CollectionError(
                    f"{self.provider} reached its {self.log_limit:,}-log limit "
                    f"for block {start}"
                )
            midpoint = (start + end) // 2
            split_windows = [(start, midpoint), (midpoint + 1, end)]
            for batch in window_batches(split_windows, self.batch_limit):
                self._collect_batch(batch)
            return
        self._store(start, end, logs)

    def _collect_batch(self, windows: list[tuple[int, int]]) -> None:
        state = self._require_state()
        try:
            for (start, end), logs in zip(windows, self._get_logs_batch(windows)):
                self._process_window(start, end, logs)
        finally:
            state.save()

    def _collect_window(self, start: int, end: int) -> None:
        self._collect_batch([(start, end)])

    def collect(self, start: int, end: int) -> None:
        state = self._require_state()
        for gap_start, gap_end in subtract_ranges(
            start, end, state.completed_ranges
        ):
            windows = block_windows(gap_start, gap_end, self.block_window)
            for batch in window_batches(windows, self.batch_limit):
                self._collect_batch(batch)
        state.save()
