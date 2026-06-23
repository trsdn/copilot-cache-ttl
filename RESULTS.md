# Public results

This report summarizes the public, GA-only measurements from the Copilot CLI cache-TTL harness.

## Summary

The latest run used a fixed prompt prefix and a delay staircase to measure whether the Copilot CLI would serve a prompt from cache or force a cache creation event. The measured values below are account- and context-specific, so they should be treated as practical lower-bound estimates rather than universal constants.

## Measured cache TTL

| Model | Lower bound | Upper bound | Estimated TTL | Notes |
| --- | ---: | ---: | ---: | --- |
| claude-opus-4.5 | 255s | 277.5s | ~266s | Cache hit at 255s, miss at 300s; final confirmation hit at 255s. |
| claude-opus-4.6 | 277.5s | 300s | ~289s | Cache hit at 277.5s, miss at 300s. |
| claude-opus-4.7 | 255s | 277.5s | ~266s | Cache hit at 255s, but prefix stability was less clean than the other two runs. |

## Method

- A stable prompt prefix was used for all probes.
- The harness waited for one of several delay values and then issued a hidden request.
- The OTel spans were inspected for `cache_read_input_tokens` vs. `cache_creation_input_tokens`.
- When the cache read counter stayed non-zero, the request was treated as a cache hit; otherwise it was treated as a cache miss.

## Context and caveats

- The measurements depend on the specific Copilot CLI version, account/session context, feature flights, and prompt prefix.
- Warm starts can bias results upward; the reported values are therefore conservative lower bounds with tight upper edges.
- The repo stores the raw artifacts in `results/` so future runs can be compared against this baseline.

## Files

- `results/results.csv`: raw probe-level measurements.
- `results/run_context.json`: configuration snapshot from the run.
- `assets/`: plots for cache-hit vs delay and cost vs delay.
