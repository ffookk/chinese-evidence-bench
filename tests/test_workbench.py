"""Local session and HTTP boundary tests using only fictional response data."""

import base64
import contextlib
from copy import deepcopy
import hashlib
import http.client
import io
import json
from pathlib import Path
import re
import socket
import threading
import unittest
from unittest.mock import patch

from evidence_bench import evaluation as ev
from evidence_bench import workbench as wb
from test_evaluation import dataset, supplied_run
from test_comparison import changed_run


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.data = dataset()
        self.session = wb.WorkbenchSession(self.data)
        self.view = self.session.dispatch("/api/create", {"run_id": "fictional-a", "model_label": "fictional-model"})

    def edit(self, **overrides):
        return {"key": self.view["key"], "revision": self.view["revision"], "metadata": {}, "records": [], **overrides}

    def test_create_complete_unscored_view_and_explicit_parameter_text(self):
        self.assertEqual(len(self.view["run"]["records"]), 3)
        self.assertEqual(self.view["metrics"]["response_coverage"], ev.ratio(0, 3))
        self.assertEqual(self.view["parameters_text"], "{}")
        self.assertNotIn("parameters", self.view["run"]["generation"])
        self.assertEqual(self.view["revision"], 1)

    def test_dataset_and_returned_views_do_not_alias_session_state(self):
        original = self.session.dispatch("/api/bootstrap", {})["dataset"]["cases"][0]["question"]
        self.data.cases[0]["question"] = "Fictional external mutation."
        self.view["run"]["records"][0]["response_text"] = "Fictional view mutation."
        bootstrap = self.session.dispatch("/api/bootstrap", {})
        self.assertEqual(bootstrap["dataset"]["cases"][0]["question"], original)
        bootstrap["dataset"]["cases"][0]["question"] = "Another fictional mutation."
        self.assertEqual(self.session.dispatch("/api/bootstrap", {})["dataset"]["cases"][0]["question"], original)
        self.assertEqual(self.session.dispatch("/api/select", {"key": self.view["key"]})["run"]["records"][0]["response_text"], "")

    def test_preview_is_authoritative_but_only_save_mutates(self):
        record = deepcopy(self.view["run"]["records"][2])
        record.update(outcome="answered", response_text="Fictional answer.")
        record["judgments"] = {axis: "correct" for axis in ev.AXES}
        payload = self.edit(records=[record])
        preview = self.session.dispatch("/api/preview", payload)
        self.assertEqual(preview["metrics"]["factual"]["score"], ev.ratio(1, 1))
        self.assertEqual(self.session.dispatch("/api/select", {"key": self.view["key"]})["metrics"]["response_coverage"], ev.ratio(0, 3))
        saved = self.session.dispatch("/api/save", payload)
        self.assertEqual(saved["metrics"], preview["metrics"])
        self.assertEqual(saved["revision"], 2)
        with self.assertRaises(wb.SessionError) as error:
            self.session.dispatch("/api/save", payload)
        self.assertEqual(error.exception.status, 409)

    def test_every_revisioned_route_rejects_null_boolean_and_stale_revisions(self):
        routes = {
            "/api/preview": self.edit(), "/api/save": self.edit(),
            "/api/remove": {"key": self.view["key"], "revision": 1},
            "/api/export": {"key": self.view["key"], "revision": 1, "kind": "run"},
        }
        for route, payload in routes.items():
            for revision in (None, True, False, 0, 2, "1"):
                with self.subTest(route=route, revision_type=type(revision).__name__), self.assertRaises(wb.SessionError) as error:
                    self.session.dispatch(route, {**payload, "revision": revision})
                self.assertEqual(error.exception.status, 409)
        for field in ("left_revision", "right_revision"):
            for revision in (None, True, 0, 2):
                payload = {"left_key": self.view["key"], "left_revision": 1, "right_key": self.view["key"], "right_revision": 1, "mode": "preview", field: revision}
                with self.subTest(field=field), self.assertRaises(wb.SessionError) as error:
                    self.session.dispatch("/api/compare", payload)
                self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.session.dispatch("/api/select", {"key": self.view["key"]})["revision"], 1)

    def test_raw_import_edit_and_exports_preserve_large_integers_and_float_types(self):
        run = supplied_run(self.data)
        run["generation"]["parameters"] = {"whole_float": 1.0, "large_integer": 9007199254740993, "negative_zero": -0.0, "nested": [2.0, 2]}
        imported = self.session.dispatch("/api/import", {"document": json.dumps(run)})
        self.assertIn('"whole_float":1.0', imported["parameters_text"])
        self.assertIn('9007199254740993', imported["parameters_text"])
        saved = self.session.dispatch("/api/save", {"key": imported["key"], "revision": 1, "metadata": {"reviewer_label": "fictional-new-reviewer"}, "records": []})
        payload = {"key": saved["key"], "revision": 2, "kind": "scored"}
        exported = self.session.dispatch("/api/export", payload)
        artifact = ev.decode_json(exported, "test output")
        ev.verify_scored(self.data, artifact)
        parameters = artifact["run"]["generation"]["parameters"]
        self.assertEqual(ev.canonical(parameters), ev.canonical(run["generation"]["parameters"]))
        self.assertIs(type(parameters["whole_float"]), float)
        self.assertIs(type(parameters["large_integer"]), int)
        self.assertEqual(parameters["large_integer"], 9007199254740993)

    def test_explicit_parameter_edit_uses_python_strict_json(self):
        result = self.session.dispatch("/api/save", self.edit(metadata={"parameters_text": '{"integer":9007199254740993,"float":1.0}'}))
        self.assertEqual(result["parameters_text"], '{"float":1.0,"integer":9007199254740993}')
        for raw in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":1e400}', '[]'):
            with self.subTest(raw=raw), self.assertRaises(ev.EvaluationError):
                self.session.dispatch("/api/save", self.edit(revision=2, metadata={"parameters_text": raw}))
        self.assertEqual(self.session.dispatch("/api/select", {"key": self.view["key"]})["revision"], 2)

    def test_corrupt_drafts_are_rejected_without_mutating_saved_state(self):
        record = deepcopy(self.view["run"]["records"][0])
        record["case_sha256"] = "0" * 64
        payloads = [self.edit(records=[record]), self.edit(records=[self.view["run"]["records"][0]] * 2), self.edit(metadata={"extra": "fictional-private-marker"}), self.edit(extra=True)]
        for payload in payloads:
            with self.assertRaises((ev.EvaluationError, wb.SessionError)) as error:
                self.session.dispatch("/api/save", payload)
            self.assertFalse("fictional-private-marker" in str(error.exception))
        self.assertEqual(self.session.dispatch("/api/select", {"key": self.view["key"]}), self.view)

    def test_scored_import_recomputes_integrity_and_rejects_mismatched_context(self):
        artifact = ev.score_run(self.data, supplied_run(self.data))
        imported = self.session.dispatch("/api/import", {"document": json.dumps(artifact)})
        self.assertEqual(imported["metrics"], artifact["metrics"])
        artifact["metrics"]["sample_size"] = 999
        with self.assertRaises(ev.EvaluationError):
            self.session.dispatch("/api/import", {"document": json.dumps(artifact)})
        run = supplied_run(self.data)
        for field, value in (("dataset_sha256", "0" * 64), ("validation_as_of", "2026-02-01")):
            changed = deepcopy(run); changed[field] = value
            with self.assertRaises(ev.EvaluationError):
                self.session.dispatch("/api/import", {"document": json.dumps(changed)})
        for document in ('{"x":1,"x":2}', chr(0xD800)):
            with self.assertRaises((ev.EvaluationError, wb.SessionError)):
                self.session.dispatch("/api/import", {"document": document})
        self.assertEqual(len(self.session.dispatch("/api/runs", {})["runs"]), 2)

    def test_run_count_and_memory_limits_leave_existing_runs_unchanged(self):
        with patch.object(wb, "MAX_RUNS", 1), self.assertRaises(wb.SessionError):
            self.session.dispatch("/api/create", {"run_id": "fictional-b", "model_label": "fictional"})
        with patch.object(wb, "MAX_RUN_BYTES", 1), self.assertRaises(wb.SessionError):
            self.session.dispatch("/api/save", self.edit())
        with patch.object(wb, "MAX_SESSION_BYTES", 1), self.assertRaises(wb.SessionError):
            self.session.dispatch("/api/save", self.edit())
        with patch.object(wb, "MAX_RUN_BYTES", 1), self.assertRaises(wb.SessionError):
            self.session.dispatch("/api/import", {"document": "{}"})
        self.assertEqual(self.session.dispatch("/api/select", {"key": self.view["key"]}), self.view)
        with patch.object(wb, "MAX_DATASET_BYTES", 1), self.assertRaises(wb.SessionError):
            wb.WorkbenchSession(self.data)

    def test_remove_requires_revision_and_frees_run_capacity(self):
        result = self.session.dispatch("/api/remove", {"key": self.view["key"], "revision": 1})
        self.assertEqual(result, {"runs": []})
        with self.assertRaises(wb.SessionError):
            self.session.dispatch("/api/select", {"key": self.view["key"]})
        created = self.session.dispatch("/api/create", {"run_id": "fictional-b", "model_label": "fictional"})
        self.assertNotEqual(created["key"], self.view["key"])

    def test_comparison_uses_saved_runs_and_authoritative_export_bytes(self):
        left = self.session.dispatch("/api/import", {"document": json.dumps(supplied_run(self.data))})
        right = self.session.dispatch("/api/import", {"document": json.dumps(changed_run(self.data))})
        request = {"left_key": left["key"], "left_revision": 1, "right_key": right["key"], "right_revision": 1, "mode": "preview"}
        report = self.session.dispatch("/api/compare", request)
        self.assertEqual(report["aggregate"]["paired_quality"]["factual"]["regressed"], 1)
        self.assertEqual(report["aggregate"]["paired_quality"]["citation"]["improved"], 1)
        exported = self.session.dispatch("/api/compare", {**request, "mode": "export"})
        self.assertEqual(ev.decode_json(exported, "test comparison"), report)
        with self.assertRaises(wb.SessionError):
            self.session.dispatch("/api/compare", {**request, "mode": "fictional-private-marker"})

    def test_session_has_no_path_or_url_operations(self):
        for route in ("/api/read", "/api/write", "/api/fetch", "/../private-input/run.json"):
            with self.assertRaises(wb.SessionError) as error:
                self.session.dispatch(route, {})
            self.assertEqual(error.exception.status, 404)
        with self.assertRaises(ev.EvaluationError):
            self.session.dispatch("/api/import", {"path": "fictional-file.json"})


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.server = wb.create_server(dataset())
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)

    def headers(self):
        return [("Host", self.server.host_header), ("Origin", self.server.origin), ("X-Workbench-Capability", self.server.capability), ("Content-Type", "application/json"), ("Content-Length", "2")]

    def request(self, method="POST", path="/api/runs", body=b"{}", headers=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=2)
        try:
            connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for key, value in (self.headers() if headers is None else headers):
                connection.putheader(key, value)
            connection.endheaders(body)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_binds_numeric_loopback_and_capability_changes_per_server(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        other = wb.create_server(dataset())
        try:
            self.assertFalse(self.server.capability == other.capability)
        finally:
            other.server_close()
        self.assertEqual(self.request()[0], 200)

    def test_page_has_fixed_hash_csp_no_cache_and_no_cookie(self):
        status, headers, body = self.request("GET", "/", b"", [("Host", self.server.host_header)])
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertNotIn("Set-Cookie", headers)
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertNotIn("Server", headers)
        text = body.decode("utf-8")
        self.assertTrue(self.server.capability in text, "The local bootstrap must contain its capability.")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        for tag in ("script", "style"):
            content = re.search("<" + tag + ">(.*?)</" + tag + ">", text, re.S).group(1)
            digest = base64.b64encode(hashlib.sha256(content.encode()).digest()).decode()
            self.assertIn("'sha256-" + digest + "'", headers["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", headers["Content-Security-Policy"])
        self.assertNotIn("unsafe-eval", headers["Content-Security-Policy"])

    def test_foreign_missing_and_duplicate_boundary_headers_fail_closed(self):
        for name, replacements in (("Host", [[], ["attacker.invalid"], [self.server.host_header] * 2]), ("Origin", [[], ["null"], ["https://attacker.invalid"], [self.server.origin] * 2]), ("X-Workbench-Capability", [[], ["invalid"], [self.server.capability] * 2, [chr(233)]])):
            for values in replacements:
                headers = [(key, value) for key, value in self.headers() if key != name] + [(name, value) for value in values]
                with self.subTest(header=name, count=len(values)):
                    status, _, body = self.request(headers=headers)
                    self.assertEqual(status, 403)
                    self.assertFalse(self.server.capability.encode() in body)
        headers = self.headers() + [("Sec-Fetch-Site", "cross-site")]
        self.assertEqual(self.request(headers=headers)[0], 403)

    def test_get_rejects_foreign_origin_and_dns_aliases(self):
        for headers in ([('Host', 'localhost:' + str(self.server.server_address[1]))], [("Host", self.server.host_header), ("Origin", "https://attacker.invalid")], [("Host", self.server.host_header), ("Sec-Fetch-Site", "cross-site")]):
            self.assertEqual(self.request("GET", "/", b"", headers)[0], 403)

    def test_invalid_lengths_and_transfer_framing_are_rejected(self):
        base = [(key, value) for key, value in self.headers() if key != "Content-Length"]
        for values in ([], ["2", "2"], ["-1"], ["2.0"], ["+2"], ["0"], ["9999999999"]):
            with self.subTest(count=len(values)):
                status = self.request(headers=base + [("Content-Length", value) for value in values])[0]
                self.assertIn(status, (411, 413))
        for header in (("Transfer-Encoding", "chunked"), ("Expect", "100-continue")):
            self.assertEqual(self.request(headers=self.headers() + [header])[0], 400)
        with patch.object(wb, "MAX_REQUEST_BYTES", 1):
            self.assertEqual(self.request()[0], 413)

    def test_content_type_and_strict_json_errors_never_echo_payload(self):
        base = [(key, value) for key, value in self.headers() if key != "Content-Type"]
        for values in ([], ["text/plain"], ["application/json", "application/json"]):
            self.assertEqual(self.request(headers=base + [("Content-Type", value) for value in values])[0], 415)
        for body in (b'{"fictional-private-marker":1}', b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e400}', b'\xff'):
            headers = [(key, str(len(body)) if key == "Content-Length" else value) for key, value in self.headers()]
            status, _, reply = self.request(body=body, headers=headers)
            self.assertEqual(status, 400)
            self.assertFalse(b"fictional-private-marker" in reply)
            self.assertFalse(self.server.capability.encode() in reply)

    def test_traversal_queries_and_get_mutation_are_unavailable(self):
        for path in ("/api/create", "/../private-input/run.json", "/%2e%2e/README.md", "/?fictional-private-marker", "//"):
            with self.subTest(path=path):
                status, _, body = self.request("GET", path, b"", [("Host", self.server.host_header)])
                self.assertNotEqual(status, 200)
                self.assertFalse(b"fictional-private-marker" in body)
        self.assertEqual(self.server.session.dispatch("/api/runs", {}), {"runs": []})

    def test_unsupported_methods_and_parse_errors_are_fixed_and_unlogged(self):
        with contextlib.redirect_stderr(io.StringIO()) as err, contextlib.redirect_stdout(io.StringIO()) as out:
            for method in ("PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT", "FICTIONAL-PRIVATE-MARKER"):
                status, headers, body = self.request(method)
                self.assertIn(status, (405, 501))
                self.assertFalse(b"FICTIONAL-PRIVATE-MARKER" in body)
                self.assertNotIn("Access-Control-Allow-Origin", headers)
            with socket.create_connection(self.server.server_address, timeout=2) as stream:
                stream.sendall(b"FICTIONAL-PRIVATE-MARKER\r\n\r\n")
                reply = stream.recv(4096)
                self.assertFalse(b"FICTIONAL-PRIVATE-MARKER" in reply)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(err.getvalue(), "")

    def test_truncated_body_returns_fixed_error_and_closes(self):
        with socket.create_connection(self.server.server_address, timeout=2) as stream:
            request = "POST /api/runs HTTP/1.1\r\n" + "\r\n".join(key + ": " + ("9" if key == "Content-Length" else value) for key, value in self.headers()) + "\r\n\r\n{}"
            stream.sendall(request.encode("ascii")); stream.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = stream.recv(4096)
                if not chunk: break
                chunks.append(chunk)
        response = b"".join(chunks)
        self.assertTrue(b" 400 " in response)
        self.assertFalse(self.server.capability.encode() in response)
        self.assertIn(b"Connection: close", response)

    def test_authenticated_http_create_export_and_revision_conflict(self):
        def post(route, payload):
            body = ev.canonical(payload)
            headers = [(key, str(len(body)) if key == "Content-Length" else value) for key, value in self.headers()]
            return self.request(path=route, body=body, headers=headers)
        status, _, body = post("/api/create", {"run_id": "fictional-a", "model_label": "fictional-test"})
        self.assertEqual(status, 200)
        view = json.loads(body)
        status, headers, data = post("/api/export", {"key": view["key"], "revision": 1, "kind": "scored"})
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Disposition"].startswith("attachment;"))
        ev.verify_scored(dataset(), json.loads(data))
        status, _, _ = post("/api/save", {"key": view["key"], "revision": 1, "metadata": {}, "records": []})
        self.assertEqual(status, 200)
        status, _, _ = post("/api/export", {"key": view["key"], "revision": 1, "kind": "run"})
        self.assertEqual(status, 409)


if __name__ == "__main__":
    unittest.main()
