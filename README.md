# Bloom Pod BLE Tester

Checks that a Bloom Pod's Bluetooth works. Scan the Pod's serial number into
the text box, the tool immediately starts a BLE scan for a device advertising
as `BLOOM_?<serial>`, connects to it over GATT and records **PASS** or **FAIL**
with the timestamp of the connection. Results accumulate in a table and can be
downloaded as CSV.

## Requirements

- macOS, Linux (BlueZ) or Windows with a Bluetooth LE adapter.
- Python 3.10+.
- On macOS the terminal app running the tool needs Bluetooth permission
  (System Settings → Privacy & Security → Bluetooth).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run

```bash
pod-ble-tester            # starts http://127.0.0.1:9999 and opens it in the browser
pod-ble-tester --no-browser --port 9000
```

Or without installing: `python -m pod_ble_tester.server`.

Workflow at the bench:

1. Put the cursor in the serial box (it stays focused automatically).
2. Scan the Pod's barcode. A keyboard-wedge scanner types the serial and
   presses Enter, which submits the form.
3. Watch the banner: *scanning* → *found* → *connecting* → **PASS** / **FAIL**.
4. Scan the next Pod. Pods scanned while a test is running are queued.
5. Press **Download CSV** at any time to export every result.

A scanned value may be the bare serial or the full BLE name
(`BLOOM_M12345678`); the prefix is stripped.

## Configuration (environment variables)

| Variable            | Default           | Meaning                                              |
|---------------------|-------------------|------------------------------------------------------|
| `POD_NAME_PREFIX`   | `BLOOM_`          | Advertised name is `<prefix><one letter><serial>`    |
| `SCAN_TIMEOUT_S`    | `20`              | Seconds to wait for the Pod to be seen advertising   |
| `CONNECT_TIMEOUT_S` | `15`              | Seconds allowed for the GATT connection              |
| `DB_PATH`           | `data/results.db` | SQLite file holding all results                      |
| `HOST` / `PORT`     | `127.0.0.1`/`9999`| Where the UI is served                               |

## CSV columns

`serial_number, result, tested_at, connected_at, duration_s, ble_name, address, rssi, error`

`tested_at` is when the test started, `connected_at` when the GATT connection
was established (empty on FAIL). Times are ISO 8601 in the machine's local
timezone. Every attempt is a row; retesting a Pod adds a new row.

## Tests

```bash
pytest
```

The tests do not use real Bluetooth; the BLE layer is mocked.
