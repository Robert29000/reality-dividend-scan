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

    def wait(self) -> None:
        now = self.clock()
        if self.next_at is not None and now < self.next_at:
            self.sleeper(self.next_at - now)
            now = self.clock()
        self.next_at = now + self.interval


def block_windows(start: int, end: int, size: int) -> list[tuple[int, int]]:
    if size <= 0:
        raise ValueError("window size must be positive")
    return [
        (block, min(end, block + size - 1))
        for block in range(start, end + 1, size)
    ]


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

    def _get_logs(self, start: int, end: int) -> list[Any]:
        self.limiter.wait()
        try:
            return list(
                self.web3.eth.get_logs(
                    {
                        "fromBlock": start,
                        "toBlock": end,
                        "address": Web3.to_checksum_address(ORACLE_ADDRESS),
                        "topics": [[ACTION_UPDATED_TOPIC, ACTION_EXECUTED_TOPIC]],
                    }
                )
            )
        except (
            Web3Exception,
            requests.RequestException,
            TypeError,
            ValueError,
        ) as exc:
            raise CollectionError(
                f"{self.provider} log request failed for {start}..{end}: {exc}"
            ) from exc

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

    def _collect_window(self, start: int, end: int) -> None:
        logs = self._get_logs(start, end)
        if self.log_limit is not None and len(logs) >= self.log_limit:
            if start == end:
                raise CollectionError(
                    f"{self.provider} reached its {self.log_limit:,}-log limit "
                    f"for block {start}"
                )
            midpoint = (start + end) // 2
            self._collect_window(start, midpoint)
            self._collect_window(midpoint + 1, end)
            return
        self._store(start, end, logs)

    def collect(self, start: int, end: int) -> None:
        for gap_start, gap_end in subtract_ranges(
            start, end, self.state.completed_ranges
        ):
            for window_start, window_end in block_windows(
                gap_start, gap_end, self.block_window
            ):
                self._collect_window(window_start, window_end)
