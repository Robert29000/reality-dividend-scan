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

RPC behavior is configured in `reality_dividends/constants.py`:

- `RPC_URL_ENV` maps provider names to endpoint environment variables.
- `RPC_BLOCK_WINDOWS` controls the inclusive block range in each `eth_getLogs`
  call.
- `RPC_BATCH_LIMITS` controls how many calls are grouped into one HTTP request.
- `RPC_REQUEST_INTERVALS` controls request pacing.
- `RPC_LOG_LIMITS` triggers recursive range splitting when a response reaches a
  provider's result cap.

To add a provider, define its name, add it to `RPC_PROVIDERS`, supply an entry in
each RPC mapping above, add its endpoint variable to `.env.example`, and add the
provider to the RPC and CLI test cases. The shared `RpcCollector` will then use
the configured block window, batch size, pacing, and log limit automatically.

## Structure

```text
reality_dividends/      CLI, ABI, RPC collection, decoding, checkpoints, output
tests/                  Offline unit tests and event fixtures
collect_dividends.py    Repository-local entry point
```
