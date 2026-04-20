#!/usr/bin/env python3
"""Small fake Elasticsearch API used by the rolling restart contract test."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
import threading


class State:
    def __init__(self, nodes, log_path, persistent_settings, fail_nodes_on):
        self.nodes = nodes
        self.log_path = log_path
        self.persistent_settings = persistent_settings
        self.fail_nodes_on = fail_nodes_on
        self.lock = threading.Lock()

    def log(self, port, method, path, body):
        with self.lock:
            with open(self.log_path, "a", encoding="utf-8") as log_file:
                log_file.write(
                    json.dumps(
                        {
                            "port": port,
                            "method": method,
                            "path": path,
                            "body": body,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )


def handler(state):
    class FakeElasticsearchHandler(BaseHTTPRequestHandler):
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

        def do_GET(self):
            state.log(self.server.server_port, "GET", self.path, "")
            if self.path.startswith("/_cluster/settings"):
                with state.lock:
                    persistent_settings = dict(state.persistent_settings)
                self._send_json({"persistent": persistent_settings})
                return
            if self.path.startswith("/_cluster/health"):
                self._send_json(
                    {
                        "status": "green",
                        "relocating_shards": 0,
                        "initializing_shards": 0,
                    }
                )
                return
            if self.path.startswith("/_cat/nodes"):
                if self.server.server_port in state.fail_nodes_on:
                    self._send_json({"error": "simulated rejoin failure"}, status=503)
                    return
                body = ("\n".join(state.nodes) + "\n").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._send_json({"error": "not found"}, status=404)

        def do_POST(self):
            body = self._read_body()
            state.log(self.server.server_port, "POST", self.path, body)
            if self.path.startswith("/_flush"):
                self._send_json({"_shards": {"failed": 0}})
                return
            self._send_json({"error": "not found"}, status=404)

        def do_PUT(self):
            body = self._read_body()
            state.log(self.server.server_port, "PUT", self.path, body)
            if self.path.startswith("/_cluster/settings"):
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError:
                    payload = {}
                with state.lock:
                    for key, value in payload.get("persistent", {}).items():
                        if value is None:
                            state.persistent_settings.pop(key, None)
                        else:
                            state.persistent_settings[key] = str(value)
                self._send_json({"acknowledged": True})
                return
            self._send_json({"error": "not found"}, status=404)

        def log_message(self, _format, *args):
            return

    return FakeElasticsearchHandler


def serve(port, state):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler(state))
    httpd.serve_forever()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ports", required=True)
    parser.add_argument("--nodes", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--persistent-settings", default="{}")
    parser.add_argument(
        "--fail-nodes-on",
        default="",
        help="Comma-separated ports whose /_cat/nodes endpoint returns 503",
    )
    args = parser.parse_args()

    ports = [int(port) for port in args.ports.split(",")]
    fail_nodes_on = {
        int(port) for port in args.fail_nodes_on.split(",") if port.strip()
    }
    state = State(
        args.nodes.split(","),
        args.log,
        json.loads(args.persistent_settings),
        fail_nodes_on,
    )

    for port in ports:
        thread = threading.Thread(target=serve, args=(port, state), daemon=True)
        thread.start()

    threading.Event().wait()


if __name__ == "__main__":
    main()
