# Historical combo P1 immutable-root contract

`qsl.us-equity-historical-combo-p1-root-manifest.v1` is the local, immutable
storage boundary for an already-validated
`qsl.us-equity-historical-combo-p1-input.v1` record.  It is deliberately
small: it seals bytes that have already been acquired; it does not decide
whether data are good enough to acquire or use.

## What one root contains

Each fresh private root has mode `0700`, each member has mode `0600`, and the
root is published through an atomic no-replace operation.  It contains:

- canonical `input.json`, the self-validating P1 metadata input;
- `price-panel.raw`, whose SHA-256 equals the input's declared raw panel
  digest;
- `quality-report.raw`, whose SHA-256 equals the input's declared quality
  report digest;
- one `universe-source/NNNN.raw` byte stream for each P1 rebalance decision,
  whose SHA-256 equals that decision's point-in-time universe source digest;
  and
- canonical `manifest.json`, which records every member's exact path, byte
  length and digest, plus the P1 input digest.

`verify_historical_combo_p1_root` checks the exact root layout, private file
modes, canonical metadata, every member digest, and the links back to the P1
price-panel and universe-source declarations.  It does not need network,
credentials, a provider, strategy code, or a broker.

## Intended use

The producer receives local bytes explicitly.  For a scriptable entry point,
use `seal-historical-combo-p1-root` with the input JSON, raw price panel,
quality report, and one `--universe-source DECISION_AT=PATH` per rebalance.
The output location must be new; retrying an already-created path intentionally
fails instead of overwriting research evidence.

This contract does **not** parse a vendor price format, repair missing data,
certify a quality report, choose a candidate, run P2/P3, publish to cloud, or
authorize paper/shadow/live activity.  A later real P3 adapter may consume a
verified root only after it separately validates the panel format, data-quality
criteria, point-in-time disclosure, cost model and frozen P1/P2 identity.
