"""Seed+probe experiment logic to measure per-model cache TTL.

A single measurement = seed (writes/refreshes cache) -> wait D seconds with NO
intervening access -> probe identical prompt. ``cache_read_tokens > 0`` on the
probe means the cached prefix was still alive after D seconds.

Each access refreshes the cache (sliding expiry), so every D must be measured with
its own seed and an uninterrupted gap. We staircase through the configured delays
to bracket the boundary, then binary-search to the requested resolution.
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

sys.path.insert(0, os.path.dirname(__file__))
from runner import run_call  # noqa: E402


@dataclass
class ProbeRecord:
    model: str
    delay_seconds: float
    phase: str            # "staircase" | "binary" | "confirm"
    cache_hit: bool
    seed_cache_read: int
    seed_cache_creation: int
    probe_cache_read: int
    probe_cache_creation: int
    probe_input_tokens: int
    probe_cost: float
    probe_nano_aiu: float
    probe_ttfc_s: float
    probe_server_ms: float
    seed_ok: bool
    probe_ok: bool
    tool_defs_hash: Optional[str] = None
    cli_version: Optional[str] = None
    seed_model: Optional[str] = None    # actual resolved model (matters for 'auto')
    probe_model: Optional[str] = None
    model_switch: bool = False          # seed/probe resolved to different models
    run_index: int = 0
    timestamp: float = field(default_factory=time.time)
    error: Optional[str] = None


@dataclass
class ModelResult:
    model: str
    ttl_lower_bound_s: Optional[float] = None   # last delay still ALIVE
    ttl_upper_bound_s: Optional[float] = None   # first delay EXPIRED
    records: list = field(default_factory=list)
    note: str = ""
    # Measurement-context fingerprint (answers "in which context did we measure?").
    cli_version: Optional[str] = None
    tool_defs_hash: Optional[str] = None
    tool_defs_count: int = 0
    cached_prefix_tokens: Optional[int] = None   # stable cache_read size when warm
    cold_check_warm: Optional[bool] = None       # was prefix already cached at start?
    interference_flags: list = field(default_factory=list)
    run_index: int = 0
    resolved_models: list = field(default_factory=list)  # actual models seen (for 'auto')

    @property
    def ttl_estimate_s(self) -> Optional[float]:
        lo, hi = self.ttl_lower_bound_s, self.ttl_upper_bound_s
        if lo is not None and hi is not None:
            return (lo + hi) / 2.0
        return lo if hi is None else None


@dataclass
class AggregateResult:
    """Aggregate of N repeated runs for one model label (e.g. 'auto')."""

    model: str
    runs: list = field(default_factory=list)        # list[ModelResult]
    ttl_mean_s: Optional[float] = None
    ttl_stdev_s: Optional[float] = None
    ttl_min_s: Optional[float] = None
    ttl_max_s: Optional[float] = None
    valid_runs: int = 0
    resolved_models: list = field(default_factory=list)
    flags: list = field(default_factory=list)

    # Compatibility shim so report helpers can treat an aggregate like a ModelResult.
    @property
    def ttl_lower_bound_s(self):
        return self.ttl_min_s

    @property
    def ttl_upper_bound_s(self):
        return self.ttl_max_s

    @property
    def ttl_estimate_s(self):
        return self.ttl_mean_s

    @property
    def records(self):
        out = []
        for r in self.runs:
            out.extend(r.records)
        return out

    @property
    def note(self):
        return "; ".join(self.flags)

    @property
    def cli_version(self):
        return self.runs[0].cli_version if self.runs else None

    @property
    def tool_defs_hash(self):
        return self.runs[0].tool_defs_hash if self.runs else None

    @property
    def tool_defs_count(self):
        return self.runs[0].tool_defs_count if self.runs else 0

    @property
    def cached_prefix_tokens(self):
        for r in self.runs:
            if r.cached_prefix_tokens is not None:
                return r.cached_prefix_tokens
        return None

    @property
    def cold_check_warm(self):
        return any(r.cold_check_warm for r in self.runs) if self.runs else None

    @property
    def interference_flags(self):
        out = []
        for r in self.runs:
            out.extend(r.interference_flags)
        return out


def aggregate_runs(model: str, runs: list) -> AggregateResult:
    """Combine repeated runs into mean/stdev/min/max TTL with resolved-model union."""
    import statistics

    agg = AggregateResult(model=model, runs=runs)
    estimates = [r.ttl_estimate_s for r in runs if r.ttl_estimate_s is not None]
    if estimates:
        agg.valid_runs = len(estimates)
        agg.ttl_mean_s = sum(estimates) / len(estimates)
        agg.ttl_min_s = min(estimates)
        agg.ttl_max_s = max(estimates)
        agg.ttl_stdev_s = statistics.stdev(estimates) if len(estimates) > 1 else 0.0
    seen = []
    for r in runs:
        for m in r.resolved_models:
            if m and m not in seen:
                seen.append(m)
    agg.resolved_models = seen
    if model == "auto" and len(seen) > 1:
        agg.flags.append(
            f"'auto' routed to multiple models across runs ({', '.join(seen)}); "
            "the mean TTL mixes different models. Inspect per-run results."
        )
    runs_with_switch = sum(
        1 for r in runs if any(rec.model_switch for rec in r.records)
    )
    if runs_with_switch:
        agg.flags.append(
            f"{runs_with_switch}/{len(runs)} run(s) had a seed/probe model switch "
            "under 'auto' (probe invalidated, not a true expiry)."
        )
    if len(estimates) < len(runs):
        agg.flags.append(
            f"only {len(estimates)}/{len(runs)} runs produced a numeric TTL estimate."
        )
    return agg


Logger = Callable[[str], None]


def _measure(model, delay, phase, prompt, runner_cfg, otel_dir, log, run_index=0) -> ProbeRecord:
    """One seed -> wait -> probe cycle."""
    log(f"  [{model}] {phase}: seeding cache, then waiting {delay:.0f}s ...")
    seed = run_call(model, prompt, runner_cfg, otel_dir)
    if not seed.ok:
        log(f"  [{model}] seed failed: {seed.error}")
    time.sleep(delay)
    probe = run_call(model, prompt, runner_cfg, otel_dir)

    seed_model = seed.metrics.model
    probe_model = probe.metrics.model
    # Under 'auto', the router may pick different models for seed vs probe. Those
    # use different caches, so a MISS is meaningless as a TTL signal -> flag it.
    model_switch = bool(
        seed_model and probe_model and seed_model != probe_model
    )
    hit = probe.metrics.cache_hit and probe.ok and not model_switch

    if model_switch:
        log(
            f"  [{model}] probe @ {delay:.0f}s -> MODEL SWITCH "
            f"(seed={seed_model}, probe={probe_model}) -> inconclusive"
        )
    else:
        log(
            f"  [{model}] probe @ {delay:.0f}s -> "
            f"{'HIT' if hit else 'MISS'} "
            f"(read={probe.metrics.cache_read_tokens}, "
            f"create={probe.metrics.cache_creation_tokens}"
            f"{', model=' + str(probe_model) if model == 'auto' else ''})"
        )
    return ProbeRecord(
        model=model,
        delay_seconds=delay,
        phase=phase,
        cache_hit=hit,
        seed_cache_read=seed.metrics.cache_read_tokens,
        seed_cache_creation=seed.metrics.cache_creation_tokens,
        probe_cache_read=probe.metrics.cache_read_tokens,
        probe_cache_creation=probe.metrics.cache_creation_tokens,
        probe_input_tokens=probe.metrics.input_tokens,
        probe_cost=probe.metrics.cost,
        probe_nano_aiu=probe.metrics.nano_aiu,
        probe_ttfc_s=probe.metrics.time_to_first_chunk_s,
        probe_server_ms=probe.metrics.server_duration_ms,
        seed_ok=seed.ok,
        probe_ok=probe.ok,
        tool_defs_hash=probe.metrics.tool_defs_hash,
        cli_version=probe.metrics.cli_version,
        seed_model=seed_model,
        probe_model=probe_model,
        model_switch=model_switch,
        run_index=run_index,
        error=None if probe.ok else probe.error,
    )


def _finalize(result: ModelResult) -> ModelResult:
    """Derive cached-prefix size and flag interference from collected records."""
    hits = [r for r in result.records if r.probe_ok and r.cache_hit]
    # Stable cached-prefix size = the cache_read value seen on hits.
    reads = [r.probe_cache_read for r in hits]
    if reads and result.cached_prefix_tokens is None:
        result.cached_prefix_tokens = max(set(reads), key=reads.count)
    if reads and (max(reads) - min(reads)) > 0.10 * max(reads):
        result.interference_flags.append(
            f"cache_read varied across hits ({min(reads)}..{max(reads)}); the cached "
            "prefix may be affected by external Copilot activity during the run."
        )
    # The cache key must stay constant across the run; a hash change = config drift.
    hashes = {r.tool_defs_hash for r in result.records if r.tool_defs_hash}
    if len(hashes) > 1:
        result.interference_flags.append(
            f"prompt-prefix hash changed mid-run ({len(hashes)} variants); the cache "
            "key was not stable, so TTL bounds may be unreliable."
        )
    if result.tool_defs_hash is None and hashes:
        result.tool_defs_hash = sorted(hashes)[0]
    # Resolved models actually used (probe side); relevant for 'auto'.
    seen = []
    for r in result.records:
        if r.probe_model and r.probe_model not in seen:
            seen.append(r.probe_model)
    result.resolved_models = seen
    return result


def measure_model(
    model: str,
    prompt: str,
    runner_cfg: dict,
    delays: list[float],
    bsearch_cfg: dict,
    otel_dir: str,
    log: Logger = print,
    run_index: int = 0,
) -> ModelResult:
    """Find the TTL boundary for one model via staircase + binary search."""
    result = ModelResult(model=model, run_index=run_index)
    delays = sorted(set(float(d) for d in delays))

    # Cold check: BEFORE we seed anything this run, probe once. If the prefix is
    # already cached (warm), the context is not exclusive — a previous run within
    # TTL, or external Copilot use of an identical stabilized prefix, is present.
    cold = run_call(model, prompt, runner_cfg, otel_dir)
    if cold.ok:
        result.cli_version = cold.metrics.cli_version
        result.tool_defs_hash = cold.metrics.tool_defs_hash
        result.tool_defs_count = cold.metrics.tool_defs_count
        result.cold_check_warm = cold.metrics.cache_hit
        if cold.metrics.cache_hit:
            result.cached_prefix_tokens = cold.metrics.cache_read_tokens
            result.interference_flags.append(
                "prefix already WARM at start (cache_read="
                f"{cold.metrics.cache_read_tokens}); ensure no other run/usage "
                "shares this stabilized prefix, or wait for it to cool down."
            )
        log(
            f"  [{model}] cold-check: prefix "
            f"{'WARM (already cached!)' if cold.metrics.cache_hit else 'cold (clean)'}, "
            f"cli={result.cli_version}, tools={result.tool_defs_count}, "
            f"prefix_hash={result.tool_defs_hash}"
        )

    last_alive: Optional[float] = None
    first_expired: Optional[float] = None

    # Staircase: increase delay until the first MISS.
    for d in delays:
        rec = _measure(model, d, "staircase", prompt, runner_cfg, otel_dir, log, run_index)
        result.records.append(rec)
        if not rec.probe_ok:
            result.note = f"probe error at {d:.0f}s: {rec.error}"
            return _finalize(result)
        if rec.model_switch:
            # 'auto' picked different models for seed vs probe -> not a TTL signal.
            # Retry this delay once; if it still switches, skip it (inconclusive).
            rec2 = _measure(
                model, d, "staircase", prompt, runner_cfg, otel_dir, log, run_index
            )
            result.records.append(rec2)
            if rec2.model_switch or not rec2.probe_ok:
                result.note = (
                    f"'auto' kept switching models around {d:.0f}s; skipped "
                    "(use a fixed --model for a clean TTL, or more repeats)."
                )
                continue
            rec = rec2
        if rec.cache_hit:
            last_alive = d
        else:
            first_expired = d
            break

    if first_expired is None:
        result.ttl_lower_bound_s = last_alive
        result.note = (
            f"cache still alive at the longest delay ({last_alive:.0f}s); "
            "TTL is at least this long. Extend delay_schedule to find the upper bound."
        )
        return _finalize(result)
    if last_alive is None:
        result.ttl_upper_bound_s = first_expired
        result.note = (
            f"cache already expired at the shortest delay ({first_expired:.0f}s); "
            "TTL is below this. Add smaller delays to narrow it."
        )
        return _finalize(result)

    # Binary search between last_alive (HIT) and first_expired (MISS).
    if bsearch_cfg.get("enabled", True):
        resolution = float(bsearch_cfg.get("resolution_seconds", 30))
        lo, hi = last_alive, first_expired
        while (hi - lo) > resolution:
            mid = (lo + hi) / 2.0
            rec = _measure(model, mid, "binary", prompt, runner_cfg, otel_dir, log, run_index)
            result.records.append(rec)
            if not rec.probe_ok or rec.model_switch:
                break
            if rec.cache_hit:
                lo = mid
            else:
                hi = mid
        last_alive, first_expired = lo, hi

        # Confirmation repeats at the boundary edges.
        confirmations = int(bsearch_cfg.get("confirmations", 0))
        for _ in range(confirmations):
            rec = _measure(model, last_alive, "confirm", prompt, runner_cfg, otel_dir, log, run_index)
            result.records.append(rec)
            if rec.probe_ok and not rec.model_switch and not rec.cache_hit:
                # Boundary drifted; widen the bracket conservatively.
                first_expired = last_alive
                last_alive = max(0.0, last_alive - resolution)

    result.ttl_lower_bound_s = last_alive
    result.ttl_upper_bound_s = first_expired
    return _finalize(result)
