# Public results

This report summarizes the public, GA-only measurements from the Copilot CLI cache-TTL harness.

## Executive summary

The latest run used a fixed prompt prefix and a delay staircase to measure whether the Copilot CLI would serve a prompt from cache or force a cache-creation event. The measured values below are account- and context-specific, so they should be treated as practical lower-bound estimates rather than universal constants.

## Measured cache TTL

| Model | Lower bound | Upper bound | Estimated TTL | Notes |
| --- | ---: | ---: | ---: | --- |
| claude-opus-4.5 | 255s | 277.5s | ~266s | Cache hit at 255s, miss at 277.5s and 300s; final confirmation hits at 255s. |
| claude-opus-4.6 | 277.5s | 300s | ~289s | Cache hit at 277.5s, miss at 300s. |
| claude-opus-4.7 | 255s | 277.5s | ~266s | Cache hit at 255s, miss at 277.5s and 300s. |

## Detailed probe results

The current public dataset contains the following probe outcomes for each model:

| Model | 30s | 60s | 120s | 210s | 255s | 277.5s | 300s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| claude-opus-4.5 | hit | hit | hit | hit | hit | miss | miss |
| claude-opus-4.6 | hit | hit | hit | hit | hit | hit | miss |
| claude-opus-4.7 | hit | hit | hit | hit | hit | miss | miss |

The public run also includes follow-up confirmation probes at 255s for claude-opus-4.5 and claude-opus-4.7, plus confirmation probes at 277.5s for claude-opus-4.6.

## How the measurement works

The harness answers a simple question: how long does a prompt-cache entry stay reusable before the service treats it as stale?

1. A stable prompt prefix and tool-definition payload are used so the cache key is comparable across probes.
2. A hidden seed request populates the cache entry for that prefix.
3. The harness waits for a chosen delay interval.
4. A second hidden probe request is sent with the same prefix and the OTel telemetry is inspected.
5. `cache_read_input_tokens` indicates a cache hit; `cache_creation_input_tokens` indicates a miss or a refresh.
6. A staircase sweep plus binary-search refinement is used to narrow the threshold window.

The measurement also records the responding model, CLI version, cache-read/cache-creation counters, and cost/latency signals for each probe so later runs can be compared with the same conditions.

## Context and caveats

- The measurements depend on the specific Copilot CLI version, account/session context, feature flights, and prompt prefix.
- Warm starts can bias results upward; the reported values are therefore conservative lower bounds with tight upper edges.
- The repo stores the raw artifacts in `results/` so future runs can be compared against this baseline.

## Files

- `results/results.csv`: raw probe-level measurements.
- `results/run_context.json`: configuration snapshot from the run.
- `assets/`: plots for cache-hit vs delay and cost vs delay.
