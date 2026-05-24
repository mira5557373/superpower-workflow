from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from superpower_workflow.dashboard.data import DashboardData, DashboardSnapshot
from superpower_workflow.dashboard.static import DASHBOARD_HTML

_GAUGE_METRICS = [
    ("sw_milestones_total", "Total milestones in workflow", "milestones_total"),
    ("sw_milestones_completed", "Completed milestones", "milestones_completed"),
    ("sw_milestones_failed", "Failed milestones", "milestones_failed"),
    ("sw_milestones_skipped", "Skipped milestones", "milestones_skipped"),
    ("sw_total_cost_usd", "Total cost in USD", "total_cost_usd"),
    ("sw_cost_per_task", "Cost per successful task in USD", "cost_per_task"),
    ("sw_elapsed_seconds", "Elapsed wall-clock seconds", "elapsed_seconds"),
    ("sw_total_duration_seconds", "Total run duration in seconds", "total_duration_seconds"),
    ("sw_rework_rate", "Rework rate (retries per milestone)", "rework_rate"),
    ("sw_defect_density", "Quality gate failure rate", "defect_density"),
]


def render_prometheus(snapshot: DashboardSnapshot) -> str:
    lines: list[str] = []
    d = snapshot.to_dict()

    for name, help_text, field_name in _GAUGE_METRICS:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name} {d[field_name]}")
        lines.append("")

    def _escape_label(v: str) -> str:
        return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    if snapshot.cost_by_milestone:
        lines.append("# HELP sw_milestone_cost_usd Cost per milestone in USD")
        lines.append("# TYPE sw_milestone_cost_usd gauge")
        for ms_name, cost in snapshot.cost_by_milestone.items():
            lines.append(f'sw_milestone_cost_usd{{milestone="{_escape_label(ms_name)}"}} {cost}')
        lines.append("")

    if snapshot.duration_by_milestone:
        lines.append("# HELP sw_milestone_duration_seconds Duration per milestone")
        lines.append("# TYPE sw_milestone_duration_seconds gauge")
        for ms_name, dur in snapshot.duration_by_milestone.items():
            safe = _escape_label(ms_name)
            lines.append(f'sw_milestone_duration_seconds{{milestone="{safe}"}} {dur}')
        lines.append("")

    return "\n".join(lines) + "\n"


def format_sse_event(snapshot: DashboardSnapshot) -> str:
    payload = json.dumps(snapshot.to_dict(), separators=(",", ":"))
    return f"data: {payload}\n\n"


def format_sse_keepalive() -> str:
    return ": keepalive\n\n"


def make_handler(data: DashboardData) -> type:
    class DashboardHandler(BaseHTTPRequestHandler):
        _data: DashboardData = data
        _shutdown_event: threading.Event = threading.Event()

        def do_GET(self) -> None:
            if self.path == "/":
                self._serve_html()
            elif self.path == "/api/snapshot":
                self._serve_snapshot()
            elif self.path == "/api/events":
                self._serve_sse()
            elif self.path == "/metrics":
                self._serve_metrics()
            else:
                self.send_error(404)

        def _serve_html(self) -> None:
            body = DASHBOARD_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_snapshot(self) -> None:
            snap = self._data.load_snapshot()
            body = json.dumps(snap.to_dict()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_sse(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                snap = self._data.load_snapshot()
                self.wfile.write(format_sse_event(snap).encode())
                self.wfile.flush()
                last_mtimes = self._data._snapshot_mtimes()
                while not self._shutdown_event.is_set():
                    self._shutdown_event.wait(timeout=2)
                    if self._shutdown_event.is_set():
                        break
                    current_mtimes = self._data._snapshot_mtimes()
                    if current_mtimes != last_mtimes:
                        snap = self._data.load_snapshot()
                        self.wfile.write(format_sse_event(snap).encode())
                        last_mtimes = current_mtimes
                    else:
                        self.wfile.write(format_sse_keepalive().encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

        def _serve_metrics(self) -> None:
            snap = self._data.load_snapshot()
            body = render_prometheus(snap).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    return DashboardHandler


class DashboardServer:
    def __init__(
        self,
        data: DashboardData,
        host: str = "localhost",
        port: int = 3000,
    ) -> None:
        self._data = data
        self._host = host
        self._port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._handler_cls: type | None = None

    @property
    def port(self) -> int:
        if self._server is not None:
            return self._server.server_address[1]
        return self._port

    def start(self) -> None:
        self._handler_cls = make_handler(self._data)
        self._handler_cls._shutdown_event.clear()
        self._server = ThreadingHTTPServer((self._host, self._port), self._handler_cls)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._handler_cls is not None:
            self._handler_cls._shutdown_event.set()
        if self._server is not None:
            self._server.shutdown()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
