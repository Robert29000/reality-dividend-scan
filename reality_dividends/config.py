"""Provider-specific RPC configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .constants import ALCHEMY_PROVIDER, DRPC_PROVIDER

REMAINING_THROUGHPUT_THRESHOLD = 0.10
_PROJECT_DIRECTORY = Path(__file__).resolve().parent.parent
RPC_PROVIDER_CONFIG_PATHS = {
    ALCHEMY_PROVIDER: _PROJECT_DIRECTORY / "configs" / "alchemy.json",
    DRPC_PROVIDER: _PROJECT_DIRECTORY / "configs" / "drpc.json",
}


class ThroughputMode(Enum):
    CU_PER_SECOND = "cu_per_second"
    CU_PER_MINUTE = "cu_per_minute"

    @property
    def period_seconds(self) -> float:
        return 1.0 if self is ThroughputMode.CU_PER_SECOND else 60.0


@dataclass(frozen=True)
class RpcProviderConfig:
    rpc_url_env: str
    block_window: int
    batch_limit: int
    log_limit: int | None
    throughput: int
    throughput_mode: ThroughputMode
    throttle_wait_seconds: float
    chain_id_cu_cost: int
    block_number_cu_cost: int
    get_logs_cu_cost: int
    # Providers charge for the member calls; neither has an extra batch charge.
    batch_base_cu_cost: int = 0

    def __post_init__(self) -> None:
        if self.block_window <= 0:
            raise ValueError("block window must be positive")
        if self.batch_limit <= 0:
            raise ValueError("batch limit must be positive")
        if self.throughput <= 0:
            raise ValueError("throughput must be positive")
        if self.throttle_wait_seconds <= 0:
            raise ValueError("throttle wait must be positive")
        for cost in (
            self.chain_id_cu_cost,
            self.block_number_cu_cost,
            self.batch_base_cu_cost,
        ):
            if cost < 0:
                raise ValueError("CU costs must be non-negative")
        if self.get_logs_cu_cost <= 0:
            raise ValueError("eth_getLogs CU cost must be positive")

    def get_logs_batch_cu_cost(self, call_count: int) -> int:
        if call_count <= 0:
            raise ValueError("batch call count must be positive")
        return self.batch_base_cu_cost + call_count * self.get_logs_cu_cost


def load_provider_config(path: Path) -> RpcProviderConfig:
    values = json.loads(path.read_text(encoding="utf-8"))
    values["throughput_mode"] = ThroughputMode(values["throughput_mode"])
    return RpcProviderConfig(**values)


RPC_PROVIDER_CONFIGS = {
    provider: load_provider_config(path)
    for provider, path in RPC_PROVIDER_CONFIG_PATHS.items()
}
RPC_PROVIDERS = tuple(RPC_PROVIDER_CONFIGS)
