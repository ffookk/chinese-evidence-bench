"""A bounded local browser session using the authoritative evaluation engine."""

import base64
from copy import deepcopy
from dataclasses import dataclass
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import threading

from . import evaluation as ev
from .comparison import compare_runs

MAX_RUNS = 8
MAX_RUN_BYTES = 8 * 1024 * 1024
MAX_SESSION_BYTES = 24 * 1024 * 1024
MAX_REQUEST_BYTES = 2 * MAX_RUN_BYTES + 1024
MAX_DATASET_BYTES = 8 * 1024 * 1024
REQUEST_TIMEOUT = 5
_MISSING = object()
METADATA_FIELDS = {"run_id", "created_at", "model_label", "parameters_text", "review_method", "reviewer_label"}


class SessionError(Exception):
    """An explicitly safe fixed message with an HTTP status."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


@dataclass
class SavedRun:
    run: dict
    revision: int
    size: int


class WorkbenchSession:
    """Keep validated runs in memory; expose copies and enforce optimistic revisions."""

    def __init__(self, dataset):
        if len(ev.canonical(dataset.cases)) > MAX_DATASET_BYTES:
            raise SessionError("The startup dataset exceeds the workbench size limit.")
        self.dataset = ev.Dataset(tuple(deepcopy(dataset.cases)), dataset.sha256, dataset.validation_as_of)
        self._runs = {}
        self._counter = 0
        self._lock = threading.RLock()

    def _saved(self, key, revision=_MISSING):
        if not isinstance(key, str) or key not in self._runs:
            raise SessionError("The selected run is unavailable.", 404)
        saved = self._runs[key]
        if revision is not _MISSING and (type(revision) is not int or revision != saved.revision):
            raise SessionError("The saved run changed in another tab. Reload it before applying edits.", 409)
        return saved

    def _store(self, run, key=None):
        size = len(ev.canonical(run))
        previous = self._runs[key].size if key is not None else 0
        if size > MAX_RUN_BYTES or sum(item.size for item in self._runs.values()) - previous + size > MAX_SESSION_BYTES:
            raise SessionError("The run or session exceeds the memory limit.", 413)
        if key is None:
            if len(self._runs) >= MAX_RUNS:
                raise SessionError("The session run limit has been reached. Remove a saved run first.", 409)
            self._counter += 1
            key = "run-" + str(self._counter)
            revision = 1
        else:
            revision = self._runs[key].revision + 1
        self._runs[key] = SavedRun(run, revision, size)
        return self._view(key)

    def _view(self, key):
        saved = self._saved(key)
        run = deepcopy(saved.run)
        # Never ask JavaScript to parse or round-trip numeric parameter metadata.
        parameters = ev.canonical(run["generation"].pop("parameters")).decode("utf-8")
        return {"key": key, "revision": saved.revision, "run": run, "parameters_text": parameters, "metrics": ev.metrics_for(run["records"])}

    def _list(self):
        return [{"key": key, "revision": saved.revision, "run_id": saved.run["run_id"], "model_label": saved.run["generation"]["model_label"]} for key, saved in self._runs.items()]

    def _draft(self, payload):
        ev._keys(payload, {"key", "revision", "metadata", "records"}, "edit request")
        saved = self._saved(payload["key"], payload["revision"])
        run = deepcopy(saved.run)
        metadata = payload["metadata"]
        if not isinstance(metadata, dict) or set(metadata) - METADATA_FIELDS:
            raise SessionError("The metadata edit has unsupported fields.")
        for field in ("run_id", "created_at"):
            if field in metadata:
                run[field] = metadata[field]
        if "model_label" in metadata:
            run["generation"]["model_label"] = metadata["model_label"]
        if "parameters_text" in metadata:
            text = metadata["parameters_text"]
            if not isinstance(text, str):
                raise SessionError("Parameters must be supplied as raw JSON text.")
            run["generation"]["parameters"] = ev.decode_json(text, "generation parameters")
        for source, target in (("review_method", "method"), ("reviewer_label", "reviewer_label")):
            if source in metadata:
                run["review"][target] = metadata[source]
        edits = payload["records"]
        if not isinstance(edits, list) or len(edits) > len(run["records"]):
            raise SessionError("The record edits must be a bounded array.")
        positions = {record["case_id"]: index for index, record in enumerate(run["records"])}
        seen = set()
        for record in edits:
            ev._keys(record, ev.RECORD_FIELDS, "edited record")
            key = record["case_id"]
            if not isinstance(key, str) or key not in positions or key in seen:
                raise SessionError("Record edits contain an unknown or duplicate case.")
            seen.add(key)
            run["records"][positions[key]] = record
        return ev.normalize_run(self.dataset, run)

    def dispatch(self, route, payload):
        """Return a JSON-compatible response or authoritative download bytes."""
        with self._lock:
            if route == "/api/bootstrap":
                ev._keys(payload, set(), "session request")
                return {"dataset": {"cases": deepcopy(self.dataset.cases), "sha256": self.dataset.sha256, "validation_as_of": self.dataset.validation_as_of}, "runs": self._list(), "limits": {"runs": MAX_RUNS, "run_bytes": MAX_RUN_BYTES, "session_bytes": MAX_SESSION_BYTES}}
            if route == "/api/runs":
                ev._keys(payload, set(), "run list request")
                return {"runs": self._list()}
            if route == "/api/create":
                ev._keys(payload, {"run_id", "model_label"}, "create request")
                return self._store(ev.prepare_run(self.dataset, run_id=payload["run_id"], model_label=payload["model_label"]))
            if route == "/api/import":
                ev._keys(payload, {"document"}, "import request")
                document = payload["document"]
                if not isinstance(document, str):
                    raise SessionError("Import requires raw JSON text.")
                try:
                    size = len(document.encode("utf-8"))
                except UnicodeError as exc:
                    raise SessionError("Import requires valid UTF-8 text.") from exc
                if size > MAX_RUN_BYTES:
                    raise SessionError("The imported document exceeds the workbench size limit.", 413)
                value = ev.decode_json(document, "imported document")
                if isinstance(value, dict) and value.get("artifact_type") == "scored_run":
                    value = ev.verify_scored(self.dataset, value)["run"]
                return self._store(ev.normalize_run(self.dataset, value))
            if route == "/api/select":
                ev._keys(payload, {"key"}, "selection request")
                return self._view(payload["key"])
            if route in {"/api/preview", "/api/save"}:
                run = self._draft(payload)
                if route == "/api/preview":
                    return {"metrics": ev.metrics_for(run["records"]), "revision": payload["revision"]}
                return self._store(run, payload["key"])
            if route == "/api/remove":
                ev._keys(payload, {"key", "revision"}, "remove request")
                self._saved(payload["key"], payload["revision"])
                del self._runs[payload["key"]]
                return {"runs": self._list()}
            if route == "/api/export":
                ev._keys(payload, {"key", "revision", "kind"}, "export request")
                saved = self._saved(payload["key"], payload["revision"])
                if payload["kind"] == "run":
                    artifact = saved.run
                elif payload["kind"] == "scored":
                    artifact = ev.score_run(self.dataset, saved.run)
                else:
                    raise SessionError("The export kind is unsupported.")
                return self._download(artifact)
            if route == "/api/compare":
                ev._keys(payload, {"left_key", "left_revision", "right_key", "right_revision", "mode"}, "comparison request")
                left = self._saved(payload["left_key"], payload["left_revision"])
                right = self._saved(payload["right_key"], payload["right_revision"])
                if payload["mode"] not in ("preview", "export"):
                    raise SessionError("The comparison mode is unsupported.")
                report = compare_runs(self.dataset, ev.score_run(self.dataset, left.run), ev.score_run(self.dataset, right.run))
                return self._download(report) if payload["mode"] == "export" else report
            raise SessionError("The requested operation is unavailable.", 404)

    @staticmethod
    def _download(artifact):
        data = json.dumps(artifact, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8") + b"\n"
        if len(data) > ev.MAX_ARTIFACT_BYTES:
            raise SessionError("The exported artifact exceeds the size limit.", 413)
        return data


class WorkbenchServer(HTTPServer):
    allow_reuse_address = False

    def handle_error(self, request, client_address):
        # Never log a request, capability, source value, or local client details.
        pass


class WorkbenchHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def setup(self):
        self.request.settimeout(REQUEST_TIMEOUT)
        super().setup()

    def log_message(self, format, *args):
        pass

    def _response(self, status, payload, content_type="application/json; charset=utf-8", download=False):
        self.close_connection = True
        self.send_response_only(status)
        headers = {
            "Content-Type": content_type, "Content-Length": str(len(payload)),
            "Cache-Control": "no-store", "Pragma": "no-cache", "Connection": "close",
            "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY", "Content-Security-Policy": self.server.csp,
            "Cross-Origin-Resource-Policy": "same-origin", "Cross-Origin-Opener-Policy": "same-origin",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        }
        if download:
            headers["Content-Disposition"] = 'attachment; filename="evidence-bench-export.json"'
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def send_error(self, code, message=None, explain=None):
        self._response(code, b'{"error":"The HTTP request was rejected."}')

    def _boundary(self, authenticated):
        host = self.headers.get_all("Host", [])
        origin = self.headers.get_all("Origin", [])
        if host != [self.server.host_header] or (origin and origin != [self.server.origin]):
            raise SessionError("The request origin was rejected.", 403)
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise SessionError("Cross-site requests are not allowed.", 403)
        if self.headers.get_all("Transfer-Encoding") or self.headers.get_all("Expect"):
            raise SessionError("The request framing is unsupported.")
        # BaseHTTPRequestHandler normalizes leading double slashes; reject that alias.
        pieces = self.raw_requestline.split()
        if len(pieces) != 3 or pieces[1].decode("iso-8859-1") != self.path:
            raise SessionError("The request target is unsupported.")
        if authenticated:
            capability = self.headers.get_all("X-Workbench-Capability", [])
            if origin != [self.server.origin] or len(capability) != 1:
                raise SessionError("Session authentication is required.", 403)
            try:
                valid = secrets.compare_digest(capability[0], self.server.capability)
            except TypeError:
                valid = False
            if not valid:
                raise SessionError("Session authentication is required.", 403)

    def do_GET(self):
        try:
            self._boundary(False)
            if self.headers.get_all("Content-Length") or self.path != "/":
                raise SessionError("The requested page is unavailable.", 404)
            self._response(200, self.server.page, "text/html; charset=utf-8")
        except SessionError as exc:
            self._response(exc.status, ev.canonical({"error": str(exc)}))

    def do_POST(self):
        try:
            self._boundary(True)
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdecimal() or len(lengths[0]) > 9:
                raise SessionError("A single valid request length is required.", 411)
            length = int(lengths[0])
            if not 1 <= length <= MAX_REQUEST_BYTES:
                raise SessionError("The request exceeds the supported size.", 413)
            if self.headers.get_all("Content-Type", []) not in (["application/json"], ["application/json; charset=utf-8"]):
                raise SessionError("The request must use UTF-8 JSON.", 415)
            data = self.rfile.read(length)
            if len(data) != length:
                raise SessionError("The request body is incomplete.")
            try:
                payload = ev.decode_json(data.decode("utf-8"), "request")
            except UnicodeError as exc:
                raise SessionError("The request must contain valid UTF-8.") from exc
            result = self.server.session.dispatch(self.path, payload)
            self._response(200, result if isinstance(result, bytes) else ev.canonical(result), download=isinstance(result, bytes))
        except SessionError as exc:
            self._response(exc.status, ev.canonical({"error": str(exc)}))
        except ev.EvaluationError as exc:
            self._response(400, ev.canonical({"error": str(exc)}))
        except (TimeoutError, OSError, ValueError):
            self._response(400, b'{"error":"The request could not be completed."}')

    def do_HEAD(self):
        self.send_error(405)

    do_OPTIONS = do_HEAD
    do_PUT = do_HEAD
    do_PATCH = do_HEAD
    do_DELETE = do_HEAD
    do_TRACE = do_HEAD
    do_CONNECT = do_HEAD


def create_server(dataset):
    """Create an ephemeral loopback server; callers own serve_forever/shutdown/close."""
    session = WorkbenchSession(dataset)
    assets = Path(__file__).with_name("workbench_assets")
    try:
        script = (assets / "app.js").read_text(encoding="utf-8")
        style = (assets / "style.css").read_text(encoding="utf-8")
        template = (assets / "index.html").read_text(encoding="utf-8")
        capability = secrets.token_hex(32)
        page = template.replace("__CAPABILITY__", capability).replace("/*__STYLE__*/", style).replace("/*__SCRIPT__*/", script).encode("utf-8")
        hashes = [base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii") for text in (script, style)]
        server = WorkbenchServer(("127.0.0.1", 0), WorkbenchHandler)
    except (OSError, UnicodeError) as exc:
        raise ev.EvaluationError("Workbench startup failed; verify the local installation and loopback availability.") from exc
    server.session = session
    server.capability = capability
    server.host_header = "127.0.0.1:" + str(server.server_address[1])
    server.origin = "http://" + server.host_header
    server.page = page
    server.csp = "default-src 'none'; script-src 'sha256-" + hashes[0] + "'; style-src 'sha256-" + hashes[1] + "'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'"
    return server


def run_workbench(args):
    try:
        dataset = ev.load_dataset(args.dataset, args.as_of.isoformat())
        server = create_server(dataset)
    except SessionError as exc:
        raise ev.EvaluationError(str(exc)) from exc
    print("Workbench available at " + server.origin + "/", flush=True)
    print("Local memory only. Open the address manually; stop the server with Ctrl-C.", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
