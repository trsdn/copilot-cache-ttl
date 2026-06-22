"""Run the Copilot CLI non-interactively and capture OTel metrics for one call.

Each invocation:
  * gets a unique COPILOT_OTEL_FILE_EXPORTER_PATH so spans are isolated per call,
  * runs hidden (no popup console window) to stay demo-safe on Windows,
  * applies stabilization flags so the cached prompt prefix stays byte-identical.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))
from otel_parse import CallMetrics, parse_otel_file  # noqa: E402

# Hide the child console window on Windows (demo-safe: no popups).
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


@dataclass
class CallResult:
    model: str
    ok: bool
    unavailable: bool
    metrics: CallMetrics
    raw_otel_path: str
    stdout: str
    stderr: str
    error: Optional[str] = None


def _copilot_exe() -> str:
    exe = shutil.which("copilot")
    if not exe:
        raise RuntimeError("copilot CLI not found on PATH")
    return exe


def build_prompt(base_prompt: str, padding_cfg: dict) -> str:
    """Compose the prompt with a fixed, byte-stable padding block."""
    if not padding_cfg or not padding_cfg.get("enabled"):
        return base_prompt
    line = padding_cfg.get("line", "")
    repeat = int(padding_cfg.get("repeat", 0))
    pad = ("\n".join([line] * repeat)) if repeat > 0 else ""
    return f"{base_prompt}\n\n{pad}"


def standing_flags(runner_cfg: dict) -> list:
    """The non-prompt CLI flags applied to every call (the stabilized config).

    These define the CLI behaviour during the test (and therefore part of the
    cache key), so they are captured verbatim into the run context.
    """
    flags = ["-s", "--allow-all", "--no-auto-update"]
    if runner_cfg.get("no_custom_instructions", True):
        flags.append("--no-custom-instructions")
    if runner_cfg.get("disable_builtin_mcps", True):
        flags.append("--disable-builtin-mcps")
    if runner_cfg.get("no_color", True):
        flags.append("--no-color")
    # Optional explicit pin of the CLI's experimental-features toggle. When unset
    # (None), the CLI uses the persisted ~/.copilot/settings.json value instead;
    # either way the effective state is recorded by cli_config.capture_cli_config.
    experimental = runner_cfg.get("experimental", None)
    if experimental is True:
        flags.append("--experimental")
    elif experimental is False:
        flags.append("--no-experimental")
    return flags


def run_call(
    model: str,
    prompt: str,
    runner_cfg: dict,
    otel_dir: str,
    workdir: Optional[str] = None,
) -> CallResult:
    """Execute a single copilot -p call and return parsed metrics."""
    otel_path = os.path.abspath(
        os.path.join(otel_dir, f"otel_{model}_{uuid.uuid4().hex}.jsonl")
    )
    os.makedirs(os.path.dirname(otel_path), exist_ok=True)

    env = dict(os.environ)
    env["COPILOT_OTEL_FILE_EXPORTER_PATH"] = otel_path
    env["COPILOT_OTEL_ENABLED"] = "true"
    # Keep child PowerShell quiet/hidden where applicable.
    env.setdefault("NO_COLOR", "1")

    cmd = [
        _copilot_exe(),
        "-p",
        prompt,
        "--model",
        model,
    ] + standing_flags(runner_cfg)

    # Run from an empty/neutral working dir so project context never enters the prefix.
    cwd = workdir or tempfile.gettempdir()
    timeout = int(runner_cfg.get("timeout_seconds", 180))

    try:
        proc = subprocess.run(
            cmd,
            env=env,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
        stdout, stderr, rc = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        return CallResult(
            model=model,
            ok=False,
            unavailable=False,
            metrics=CallMetrics(model=model),
            raw_otel_path=otel_path,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            error=f"timeout after {timeout}s",
        )

    combined = f"{stdout}\n{stderr}"
    unavailable = "is not available" in combined

    metrics = parse_otel_file(otel_path)

    ok = (rc == 0) and metrics.span_found and not unavailable
    error = None
    if unavailable:
        error = "model not available"
    elif not metrics.span_found:
        error = f"no chat span in OTel output (rc={rc})"

    return CallResult(
        model=model,
        ok=ok,
        unavailable=unavailable,
        metrics=metrics,
        raw_otel_path=otel_path,
        stdout=stdout,
        stderr=stderr,
        error=error,
    )


if __name__ == "__main__":
    import json

    res = run_call(
        sys.argv[1] if len(sys.argv) > 1 else "claude-opus-4.8",
        "Reply with the single word: ok",
        {"timeout_seconds": 180},
        tempfile.gettempdir(),
    )
    print(json.dumps({"ok": res.ok, "error": res.error, **res.metrics.to_dict()}, indent=2))
