"""Reporting: CSV, console summary table, and charts."""
from __future__ import annotations

import csv
import os
from typing import List

from tabulate import tabulate

_FIELDS = [
    "model",
    "delay_seconds",
    "phase",
    "cache_hit",
    "probe_cache_read",
    "probe_cache_creation",
    "probe_input_tokens",
    "probe_cost",
    "probe_nano_aiu",
    "probe_ttfc_s",
    "probe_server_ms",
    "seed_cache_read",
    "seed_cache_creation",
    "seed_ok",
    "probe_ok",
    "tool_defs_hash",
    "cli_version",
    "seed_model",
    "probe_model",
    "model_switch",
    "run_index",
    "timestamp",
    "error",
]


def _fmt_ttl(seconds):
    if seconds is None:
        return "n/a"
    if seconds >= 60:
        return f"{seconds/60:.1f} min ({seconds:.0f}s)"
    return f"{seconds:.0f}s"


def write_csv(results, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_FIELDS)
        w.writeheader()
        for mr in results:
            for rec in mr.records:
                row = {k: getattr(rec, k) for k in _FIELDS}
                w.writerow(row)


def print_summary(results) -> None:
    rows = []
    for mr in results:
        rows.append(
            [
                mr.model,
                _fmt_ttl(mr.ttl_lower_bound_s),
                _fmt_ttl(mr.ttl_upper_bound_s),
                _fmt_ttl(mr.ttl_estimate_s),
                len(mr.records),
                mr.note or "",
            ]
        )
    headers = ["Model", "Last alive", "First expired", "TTL estimate", "Probes", "Note"]
    print("\n" + tabulate(rows, headers=headers, tablefmt="github"))


def _fmt_secs(seconds):
    if seconds is None:
        return "n/a"
    if seconds >= 60:
        return f"{seconds/60:.1f}min"
    return f"{seconds:.0f}s"


def _aggregate_summary(results) -> None:
    """Print mean/stdev/min/max TTL across repeated runs (only for aggregates)."""
    from experiment import AggregateResult

    aggs = [r for r in results if isinstance(r, AggregateResult)]
    if not aggs:
        return
    rows = []
    for a in aggs:
        rows.append(
            [
                a.model,
                len(a.runs),
                a.valid_runs,
                _fmt_secs(a.ttl_mean_s),
                _fmt_secs(a.ttl_stdev_s),
                _fmt_secs(a.ttl_min_s),
                _fmt_secs(a.ttl_max_s),
                ", ".join(a.resolved_models) or "n/a",
            ]
        )
    headers = [
        "Model",
        "Runs",
        "Valid",
        "TTL mean",
        "TTL stdev",
        "TTL min",
        "TTL max",
        "Resolved model(s)",
    ]
    print("\nMulti-run aggregate (mean TTL across repeats):")
    print(tabulate(rows, headers=headers, tablefmt="github"))
    for a in aggs:
        for f in a.flags:
            print(f"  - [{a.model}] {f}")


def _hit_miss_economics(results) -> None:
    """Per-model averaged cost/latency for cache hits vs misses."""
    rows = []
    for mr in results:
        hits = [r for r in mr.records if r.probe_ok and r.cache_hit]
        misses = [r for r in mr.records if r.probe_ok and not r.cache_hit]

        def avg(items, attr):
            vals = [getattr(i, attr) for i in items]
            return sum(vals) / len(vals) if vals else None

        rows.append(
            [
                mr.model,
                len(hits),
                len(misses),
                _num(avg(hits, "probe_cost")),
                _num(avg(misses, "probe_cost")),
                _num(avg(hits, "probe_ttfc_s")),
                _num(avg(misses, "probe_ttfc_s")),
            ]
        )
    headers = [
        "Model",
        "#Hit",
        "#Miss",
        "Cost(hit)",
        "Cost(miss)",
        "TTFC s(hit)",
        "TTFC s(miss)",
    ]
    print("\nHit vs miss economics (averaged):")
    print(tabulate(rows, headers=headers, tablefmt="github"))


def _num(v):
    return "n/a" if v is None else f"{v:.3f}"


def render_charts(results, charts_dir: str) -> List[str]:
    """Render cache_read-vs-delay and cost-vs-delay charts. Returns file paths."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover
        print(f"[charts] matplotlib unavailable, skipping charts: {exc}")
        return []

    os.makedirs(charts_dir, exist_ok=True)
    paths = []

    # Chart 1: probe cache_read tokens vs delay (per model).
    fig, ax = plt.subplots(figsize=(9, 5))
    for mr in results:
        recs = sorted(
            [r for r in mr.records if r.probe_ok], key=lambda r: r.delay_seconds
        )
        if not recs:
            continue
        xs = [r.delay_seconds / 60.0 for r in recs]
        ys = [r.probe_cache_read for r in recs]
        ax.plot(xs, ys, marker="o", label=mr.model)
        if mr.ttl_estimate_s is not None:
            ax.axvline(
                mr.ttl_estimate_s / 60.0, linestyle="--", alpha=0.4
            )
    ax.set_xlabel("Delay since last access (minutes)")
    ax.set_ylabel("Probe cache_read tokens (0 = cache expired)")
    ax.set_title("Cache survival vs delay per model")
    ax.legend()
    ax.grid(True, alpha=0.3)
    p1 = os.path.join(charts_dir, "cache_read_vs_delay.png")
    fig.tight_layout()
    fig.savefig(p1, dpi=120)
    plt.close(fig)
    paths.append(p1)

    # Chart 2: probe cost vs delay (per model).
    fig, ax = plt.subplots(figsize=(9, 5))
    for mr in results:
        recs = sorted(
            [r for r in mr.records if r.probe_ok], key=lambda r: r.delay_seconds
        )
        if not recs:
            continue
        xs = [r.delay_seconds / 60.0 for r in recs]
        ys = [r.probe_cost for r in recs]
        ax.plot(xs, ys, marker="s", label=mr.model)
    ax.set_xlabel("Delay since last access (minutes)")
    ax.set_ylabel("Probe cost (AIU)")
    ax.set_title("Probe cost vs delay per model")
    ax.legend()
    ax.grid(True, alpha=0.3)
    p2 = os.path.join(charts_dir, "cost_vs_delay.png")
    fig.tight_layout()
    fig.savefig(p2, dpi=120)
    plt.close(fig)
    paths.append(p2)

    return paths


def _measurement_context(results) -> None:
    """Print the context each model's TTL was measured in, plus interference flags."""
    rows = []
    for mr in results:
        warm = (
            "n/a"
            if mr.cold_check_warm is None
            else ("WARM(!)" if mr.cold_check_warm else "cold(ok)")
        )
        rows.append(
            [
                mr.model,
                mr.cli_version or "n/a",
                mr.tool_defs_count or "n/a",
                mr.tool_defs_hash or "n/a",
                mr.cached_prefix_tokens if mr.cached_prefix_tokens is not None else "n/a",
                warm,
            ]
        )
    headers = [
        "Model",
        "CLI ver",
        "#Tools",
        "Prefix hash",
        "Cached tokens",
        "Start state",
    ]
    print("\nMeasurement context (the cache key each TTL was measured against):")
    print(tabulate(rows, headers=headers, tablefmt="github"))

    any_flag = False
    for mr in results:
        for flag in mr.interference_flags:
            if not any_flag:
                print("\n[!] Interference / isolation warnings:")
                any_flag = True
            print(f"  - [{mr.model}] {flag}")
    if not any_flag:
        print(
            "\nIsolation: no interference detected - prefixes started cold and the "
            "cache key stayed constant across each run."
        )


def _copilot_cli_config_summary(cli_config: dict) -> None:
    """Print Copilot CLI configuration and experimental features table."""
    if not cli_config:
        return

    print("\n" + "=" * 70)
    print("Copilot CLI Configuration & Experimental Features (during test)")
    print("=" * 70)

    # 1. General Settings
    settings_rows = []
    settings = cli_config.get("settings_json", {})
    for k, v in settings.items():
        settings_rows.append([k, str(v)])

    # Also add global experimental flag status
    settings_rows.append(["experimental (effective)", str(cli_config.get("experimental_enabled", False))])

    if settings_rows:
        print("\nGeneral Settings (from ~/.copilot/settings.json):")
        print(tabulate(settings_rows, headers=["Setting", "Value"], tablefmt="github"))

    # 2. Active Flighted Parameters / Features
    flight_rows = []
    flight_configs = cli_config.get("active_flight_configs", {})
    for k, v in sorted(flight_configs.items()):
        flight_rows.append([k, str(v)])

    if flight_rows:
        print("\nActive Experimental Features & Flights (A/B Test Assignments):")
        print(tabulate(flight_rows, headers=["Feature / Parameter", "Value"], tablefmt="github"))
    else:
        # Check if there are active flights list
        flights = cli_config.get("active_flights", [])
        if flights:
            print("\nActive Flights:")
            for f in sorted(flights):
                print(f"  - {f}")
        else:
            print("\nNo active experimental features or flights found.")

    # 3. WorkIQ / App Experiments
    m_settings = cli_config.get("m_settings_json", {})
    m_experiments = m_settings.get("experiments", {})
    m_rows = []
    for k, v in sorted(m_experiments.items()):
        m_rows.append([k, str(v)])

    if m_rows:
        print("\nWorkIQ / App Experiments (from ~/.copilot/m-settings.json):")
        print(tabulate(m_rows, headers=["Experiment", "Value"], tablefmt="github"))


def report(results, results_dir: str, csv_name: str, charts: bool, cli_config: dict = None) -> None:
    csv_path = os.path.join(results_dir, csv_name)
    write_csv(results, csv_path)
    print_summary(results)
    _aggregate_summary(results)
    _hit_miss_economics(results)
    _measurement_context(results)
    _copilot_cli_config_summary(cli_config)
    print(f"\nRaw per-probe data: {csv_path}")
    if charts:
        paths = render_charts(results, os.path.join(results_dir, "charts"))
        for p in paths:
            print(f"Chart: {p}")
