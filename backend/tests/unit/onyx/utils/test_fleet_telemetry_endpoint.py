"""Fleet telemetry must never default to Onyx's collector (Yahont fork).

The endpoint is a module constant read once at import, so each case imports
the module in a fresh interpreter with a controlled environment.
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from onyx.utils import fleet_telemetry

_BACKEND_DIR = Path(__file__).resolve().parents[4]


def _endpoint_with(env_overrides: dict[str, str]) -> str:
    env = {
        key: value
        for key, value in os.environ.items()
        if key != "ONYX_TELEMETRY_ENDPOINT"
    }
    env.update(env_overrides)
    env["PYTHONPATH"] = str(_BACKEND_DIR)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from onyx.utils import fleet_telemetry; print(fleet_telemetry._ENDPOINT)",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=_BACKEND_DIR,
        timeout=120,
        check=True,
    )
    return result.stdout.strip().splitlines()[-1]


def test_default_endpoint_is_yahont() -> None:
    assert _endpoint_with({}) == "https://telemetry.yahont.ai"


def test_env_overrides_default_endpoint() -> None:
    assert (
        _endpoint_with({"ONYX_TELEMETRY_ENDPOINT": "https://collector.example/"})
        == "https://collector.example"
    )


def test_disabled_telemetry_starts_no_sender(monkeypatch: Any) -> None:
    monkeypatch.setattr(fleet_telemetry, "DISABLE_TELEMETRY", True)

    assert fleet_telemetry.start_telemetry() is None
