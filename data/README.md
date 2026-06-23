# Public Data

This directory contains the cleaned, public result tables used by README.md and RESULTS.md.

| File | Purpose |
| --- | --- |
| `public-model-summary.csv` | Model-level TTL summary with public notes. |
| `public-probe-matrix.csv` | Compact probe matrix used by the public report. |

The raw `results/` directory is local-only and ignored by Git. Review generated artifacts before copying anything into this directory. Public data must only reference generally available model names and must not include non-public details.

## Checklist

Before updating these files:

1. Confirm each model name is generally available and safe to publish.
2. Remove local account, configuration, and raw telemetry details.
3. Keep `public-model-summary.csv` and `public-probe-matrix.csv` aligned.
4. Regenerate `README.md` and `RESULTS.md` from the cleaned public data.
5. Run `git diff --check` before committing.
