"""JSON-RPC event collection utilities."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import requests
from web3 import Web3
from web3.exceptions import Web3Exception

from .constants import (
    ACTION_EXECUTED_TOPIC,
    ACTION_UPDATED_TOPIC,
    CHAIN_ID,
    ORACLE_ADDRESS,
    RPC_BATCH_LIMITS,
    RPC_BLOCK_WINDOWS,
    RPC_LOG_LIMITS,
    RPC_PROVIDERS,
    RPC_REQUEST_INTERVALS,
)
from .decode import DecodeError, dividend_record
from .state import ScanState, subtract_ranges


class CollectionError(RuntimeError):
    pass


class RateLimiter:
    def __init__(
        self,
        interval: float,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.interval = interval
        self.sleeper = sleeper
        self.clock = clock
        self.next_at: float | None = None

    def wait(self, request_count: int = 1) -> None:
        if request_count <= 0:
            raise ValueError("request count must be positive")
        now = self.clock()
        if self.next_at is not None and now < self.next_at:
            self.sleeper(self.next_at - now)
            now = self.clock()
        self.next_at = now + self.interval * request_count


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
        state: ScanState,
        web3: Web3 | Any | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if provider not in RPC_PROVIDERS:
            raise ValueError(f"unsupported RPC provider: {provider}")
        self.provider = provider
        self.state = state
        self.block_window = RPC_BLOCK_WINDOWS[provider]
        self.batch_limit = RPC_BATCH_LIMITS[provider]
        self.log_limit = RPC_LOG_LIMITS[provider]
        self.web3 = web3 or Web3(
            Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30})
        )
        self.limiter = RateLimiter(RPC_REQUEST_INTERVALS[provider], sleeper, clock)

    def validate_chain(self) -> None:
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

        self.limiter.wait(len(windows))
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
        self.state.add_records(records)
        self.state.complete(start, end)
        self.state.save()

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
        for (start, end), logs in zip(windows, self._get_logs_batch(windows)):
            self._process_window(start, end, logs)

    def _collect_window(self, start: int, end: int) -> None:
        self._collect_batch([(start, end)])

    def collect(self, start: int, end: int) -> None:
        for gap_start, gap_end in subtract_ranges(
            start, end, self.state.completed_ranges
        ):
            windows = block_windows(gap_start, gap_end, self.block_window)
            for batch in window_batches(windows, self.batch_limit):
                self._collect_batch(batch)
