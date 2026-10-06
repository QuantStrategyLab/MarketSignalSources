# Security Policy

Thanks for helping keep `MarketSignalSources` safe.

This repository builds and publishes market signal artifacts consumed by QuantStrategyLab strategy and platform repositories. It does not hold broker credentials or submit orders, but published artifacts and manifests can still affect what downstream platforms inject into live strategies. Please do **not** open a public issue for vulnerabilities involving provider credentials, artifact integrity (e.g. a way to forge or tamper with a signal bundle's hash/provenance so it passes validation), or secret material.

## Reporting a Vulnerability

- Contact the maintainer directly at GitHub: `@Pigbibi`.
- Include the repository name, affected commit or branch, environment details, and exact reproduction steps.

## Secret and Credential Exposure

If you suspect provider API keys, tokens, or other credentials were exposed in this repository (for example in a committed artifact, fixture, or log):

1. Rotate the exposed secrets immediately.
2. Pause any scheduled publication job that depends on the exposed credential.
3. Share only the minimum evidence needed to reproduce the issue.

## Scope Notes

Security fixes should stay minimal and focused. Please avoid bundling unrelated refactors with a security report or patch.
