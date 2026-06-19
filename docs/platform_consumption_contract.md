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
- catalog has a family matching the bundle transform, runtime consumer,
  freshness policy, symbols, and emitted indicator fields
- registry contains the runtime consumer and all required fields are present
- freshness policy is acceptable for the strategy's evaluation lag

Platform handoff matching uses the catalog family's `runtime_consumers`, not the
broader `compatible_profiles` list. `research:*` consumers must use
`market_signal_research_handoff.v1`; they are contract-checkable for backtests
but are not runtime-injectable.

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

The same command can write that summary as a deployment audit artifact and later
validate the saved record:

```bash
python -m market_signal_sources.cli.audit_signal_consumption \
  --platform-handoff-index ./data/output/platform_handoffs/index.json \
  --consumer us_equity:ibit_smart_dca \
  --as-of 2026-06-19 \
  --require-all-known-families \
  --require-all-known-consumers \
  --output-json ./data/output/platform_handoffs/ibit_smart_dca.audit.json \
  --pretty

python -m market_signal_sources.cli.audit_signal_consumption \
  --validate-json ./data/output/platform_handoffs/ibit_smart_dca.audit.json \
  --pretty
```

After a runtime audit succeeds, platforms can also persist the minimal injection
plan and validate it separately:

```bash
python -m market_signal_sources.cli.audit_signal_consumption \
  --platform-handoff-index ./data/output/platform_handoffs/index.json \
  --consumer us_equity:ibit_smart_dca \
  --as-of 2026-06-19 \
  --require-all-known-families \
  --require-all-known-consumers \
  --output-runtime-plan-json ./data/output/platform_handoffs/ibit_smart_dca.runtime_plan.json \
  --pretty

python -m market_signal_sources.cli.audit_signal_consumption \
  --validate-runtime-plan-json ./data/output/platform_handoffs/ibit_smart_dca.runtime_plan.json \
  --pretty

python -m market_signal_sources.cli.audit_signal_consumption \
  --validate-runtime-plan-with-audit ./data/output/platform_handoffs/ibit_smart_dca.runtime_plan.json \
  --audit-json ./data/output/platform_handoffs/ibit_smart_dca.audit.json \
  --pretty
```

The runtime adapter should treat those saved artifacts as a small state machine:

| Stage | Required artifact | Required status |
| --- | --- | --- |
| Deploy gate | `market_signal_consumption_audit.v1` | `ready_for_runtime_injection=true` and `runtime_injection_allowed=true` |
| Startup gate | saved audit artifact | `validate-json` succeeds against the same file selected at deploy |
| Injection mapping | `market_signal_runtime_injection_plan.v1` | `injection_allowed=true` and `target_path=market_data.<market_data_key>` |
| Plan provenance | `market_signal_runtime_plan_audit_match.v1` | `matched=true` for the saved plan and saved audit |

Only after all four checks pass should the platform inject the payload into
`StrategyContext.market_data`. A valid runtime plan without a matching saved
audit is not enough to enable a strategy, because it proves shape but not
deployment identity.

For runtime handoffs, the audit summary must show
`ready_for_runtime_injection=true`, `runtime_injection_allowed=true`, and the
expected `runtime_market_data_key`, such as `derived_indicators`.
It also includes `matched_source_families`, which records the exact source
family or families that matched the runtime bundle and consumer.
When a platform only needs the injection mapping after validation, it can ask
the same command for the minimal runtime plan:

```bash
python -m market_signal_sources.cli.audit_signal_consumption \
  --platform-handoff-index ./data/output/platform_handoffs/index.json \
  --consumer us_equity:ibit_smart_dca \
  --as-of 2026-06-19 \
  --require-all-known-families \
  --require-all-known-consumers \
  --runtime-injection-plan \
  --pretty
```

## Platform Adapter Playbook

A consuming strategy platform should keep the adapter small and treat
`market_signal_consumption_audit.v1` as the handoff decision record. The platform
adapter should not import provider modules or recompute indicators.

Recommended runtime adapter responsibilities:

- Read a strategy config that names the expected `consumer`, handoff index or
  handoff manifest, optional `as_of`, and accepted freshness statuses.
- Run the consumption audit in CI before deploy and again at startup before the
  strategy is enabled.
- Require `ready_for_runtime_injection=true`,
  `runtime_injection_allowed=true`, `consumer_contract_verified=true`, and
  `source_catalog_verified=true`.
- Load only the signal bundle pinned by the audited handoff, then inject the
  payload under `runtime_market_data_key`.
- Persist the audit summary path or JSON next to the strategy deployment record
  so an order run can be traced back to exact bundle, source catalog, and
  consumer registry hashes.

Recommended configuration shape:

```json
{
  "strategy": "ibit_smart_dca",
  "signal_consumer": "us_equity:ibit_smart_dca",
  "signal_handoff_index": "./data/output/platform_handoffs/index.json",
  "signal_as_of": "2026-06-19",
  "accepted_freshness_statuses": ["fresh"]
}
```

The platform should convert a successful audit into this runtime injection:

```python
market_data[audit["runtime_market_data_key"]] = bundle[
    audit["runtime_payload_field"]
]
```

Consumers using the Python API can ask this package to derive the same minimal
plan after the audit succeeds:

```python
from market_signal_sources.artifacts.consumption import (
    audit_signal_consumption,
    runtime_signal_injection_plan,
    validate_runtime_signal_injection_plan_matches_audit,
)

audit = audit_signal_consumption(
    platform_handoff_index="./data/output/platform_handoffs/index.json",
    consumer="us_equity:ibit_smart_dca",
    as_of="2026-06-19",
    require_all_known_families=True,
    require_all_known_consumers=True,
)
plan = runtime_signal_injection_plan(audit)
market_data[plan["market_data_key"]] = bundle[plan["payload_field"]]
```

`runtime_signal_injection_plan()` rejects research handoff audits and any audit
summary that is not explicitly marked runtime-injectable.
For saved artifacts, `validate_runtime_signal_injection_plan_matches_audit()`
checks that the runtime plan still matches the exact audit identity, bundle,
manifest hashes, source families, consumer contracts, and payload path before
deployment consumes it.

Failure policy:

- If audit validation fails, the platform must not enable the strategy run.
- If no matching fresh handoff exists for the requested `as_of`, either block
  the run or fall back only to a previously approved deployment record; do not
  silently use an arbitrary latest file.
- If a runtime strategy asks for a `research:` consumer or a research handoff,
  keep `runtime_injection_allowed=false` and fail the runtime adapter.
- If a required field changes, update the consumer registry and strategy-side
  expected consumer id together; a hash-valid but contract-insufficient bundle
  is not deployable.

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
