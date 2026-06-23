# Copilot CLI Cache TTL Measurement Harness

This repository measures how long a Copilot CLI prompt-cache entry remains reusable before a follow-up request has to create cache again. The harness sends a stable hidden prompt, waits for controlled delay intervals, then reads the Copilot CLI OpenTelemetry counters to classify each probe as a cache hit or miss.

This measures observed prompt-cache reuse TTL only. It does not measure session lifetime, model memory, token limits, or an official product SLA.

## Current Public Results

The current public, GA-only report is generated from the cleaned CSV files under `data/`:

- `data/public-model-summary.csv`
- `data/public-probe-matrix.csv`

Headline TTL windows:

| Model | Observed TTL window | Public interpretation |
| --- | ---: | --- |
| claude-haiku-4.5 | 225s-255s | about 4.0 min; mixed boundary at 255s |
| claude-opus-4.5 | 255s-277.5s | about 4.4 min |
| claude-opus-4.6 | 277.5s-300s | about 4.8 min |
| claude-opus-4.7 | 255s-277.5s | about 4.4 min; prefix changed mid-run |
| claude-opus-4.8 | 277.5s-300s | about 4.8 min |
| claude-sonnet-4.5 | 277.5s-300s | about 4.8 min |
| claude-sonnet-4.6 | 255s-277.5s | about 4.4 min |
| gemini-3.5-flash | roughly 1200s-1500s | about 24.8 min; noisy boundary |
| gpt-5.4 | <30s | no stable cache at first probe |
| gpt-5.4-mini | 918.75s-937.5s | about 15.5 min |
| gpt-5.5 | 1031.25s-1050s | about 17.3 min |
| gpt-5-mini | >=1800s | still cached at the 30-minute ceiling |
| gpt-5.3-codex | >=1800s | still cached at the 30-minute ceiling |
| auto | routed | no single TTL; routed model varies |

Full details are in [RESULTS.md](RESULTS.md), including the probe matrix, measurement method, caveats, and artifact list.

## Public Vs Local Artifacts

The public report is built from reviewed files in `data/`. The local `results/` directory is ignored by Git because it can contain raw telemetry and run-context details that should be reviewed before publication.

Use [PUBLISHING.md](PUBLISHING.md) before updating public results. The short rule is: publish from cleaned `data/` files, not directly from raw `results/` files.

## How It Works

1. Build a stable request prefix from the Copilot CLI system prompt, tool definitions, and a tiny fixed user prompt.
2. Send a hidden seed request to populate the prompt cache for that prefix.
3. Wait for a configured delay such as 30s, 60s, 120s, 300s, or a refined midpoint.
4. Send a hidden probe request with the same prefix.
5. `cache_read_input_tokens` indicates a cache hit; `cache_creation_input_tokens` indicates a miss or refresh.
6. Use an initial staircase plus binary-search refinement to bracket the hit/miss boundary.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `src/` | Runner, telemetry parsing, experiment logic, and report helpers. |
| `config.yaml` | Delay schedule, model list, runner settings, and output configuration for future local runs. |
| `PUBLISHING.md` | Checklist for moving local run output into public data. |
| `data/README.md` | Public-data contract for the cleaned CSV files. |
| `data/public-model-summary.csv` | Cleaned public model-level result summary. |
| `data/public-probe-matrix.csv` | Cleaned public probe matrix. |
| `results/` | Local generated run artifacts and raw telemetry outputs. |
| `assets/` | Public chart exports for cache survival and probe cost. |
| `RESULTS.md` | Public report prepared from the cleaned data. |

## Reproducibility Notes

- Run in a quiet CLI/account context. Other activity that shares the same stabilized prefix can make a cache entry appear warm before the run starts.
- Treat the TTL windows as account-, version-, and context-specific measurements, not product guarantees.
- Review generated context files before publishing. Public documentation and git history must only reference generally available model names and must not include non-public details.
- `config.yaml` is a run recipe, not proof that those models are part of the current public snapshot. The current published snapshot is the reviewed data under `data/`.
