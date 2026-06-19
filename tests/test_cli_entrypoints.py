from __future__ import annotations

import importlib
from pathlib import Path
import tomllib


def test_pyproject_cli_entrypoints_point_to_main_functions() -> None:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    scripts = payload["project"]["scripts"]

    assert {
        "audit-signal-consumption",
        "build-btc-cycle-bundle",
        "build-daily-technical-bundle",
        "build-semiconductor-rotation-bundle",
        "build-platform-handoff",
        "build-research-handoff",
        "export-btc-cycle-research-csv",
        "export-us-equity-context-research-csv",
        "export-us-equity-price-proxy-research-csv",
        "export-us-equity-public-context-research-csv",
        "list-signal-consumer-contracts",
        "list-signal-source-families",
        "validate-quality-report",
        "validate-research-export",
        "validate-signal-bundle",
    }.issubset(scripts)

    for target in scripts.values():
        module_name, function_name = target.split(":", 1)
        module = importlib.import_module(module_name)
        assert callable(getattr(module, function_name))
