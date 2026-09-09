"""Deterministic tests for the EOL monitor's date classification."""

from datetime import date
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from check_eol import classify_eol, write_github_env  # noqa: E402


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
