import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pod_ble_tester import ble


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("M12345678", "M12345678"),
        ("  M12345678\n", "M12345678"),
        ("BLOOM_M12345678", "M12345678"),
        ("", ""),
    ],
)
def test_normalize_serial(raw, expected):
    assert ble.normalize_serial(raw) == expected


@pytest.mark.parametrize(
    "serial, name, ok",
    [
        ("M12345678", "BLOOM_M12345678", True),
        ("M12345678", "BLOOM_A12345678", False),  # other revision letter
        ("M12345678", "BLOOM_M123456789", False),  # longer serial
        ("M12345678", "BLOOM_M1234567", False),
        ("M12345678", "BLOOM_12345678", False),  # missing revision letter
        ("M12345678", "MBAND_M12345678", False),
        ("M12345678", None, False),
    ],
)
def test_name_matches(serial, name, ok):
    assert ble.name_matches(serial, name) is ok


def test_expected_name_prepends_prefix():
    assert ble.expected_name("M12345678") == "BLOOM_M12345678"


def test_find_pod_scans_for_prefixed_serial():
    device = SimpleNamespace(address="AA", name=None)

    class FakeScanner:
        def __init__(self, detection_callback):
            self.cb = detection_callback

        async def __aenter__(self):
            self.cb(device, SimpleNamespace(local_name="BLOOM_M999", rssi=-40))
            self.cb(device, SimpleNamespace(local_name="BLOOM_M123", rssi=-50))
            return self

        async def __aexit__(self, *exc):
            return False

    messages = []

    async def status(stage, msg):
        messages.append(msg)

    with patch.object(ble, "BleakScanner", FakeScanner):
        _, adv = asyncio.run(ble.find_pod("M123", 1, status))

    assert adv.local_name == "BLOOM_M123"
    assert "BLOOM_M123" in messages[0]


def test_test_pod_reports_not_found_on_scan_timeout():
    async def never_found(serial, timeout, status=None):
        await status("scanning", "...")
        raise asyncio.TimeoutError

    stages = []

    async def status(stage, msg):
        stages.append(stage)

    with patch.object(ble, "find_pod", never_found):
        outcome = asyncio.run(ble.test_pod("ABC", status, scan_timeout=0.01))

    assert outcome.passed is False
    assert outcome.result == "FAIL"
    assert "not found" in outcome.error.lower()
    assert outcome.connected_at is None
    assert stages == ["scanning", "done"]


def test_test_pod_passes_when_connection_succeeds():
    device = SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name=None)
    adv = SimpleNamespace(local_name="BLOOM_MABC", rssi=-55)

    async def found(serial, timeout, status=None):
        await status("scanning", "...")
        return device, adv

    class FakeClient:
        def __init__(self, dev, timeout=None):
            self.is_connected = False
            self.services = ["a", "b", "c"]

        async def __aenter__(self):
            self.is_connected = True
            return self

        async def __aexit__(self, *exc):
            self.is_connected = False

    stages = []

    async def status(stage, msg):
        stages.append(stage)

    with patch.object(ble, "find_pod", found), patch.object(ble, "BleakClient", FakeClient):
        outcome = asyncio.run(ble.test_pod("ABC", status))

    assert outcome.passed is True
    assert outcome.ble_name == "BLOOM_MABC"
    assert outcome.address == "AA:BB:CC:DD:EE:FF"
    assert outcome.rssi == -55
    assert outcome.service_count == 3
    assert outcome.connected_at is not None
    assert stages == ["scanning", "found", "connecting", "connected", "done"]


def test_test_pod_fails_when_connection_raises():
    device = SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name="BLOOM_MABC")
    adv = SimpleNamespace(local_name=None, rssi=-70)

    async def found(serial, timeout, status=None):
        return device, adv

    class FailingClient:
        def __init__(self, dev, timeout=None):
            pass

        async def __aenter__(self):
            raise OSError("connection refused")

        async def __aexit__(self, *exc):
            return False

    with patch.object(ble, "find_pod", found), patch.object(ble, "BleakClient", FailingClient):
        outcome = asyncio.run(ble.test_pod("ABC", connect_attempts=1))

    assert outcome.passed is False
    assert outcome.ble_name == "BLOOM_MABC"
    assert "connection refused" in outcome.error


def _flaky_client(failures):
    """BleakClient fake whose first ``failures`` connects drop the link."""
    calls = {"n": 0}

    class FlakyClient:
        def __init__(self, dev, timeout=None):
            self.is_connected = False
            self.services = ["a"]

        async def __aenter__(self):
            calls["n"] += 1
            if calls["n"] <= failures:
                raise RuntimeError("disconnected")
            self.is_connected = True
            return self

        async def __aexit__(self, *exc):
            return False

    return FlakyClient, calls


async def _found(serial, timeout, status=None):
    return (
        SimpleNamespace(address="AA", name="BLOOM_MABC"),
        SimpleNamespace(local_name="BLOOM_MABC", rssi=-78),
    )


def test_test_pod_retries_connection_after_link_drop():
    client, calls = _flaky_client(failures=2)
    with patch.object(ble, "find_pod", _found), patch.object(ble, "BleakClient", client), \
            patch.object(ble.config, "CONNECT_RETRY_DELAY_S", 0):
        outcome = asyncio.run(ble.test_pod("MABC", connect_attempts=3))

    assert calls["n"] == 3
    assert outcome.passed is True
    assert outcome.error is None
    assert outcome.stages == ["found", "connecting", "connecting", "connecting", "connected", "done"]


def test_test_pod_fails_after_all_connection_attempts():
    client, calls = _flaky_client(failures=99)
    with patch.object(ble, "find_pod", _found), patch.object(ble, "BleakClient", client), \
            patch.object(ble.config, "CONNECT_RETRY_DELAY_S", 0):
        outcome = asyncio.run(ble.test_pod("MABC", connect_attempts=3))

    assert calls["n"] == 3
    assert outcome.passed is False
    assert "disconnected" in outcome.error
    assert "3 attempts" in outcome.error
    assert outcome.connected_at is None
