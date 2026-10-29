# MarketSignalSources

Build and validate market signal artifacts from local source data.

English | [简体中文](README.zh-CN.md)

## Status

Experimental. This project is not financial advice and does not guarantee a
trading result. Downstream live trading can lose money; users are responsible
for their configuration and orders.

## What this is

A Python package for developers who need reproducible inputs for strategy
research and platform integration. It normalizes local data, computes derived
indicators, and writes JSON or CSV artifacts with hashes, provenance, freshness
metadata, and consumer contracts that define the fields each reader requires.

The package includes BTC cycle indicators, daily OHLCV (open, high, low, close, and volume) technical indicators,
semiconductor rotation inputs, and US equity research exports. Catalog and
contract validators check that a source family supplies its consumer's required
symbols and fields.

## What this is not

This package does not plan or submit orders, manage broker accounts, or change
platform settings. A valid signal artifact does not establish historical data
availability, confer a data license, or authorize trading. Broker adapters consume
validated artifacts rather than computing shared signals themselves.

## Quick start

Use Python 3.11 or newer. For a local checkout:

```bash
git clone https://github.com/QuantStrategyLab/MarketSignalSources.git
cd MarketSignalSources
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e . pytest
python -m pytest tests -q
```

Inspect the built-in catalog without fetching data or writing artifacts:

```bash
python -m market_signal_sources.cli.list_signal_source_families --pretty
python -m market_signal_sources.cli.list_consumer_contracts --pretty
```

For downstream installation, pin a reviewed immutable revision:

```text
market-signal-sources @ git+https://github.com/QuantStrategyLab/MarketSignalSources.git@<commit-sha>
```

For development against the current public branch:

```bash
python -m pip install "market-signal-sources @ git+https://github.com/QuantStrategyLab/MarketSignalSources.git@main"
uv add "market-signal-sources @ git+https://github.com/QuantStrategyLab/MarketSignalSources.git@main"
```

See the [CLI reference](docs/cli-reference.md) for local bundle construction,
research exports, artifact validation, and handoff examples. A handoff manifest
links a signal bundle, source catalog, and consumer registry by their hashes.

## Configuration

Core CLIs use explicit arguments and local files. The following options apply to
`build_btc_cycle_bundle`; other commands define their options in `--help`.

| Option | Required | Default | Purpose |
| --- | --- | --- | --- |
| `--input-csv` | Yes | none | Local OHLCV CSV, such as `./btc_daily.csv`. |
| `--output-dir` | Yes | none | Directory for the bundle, quality report, manifest, and local index. |
| `--as-of` | Yes | none | Source cutoff date in `YYYY-MM-DD` format. |
| `--generated-at` | Yes | none | Artifact generation timestamp with timezone. |
| `--symbol` | No | `BTC-USD` | Symbol represented by the input CSV. |
| `--provider` | No | `local_csv` | Source provider recorded in provenance. |
| `--provider-dataset` | No | `btc_usd_daily_ohlcv` | Source dataset recorded in provenance. |
| `--source-version` | No | `0.1.0` | Producer version recorded in provenance. |
| `--code-commit` | No | Zero-filled commit placeholder | Producer revision; set a real revision for published artifacts. |
| `--license-scope` | No | `internal_runtime` | Declared source usage scope; does not grant a license. |
| `--max-age-hours` | No | `36` | Bundle freshness limit in hours. |
| `--publication-index` | No | none | Optional shared local index to update with the new manifest. |

Local CSV input needs `date` and `close` columns by default. Missing `high` and
`low` columns use the close column; `volume` is optional. Column names can be
configured. Artifacts must not contain signed URLs, tokens, cookies, account IDs,
or raw broker data.

## Architecture

The `providers` package reads local inputs, `derived` computes indicators,
`artifacts` writes and validates contracts, and `cli` exposes command entrypoints.
See the [signal source architecture](docs/platform-signal-source-architecture.md)
and [platform consumption contract](docs/platform-consumption-contract.md).

The [CLI reference](docs/cli-reference.md) covers bundle and registry schemas,
source catalogs, quality checks, freshness policies, runtime input mapping, and
research-only exports. For the organization overview, see
[QuantStrategyLab](https://github.com/QuantStrategyLab/.github/blob/main/profile/README.md).

## Repository layout

```text
src/market_signal_sources/    providers, indicators, artifacts, and CLI commands
tests/                       unit and local artifact tests
docs/                        architecture, contracts, and CLI reference
scripts/                     publication and maintenance entrypoints
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). AI assistants and maintainers also follow [AGENTS.md](AGENTS.md). Documentation follows the
[QuantStrategyLab documentation style guide](https://github.com/QuantStrategyLab/.github/blob/main/docs/STYLE_GUIDE.md).

## Security

See [SECURITY.md](SECURITY.md) for private vulnerability reporting. Do not open a
public issue with credentials or a vulnerability report.

## License

[MIT](LICENSE).
