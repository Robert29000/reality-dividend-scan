"""Provider-specific RPC configuration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .constants import ALCHEMY_PROVIDER, DRPC_PROVIDER


class ThroughputMode(Enum):
    CU_PER_SECOND = 1.0
    CU_PER_MINUTE = 60.0

    @property
    def period_seconds(self) -> float:
        return float(self.value)


@dataclass(frozen=True)
class RpcProviderConfig:
    name: str
    rpc_url_env: str
    block_window: int
    batch_limit: int
    log_limit: int | None
    throughput: int
    throughput_mode: ThroughputMode
    remaining_threshold: float
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
        if not 0 <= self.remaining_threshold < 1:
            raise ValueError("remaining threshold must be between zero and one")
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


ALCHEMY_RPC_CONFIG = RpcProviderConfig(
    name=ALCHEMY_PROVIDER,
    rpc_url_env="ALCHEMY_RPC_URL",
    block_window=10,
    batch_limit=500,
    log_limit=10_000,
    throughput=500,
    throughput_mode=ThroughputMode.CU_PER_SECOND,
    remaining_threshold=0.10,
    throttle_wait_seconds=1.0,
    chain_id_cu_cost=5,
    block_number_cu_cost=10,
    get_logs_cu_cost=60,
    batch_base_cu_cost=0,
)

DRPC_RPC_CONFIG = RpcProviderConfig(
    name=DRPC_PROVIDER,
    rpc_url_env="DRPC_RPC_URL",
    block_window=100,
    batch_limit=3,
    log_limit=10_000,
    throughput=50_400,
    throughput_mode=ThroughputMode.CU_PER_MINUTE,
    remaining_threshold=0.10,
    throttle_wait_seconds=60.0,
    chain_id_cu_cost=10,
    block_number_cu_cost=20,
    get_logs_cu_cost=20,
    batch_base_cu_cost=0,
)

RPC_PROVIDER_CONFIGS = {
    config.name: config for config in (ALCHEMY_RPC_CONFIG, DRPC_RPC_CONFIG)
}
RPC_PROVIDERS = tuple(RPC_PROVIDER_CONFIGS)
