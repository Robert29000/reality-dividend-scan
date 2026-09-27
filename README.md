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

- `creation` scans from the oracle creation block through the current chain head.
- `range` scans the inclusive `--from-block`/`--to-block` interval; its start must
  not precede the oracle creation block.

Both commands require `--provider` and
`--output-type`. Use `--output-dir PATH` to replace the default `output/`
directory.

## Provider configuration

Immutable chain, contract, and event values live in
`reality_dividends/constants.py`. Provider-specific behavior lives in
JSON files under the repository-level `configs/` directory.
`reality_dividends/config.py` maps each provider to its JSON path, loads those
files into `RpcProviderConfig` instances, and defines the shared
remaining-throughput threshold.

### Configure an existing provider

1. Open the provider file in `configs/`, such as `configs/alchemy.json`.
2. Set `rpc_url_env` to the name of the environment variable that contains the
   provider endpoint. Store the URL in `.env`; do not place credentials in the
   JSON file.
3. Set the block, batch, and log limits according to the provider's published
   restrictions.
4. Set the throughput rate, rate period, rolling-window length, and throttle
   pause according to the account's active plan.
5. Set the compute-unit costs for every RPC method used by the collector.
6. Run the offline test suite after changing provider settings.

### Configuration fields

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
| `batch_base_cu_cost` | Additional compute-unit cost charged once per batch, before member-call costs; defaults to `0` when omitted |

Use provider documentation and the account dashboard as the source of truth
for these values. In particular, `throughput` is the allowance for the period
specified by `throughput_rate_period_seconds`; it is not the total allowance
for the rolling window.

### Runtime behavior

The rolling-window allowance is calculated as:

```text
throughput / throughput_rate_period_seconds * rate_limit_window_seconds
```

For example, 300 CU per 1 second permits 3,000 CU during a 10-second window.
The collector retains a shared 10% reserve and waits before a request would
enter that reserve. Previously consumed units remain charged until they leave
the rolling window. `throttle_wait_seconds` is a minimum pause and is separate
from both the rate period and the rolling-window length.

The collector uses a 30-second HTTP timeout and retains Web3.py's default HTTP
provider retry configuration. Provider configuration does not override that
retry policy.

### Add a provider

1. Confirm that the provider offers an Arbitrum One HTTP endpoint. The
   collector validates chain ID `42161` before scanning.
2. Add a JSON configuration file under `configs/` containing every required
   field listed above. Set `rpc_url_env` to a unique environment-variable name.
3. Define a unique provider identifier constant in
   `reality_dividends/config.py`, for example `INFURA_PROVIDER = "infura"`, and
   add its JSON path to `RPC_PROVIDER_CONFIG_PATHS`. Lowercase CLI values are
   the project convention. The mapping automatically adds the provider to the
   CLI's `--provider` choices.
4. Add the environment variable to `.env.example` with an empty value. Users
   must supply the actual endpoint through their local environment.
5. Extend the RPC tests with the provider's limits, costs, batching behavior,
   and log-cap behavior. Extend the CLI provider matrix and its test
   environment with the new provider.
6. Run the complete offline test suite before using the provider.

## Test

Run the offline test suite with:

```sh
python -m unittest discover -v
```

## Structure

```text
abi/                    Reality Finance event ABI
configs/                Provider-specific RPC configuration
reality_dividends/      CLI, RPC collection, decoding, checkpoints, output
tests/                  Offline unit tests and event fixtures
collect_dividends.py    Repository-local entry point
```
