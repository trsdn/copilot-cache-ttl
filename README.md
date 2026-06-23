# Copilot CLI cache TTL measurement harness

This repository measures how long a Copilot CLI prompt-cache entry remains reusable before the service treats it as stale. The project uses the Copilot CLI's own OpenTelemetry export to observe cache read vs. cache creation for a fixed prompt prefix and a staircase of waiting delays.

## Public headline

Under the measured setup, the cache entry survived roughly 4.25-5.0 minutes for the GA Claude Opus variants tested here:

- claude-opus-4.5: about 4.25-4.63 minutes
- claude-opus-4.6: about 4.63-5.00 minutes
- claude-opus-4.7: about 4.25-4.63 minutes

These values are best interpreted as lower-bound estimates for a specific account/session context. They are not universal guarantees and should be re-run if the prompt prefix, CLI version, model, or feature flighting changes.

## What is in this repo

- `src/` contains the runner, parser, and reporting code.
- `results/` contains generated CSV/JSON artifacts and plots.
- `assets/` contains the exported charts.

## Reproducibility notes

- The harness runs hidden, non-interactive Copilot CLI requests.
- It records the copied prompt prefix hash and the OTel cache counters for each probe.
- The output is stored under `results/` and can be re-processed with the scripts in `src/`.

## Public policy

Public documentation and git history should only mention generally available (GA) model names. Internal, preview, or otherwise non-public model names must not be published here.
