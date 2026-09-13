"""Regression checks for the Kibana extras stopped-service verification branch."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "molecule" / "kibana_extras" / "verify.yml"


def _stopped_probe_task():
    document = yaml.safe_load(VERIFY.read_text()) or []

    def visit(node):
        if isinstance(node, dict):
            if node.get("name") == "Run the shared readiness probe against a stopped Kibana":
                return node
            for value in node.values():
                found = visit(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = visit(item)
                if found is not None:
                    return found
        return None

    task = visit(document)
    if task is None:
        raise AssertionError("stopped Kibana readiness branch is missing")
    return task


class TestKibanaExtrasVerify(unittest.TestCase):
    def test_expected_failure_is_scoped_for_multi_host_ansible_runs(self):
        task = _stopped_probe_task()

        self.assertIs(task.get("any_errors_fatal"), False)
        included = task["block"][0]["ansible.builtin.include_tasks"]
        self.assertIn("wait_for_http_service.yml", included["file"])

        rescue = task["rescue"]
        assertions = [
            expression
            for item in rescue
            for expression in item.get("ansible.builtin.assert", {}).get("that", [])
        ]
        self.assertTrue(
            any(
                "service died while waiting for HTTP readiness" in expression
                for expression in assertions
            )
        )
