import csv
import io

from pod_ble_tester.ble import TestOutcome
from pod_ble_tester.store import CSV_COLUMNS, ResultStore


def make_store(tmp_path):
    return ResultStore(tmp_path / "results.db")


def test_add_and_list(tmp_path):
    store = make_store(tmp_path)
    store.add(TestOutcome("S1", True, "2026-11-09T10:00:00+00:00", connected_at="2026-11-09T10:00:03+00:00", duration_s=3.2))
    store.add(TestOutcome("S2", False, "2026-11-09T10:01:00+00:00", error="Pod not found"))

    rows = store.all()
    assert [r["serial_number"] for r in rows] == ["S2", "S1"]  # newest first
    assert rows[1]["result"] == "PASS"
    assert rows[0]["result"] == "FAIL"
    assert rows[0]["error"] == "Pod not found"
    assert store.summary() == {"total": 2, "passed": 1, "failed": 1}


def test_persistence_across_instances(tmp_path):
    path = tmp_path / "results.db"
    ResultStore(path).add(TestOutcome("S1", True, "2026-11-09T10:00:00+00:00"))
    assert ResultStore(path).summary()["total"] == 1


def test_csv_export(tmp_path):
    store = make_store(tmp_path)
    store.add(TestOutcome("S1", True, "2026-11-09T10:00:00+00:00", connected_at="2026-11-09T10:00:03+00:00",
                          duration_s=3.2, ble_name="BLOOM_MS1", address="AA", rssi=-50))
    store.add(TestOutcome("S2", False, "2026-11-09T10:01:00+00:00", error='Pod "not" found'))

    reader = csv.DictReader(io.StringIO(store.to_csv()))
    assert reader.fieldnames == CSV_COLUMNS
    rows = list(reader)
    assert len(rows) == 2
    assert rows[0]["serial_number"] == "S1"  # chronological order in the CSV
    assert rows[0]["result"] == "PASS"
    assert rows[0]["connected_at"] == "2026-11-09T10:00:03+00:00"
    assert rows[1]["result"] == "FAIL"
    assert rows[1]["connected_at"] == ""
    assert rows[1]["error"] == 'Pod "not" found'
