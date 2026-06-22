"""Model discovery / availability checking for the harness."""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from runner import run_call  # noqa: E402


def check_available(model: str, runner_cfg: dict, prompt: str = "Reply with: ok") -> bool:
    """Return True if the model is usable on this account.

    Performs one tiny call; the CLI reports ``is not available`` for models the
    account cannot use. A successful chat span means the model works.
    """
    res = run_call(model, prompt, runner_cfg, tempfile.gettempdir())
    if res.unavailable:
        return False
    return res.ok


def filter_available(models: list[str], runner_cfg: dict) -> tuple[list[str], list[str]]:
    """Split the candidate list into (available, skipped)."""
    available, skipped = [], []
    for m in models:
        if check_available(m, runner_cfg):
            available.append(m)
        else:
            skipped.append(m)
    return available, skipped
