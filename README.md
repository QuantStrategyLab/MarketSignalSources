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
  --pretty
```

Export a daily BTC cycle research CSV for offline smart-DCA candidate comparison:

```bash
python -m market_signal_sources.cli.export_btc_cycle_research_csv \
  --input-csv ./btc_daily.csv \
  --output-csv ./data/output/research/btc_cycle_indicators.csv \
  --as-of 2026-06-19 \
  --pretty
```

The exported CSV includes `date`, `close`, `ahr999`, `ahr999_sma`, `mayer_multiple`,
`sma200_gap`, `drawdown_252d`, and related deterministic price-derived fields. It
is intended for offline research tooling, not direct platform injection.

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
