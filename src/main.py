"""Entry point: orchestrate the per-model cache-TTL measurement run.

Usage:
    python src/main.py [--config config.yaml] [--models m1,m2] [--quick]

The harness:
  1. loads config,
  2. filters the candidate model list to those available on this account,
  3. for each model, seeds a cache and probes at increasing delays to find the
     TTL boundary (staircase + binary search),
  4. writes results.csv, prints summary tables, and renders charts.

Run in a QUIET window: any other Copilot use of the same model during the run can
refresh the shared system+tools cache and bias the measurement.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import yaml

sys.path.insert(0, os.path.dirname(__file__))
from experiment import measure_model, aggregate_runs, AggregateResult  # noqa: E402
from models import filter_available  # noqa: E402
from report import report  # noqa: E402
from runner import build_prompt  # noqa: E402
from cli_config import (  # noqa: E402
    capture_cli_config,
    reconcile_tested_versions,
    summarize_cli_config,
)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure Copilot cache token lifetime per model.")
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    ap.add_argument("--models", help="Comma-separated override of models to test.")
    ap.add_argument(
        "--quick",
        action="store_true",
        help="Use a short delay schedule (10,30,60,120s) for a fast smoke run.",
    )
    ap.add_argument("--no-charts", action="store_true")
    ap.add_argument(
        "--parallel",
        type=int,
        default=1,
        metavar="N",
        help="Measure up to N models concurrently. Safe because each MODEL has its "
        "own server-side cache; never run the SAME model in parallel (it would "
        "refresh its own prefix and inflate the measured TTL).",
    )
    ap.add_argument(
        "--repeats",
        type=int,
        default=None,
        metavar="N",
        help="Run each model's measurement N times and report mean/stdev/min/max. "
        "Recommended for --models auto, whose routed model can vary per run. "
        "Overrides the 'repeats' value in config.yaml.",
    )
    ap.add_argument(
        "--auto",
        action="store_true",
        help="Shortcut to include the 'auto' model (Copilot picks the model).",
    )
    ap.add_argument(
        "--auto-repeats",
        type=int,
        default=3,
        metavar="N",
        help="How many times to repeat the 'auto' model (averaged). Named models "
        "use --repeats. Default 3.",
    )
    ap.add_argument(
        "--max-delay",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Cap the staircase delay schedule at this many seconds (e.g. 1800 "
        "for a 30-minute ceiling).",
    )
    args = ap.parse_args()

    cfg = load_config(args.config)
    runner_cfg = cfg.get("runner", {})
    out = cfg.get("output", {})
    results_dir = os.path.join(HERE, out.get("results_dir", "results"))
    os.makedirs(results_dir, exist_ok=True)
    otel_dir = os.path.join(results_dir, "otel_raw")
    os.makedirs(otel_dir, exist_ok=True)

    prompt = build_prompt(cfg.get("prompt", "Reply with the single word: ok"),
                          cfg.get("padding", {}))

    candidates = (
        [m.strip() for m in args.models.split(",") if m.strip()]
        if args.models
        else cfg.get("models", [])
    )
    if args.auto and "auto" not in candidates:
        candidates = candidates + ["auto"]
    # Named models use the base repeats; 'auto' uses its own (it can route to
    # different models per run, so averaging is what makes its TTL meaningful).
    base_repeats = max(
        1, args.repeats if args.repeats is not None else int(cfg.get("repeats", 1))
    )
    auto_repeats = max(1, int(args.auto_repeats))

    def repeats_for(model: str) -> int:
        return auto_repeats if model == "auto" else base_repeats

    delays = [10, 30, 60, 120] if args.quick else list(cfg.get("delay_schedule_seconds", []))
    if args.max_delay is not None:
        delays = [d for d in delays if d <= args.max_delay]
    bsearch = cfg.get("binary_search", {})
    if args.quick:
        bsearch = dict(bsearch)
        bsearch.setdefault("resolution_seconds", 10)
        bsearch["confirmations"] = 0

    def log(msg: str) -> None:
        print(msg, flush=True)

    log("=" * 70)
    log("Copilot cache-token-lifetime harness")
    log(f"Candidates: {candidates}")
    log(f"Repeats: named models x{base_repeats}, auto x{auto_repeats}")
    log(f"Delay schedule (s): {delays}")
    cli_cfg = capture_cli_config(runner_cfg)
    summarize_cli_config(cli_cfg, log)
    log("Checking model availability ...")
    available, skipped = filter_available(candidates, runner_cfg)
    log(f"Available: {available}")
    if skipped:
        log(f"Skipped (unavailable): {skipped}")
    if not available:
        log("No available models to test. Exiting.")
        return 1

    results = []
    t0 = time.time()
    parallel = max(1, int(args.parallel))

    def measure_model_repeated(model):
        n = repeats_for(model)
        runs = []
        for i in range(n):
            if n > 1:
                log(f"[{model}] run {i + 1}/{n}")
            runs.append(
                measure_model(
                    model, prompt, runner_cfg, delays, bsearch, otel_dir, log, run_index=i
                )
            )
        if n > 1:
            return aggregate_runs(model, runs)
        return runs[0]

    if parallel > 1 and len(available) > 1:
        workers = min(parallel, len(available))
        log("-" * 70)
        log(
            f"Measuring {len(available)} models with up to {workers} in parallel. "
            "Distinct models = distinct caches, so no cross-dilution; repeats of the "
            "SAME model run sequentially on purpose."
        )
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(measure_model_repeated, available))
    else:
        for model in available:
            log("-" * 70)
            log(f"Measuring TTL for: {model} (x{repeats_for(model)} run(s))")
            results.append(measure_model_repeated(model))
    log(f"\nTotal wall time: {(time.time() - t0)/60:.1f} min")

    # Reconcile the version reported by the binary with the version that actually
    # ran each call (from the OTel spans) so the run records what was truly tested.
    reconcile_tested_versions(
        cli_cfg, [mr.cli_version for mr in results], log=log
    )

    report(
        results,
        results_dir,
        out.get("csv_name", "results.csv"),
        charts=(out.get("charts", True) and not args.no_charts),
    )

    # Persist the run context so the measurement is auditable: which CLI version,
    # which stabilized prefix (hash/tool count), and whether each prefix started cold.
    def model_ctx(mr):
        d = {
            "model": mr.model,
            "cli_version": mr.cli_version,
            "tool_defs_hash": mr.tool_defs_hash,
            "tool_defs_count": mr.tool_defs_count,
            "cached_prefix_tokens": mr.cached_prefix_tokens,
            "cold_check_warm": mr.cold_check_warm,
            "ttl_lower_bound_s": mr.ttl_lower_bound_s,
            "ttl_upper_bound_s": mr.ttl_upper_bound_s,
            "ttl_estimate_s": mr.ttl_estimate_s,
            "interference_flags": mr.interference_flags,
        }
        if isinstance(mr, AggregateResult):
            d.update(
                {
                    "repeats": len(mr.runs),
                    "valid_runs": mr.valid_runs,
                    "ttl_mean_s": mr.ttl_mean_s,
                    "ttl_stdev_s": mr.ttl_stdev_s,
                    "ttl_min_s": mr.ttl_min_s,
                    "ttl_max_s": mr.ttl_max_s,
                    "resolved_models": mr.resolved_models,
                    "per_run_ttl_estimate_s": [r.ttl_estimate_s for r in mr.runs],
                    "per_run_resolved_models": [r.resolved_models for r in mr.runs],
                    "aggregate_flags": mr.flags,
                }
            )
        else:
            d["resolved_models"] = mr.resolved_models
        return d

    context = {
        "started_at": t0,
        "finished_at": time.time(),
        "repeats": {"named": base_repeats, "auto": auto_repeats},
        "max_delay_s": args.max_delay,
        "parallel": parallel,
        "stabilization": {
            "disable_builtin_mcps": runner_cfg.get("disable_builtin_mcps", True),
            "no_custom_instructions": runner_cfg.get("no_custom_instructions", True),
            "no_color": runner_cfg.get("no_color", True),
            "neutral_working_dir": True,
        },
        "copilot_cli_config": cli_cfg,
        "prompt": prompt,
        "delays": delays,
        "models": [model_ctx(mr) for mr in results],
    }
    ctx_path = os.path.join(results_dir, "run_context.json")
    with open(ctx_path, "w", encoding="utf-8") as fh:
        json.dump(context, fh, indent=2)
    log(f"Run context: {ctx_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
