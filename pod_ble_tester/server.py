"""FastAPI app: serves the UI, queues pod tests, streams status over WebSocket.

Tests run one at a time on a single worker task because there is one BLE
adapter. The barcode scanner can keep scanning pods; they are queued.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel

from . import ble, config
from .store import ResultStore

log = logging.getLogger("pod_ble_tester")
STATIC_DIR = Path(__file__).parent / "static"

# Signature of the function that actually tests a pod. Swapped out in tests.
PodTester = Callable[[str, Optional[ble.StatusCallback]], Awaitable[ble.TestOutcome]]


class TestRequest(BaseModel):
    serial: str


class Broadcaster:
    """Fan-out of JSON events to every connected WebSocket client."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def send(self, event: dict[str, Any]) -> None:
        payload = json.dumps(event)
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


class TestRunner:
    """Serialises pod tests through an asyncio queue and publishes progress."""

    def __init__(self, store: ResultStore, broadcaster: Broadcaster, tester: PodTester) -> None:
        self.store = store
        self.broadcaster = broadcaster
        self.tester = tester
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.current: Optional[str] = None
        self.stage: Optional[str] = None
        self.message: Optional[str] = None
        self._task: Optional[asyncio.Task[None]] = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._worker(), name="pod-test-worker")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def status(self) -> dict[str, Any]:
        return {
            "busy": self.current is not None,
            "current": self.current,
            "stage": self.stage,
            "message": self.message,
            "queued": list(self.queue._queue),  # type: ignore[attr-defined]
        }

    async def enqueue(self, serial: str) -> dict[str, Any]:
        await self.queue.put(serial)
        await self.broadcaster.send({"type": "queued", "serial": serial, "status": self.status()})
        return self.status()

    async def _worker(self) -> None:
        while True:
            serial = await self.queue.get()
            self.current = serial
            try:
                await self._run_one(serial)
            except Exception:  # never let the worker die
                log.exception("unexpected error testing %s", serial)
            finally:
                self.current = self.stage = self.message = None
                self.queue.task_done()
                await self.broadcaster.send({"type": "idle", "status": self.status()})

    async def _run_one(self, serial: str) -> None:
        async def on_status(stage: str, message: str) -> None:
            self.stage, self.message = stage, message
            log.info("[%s] %s: %s", serial, stage, message)
            await self.broadcaster.send(
                {"type": "status", "serial": serial, "stage": stage, "message": message, "status": self.status()}
            )

        outcome = await self.tester(serial, on_status)
        record = self.store.add(outcome)
        await self.broadcaster.send({"type": "result", "record": record, "summary": self.store.summary()})


def create_app(store: Optional[ResultStore] = None, tester: Optional[PodTester] = None) -> FastAPI:
    store = store or ResultStore(config.DB_PATH)
    broadcaster = Broadcaster()
    runner = TestRunner(store, broadcaster, tester or ble.test_pod)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        runner.start()
        try:
            yield
        finally:
            await runner.stop()

    app = FastAPI(title="Bloom Pod BLE Tester", lifespan=lifespan)
    app.state.store = store
    app.state.runner = runner

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/config")
    async def get_config() -> dict[str, Any]:
        return {
            "pod_name_prefix": config.POD_NAME_PREFIX,
            "scan_timeout_s": config.SCAN_TIMEOUT_S,
            "connect_timeout_s": config.CONNECT_TIMEOUT_S,
        }

    @app.get("/api/status")
    async def get_status() -> dict[str, Any]:
        return runner.status()

    @app.get("/api/results")
    async def get_results() -> dict[str, Any]:
        return {"results": store.all(), "summary": store.summary()}

    @app.get("/api/results.csv", response_class=PlainTextResponse)
    async def download_csv() -> Response:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return Response(
            content=store.to_csv(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="pod_ble_results_{stamp}.csv"'},
        )

    @app.post("/api/test", status_code=202)
    async def start_test(req: TestRequest) -> dict[str, Any]:
        serial = ble.normalize_serial(req.serial)
        if not serial:
            raise HTTPException(status_code=400, detail="Serial number is empty")
        return {"serial": serial, "status": await runner.enqueue(serial)}

    @app.websocket("/ws")
    async def websocket(ws: WebSocket) -> None:
        await broadcaster.connect(ws)
        try:
            await ws.send_text(json.dumps({"type": "hello", "status": runner.status(), "summary": store.summary()}))
            while True:
                await ws.receive_text()  # keep-alive; clients may send pings
        except WebSocketDisconnect:
            pass
        finally:
            broadcaster.disconnect(ws)

    return app





def main(argv: Optional[list[str]] = None) -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Bloom Pod BLE connection tester")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--no-browser", action="store_true", help="do not open the UI in a browser")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    url = f"http://{args.host}:{args.port}/"
    log.info("Bloom Pod BLE tester at %s (results in %s)", url, config.DB_PATH)
    if not args.no_browser:
        webbrowser.open(url)
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
