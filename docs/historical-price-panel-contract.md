# Historical price-panel contract

`qsl.us-equity-historical-price-panel.v1` is a compact provenance record for a
price panel that has already been acquired for offline US-equity research. It
binds its raw-content and quality-report SHA-256 values to:

- an exact symbol set and observation window;
- a named market calendar and at least one trading-session execution lag;
- the price basis for signals and for portfolio returns; and
- whether the provider supplies true point-in-time snapshots or only historical
  closes consumed with a declared lag.

`unadjusted_close` and a zero-session reaction are rejected. This prevents a
research result from silently treating stock splits, distributions, or the same
day close as a fully specified execution assumption.

The `historical_close_with_declared_lag` status is useful but is not equivalent
to a vendor's as-published, point-in-time history. P3 evidence must disclose
that distinction. A source whose history is known to be revised is rejected by
this contract instead of being relabelled as historical proof.

The artifact does not download a vendor file, open raw prices, choose a
provider, or run a strategy. A future combo P1 assembler must bind this panel
to the matching point-in-time constituent snapshots, and must validate the
actual price quality reports separately.
