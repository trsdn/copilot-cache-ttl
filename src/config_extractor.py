"""Retrieve Copilot CLI configuration and active experimental features/flights."""
from __future__ import annotations

import os
import json


def get_copilot_cli_config() -> dict:
    """Read ~/.copilot config/settings to extract effective settings and flights."""
    config_info = {
        "config_json": {},
        "settings_json": {},
        "m_settings_json": {},
        "experimental_enabled": False,
        "active_flights": [],
        "active_flight_configs": {}
    }

    home = os.path.expanduser("~")
    copilot_dir = os.path.join(home, ".copilot")
    if not os.path.exists(copilot_dir):
        return config_info

    config_path = os.path.join(copilot_dir, "config.json")
    settings_path = os.path.join(copilot_dir, "settings.json")
    m_settings_path = os.path.join(copilot_dir, "m-settings.json")

    # 1. Parse config.json (stripping comment lines)
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as fh:
                content = fh.read()
            lines = []
            for line in content.splitlines():
                if line.strip().startswith("//"):
                    continue
                lines.append(line)
            config_info["config_json"] = json.loads("\n".join(lines))
        except Exception:
            pass

    # 2. Parse settings.json
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as fh:
                config_info["settings_json"] = json.load(fh)
        except Exception:
            pass

    # 3. Parse m-settings.json
    if os.path.exists(m_settings_path):
        try:
            with open(m_settings_path, "r", encoding="utf-8") as fh:
                config_info["m_settings_json"] = json.load(fh)
        except Exception:
            pass

    # 4. Extract experimental flags
    settings = config_info["settings_json"]
    experimental = settings.get("experimental")
    if experimental is not None:
        config_info["experimental_enabled"] = bool(experimental)

    # 5. Extract flights and their associated configs
    exp_cache = config_info["config_json"].get("expAssignmentsCache", {})
    for k, v in exp_cache.items():
        if isinstance(v, dict) and "response" in v:
            resp = v["response"] or {}
            features = resp.get("Features", [])
            if features:
                config_info["active_flights"] = features
            configs = resp.get("Configs", [])
            for cfg in configs:
                if isinstance(cfg, dict) and "Parameters" in cfg:
                    config_info["active_flight_configs"] = cfg["Parameters"]
            break  # Usually there's only one relevant entry

    return config_info
