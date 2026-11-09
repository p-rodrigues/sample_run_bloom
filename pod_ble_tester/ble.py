"""BLE side of the tester: find a Pod by serial number, connect, report.

Bloom Pods advertise a local name of the form ``BLOOM_<x><serial>`` where
``<x>`` is a single revision letter (``M`` on current pods). A test consists of:

1. scanning until an advertisement whose name matches the serial is seen,
2. opening a GATT connection to that device (service discovery included),
3. disconnecting cleanly.

Any failure or timeout along the way is a FAIL with a human readable reason.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Awaitable, Callable, Optional

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from . import config

# (stage, message) -> awaitable. Stages: scanning, found, connecting, connected, done.
StatusCallback = Callable[[str, str], Awaitable[None]]


def normalize_serial(raw: str) -> str:
    """Trim a scanned value and strip a full BLE name down to the bare serial.

    Operators may scan the serial printed on the pod, or paste the advertised
    name. Both end up as the bare serial, e.g. ``"BLOOM_M12345678"`` -> ``"12345678"``.
    """
    value = raw.strip()
    match = re.fullmatch(re.escape(config.POD_NAME_PREFIX) + r".(.+)", value)
    if match:
        value = match.group(1)
    return value


def expected_name_pattern(serial: str) -> re.Pattern[str]:
    """Regex matching the advertised name of the pod with ``serial``."""
    return re.compile(rf"^{re.escape(config.POD_NAME_PREFIX)}.{re.escape(serial)}$")


def name_matches(serial: str, name: Optional[str]) -> bool:
    return bool(name) and expected_name_pattern(serial).match(name) is not None


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class TestOutcome:
    __test__ = False  # not a pytest test class
    serial: str
    passed: bool
    tested_at: str
    connected_at: Optional[str] = None
    duration_s: float = 0.0
    ble_name: Optional[str] = None
    address: Optional[str] = None
    rssi: Optional[int] = None
    service_count: Optional[int] = None
    error: Optional[str] = None
    stages: list[str] = field(default_factory=list)

    @property
    def result(self) -> str:
        return "PASS" if self.passed else "FAIL"


async def _emit(status: Optional[StatusCallback], stage: str, message: str) -> None:
    if status is not None:
        await status(stage, message)


async def find_pod(
    serial: str,
    timeout: float,
    status: Optional[StatusCallback] = None,
) -> tuple[BLEDevice, AdvertisementData]:
    """Scan until a device advertising the expected name is seen.

    Raises ``asyncio.TimeoutError`` if nothing matching shows up in ``timeout`` s.
    """
    pattern = expected_name_pattern(serial)
    loop = asyncio.get_running_loop()
    found: asyncio.Future[tuple[BLEDevice, AdvertisementData]] = loop.create_future()

    def on_advertisement(device: BLEDevice, adv: AdvertisementData) -> None:
        name = adv.local_name or device.name
        if name and pattern.match(name) and not found.done():
            found.set_result((device, adv))

    async def scan() -> tuple[BLEDevice, AdvertisementData]:
        async with BleakScanner(detection_callback=on_advertisement):
            return await found

    await _emit(status, "scanning", f"Scanning for {config.POD_NAME_PREFIX}?{serial} (up to {timeout:.0f}s)")
    # The timeout covers scanner start-up too: on macOS the first launch can
    # block on the Bluetooth permission prompt / adapter power-on wait.
    return await asyncio.wait_for(scan(), timeout=timeout)


async def test_pod(
    serial: str,
    status: Optional[StatusCallback] = None,
    scan_timeout: Optional[float] = None,
    connect_timeout: Optional[float] = None,
) -> TestOutcome:
    """Run the full scan -> connect -> disconnect check for one pod."""
    scan_timeout = config.SCAN_TIMEOUT_S if scan_timeout is None else scan_timeout
    connect_timeout = config.CONNECT_TIMEOUT_S if connect_timeout is None else connect_timeout

    started = time.monotonic()
    outcome = TestOutcome(serial=serial, passed=False, tested_at=_now_iso())

    async def track(stage: str, message: str) -> None:
        outcome.stages.append(stage)
        await _emit(status, stage, message)

    # 1. Scan
    try:
        device, adv = await find_pod(serial, scan_timeout, track)
    except asyncio.TimeoutError:
        outcome.error = f"Pod not found: no advertisement named {config.POD_NAME_PREFIX}?{serial} within {scan_timeout:.0f}s"
        outcome.duration_s = round(time.monotonic() - started, 2)
        await track("done", outcome.error)
        return outcome
    except Exception as exc:  # adapter off, permission denied, ...
        outcome.error = f"BLE scan error: {exc.__class__.__name__}: {exc}"
        outcome.duration_s = round(time.monotonic() - started, 2)
        await track("done", outcome.error)
        return outcome

    outcome.ble_name = adv.local_name or device.name
    outcome.address = device.address
    outcome.rssi = adv.rssi
    await track("found", f"Found {outcome.ble_name} ({device.address}) RSSI {adv.rssi} dBm")

    # 2. Connect (bleak performs service discovery as part of connect)
    await track("connecting", f"Connecting to {outcome.ble_name} (up to {connect_timeout:.0f}s)")
    try:
        async with BleakClient(device, timeout=connect_timeout) as client:
            if not client.is_connected:
                raise RuntimeError("connect() returned but client is not connected")
            outcome.connected_at = _now_iso()
            outcome.service_count = len(list(client.services))
            await track("connected", f"Connected, {outcome.service_count} GATT services discovered")
    except asyncio.TimeoutError:
        outcome.error = f"Connection timed out after {connect_timeout:.0f}s"
    except Exception as exc:
        outcome.error = f"Connection failed: {exc.__class__.__name__}: {exc}"

    outcome.passed = outcome.error is None
    outcome.duration_s = round(time.monotonic() - started, 2)
    await track("done", "PASS" if outcome.passed else outcome.error or "FAIL")
    return outcome
