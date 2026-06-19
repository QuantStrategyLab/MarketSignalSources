# Platform Signal Source Architecture

This repository is an artifact producer for strategy platforms. It owns market
signal normalization, deterministic derived indicators, and auditable artifact
publication. Strategy repositories consume the artifacts after validation; they
do not fetch vendors, keep data-source secrets, or compute cross-platform signal
provenance at runtime.

## Current Architecture

The MVP has four layers:

- `providers`: local input adapters such as CSV readers and OHLCV normalization.
- `derived`: deterministic signal transforms, currently BTC cycle indicators.
- `artifacts`: stable JSON/CSV schemas, manifest writing, checksums, indexes, and
  consumer contract validation.
- `cli`: small commands for building, exporting, listing contracts, and validating
  artifacts in CI or release jobs.

The platform-facing outputs are:

- `market_signal_quality_report.v1`: raw input quality proof, row counts, date
  range, duplicate/gap checks, and source file hash.
- `market_signal_bundle.v1`: runtime signal payload for platform injection.
- `market_signal_manifest.v1`: hash, provenance, freshness, and schema proof for
  one bundle.
- `market_signal_index.v1`: local manifest lookup for a canonical input and date.
- `research_export.v1`: offline CSV export for strategy research and backtests.
- `market_signal_consumer_contracts.v1`: required fields by downstream consumer.
- `market_signal_consumer_contract_manifest.v1`: manifest for the consumer
  registry itself.
- `market_signal_source_families.v1`: family-level catalog for canonical input,
  transform, freshness policy, produced fields, and compatible consumers.
- `market_signal_source_family_catalog_manifest.v1`: manifest for the source
  family catalog itself.
- `market_signal_platform_handoff.v1`: platform-facing manifest that pins the
  signal bundle manifest, source family catalog manifest, and consumer contract
  registry manifest as one release unit.
- `market_signal_platform_handoff_index.v1`: platform-facing index that lets
  consumers resolve the latest matching handoff by consumer, canonical input,
  freshness, and `as_of`.

For offline strategy research, `research_export.v1` can also pin a
`quality_report` file record. That keeps public or local context-source quality
proofs attached to the exact CSV that downstream backtests consume, even when the
artifact is not a runtime `market_signal_bundle.v1`.

## Design Pressure

IBIT is a US equity strategy, but its useful signal is crypto-native. That makes
it different from platform-local market data:

- The trading platform can own IBIT order execution without owning BTC signal
  derivation.
- BTC indicators such as AHR999 and Mayer Multiple need external raw data and
  deterministic transforms.
- Research and runtime need the same signal definitions, but not necessarily the
  same file shape.
- Platform CI needs to detect contract drift before a strategy deploys.

## Recommended Boundary

Keep this repository as a ports-and-artifacts layer rather than a shared runtime
service.

Producers write immutable artifacts with hashes. Consumers validate manifests and
contracts before injecting only the canonical input into strategy context:

```python
StrategyContext(
    market_data={"derived_indicators": bundle["derived_indicators"]},
)
```

The strategy platform remains responsible for account state, scheduling,
retrying failed orders, broker constraints, and order submission. The signal
source layer remains responsible for source data provenance, deterministic
indicator calculation, freshness, bundle `compatible_profiles`, and consumer
field coverage.

This is lower risk than adding a live signal service now because the existing
platforms can consume files in CI and runtime without new network dependencies,
credential paths, or service lifecycle ownership.

## Publication Flow

1. Build a source bundle from local or upstream-approved input data.
2. Capture provider metadata for the source artifact. The local CSV provider
   records provider name, dataset, provider timestamp, raw artifact SHA-256,
   license scope, and generator id; later network providers should return the
   same metadata shape while adding their own timeout, retry, and rate-limit
   behavior outside strategy repositories.
3. Write `quality_report.json`, `signal_bundle.json`, `manifest.json`, and the
   bundle-directory `index.json`. The artifact writer validates the written
   index chain by default before returning publishable paths.
4. Upsert the bundle manifest into a platform-facing publication index such as
   `signal_bundles/index.json`. This root index can reference multiple dated
   bundle directories and is the preferred platform lookup entry.
5. Validate `quality_report.json` directly, then validate its hash through
   `manifest.json`. Manifest validation also checks that the quality report's
   input CSV hash matches the bundle provenance raw artifact hash.
6. Validate the manifest or index with the target consumer identifier. This
   checks both `consumer_contract.compatible_profiles` membership and required
   indicator field coverage.
   `us_equity:ibit_smart_dca` currently requires only `ahr999`; deterministic
   BTC research helpers remain available through research consumers such as
   `research:ibit_btc_ahr999_helper_precomputed_variants` and
   `research:ibit_btc_ahr999_mayer_precomputed_variants`.
   The manifest and index also carry `compatible_profiles`, and validation
   rejects profile drift across index, manifest, and bundle.
7. Publish the source family catalog and the consumer contract registry with
   their manifests.
8. Write `market_signal_platform_handoff.v1` to pin the signal bundle manifest,
   source family catalog manifest, and consumer contract registry manifest as a
   single platform handoff unit.
9. Upsert the handoff manifest into `market_signal_platform_handoff_index.v1`
   when the platform needs a stable lookup entry across dated releases.
10. Strategy CI validates the handoff manifest or handoff index before allowing a strategy config
   to reference the artifact. Strategy repositories should also compare the
   source catalog's transform and `compatible_profiles`, plus the registry's
   consumer entries, with their own expected consumer identifiers and required
   fields, so a hash-valid catalog or registry that omits the target strategy
   still fails before release.
11. Runtime loads the validated bundle and injects only `derived_indicators`.

For research-only work, export `research_export.v1` CSVs and their manifests.
Research tooling should depend on those CSV manifests rather than on runtime
bundle files.
The BTC path uses `artifact_type=btc_cycle_research_csv`; the Nasdaq/S&P
external context path uses `artifact_type=us_equity_context_research_csv` and
`transform=us_equity.nasdaq_sp500.context.v1`. Both are hash-pinned offline
research inputs, not runtime platform injection contracts. The US equity context
export can also write `us_equity_context_availability_report.v1`, which gates
missing fields, date validity, percentile ranges, duplicate dates, and date gaps
before strategy research ranks any candidate.

## Multi-Market Extension

Future Hong Kong, US equity, and crypto signal families should add new derived
transforms and canonical inputs without changing existing consumers:

- `derived.crypto.*`: BTC, ETH, stablecoin, or cycle indicators.
- `derived.us_equity.*`: index breadth, valuation, volatility, or macro-derived
  indicators.
- `derived.hk_equity.*`: Hong Kong market breadth, FX-sensitive indicators, or
  local index regime signals.

Each new family should define:

- raw provider input assumptions
- quality report thresholds
- deterministic transform version
- output schema and canonical input
- minimum history and freshness window
- consumer contract entries
- validation tests for manifest, contract coverage, and sensitive-field rejection

The family catalog should be updated before runtime consumers are added. It is a
small compatibility map, not a provider registry or live service definition.
CI can read it through `python -m market_signal_sources.cli.list_signal_source_families`.
For platform handoff, publish it with `--output-dir` and validate the linked
manifest with `--validate-manifest` and `--require-all-known-families`. That validation also
checks each family's `compatible_profiles` against the consumer contract registry,
and rejects a family that does not produce the symbols or indicator fields its
declared consumers require.

The catalog also includes a top-level `domain_coverage` roadmap. It lists the
implemented source families and planned family names for `crypto`, `us_equity`,
and `hk_equity`, plus the canonical input categories each domain is expected to
publish. Planned entries in `domain_coverage` are intentionally not included in
`known_signal_source_families()` and do not satisfy
`--require-all-known-families`; they become runtime-compatible only after a real
family record, consumer contract, artifact writer, and validation test exist.

The first US equity family is `us_equity.nasdaq_sp500_context_daily`. It uses the
same `derived_indicators` envelope as BTC cycle signals, with the stable symbol
`US-EQUITY-CONTEXT` and fields such as `cape_percentile`, `vix_percentile`, and
`breadth_above_sma200_pct`. Its initial consumer is
`research:nasdaq_sp500_external_context_precomputed`, so it supports offline
Nasdaq/S&P smart-DCA research before any runtime profile depends on it.

There is also a narrower research family,
`us_equity.nasdaq_sp500_public_context_daily`, for CAPE/VIX-only experiments
when point-in-time breadth is not available. It uses the same
`artifact_type=us_equity_context_research_csv` and
`transform=us_equity.nasdaq_sp500.context.v1` manifest shape, but its compatible
consumer is `research:nasdaq_sp500_cape_vix_external_context_precomputed`.
That consumer intentionally does not satisfy the full-context consumer because
it lacks `breadth_above_sma200_pct`.

That family also carries source-profile metadata:

- `fred.vixcls` produces `vix_percentile` from FRED `VIXCLS`; research should pin
  the downloaded CSV, `as_of`, and percentile lookback, and should use at least a
  T+1 execution lag.
- `shiller.cape_monthly` produces `cape_percentile` from a preserved Shiller
  CAPE download snapshot. CAPE is monthly and revision-prone, so daily timing
  must be modeled as a low-frequency valuation input, not a same-day signal.
- `index_breadth.point_in_time_vendor` produces `breadth_above_sma200_pct`.
  Current-constituent backfills are not accepted because they introduce
  survivorship bias; use point-in-time constituents or an auditable historical
  breadth index.

The public-context exporter reads only local FRED and Shiller CSV snapshots. It
does not fetch network data or parse broker/platform state. It computes
expanding point-in-time percentiles per source first, then aligns CAPE to VIX
dates with backward as-of logic so monthly CAPE values are not repeatedly counted
when calculating their own percentile.
Its `us_equity_public_context_availability_report.v1` quality report audits the
two public source snapshots and the merged CAPE/VIX output. It deliberately does
not claim breadth availability or point-in-time constituent coverage. The report
also gates source freshness: by default FRED VIX must be within 10 days of
`as_of`, while the monthly Shiller CAPE snapshot must be within 120 days. This
keeps a stale low-frequency valuation file from being backward-filled into a
current signal without an explicit research override.

The US equity context availability report records missing provider timestamps,
provider timestamps after `as_of`, missing breadth universe snapshot ids, and
breadth universe dates after the observation date. Strict research exports can
turn missing point-in-time metadata from warnings into failures.

New transforms should reuse the generic `derived_indicators` bundle builder for
the artifact envelope, then keep market-specific calculations inside `derived.*`
modules. Do not add a new market-specific envelope builder unless the runtime
contract itself changes.

## Compatibility Rules

- Additive fields are allowed when old consumers can ignore them.
- Required field changes must update the consumer contract registry and be
  validated by strategy CI before rollout.
- Breaking schema changes should use a new schema version suffix.
- Artifacts must not contain tokens, cookies, signed URLs, account IDs, raw broker
  payloads, or vendor credentials.
- Research exports should not be used as runtime inputs unless a strategy
  explicitly validates that profile.

## Not Recommended

Do not put broker scheduling, account balance logic, or order retry policy in
this repository. Those decisions depend on platform runtime state and should stay
inside each strategy platform.

Do not make strategy repositories import provider adapters directly. That would
couple runtime strategies to data vendor details and make cross-platform signal
reuse harder to audit.
