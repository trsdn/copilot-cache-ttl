# Publishing Public Results

This repo separates local run artifacts from reviewed public data.

## Source Of Truth

| Path | Role |
| --- | --- |
| `results/` | Local generated artifacts from a run. Ignored by Git. |
| `data/public-model-summary.csv` | Reviewed model-level public result summary. |
| `data/public-probe-matrix.csv` | Reviewed public probe matrix. |
| `README.md` | Short public overview generated from `data/`. |
| `RESULTS.md` | Detailed public report generated from `data/`. |

`config.yaml` describes how to run the harness. It is not the source of truth for the current public result snapshot.

## Publication Checklist

Before copying run output into `data/` or updating public Markdown:

1. Confirm every model name in the proposed public files is generally available and safe to publish.
2. Remove account-specific, local configuration, raw telemetry, and run-context details.
3. Keep `results/` local; do not commit raw run artifacts.
4. Update both `data/public-model-summary.csv` and `data/public-probe-matrix.csv` together.
5. Verify every model in `data/public-model-summary.csv` also appears in `data/public-probe-matrix.csv`.
6. Update `README.md` and `RESULTS.md` from the cleaned `data/` files.
7. Run `git diff --check` before committing.

## Scope Of Measurement

This harness measures observed prompt-cache reuse TTL through Copilot CLI telemetry. It does not measure session lifetime, model memory, token limits, or an official product SLA.