#!/usr/bin/env python3
"""Small stateful Elasticsearch security API fake for contract tests."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse
import argparse
import json
import threading


class State:
    def __init__(self, log_path):
        self.log_path = log_path
        self.users = {}
        self.passwords = {}
        self.roles = {}
        self.role_mappings = {}
        self.lock = threading.Lock()

    @staticmethod
    def _redacted_body(body):
        if not body:
            return ""
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return body
        if not isinstance(payload, dict):
            return payload
        redacted = dict(payload)
        for key in ("password", "password_hash"):
            if key in redacted:
                redacted.pop(key)
                redacted["password_set"] = True
        return redacted

    def log(self, method, path, body):
        with self.lock:
            with open(self.log_path, "a", encoding="utf-8") as log_file:
                log_file.write(
                    json.dumps(
                        {
                            "body": self._redacted_body(body),
                            "method": method,
                            "path": path,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )


def handler(state):
    class FakeElasticsearchSecurityHandler(BaseHTTPRequestHandler):
        def _send_json(self, payload, status=200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self):
            length = int(self.headers.get("Content-Length", "0"))
            if length == 0:
                return ""
            return self.rfile.read(length).decode("utf-8")

        def _resource(self):
            path = urlparse(self.path).path
            parts = [unquote(part) for part in path.split("/") if part]
            if len(parts) < 3 or parts[0] != "_security":
                return None, None
            resource = parts[1]
            name = parts[2]
            suffix = parts[3:] if len(parts) > 3 else []
            return (resource, name), suffix

        def do_GET(self):
            state.log("GET", self.path, "")
            path = urlparse(self.path).path
            if path == "/" or path == "":
                self._send_json({"cluster_name": "fake-security"})
                return

            resource_info, suffix = self._resource()
            if resource_info is None or suffix:
                self._send_json({"error": "not found"}, status=404)
                return
            resource, name = resource_info
            with state.lock:
                if resource == "user":
                    value = state.users.get(name)
                    if value is not None:
                        self._send_json({name: dict(value)})
                        return
                elif resource == "role":
                    value = state.roles.get(name)
                    if value is not None:
                        self._send_json({name: dict(value)})
                        return
                elif resource == "role_mapping":
                    value = state.role_mappings.get(name)
                    if value is not None:
                        self._send_json({name: dict(value)})
                        return
            self._send_json({"error": "not found"}, status=404)

        def _put_user(self, name, body, password_endpoint=False):
            try:
                payload = json.loads(body) if body else {}
            except json.JSONDecodeError:
                self._send_json({"error": "invalid json"}, status=400)
                return
            with state.lock:
                if password_endpoint:
                    state.passwords[name] = payload.get("password")
                else:
                    public = {
                        key: value
                        for key, value in payload.items()
                        if key not in ("password", "password_hash")
                    }
                    state.users[name] = public
                    if "password" in payload:
                        state.passwords[name] = payload["password"]
                    if "password_hash" in payload:
                        state.passwords[name] = payload["password_hash"]
            self._send_json({"created": True})

        def _put_resource(self, resource, name, body):
            try:
                payload = json.loads(body) if body else {}
            except json.JSONDecodeError:
                self._send_json({"error": "invalid json"}, status=400)
                return
            with state.lock:
                if resource == "role":
                    state.roles[name] = payload
                else:
                    state.role_mappings[name] = payload
            self._send_json({"created": True})

        def _write(self, method):
            body = self._read_body()
            state.log(method, self.path, body)
            resource_info, suffix = self._resource()
            if resource_info is None or len(suffix) > 1:
                self._send_json({"error": "not found"}, status=404)
                return
            resource, name = resource_info
            if resource == "user":
                self._put_user(name, body, suffix == ["_password"])
                return
            if resource in ("role", "role_mapping") and not suffix:
                self._put_resource(resource, name, body)
                return
            self._send_json({"error": "not found"}, status=404)

        def do_PUT(self):
            self._write("PUT")

        def do_POST(self):
            self._write("POST")

        def log_message(self, _format, *args):
            return

    return FakeElasticsearchSecurityHandler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--log", required=True)
    args = parser.parse_args()

    state = State(args.log)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(state))
    server.serve_forever()


if __name__ == "__main__":
    main()
