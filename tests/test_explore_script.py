"""The fixture-recording script reads the integration's constants."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "explore_api.py"


def test_explore_script_loads_const_without_home_assistant() -> None:
    """The script must stay runnable outside a Home Assistant environment.

    Loading it in a fresh interpreter must not import `homeassistant`, and
    the constants it probes with must be the integration's own.
    """
    probe = f"""
import importlib.util, sys
spec = importlib.util.spec_from_file_location("explore_api", {str(SCRIPT)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert not any(name.split(".")[0] == "homeassistant" for name in sys.modules)
assert not any(name.startswith("custom_components") for name in sys.modules)
const = module.const
assert module.SY_PRECIPITATION == const.SY_PRECIPITATION
assert module.SY_CLOUD == frozenset(range(1, 6))
assert module.PRECIP_MIN_MM == const.PRECIP_MIN_MM
assert module.NWP_PARAMS.split(",") == list(const.AROME_PARAMETERS)
assert module.ENSEMBLE_PARAMS.split(",") == list(const.ENSEMBLE_PARAMETERS)
print("ok")
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
