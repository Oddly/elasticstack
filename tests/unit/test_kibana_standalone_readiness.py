"""Contract checks for Kibana standalone preboot readiness."""

from ast import literal_eval
from pathlib import Path
import unittest

from jinja2 import Environment
import yaml


ROOT = Path(__file__).resolve().parents[2]
CALLERS = (
    ROOT / "roles" / "kibana" / "tasks" / "main.yml",
    ROOT / "roles" / "kibana" / "tasks" / "restart_and_verify_kibana.yml",
)
EXPECTED_STANDALONE_STATUSES = [200, 401, 503]
EXPECTED_FULL_STACK_STATUSES = [200, 401]


def _ansible_bool(value):
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off", "none", "null"}
    return bool(value)


def _wait_vars(path):
    document = yaml.safe_load(path.read_text()) or []
    matches = []

    def visit(node):
        if isinstance(node, dict):
            include = node.get("ansible.builtin.include_tasks")
            include_file = include.get("file", "") if isinstance(include, dict) else ""
            if "wait_for_http_service.yml" in include_file:
                matches.append(node.get("vars", {}))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(document)
    return matches


def _render_statuses(expression, full_stack):
    environment = Environment()
    environment.filters["bool"] = _ansible_bool
    rendered = environment.from_string(expression).render(
        elasticstack_full_stack=full_stack
    )
    return literal_eval(rendered)


class TestKibanaStandaloneReadiness(unittest.TestCase):
    def test_both_kibana_readiness_callers_scope_preboot_503_to_standalone(self):
        for path in CALLERS:
            with self.subTest(path=path):
                matches = _wait_vars(path)
                self.assertEqual(len(matches), 1)
                expression = matches[0]["_wait_success_statuses"]
                self.assertEqual(
                    _render_statuses(expression, full_stack=False),
                    EXPECTED_STANDALONE_STATUSES,
                )
                self.assertEqual(
                    _render_statuses(expression, full_stack=True),
                    EXPECTED_FULL_STACK_STATUSES,
                )

    def test_standalone_molecule_contract_accepts_kibana_9_preboot(self):
        converge = yaml.safe_load(
            (ROOT / "molecule" / "kibana_default" / "converge.yml").read_text()
        )
        verify = yaml.safe_load(
            (ROOT / "molecule" / "kibana_default" / "verify.yml").read_text()
        )

        self.assertFalse(converge[0]["vars"]["elasticstack_full_stack"])

        uri_tasks = []

        def collect_uri_tasks(node):
            if isinstance(node, dict):
                if "ansible.builtin.uri" in node:
                    uri_tasks.append(node)
                for value in node.values():
                    collect_uri_tasks(value)
            elif isinstance(node, list):
                for item in node:
                    collect_uri_tasks(item)

        collect_uri_tasks(verify)
        status_tasks = [
            task
            for task in uri_tasks
            if task["ansible.builtin.uri"].get("url", "").endswith("/api/status")
        ]
        self.assertEqual(len(status_tasks), 1)
        self.assertEqual(
            status_tasks[0]["ansible.builtin.uri"]["status_code"],
            EXPECTED_STANDALONE_STATUSES,
        )
        self.assertIn("in [200, 401, 503]", status_tasks[0]["until"])


if __name__ == "__main__":
    unittest.main()
