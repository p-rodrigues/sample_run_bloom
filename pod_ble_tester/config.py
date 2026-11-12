"""Runtime configuration, overridable through environment variables."""

from __future__ import annotations

import os
from pathlib import Path

# Bloom Pods advertise as "<POD_NAME_PREFIX><serial>". The scanned serial
# already carries the revision letter ("M12345678"), so the name is simply
# the prefix + serial, e.g. "BLOOM_M12345678" (see ble.expected_name).
POD_NAME_PREFIX: str = os.environ.get("POD_NAME_PREFIX", "BLOOM_")

# Seconds to wait for the Pod to show up in a BLE scan before failing.
SCAN_TIMEOUT_S: float = float(os.environ.get("SCAN_TIMEOUT_S", "20"))

# Seconds allowed for the GATT connection to be established.
CONNECT_TIMEOUT_S: float = float(os.environ.get("CONNECT_TIMEOUT_S", "15"))

# How many times to try connecting before failing. Links that drop during
# connect ("BleakError: disconnected") are usually transient.
CONNECT_ATTEMPTS: int = int(os.environ.get("CONNECT_ATTEMPTS", "3"))

# Pause between connection attempts.
CONNECT_RETRY_DELAY_S: float = float(os.environ.get("CONNECT_RETRY_DELAY_S", "1"))

# Where results are persisted (SQLite).
DATA_DIR: Path = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DB_PATH: Path = Path(os.environ.get("DB_PATH", DATA_DIR / "results.db"))

HOST: str = os.environ.get("HOST", "127.0.0.1")
PORT: int = int(os.environ.get("PORT", "9999"))
