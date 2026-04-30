from __future__ import annotations

import json
from socketserver import ThreadingMixIn
from threading import Event, Thread
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from prometheus_client import make_wsgi_app

from .config import ServerConfig


class _ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class MetricsHttpServer:
    def __init__(self, config: ServerConfig, registry, runtime_state) -> None:
        self._config = config
        self._registry = registry
        self._runtime_state = runtime_state
        self._thread: Thread | None = None
        self._stop = Event()
        self._server = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = Thread(target=self._serve, name="metrics-http", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _serve(self) -> None:
        metrics_app = make_wsgi_app(self._registry)

        def app(environ, start_response):
            path = environ.get("PATH_INFO", "/")
            if path == self._config.metrics_path:
                return metrics_app(environ, start_response)
            if path == "/info":
                payload = json.dumps(self._runtime_state.snapshot_info(), indent=2, sort_keys=True).encode("utf-8")
                start_response("200 OK", [("Content-Type", "application/json"), ("Content-Length", str(len(payload)))])
                return [payload]
            if path == "/status":
                payload = json.dumps(self._runtime_state.snapshot_status(), indent=2, sort_keys=True).encode("utf-8")
                start_response("200 OK", [("Content-Type", "application/json"), ("Content-Length", str(len(payload)))])
                return [payload]
            if path == "/":
                payload = (
                    "<html><head><title>MQ Exporter</title></head>"
                    "<body><h1>MQ Exporter</h1>"
                    f"<p><a href='{self._config.metrics_path}'>Metrics</a></p>"
                    "<p><a href='/info'>Info</a></p>"
                    "<p><a href='/status'>Status</a></p>"
                    "</body></html>"
                ).encode("utf-8")
                start_response("200 OK", [("Content-Type", "text/html"), ("Content-Length", str(len(payload)))])
                return [payload]
            payload = b"not found"
            start_response("404 Not Found", [("Content-Type", "text/plain"), ("Content-Length", str(len(payload)))])
            return [payload]

        self._server = make_server(
            self._config.host,
            self._config.port,
            app,
            server_class=_ThreadingWSGIServer,
            handler_class=WSGIRequestHandler,
        )
        self._server.serve_forever()
