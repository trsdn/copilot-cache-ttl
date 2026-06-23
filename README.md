# Copilot CLI cache TTL measurement harness

This repository measures how long a Copilot CLI prompt-cache entry remains reusable before the service treats it as stale. Instead of relying on undocumented product promises, it uses the Copilot CLI's own OpenTelemetry export to observe whether a follow-up request is served from cache or forces a new cache-creation event.

## Public results

The full public report is here: [RESULTS.md](RESULTS.md).

## Current measured results

The current public run contains probe points for three GA Claude Opus variants. The raw outcomes are:

| Model | 30s | 60s | 120s | 210s | 255s | 277.5s | 300s | Public TTL window |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| claude-opus-4.5 | hit | hit | hit | hit | hit | miss | miss | 255s-277.5s |
| claude-opus-4.6 | hit | hit | hit | hit | hit | hit | miss | 277.5s-300s |
| claude-opus-4.7 | hit | hit | hit | hit | hit | miss | miss | 255s-277.5s |

The public headline is therefore:

- claude-opus-4.5: about 4.25-4.63 minutes
- claude-opus-4.6: about 4.63-5.00 minutes
- claude-opus-4.7: about 4.25-4.63 minutes

These values are best interpreted as lower-bound estimates for a specific account/session context. They are not universal guarantees and should be re-run if the prompt prefix, CLI version, model, or feature flighting changes.

## How the approach works

The measurement is intentionally simple and reproducible:

1. Pick a stable prompt prefix and tool-definition payload so the cache key is comparable across probes.
2. Send a hidden seed request to populate the cache entry for that prefix.
3. Wait for a chosen delay interval such as 30s, 60s, 120s, 300s, or longer.
4. Send a second hidden probe request with the same prefix and inspect the OTel span attributes.
5. If the request shows `cache_read_input_tokens`, it hit the cache. If it shows `cache_creation_input_tokens`, the cache entry was not reused.
6. Use a staircase plus binary-search refinement to narrow the TTL window until the hit/miss boundary is clear.

The harness also records the serving model, CLI version, cost signals, latency, and the exact prefix hash so later runs can be compared under similar conditions.

## What is in this repo

- `src/` contains the runner, parser, and reporting code.
- `results/` contains generated CSV/JSON artifacts and plots.
- `assets/` contains the exported charts.
- `config.yaml` contains the model, delay, and repetition settings used for the runs.

## Reproducibility notes

- The harness runs hidden, non-interactive Copilot CLI requests.
- It records the prompt prefix hash and the OTel cache counters for each probe.
- The output is stored under `results/` and can be re-processed with the scripts in `src/`.

## Public policy

Public documentation and git history should only mention generally available (GA) model names. Internal, preview, or otherwise non-public model names must not be published here.
