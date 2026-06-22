"""Capture the Copilot CLI configuration and enabled experimental features.

For the measured TTLs to be reproducible, the run record must state *how the CLI
was configured during the test*: its version, the stabilization flags the harness
pinned, whether the CLI's experimental-features toggle was on, and which
server-assigned experiment/feature flags were active for this account.

Only non-sensitive fields are captured. Account identity (login), auth tokens and
local filesystem paths (e.g. trustedFolders) are intentionally **never** read or
written into the run context.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Optional

from runner import standing_flags

# Env vars whose values steer the CLI/OTel during the test (recorded as on/off,
# never their secret contents).
_RELEVANT_ENV = [
    "COPILOT_OTEL_ENABLED",
    "COPILOT_ALLOW_ALL",
    "COPILOT_MODEL",
    "COPILOT_HOME",
    "COPILOT_CONFIG_DIR",
    "NO_COLOR",
]


def _copilot_home() -> str:
    for var in ("COPILOT_HOME", "COPILOT_CONFIG_DIR"):
        val = os.environ.get(var)
        if val and os.path.isdir(val):
            return val
    return os.path.join(os.path.expanduser("~"), ".copilot")


def _cli_version() -> Optional[str]:
    exe = shutil.which("copilot")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=30
        ).stdout
    except Exception:
        return None
    # e.g. "GitHub Copilot CLI 1.0.64-2."
    import re

    m = re.search(r"(\d+\.\d+\.\d+(?:-\d+)?)", out)
    return m.group(1) if m else (out.strip() or None)


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        # config.json / settings.json may carry leading // comment lines.
        lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("//")]
        return json.loads("\n".join(lines))
    except Exception:
        return None


def _safe_settings(settings: Optional[dict]) -> dict:
    """Whitelist of behaviour-affecting, non-sensitive settings.json fields."""
    if not isinstance(settings, dict):
        return {}
    keys = ("experimental", "model", "logLevel", "showReasoning", "enabledPlugins")
    return {k: settings[k] for k in keys if k in settings}


def _exp_assignments(config: Optional[dict]) -> dict:
    """Extract the server-assigned experiment/feature flags from config.json.

    These A/B "flights" change CLI behaviour (request shape, batching, routing),
    so they belong in the audit trail alongside the CLI version.
    """
    if not isinstance(config, dict):
        return {}
    cache = config.get("expAssignmentsCache")
    if not isinstance(cache, dict) or not cache:
        return {}
    # The cache is keyed by an assignment-context hash; take the freshest entry.
    entries = [e for e in cache.values() if isinstance(e, dict)]
    if not entries:
        return {}
    entry = max(entries, key=lambda e: e.get("retrievedAt", ""))
    resp = entry.get("response", {}) if isinstance(entry.get("response"), dict) else {}
    params = {}
    configs = resp.get("Configs")
    if isinstance(configs, list) and configs:
        first = configs[0]
        if isinstance(first, dict) and isinstance(first.get("Parameters"), dict):
            params = first["Parameters"]
    enabled_params = sorted(
        k for k, v in params.items() if v is True
    )
    return {
        "retrieved_at": entry.get("retrievedAt"),
        "flighting_version": resp.get("FlightingVersion"),
        "impression_id": resp.get("ImpressionId"),
        "feature_codes": resp.get("Features") or [],
        "config_parameters": params,
        "enabled_feature_flags": enabled_params,
    }


def capture_cli_config(runner_cfg: dict) -> dict:
    """Return a non-sensitive snapshot of the CLI config used during the test."""
    home = _copilot_home()
    settings = _read_json(os.path.join(home, "settings.json"))
    config = _read_json(os.path.join(home, "config.json"))
    safe_settings = _safe_settings(settings)

    # Resolve the experimental toggle that actually applies during the test.
    pinned = runner_cfg.get("experimental", None)
    if pinned is True or pinned is False:
        experimental_effective = pinned
        experimental_source = "pinned via runner.experimental"
    else:
        experimental_effective = safe_settings.get("experimental")
        experimental_source = "persisted ~/.copilot/settings.json"

    env_state = {
        k: os.environ[k] for k in _RELEVANT_ENV if k in os.environ
    }

    return {
        "cli_version_reported": _cli_version(),
        "copilot_home": home,
        "experimental_enabled": experimental_effective,
        "experimental_source": experimental_source,
        "standing_flags": standing_flags(runner_cfg),
        "settings": safe_settings,
        "exp_assignments": _exp_assignments(config),
        "relevant_env": env_state,
    }


def reconcile_tested_versions(cfg: dict, observed_versions, log=None) -> dict:
    """Record the CLI version actually exercised, from the OTel spans.

    `cli_version_reported` comes from `copilot --version` at startup; the version
    that truly ran each call is the span's `service.version`. They can differ (e.g.
    a pending auto-update). The tested version is authoritative, so we record it and
    flag any mismatch.
    """
    tested = sorted({v for v in observed_versions if v})
    cfg["cli_version_tested"] = tested
    cfg["cli_version"] = tested[0] if len(tested) == 1 else (
        cfg.get("cli_version_reported")
    )
    reported = cfg.get("cli_version_reported")
    flags = []
    if len(tested) > 1:
        flags.append(
            "multiple CLI versions observed across spans "
            f"({', '.join(tested)}); the run mixed CLI versions."
        )
    elif tested and reported and tested[0] != reported:
        flags.append(
            f"tested CLI version {tested[0]} differs from the binary's reported "
            f"version {reported}; trust the tested version."
        )
    cfg["cli_version_flags"] = flags
    if log:
        if tested:
            log(f"  CLI version tested : {', '.join(tested)} (from OTel spans)")
        for f in flags:
            log(f"  [!] {f}")
    return cfg


def summarize_cli_config(cfg: dict, log) -> None:
    """Print a concise console summary of the captured CLI config."""
    log("-" * 70)
    log("Copilot CLI configuration (recorded for reproducibility):")
    log(f"  CLI version (binary): {cfg.get('cli_version_reported')}")
    exp = cfg.get("experimental_enabled")
    exp_str = "ON" if exp is True else ("OFF" if exp is False else "unknown")
    log(f"  Experimental mode  : {exp_str} ({cfg.get('experimental_source')})")
    log(f"  Standing flags     : {' '.join(cfg.get('standing_flags', []))}")
    exa = cfg.get("exp_assignments", {})
    if exa:
        enabled = exa.get("enabled_feature_flags", [])
        log(
            f"  Experiment flights : v{exa.get('flighting_version')} | "
            f"{len(exa.get('feature_codes', []))} feature codes | "
            f"{len(enabled)} enabled config flags"
        )
        if enabled:
            log("  Enabled feature flags:")
            for name in enabled:
                log(f"    - {name}")
    else:
        log("  Experiment flights : none found")
