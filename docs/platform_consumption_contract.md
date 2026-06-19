# Platform Consumption Contract

This document defines how strategy platforms consume artifacts from
MarketSignalSources without importing provider adapters or moving trading logic
into this repository.

## Current Architecture Understanding

MarketSignalSources is a ports-and-artifacts layer. It owns source normalization,
deterministic transforms, quality reports, manifests, family catalogs, consumer
contracts, and handoff manifests.

Strategy repositories and platforms remain responsible for strategy parameters,
account state, scheduling, retry policy, broker constraints, and order
submission. They consume only validated artifacts and inject only the agreed
canonical input into strategy context.

The current public boundary is:

- runtime artifacts: `market_signal_bundle.v1`, `market_signal_manifest.v1`,
  `market_signal_platform_handoff.v1`, and
  `market_signal_platform_handoff_index.v1`
- research artifacts: `research_export.v1` and
  `market_signal_research_handoff.v1`
- compatibility artifacts: `market_signal_source_families.v1` and
  `market_signal_consumer_contracts.v1`, each with a hash-pinned manifest

## Design Pressure Points

- Cross-market strategies can trade one market while depending on signals from
  another market, such as IBIT trading through a US equity platform while using
  BTC cycle indicators.
- Strategy platforms need a stable lookup and validation entry; they should not
  know provider-specific raw files, credentials, retry policies, or transform
  internals.
- Research needs richer fields than production runtime. Those richer fields must
  be contract-checked without becoming implicit production defaults.
- New Hong Kong equity, US equity, and crypto families should be additive. A new
  source family must not change existing consumer behavior unless its consumer
  contract changes deliberately.

## Recommended Low-Risk Boundary

Use artifact handoffs as the platform adapter boundary.

Runtime platforms should resolve a `market_signal_platform_handoff.v1` directly
or through `market_signal_platform_handoff_index.v1`, validate the linked bundle
manifest, catalog manifest, and contract registry manifest, then inject only the
bundle's `canonical_input` payload. For the current derived-indicator envelope
that means:

```python
StrategyContext(
    market_data={"derived_indicators": bundle["derived_indicators"]},
)
```

Research tooling should consume `research_export.v1` through
`market_signal_research_handoff.v1`. Research CSVs can be wide and can include
helper fields, but they are not runtime injection artifacts.

This keeps providers and transform implementation in MarketSignalSources while
letting each platform keep its own broker, account, and scheduler code.

## Runtime Flow

1. Build the signal bundle from a local or upstream-approved source artifact.
2. Write and validate the quality report, bundle, bundle manifest, and bundle
   index.
3. Publish the source family catalog and consumer contract registry with their
   manifests.
4. Build a `market_signal_platform_handoff.v1` that pins all three manifests.
5. Optionally upsert that handoff into a platform-facing handoff index.
6. Platform CI validates the handoff or index for its exact consumer id, such as
   `us_equity:ibit_smart_dca`.
7. Runtime loads the validated bundle and injects only the canonical input
   payload into strategy context.

Required platform checks:

- handoff manifest SHA-256 matches the index entry when using an index
- bundle manifest SHA-256 matches the handoff
- source family catalog manifest SHA-256 matches the handoff
- consumer contract registry manifest SHA-256 matches the handoff
- bundle `compatible_profiles` includes the runtime consumer
- catalog has a family matching the bundle transform and runtime consumer
- registry contains the runtime consumer and all required fields are present
- freshness policy is acceptable for the strategy's evaluation lag

The unified consumption audit command runs those checks through the same
validator path and returns a `market_signal_consumption_audit.v1` summary:

```bash
python -m market_signal_sources.cli.audit_signal_consumption \
  --platform-handoff-index ./data/output/platform_handoffs/index.json \
  --consumer us_equity:ibit_smart_dca \
  --as-of 2026-06-19 \
  --require-all-known-families \
  --require-all-known-consumers \
  --pretty
```

For runtime handoffs, the audit summary must show
`ready_for_runtime_injection=true`, `runtime_injection_allowed=true`, and the
expected `runtime_market_data_key`, such as `derived_indicators`.

## Research Flow

1. Export a `research_export.v1` CSV and manifest from the relevant source
   transform.
2. Attach a quality report when the source requires availability, freshness, or
   point-in-time proof.
3. Publish the source family catalog and consumer contract registry with their
   manifests.
4. Build a `market_signal_research_handoff.v1` for the target research consumer.
5. Strategy research CLI validates the handoff and records the audit summary in
   its scenario artifact.

Research consumers should be explicit. If a candidate set is compatible with
multiple `research:` consumers, the backtest command should select one
explicitly so a helper-field experiment does not silently validate against a
weaker AHR999-only contract.

The same audit CLI validates research handoffs, but its summary intentionally
keeps `ready_for_runtime_injection=false`:

```bash
python -m market_signal_sources.cli.audit_signal_consumption \
  --research-handoff-manifest ./data/output/research_handoff.json \
  --consumer research:ibit_btc_ahr999_mayer_precomputed \
  --pretty
```

Research promotion rule:

- A smart-DCA indicator variant may be retained for analysis if it is
  deterministic and contract-covered.
- It should not become a production runtime consumer unless it improves the
  fixed-DCA baseline or a production owner deliberately accepts the tradeoff.
- If fixed DCA remains better, keep the platform feature as a configurable DCA
  executor with fixed and smart modes, and keep smart variants as research
  options rather than defaults.

## Adding A New Source Family

Add new families incrementally. The minimum complete slice is:

- provider input assumptions and source profile metadata
- quality report or explicit reason why the source does not need one
- deterministic transform under `derived.<domain>`
- output schema and canonical input
- freshness policy and minimum history
- consumer contract entry for every intended runtime or research consumer
- source family catalog record with compatible profiles
- CLI or artifact writer that emits the relevant bundle or research export
- validation tests for manifest hash checks, field coverage, freshness or
  quality gates, and sensitive-field rejection

Do not add a new runtime consumer only because a planned family exists in
`domain_coverage`. Planned families become compatible only after a real family
record, contract entry, artifact writer, and validation test exist.

## Not Recommended

- Do not make strategy repositories import provider adapters directly.
- Do not put broker scheduling, retry policy, order sizing, or account balance
  logic in MarketSignalSources.
- Do not use research CSVs as runtime inputs unless the strategy explicitly
  validates that profile and accepts the operational risk.
- Do not add a live signal service until file-based handoffs become an actual
  operational bottleneck.

## Verification Strategy

For runtime publication:

```bash
python -m market_signal_sources.cli.list_signal_source_families \
  --validate-manifest ./data/output/source_catalog/signal_source_families.manifest.json \
  --require-all-known-families

python -m market_signal_sources.cli.list_consumer_contracts \
  --validate-manifest ./data/output/contracts/market_signal_consumers.manifest.json \
  --require-all-known-consumers

python -m market_signal_sources.cli.build_platform_handoff \
  --validate-index ./data/output/platform_handoffs/index.json \
  --consumer us_equity:ibit_smart_dca \
  --as-of 2026-06-19 \
  --require-all-known-families \
  --require-all-known-consumers
```

For research handoff:

```bash
python -m market_signal_sources.cli.validate_research_export \
  ./data/output/research/btc_cycle_indicators.manifest.json \
  --expected-artifact-type btc_cycle_research_csv \
  --expected-transform crypto.btc.ahr999.v1

python -m market_signal_sources.cli.build_research_handoff \
  --validate-manifest ./data/output/research_handoff.json \
  --consumer research:ibit_btc_ahr999_mayer_precomputed
```

Strategy repositories should run their own handoff validators too, because they
own the expected consumer id, expected transform, and candidate-set field needs.
The `audit_signal_consumption()` function is the low-level facade behind the CLI
for consumers that prefer a Python API over a subprocess.

## Compatibility And Risk

This contract is additive over the existing artifact layout. Existing platforms
can continue validating bundle manifests directly, but new platform integrations
should prefer the platform handoff or handoff index because it pins the bundle,
source catalog, and consumer registry as one release unit.

The main migration risk is a platform using only hash checks without consumer
contract checks. That can pass a valid but insufficient artifact. Platform CI
must validate the exact consumer id before rollout.
