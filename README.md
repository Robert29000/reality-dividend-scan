# Reality Finance dividend research

A Python CLI that collects Reality Finance oracle events on Arbitrum One,
keeps dividend actions, decodes them with Web3.py, and writes a CSV or Markdown
report.

## Install

Python 3.11 or newer is required.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
cp .env.example .env
```

Add an Alchemy or dRPC Arbitrum endpoint to `.env`, then load it with
`set -a; . ./.env; set +a`.

## Run

```sh
collect-dividends creation --provider alchemy --output-type csv
collect-dividends creation --provider drpc --output-type markdown
collect-dividends range --provider drpc --output-type csv --from-block 469276570 --to-block 469276575
```

The selected report and an automatic resumable scan checkpoint are written to
`output/`. Range scans must start at or after the oracle creation block.

Immutable chain, contract, and event values live in
`reality_dividends/constants.py`. Provider-specific behavior lives in
JSON files under the repository-level `configs/` directory.
`reality_dividends/config.py` maps each provider to its JSON path, loads those
files into `RpcProviderConfig` instances, and defines the shared
remaining-throughput threshold.

### Provider throughput and retries

Every provider JSON field is described below:

| Field | Meaning |
| --- | --- |
| `rpc_url_env` | Environment variable containing the provider's RPC endpoint URL |
| `block_window` | Maximum number of consecutive blocks covered by one `eth_getLogs` call |
| `batch_limit` | Maximum number of RPC calls sent in one JSON-RPC batch; the collector may reduce it to fit the throughput budget |
| `log_limit` | Provider response-log cap; responses at the cap are recursively split into smaller block ranges; `null` disables splitting |
| `throughput` | Compute units allowed during one throughput-rate period |
| `throughput_rate_period_seconds` | Number of seconds represented by `throughput`, such as `1` for CU/s or `60` for CU/min |
| `rate_limit_window_seconds` | Rolling window during which previously consumed compute units remain charged |
| `throttle_wait_seconds` | Minimum pause when the local throughput limiter throttles a request |
| `chain_id_cu_cost` | Compute-unit cost of `eth_chainId` |
| `block_number_cu_cost` | Compute-unit cost of `eth_blockNumber` |
| `get_logs_cu_cost` | Compute-unit cost of each `eth_getLogs` call |
| `batch_base_cu_cost` | Additional compute-unit cost charged once per batch, before member-call costs |

Rolling-window capacity is calculated as
`throughput / throughput_rate_period_seconds * rate_limit_window_seconds`.
For example, Alchemy's configured 300 CU per 1 second permits 3,000 CU over
its 10-second rolling window. `throttle_wait_seconds` is
independent of both the throughput-rate period and rate-limit window.

Before each request, the collector sums consumption still inside the rolling
window while preserving the shared 10% reserve. Request costs expire only when
their timestamps leave that window; there is no fixed reset or continuous
refill. The constructed HTTP provider retains Web3.py's default exception
retry configuration.

To add a provider, define its name in `constants.py`, add a JSON file under
`configs/`, add its explicit path to `RPC_PROVIDER_CONFIG_PATHS`, add its
endpoint variable to `.env.example`, and cover it in the RPC and CLI tests. The
shared `RpcCollector` applies its batching, rolling throughput, and retry
rules.

## Structure

```text
abi/                    Reality Finance event ABI
configs/                Provider-specific RPC configuration
reality_dividends/      CLI, RPC collection, decoding, checkpoints, output
tests/                  Offline unit tests and event fixtures
collect_dividends.py    Repository-local entry point
```
