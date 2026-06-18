# MarketSignalSources

Artifact-first market signal source builders for QuantStrategyLab strategy platforms.

This repository starts with a narrow MVP:

- read local BTC daily OHLCV CSV
- compute BTC cycle indicators used by `us_equity:ibit_smart_dca`
- publish a `market_signal_bundle.v1` JSON bundle with manifest and index files

It intentionally does not fetch vendor data, load secrets, call broker APIs, or make trading decisions.

## BTC Cycle Bundle

Example:

```bash
python -m market_signal_sources.cli.build_btc_cycle_bundle \
  --input-csv ./btc_daily.csv \
  --output-dir ./data/output/crypto/btc/derived_indicators/2026-06-19 \
  --as-of 2026-06-19 \
  --symbol BTC-USD \
  --provider local_csv \
  --provider-dataset btc_usd_daily_ohlcv \
  --source-version 0.1.0 \
  --code-commit 0000000000000000000000000000000000000000 \
  --generated-at 2026-06-19T00:15:00Z \
  --pretty
```

Outputs:

- `signal_bundle.json`
- `manifest.json`
- `index.json`

Validate the generated artifacts before publishing or handing them to a platform:

```bash
python -m market_signal_sources.cli.validate_signal_bundle \
  ./data/output/crypto/btc/derived_indicators/2026-06-19/manifest.json \
  --pretty
```

Or resolve through the local index:

```bash
python -m market_signal_sources.cli.validate_signal_bundle \
  --index ./data/output/crypto/btc/derived_indicators/2026-06-19/index.json \
  --as-of 2026-06-20 \
  --consumer research:ibit_btc_ahr999_mayer_precomputed_variants \
  --pretty
```

The optional `--consumer` check validates downstream field coverage before
publishing. For `research:ibit_btc_ahr999_mayer_precomputed_variants`, the
`BTC-USD` payload must include `ahr999`, `ahr999_sma`, and `mayer_multiple`.

Consumer field requirements are also exposed as a JSON registry so platform and
strategy repositories can run drift checks without importing this package at
runtime:

```bash
python -m market_signal_sources.cli.list_consumer_contracts \
  --consumer us_equity:ibit_smart_dca \
  --pretty
```

The registry uses `market_signal_consumer_contracts.v1` and lists each
consumer's canonical input plus required indicator fields by symbol.
To publish the registry as an artifact with SHA-256 metadata:

```bash
python -m market_signal_sources.cli.list_consumer_contracts \
  --output-json ./data/output/market_signal_consumers.json \
  --pretty
```

The printed summary includes `sha256`, `size_bytes`, `schema_version`,
`canonical_input`, and `consumer_count`.

Export a daily BTC cycle research CSV for offline smart-DCA candidate comparison:

```bash
python -m market_signal_sources.cli.export_btc_cycle_research_csv \
  --input-csv ./btc_daily.csv \
  --output-csv ./data/output/research/btc_cycle_indicators.csv \
  --manifest-path ./data/output/research/btc_cycle_indicators.manifest.json \
  --as-of 2026-06-19 \
  --pretty
```

The exported CSV includes `date`, `close`, `ahr999`, `ahr999_sma`, `mayer_multiple`,
`sma200_gap`, `drawdown_252d`, and related deterministic price-derived fields. It
is intended for offline research tooling, not direct platform injection. The
research manifest records input/output SHA-256 hashes, row count, columns,
date range, transform, source version, and `min_history`.

Validate the research CSV manifest before handing it to strategy research tooling:

```bash
python -m market_signal_sources.cli.validate_research_export \
  ./data/output/research/btc_cycle_indicators.manifest.json \
  --expected-artifact-type btc_cycle_research_csv \
  --expected-transform crypto.btc.ahr999.v1 \
  --pretty
```

Downstream platforms should validate the manifest and bundle hashes, freshness, provenance, and canonical input before injecting:

```python
StrategyContext(
    market_data={"derived_indicators": bundle["derived_indicators"]},
    ...
)
```

## Boundary

Allowed here:

- local CSV or artifact inputs
- OHLCV normalization
- deterministic derived indicators
- artifact writing, hashes, freshness, provenance

Not allowed here:

- broker account state
- order planning or submission
- platform enable/disable switches
- signed URLs, tokens, cookies, account IDs, or raw broker payloads in artifacts
