"""Deterministic tests for the EOL monitor."""

from contextlib import redirect_stdout
from datetime import date
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import check_eol  # noqa: E402
from check_eol import DEPENDENCIES, classify_eol, write_github_env  # noqa: E402


class TestEolClassification(unittest.TestCase):
    TODAY = date(2026, 9, 9)

    def test_boolean_eol_values(self):
        self.assertEqual(classify_eol("Python 3.11", False, self.TODAY)["level"], "supported")
        self.assertEqual(classify_eol("Python 3.11", "false", self.TODAY)["level"], "supported")
        self.assertEqual(classify_eol("Python 3.10", True, self.TODAY)["level"], "eol")
        self.assertEqual(classify_eol("Python 3.10", "true", self.TODAY)["level"], "eol")

    def test_date_boundaries_are_classified(self):
        expired = classify_eol("Ansible 2.19", "2026-09-08", self.TODAY)
        warning = classify_eol("Ansible 2.20", "2026-12-01", self.TODAY)
        supported = classify_eol("Ansible 2.21", "2027-03-08", self.TODAY)

        self.assertEqual(expired["level"], "eol")
        self.assertIn("since 2026-09-08", expired["message"])
        self.assertEqual(warning["level"], "warning")
        self.assertIn("83 days", warning["message"])
        self.assertEqual(supported["level"], "supported")
        self.assertIn("180 days", supported["message"])

    def test_malformed_values_are_reported_as_issues(self):
        result = classify_eol("unknown dependency", "not-a-date", self.TODAY)
        self.assertEqual(result["level"], "unknown")
        self.assertIn("unknown dependency", result["message"])
        self.assertIsNotNone(result["issue"])

    def test_github_environment_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "github-env"
            write_github_env(path, ["- **Python 3.10** is EOL"])
            self.assertEqual(
                path.read_text(),
                "ISSUES<<EOF\n- **Python 3.10** is EOL\nEOF\nHAS_ISSUES=true\n",
            )

            write_github_env(path, [])
            self.assertTrue(path.read_text().endswith("HAS_ISSUES=false\n"))


class TestEolCommand(unittest.TestCase):
    TODAY = "2026-09-09"

    def test_main_fetches_every_dependency_and_writes_findings(self):
        api = "https://example.test/api"
        values = {(product, version): False for product, version, _ in DEPENDENCIES}
        values[DEPENDENCIES[0][:2]] = "2026-09-08"
        values[DEPENDENCIES[1][:2]] = "2026-12-01"
        calls = []

        def fetch(api_url, product, version):
            calls.append((api_url, product, version))
            return {"eol": values[(product, version)]}

        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / "github-env"
            output = io.StringIO()
            with mock.patch.object(check_eol, "_fetch_eol", side_effect=fetch):
                with redirect_stdout(output):
                    result = check_eol.main(
                        [
                            "--api",
                            api,
                            "--today",
                            self.TODAY,
                            "--github-env",
                            str(env_path),
                        ]
                    )

            self.assertEqual(result, 0)
            self.assertEqual(
                calls,
                [(api, product, version) for product, version, _ in DEPENDENCIES],
            )
            self.assertIn("ALERT: Rocky Linux 9 is EOL", output.getvalue())
            self.assertIn("WARNING: Rocky Linux 10 reaches EOL", output.getvalue())
            self.assertIn("::warning::EOL dependencies detected", output.getvalue())
            self.assertIn("HAS_ISSUES=true", env_path.read_text())
            self.assertIn("**Rocky Linux 9** is EOL", env_path.read_text())

    def test_main_continues_after_fetch_errors_and_bad_payloads(self):
        errors = (
            HTTPError("https://example.test", 503, "unavailable", {}, None),
            URLError("offline"),
            TimeoutError("timed out"),
            OSError("broken connection"),
            json.JSONDecodeError("bad JSON", "payload", 0),
        )
        calls = []

        def fetch(_api, product, version):
            calls.append((product, version))
            if len(calls) <= len(errors):
                raise errors[len(calls) - 1]
            if len(calls) == len(errors) + 1:
                return []
            return {"eol": False}

        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / "github-env"
            output = io.StringIO()
            with mock.patch.object(check_eol, "_fetch_eol", side_effect=fetch):
                with redirect_stdout(output):
                    result = check_eol.main(
                        ["--today", self.TODAY, "--github-env", str(env_path)]
                    )

            self.assertEqual(result, 0)
            self.assertEqual(
                calls,
                [(product, version) for product, version, _ in DEPENDENCIES],
            )
            self.assertEqual(output.getvalue().count("Could not fetch EOL data"), 5)
            self.assertIn("Could not parse EOL data", output.getvalue())
            self.assertIn("HAS_ISSUES=true", env_path.read_text())
