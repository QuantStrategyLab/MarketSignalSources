# Historical combo P1 input contract

`qsl.us-equity-historical-combo-p1-input.v1` is the smallest reusable P1
binding for an offline US-equity combination replay. It packages only metadata:

- the named strategy revision and frozen candidate-config digest;
- the exact replay window and non-zero, next-session execution-cost assumptions;
- every decision timestamp with its point-in-time universe snapshot; and
- one price-panel record whose symbols and dates cover those inputs.

Validation rejects a constituent snapshot that was unavailable at the stated
decision time, a price panel that omits a constituent, a panel that does not
cover the replay dates, unsorted decisions, zero transaction-cost assumptions,
or any digest mismatch. This removes the two easy ways for a historical combo
run to look better than it could have been: using today's constituents or
quietly ignoring missing/costly legs.

This is a research-only binding. It does not fetch or open market data, select
a candidate, run P2/P3, write an artifact, change a strategy, or authorize
paper, shadow, or live execution. A later P1 producer must separately store
the raw price and constituent members in an immutable root whose hashes agree
with this metadata; P2 and P3 remain separate stages.
