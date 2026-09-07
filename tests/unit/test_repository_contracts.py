"""Executable regression checks for repository-level hardening changes."""

from pathlib import Path
import re
import stat
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
ACTION_SHA = re.compile(r"^[0-9a-f]{40}$")
COLLECTION_CONSTRAINTS = {
    "community.general": ">=12.3.0,<13.0.0",
    "community.crypto": ">=3.1.1,<4.0.0",
    "ansible.posix": ">=2.1.0,<3.0.0",
}


def _run(command, cwd):
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


class TestRepositoryContracts(unittest.TestCase):
    def test_external_actions_are_commit_pinned(self):
        action_files = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
        action_files += sorted((ROOT / ".github" / "actions").rglob("*.yml"))
        references = []

        for path in action_files:
            for line_number, line in enumerate(path.read_text().splitlines(), 1):
                match = re.match(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", line)
                if not match or match.group(1).startswith("./"):
                    continue
                references.append((path, line_number, line, match.group(1)))

        self.assertTrue(references)
        for path, line_number, line, reference in references:
            self.assertIn("@", reference, f"{path}:{line_number} is not pinned")
            ref = reference.rsplit("@", 1)[1]
            self.assertRegex(
                ref,
                ACTION_SHA,
                f"{path}:{line_number} must use a full commit SHA: {line}",
            )
            self.assertIn(
                "#",
                line,
                f"{path}:{line_number} should retain the upstream version comment",
            )

    def test_container_images_are_digest_pinned(self):
        images = []
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
            for line in path.read_text().splitlines():
                if "docker run" in line or "checkmarx/kics:" in line:
                    images.extend(re.findall(r"([\w.-]+/[\w.-]+:[^\s\\]+)", line))

        self.assertTrue(images)
        for image in images:
            self.assertRegex(
                image,
                r"@sha256:[0-9a-f]{64}$",
                f"Container image is not digest pinned: {image}",
            )

    def test_dependency_constraints_are_reproducible_and_compatible(self):
        requirements = (ROOT / "requirements-test.txt").read_text()
        for requirement in (
            "ansible-core>=2.20,<2.21",
            "ansible-lint>=26.8,<27",
            "molecule>=25.4,<26",
            "pytest>=8.3,<9",
            "passlib==1.7.4",
        ):
            self.assertRegex(requirements, rf"(?m)^{re.escape(requirement)}$")

        docs_requirements = (ROOT / "requirements-docs.txt").read_text()
        for requirement in (
            "mkdocs==1.6.1",
            "mkdocs-material==9.7.7",
            "pymdown-extensions==11.0.2",
        ):
            self.assertRegex(docs_requirements, rf"(?m)^{re.escape(requirement)}$")

        galaxy = yaml.safe_load((ROOT / "galaxy.yml").read_text())
        self.assertEqual(galaxy["dependencies"], COLLECTION_CONSTRAINTS)

        for path in sorted((ROOT / "molecule").glob("*/requirements.yml")):
            # This is a local, untracked scenario used while developing the
            # shared-passphrase test; check-ci-coverage deliberately ignores
            # scenarios that are not in Git.
            if path.parent.name == "elasticstack_common_passphrase":
                continue
            document = yaml.safe_load(path.read_text()) or {}
            for collection in document.get("collections", []):
                self.assertEqual(
                    collection.get("version"),
                    COLLECTION_CONSTRAINTS[collection["name"]],
                    f"{path} leaves {collection['name']} unresolved",
                )

    def test_supported_ansible_metadata_is_consistent(self):
        runtime = yaml.safe_load((ROOT / "meta" / "runtime.yml").read_text())
        self.assertEqual(runtime["requires_ansible"], ">=2.20.0")

        for path in sorted((ROOT / "roles").glob("*/meta/main.yml")):
            metadata = yaml.safe_load(path.read_text())
            self.assertEqual(metadata["galaxy_info"]["min_ansible_version"], "2.20")
            debian = next(
                platform
                for platform in metadata["galaxy_info"]["platforms"]
                if platform["name"] == "Debian"
            )
            self.assertNotIn("bookworm", debian["versions"])
            self.assertIn("trixie", debian["versions"])

    def test_security_defaults_and_secret_annotations(self):
        elasticsearch = yaml.safe_load(
            (ROOT / "roles" / "elasticsearch" / "defaults" / "main.yml").read_text()
        )
        self.assertEqual(elasticsearch["elasticsearch_elastic_password"], "")
        self.assertEqual(elasticsearch["elasticsearch_security_roles"], [])
        self.assertEqual(elasticsearch["elasticsearch_users"], [])
        self.assertEqual(elasticsearch["elasticsearch_builtin_passwords"], {})
        self.assertEqual(elasticsearch["elasticsearch_role_mappings"], [])

        logstash = yaml.safe_load(
            (ROOT / "roles" / "logstash" / "defaults" / "main.yml").read_text()
        )
        self.assertEqual(logstash["logstash_user_password"], "")

        kibana_specs = yaml.safe_load(
            (ROOT / "roles" / "kibana" / "meta" / "argument_specs.yml").read_text()
        )
        self.assertEqual(
            kibana_specs["argument_specs"]["main"]["options"]["kibana_system_password"]["default"],
            "",
        )

        elasticsearch_specs = yaml.safe_load(
            (ROOT / "roles" / "elasticsearch" / "meta" / "argument_specs.yml").read_text()
        )
        options = elasticsearch_specs["argument_specs"]["main"]["options"]
        self.assertTrue(options["elasticsearch_users"]["no_log"])
        self.assertTrue(options["elasticsearch_builtin_passwords"]["no_log"])

    def test_markdownlint_scope_enforces_the_new_rules(self):
        config = yaml.safe_load((ROOT / ".markdownlint-cli2.yaml").read_text())
        self.assertEqual(config["config"]["MD040"], True)
        self.assertEqual(config["config"]["MD046"]["style"], "fenced")
        self.assertCountEqual(
            config["globs"],
            [
                "*.md",
                "ci/**/*.md",
                "docs/**/*.md",
                "plugins/**/*.md",
                "roles/**/README.md",
            ],
        )

    def test_ci_coverage_script_handles_untracked_and_quoted_scenarios(self):
        with tempfile.TemporaryDirectory(prefix="elasticstack-ci-coverage-") as directory:
            repo = Path(directory)
            workflows = repo / ".github" / "workflows"
            workflows.mkdir(parents=True)
            (repo / "molecule" / "scenario with spaces").mkdir(parents=True)
            (repo / "molecule" / "local-only").mkdir(parents=True)
            (repo / "scripts").mkdir()

            script = repo / "scripts" / "check-ci-coverage.sh"
            script.write_text((ROOT / "scripts" / "check-ci-coverage.sh").read_text())
            script.chmod(script.stat().st_mode | stat.S_IXUSR)
            (workflows / "test_unit.yml").write_text("scenario with spaces\n")
            (repo / "molecule" / "scenario with spaces" / "molecule.yml").write_text(
                "---\n"
            )
            (repo / "molecule" / "scenario with spaces" / "verify.yml").write_text(
                "---\n"
            )
            (repo / "molecule" / "local-only" / "molecule.yml").write_text("---\n")

            _run(["git", "init", "-q"], repo)
            _run(["git", "add", ".github", "molecule/scenario with spaces", "scripts"], repo)
            result = subprocess.run(
                [str(script)],
                cwd=repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("OK: All scenarios are referenced", result.stdout)
            self.assertIn("OK: All scenarios have verify.yml", result.stdout)

    def test_ci_coverage_script_reports_tracked_failures(self):
        with tempfile.TemporaryDirectory(prefix="elasticstack-ci-coverage-") as directory:
            repo = Path(directory)
            workflows = repo / ".github" / "workflows"
            workflows.mkdir(parents=True)
            (repo / "molecule" / "orphan").mkdir(parents=True)
            (repo / "molecule" / "missing-verify").mkdir(parents=True)
            (repo / "scripts").mkdir()

            script = repo / "scripts" / "check-ci-coverage.sh"
            script.write_text((ROOT / "scripts" / "check-ci-coverage.sh").read_text())
            script.chmod(script.stat().st_mode | stat.S_IXUSR)
            (repo / "molecule" / "orphan" / "molecule.yml").write_text("---\n")
            (repo / "molecule" / "missing-verify" / "molecule.yml").write_text("---\n")
            (workflows / "test_unit.yml").write_text("missing-verify\n")

            _run(["git", "init", "-q"], repo)
            _run(["git", "add", ".github", "molecule", "scripts"], repo)
            result = subprocess.run(
                [str(script)],
                cwd=repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("molecule/orphan is not referenced", result.stdout)
            self.assertIn("molecule/orphan has no verify.yml", result.stdout)
            self.assertIn("molecule/missing-verify has no verify.yml", result.stdout)


if __name__ == "__main__":
    unittest.main()
