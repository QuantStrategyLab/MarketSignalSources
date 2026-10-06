# Contributing

Thanks for contributing to `MarketSignalSources`.

## Ground Rules

- Prefer small, low-risk pull requests.
- Keep refactors separate from behavior changes.
- Add or update tests when changing runtime behavior.
- Do not use deployment or scheduled workflows as a substitute for local verification.
- This repository only produces signal artifacts and contract validators; it does not submit orders, hold broker credentials, or mutate platform runtime settings. Changes that would add any of those belong in a different repository.
- Keep artifact schemas (`market_signal_bundle.v1`, `market_signal_quality_report.v1`, `market_signal_consumer_contracts.v1`, and related manifests) backward compatible, or call out the break explicitly and update all affected validators in the same pull request.

## Branching and Pull Requests

- Create a topic branch for each change.
- Open a pull request with a short summary and a concrete test plan.
- Wait for CI to pass before merging.

## Local Verification

Run the main verification commands before opening a pull request:

```bash
python -m pip install -e . pytest 'ruff==0.15.22' build
ruff check .
python -m pytest tests -q
```
