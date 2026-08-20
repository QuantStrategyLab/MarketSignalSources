# Point-in-time universe snapshot contract

`qsl.us-equity-point-in-time-universe.v1` is the smallest reusable input
artifact needed before historical constituent strategies can claim a
no-look-ahead replay. It binds:

- the named universe and effective date;
- the timestamp when the source was available to a decision process;
- the raw source-content SHA-256 and declared licence scope; and
- the exact, sorted constituent symbols.

The decision-time validator rejects a snapshot whose `available_at` is later
than the proposed decision. This is intentionally stronger than simply storing
an “as of” date: a constituent list published after a rebalance cannot be used
to make that earlier rebalance look better.

The artifact does not fetch iShares, a market-data vendor, or any website. It
also does not prove adjusted prices, corporate actions, execution costs, or a
strategy result. The first consumer is the future historical P1 reconstruction
for the Russell/ETF combo research lane; it must pair every universe artifact
with separately verified price and calendar inputs before P2/P3 may run.
