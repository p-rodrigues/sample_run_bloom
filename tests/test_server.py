import asyncio

from fastapi.testclient import TestClient

from pod_ble_tester.ble import TestOutcome
from pod_ble_tester.server import create_app
from pod_ble_tester.store import ResultStore


def fake_tester(result_for):
    async def tester(serial, status=None):
        if status:
            await status("scanning", "fake scan")
        passed = result_for(serial)
        return TestOutcome(serial, passed, "2026-11-09T10:00:00+00:00",
                           connected_at="2026-11-09T10:00:02+00:00" if passed else None,
                           error=None if passed else "Pod not found")
    return tester


def make_client(tmp_path, result_for=lambda s: True):
    app = create_app(store=ResultStore(tmp_path / "db.sqlite"), tester=fake_tester(result_for))
    return TestClient(app)


def wait_idle(client, tries=100):
    for _ in range(tries):
        if not client.get("/api/status").json()["busy"] and not client.get("/api/status").json()["queued"]:
            return
        asyncio.run(asyncio.sleep(0.01))
    raise AssertionError("runner never became idle")


def test_index_served(tmp_path):
    with make_client(tmp_path) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "Bloom Pod BLE Tester" in r.text


def test_submit_test_and_get_results(tmp_path):
    with make_client(tmp_path, result_for=lambda s: s == "GOOD") as client:
        r = client.post("/api/test", json={"serial": " BLOOM_MGOOD "})
        assert r.status_code == 202
        assert r.json()["serial"] == "GOOD"
        client.post("/api/test", json={"serial": "BAD"})
        wait_idle(client)

        data = client.get("/api/results").json()
        assert data["summary"] == {"total": 2, "passed": 1, "failed": 1}
        by_serial = {row["serial_number"]: row for row in data["results"]}
        assert by_serial["GOOD"]["result"] == "PASS"
        assert by_serial["GOOD"]["connected_at"] is not None
        assert by_serial["BAD"]["result"] == "FAIL"


def test_empty_serial_rejected(tmp_path):
    with make_client(tmp_path) as client:
        assert client.post("/api/test", json={"serial": "   "}).status_code == 400


def test_csv_download(tmp_path):
    with make_client(tmp_path) as client:
        client.post("/api/test", json={"serial": "S1"})
        wait_idle(client)
        r = client.get("/api/results.csv")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert "attachment" in r.headers["content-disposition"]
        lines = r.text.strip().splitlines()
        assert lines[0].startswith("serial_number,result,tested_at,connected_at")
        assert lines[1].startswith("S1,PASS,")


def test_websocket_receives_status_and_result(tmp_path):
    with make_client(tmp_path) as client:
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "hello"
            client.post("/api/test", json={"serial": "S1"})
            types = []
            for _ in range(10):
                ev = ws.receive_json()
                types.append(ev["type"])
                if ev["type"] == "idle":
                    break
            assert "status" in types
            assert "result" in types
            assert types[-1] == "idle"
