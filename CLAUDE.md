# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A bench tool for Sword Health's Bloom Pod production: scan a Pod serial number,
the tool BLE-scans for the Pod, connects over GATT, and records PASS/FAIL with a
connection timestamp. Web UI served locally by a Python backend. Results in SQLite,
exportable as CSV. See README.md for operator usage and configuration.

## Commands

```bash
source .venv/bin/activate          # venv lives in .venv (gitignored)
pip install -e ".[dev]"            # install package + pytest/httpx
pod-ble-tester --no-browser        # run the server (http://127.0.0.1:8764)
python -m pod_ble_tester.server    # same, without installing the entry point
pytest                             # all tests
pytest tests/test_ble.py -k connection   # one test / module
```

Tests never touch real Bluetooth: `ble.find_pod` and `ble.BleakClient` are
patched, and `server.create_app(store=..., tester=...)` accepts a fake tester.
Keep it that way so the suite runs on CI boxes without an adapter.

## Architecture

Three layers in `pod_ble_tester/`, wired together in `server.create_app()`:

- `ble.py` — the actual check. `test_pod(serial, status_cb)` runs
  scan → connect → disconnect using **bleak** and returns a `TestOutcome`
  (never raises; failures become `error` text). Progress is reported through
  the async `status_cb(stage, message)` with stages
  `scanning, found, connecting, connected, done`. Pods advertise as
  `BLOOM_M<serial>`; the name must match exactly (prefix from
  `config.POD_NAME_PREFIX`). `normalize_serial` accepts either the bare serial
  or the full BLE name.
- `store.py` — `ResultStore`, a thin SQLite wrapper (one row per attempt,
  newest first in the API, chronological in CSV). CSV column order is
  `CSV_COLUMNS`; the UI table and README document the same columns.
- `server.py` — FastAPI app. `TestRunner` owns a single worker task that pops
  serials from an `asyncio.Queue` so tests run one at a time (one BLE adapter)
  while the scanner keeps queuing. Every status/result event is fanned out to
  WebSocket clients via `Broadcaster`; the UI also refetches `/api/results`
  on each result so a dropped socket only loses live progress, not data.
  `static/index.html` is the whole frontend (vanilla JS, no build step).

Configuration is all in `config.py`, read from environment variables at import
time. Defaults: `data/results.db`, port 8764, 20 s scan / 15 s connect timeouts.

## Conventions

- Commit every change (the owner asked for all work to be committed in git).
- Keep the barcode-scanner flow intact in the UI: the serial input must stay
  focused and clear itself after submit, and Enter must submit.
- `TestOutcome.error` is shown verbatim to operators; keep messages short and
  say what to do (not found vs. connection failed).
