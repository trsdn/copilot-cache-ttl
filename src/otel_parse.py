"""Parse Copilot CLI OTel JSONL exporter output into per-call metrics.

The CLI writes one JSON object per line. We care about the ``chat <model>`` span,
whose ``attributes`` carry token usage, cache token counts, cost and latency.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Optional
import hashlib


@dataclass
class CallMetrics:
    """Metrics extracted from a single ``chat <model>`` span."""

    model: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0  # cache WRITE (miss / first seed)
    cache_read_tokens: int = 0      # cache HIT (prefix still alive)
    cost: float = 0.0               # github.copilot.cost (AIU)
    nano_aiu: float = 0.0
    server_duration_ms: float = 0.0
    time_to_first_chunk_s: float = 0.0
    finish_reason: Optional[str] = None
    span_found: bool = False
    # Context identifying WHICH cached prefix this call hit. Two calls collide in
    # the server cache only if these match (same model + same tool/prompt prefix).
    cli_version: Optional[str] = None
    tool_defs_hash: Optional[str] = None
    tool_defs_count: int = 0

    @property
    def cache_hit(self) -> bool:
        """A hit is when the server served cached prefix tokens."""
        return self.cache_read_tokens > 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["cache_hit"] = self.cache_hit
        return d


def _attr(attrs: dict, *names: str, default=0):
    """Return the first present attribute among aliases (provider differences)."""
    for n in names:
        if n in attrs and attrs[n] is not None:
            return attrs[n]
    return default


def parse_otel_file(path: str) -> CallMetrics:
    """Parse a JSONL OTel file and return metrics for its ``chat`` span.

    Robust to OpenAI vs Anthropic cache field naming. If multiple chat spans
    exist (should not for a single -p call), the last one wins.
    """
    metrics = CallMetrics()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return metrics

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "span":
            continue
        name = obj.get("name", "")
        if not name.startswith("chat "):
            continue
        attrs = obj.get("attributes", {}) or {}

        metrics.span_found = True
        metrics.model = _attr(
            attrs, "gen_ai.response.model", "gen_ai.request.model", default=None
        )
        metrics.input_tokens = int(_attr(attrs, "gen_ai.usage.input_tokens"))
        metrics.output_tokens = int(_attr(attrs, "gen_ai.usage.output_tokens"))
        metrics.cache_creation_tokens = int(
            _attr(
                attrs,
                "gen_ai.usage.cache_creation_input_tokens",
                "gen_ai.usage.cache_creation_tokens",
            )
        )
        metrics.cache_read_tokens = int(
            _attr(
                attrs,
                "gen_ai.usage.cache_read_input_tokens",
                "gen_ai.usage.cached_tokens",
                "gen_ai.usage.cache_read_tokens",
            )
        )
        metrics.cost = float(_attr(attrs, "github.copilot.cost", default=0.0))
        metrics.nano_aiu = float(_attr(attrs, "github.copilot.nano_aiu", default=0.0))
        metrics.server_duration_ms = float(
            _attr(attrs, "github.copilot.server_duration", default=0.0)
        )
        metrics.time_to_first_chunk_s = float(
            _attr(attrs, "gen_ai.response.time_to_first_chunk", default=0.0)
        )
        fr = attrs.get("gen_ai.response.finish_reasons")
        if isinstance(fr, list) and fr:
            metrics.finish_reason = str(fr[0])

        # Cache-context fingerprint: which prefix did this call hit?
        tool_defs = attrs.get("gen_ai.tool.definitions")
        if isinstance(tool_defs, str) and tool_defs:
            metrics.tool_defs_hash = hashlib.sha256(
                tool_defs.encode("utf-8")
            ).hexdigest()[:16]
            try:
                metrics.tool_defs_count = len(json.loads(tool_defs))
            except (json.JSONDecodeError, TypeError):
                metrics.tool_defs_count = 0
        res_attrs = (obj.get("resource", {}) or {}).get("attributes", {}) or {}
        metrics.cli_version = res_attrs.get("service.version")

    return metrics


if __name__ == "__main__":
    import sys

    m = parse_otel_file(sys.argv[1])
    print(json.dumps(m.to_dict(), indent=2))
