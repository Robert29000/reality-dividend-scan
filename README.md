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
`reality_dividends/config.py`; each `RpcProviderConfig` defines the endpoint
environment variable, block and batch limits, log cap, CU costs, throughput
period, reserved-capacity threshold, and throttle wait.

To add a provider, define its name in `constants.py`, create an
`RpcProviderConfig` in `config.py`, include it in `RPC_PROVIDER_CONFIGS`, add its
endpoint variable to `.env.example`, and cover it in the RPC and CLI tests. The
shared `RpcCollector` applies the provider's batching and throughput rules.

## Structure

```text
reality_dividends/      CLI, ABI, RPC collection, decoding, checkpoints, output
tests/                  Offline unit tests and event fixtures
collect_dividends.py    Repository-local entry point
```
