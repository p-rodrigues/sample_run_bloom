"""Runtime configuration, overridable through environment variables."""

from __future__ import annotations

import os
from pathlib import Path

# Bloom Pods advertise as "<POD_NAME_PREFIX><serial>", e.g. "BLOOM_M12345678".
POD_NAME_PREFIX: str = os.environ.get("POD_NAME_PREFIX", "BLOOM_M")

# Seconds to wait for the Pod to show up in a BLE scan before failing.
SCAN_TIMEOUT_S: float = float(os.environ.get("SCAN_TIMEOUT_S", "20"))

# Seconds allowed for the GATT connection to be established.
CONNECT_TIMEOUT_S: float = float(os.environ.get("CONNECT_TIMEOUT_S", "15"))

# Where results are persisted (SQLite).
DATA_DIR: Path = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DB_PATH: Path = Path(os.environ.get("DB_PATH", DATA_DIR / "results.db"))

HOST: str = os.environ.get("HOST", "127.0.0.1")
PORT: int = int(os.environ.get("PORT", "8764"))
