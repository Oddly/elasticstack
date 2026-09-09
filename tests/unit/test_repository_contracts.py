"""Executable regression checks for repository-level hardening changes."""

from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from gen_argspecs import (  # noqa: E402
    build_argument_specs,
    merge_main_options,
    parse_defaults,
)

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


def _assertion_text(path):
    """Return the expressions under every Ansible assert task's ``that`` key."""
    document = yaml.safe_load(path.read_text()) or {}
    expressions = []

    def visit(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "that":
                    values = value if isinstance(value, list) else [value]
                    expressions.extend(str(item) for item in values)
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(document)
    return "\n".join(expressions)


class TestRepositoryContracts(unittest.TestCase):
    def test_argspec_generator_refreshes_defaults_and_preserves_metadata(self):
        entries = [
            {
                "name": "beats_fields",
                "description": "New description",
                "default": [],
                "has_default": True,
            }
        ]
        generated = build_argument_specs("beats", entries, "", "")["argument_specs"]["main"]
        merged = merge_main_options(
            {
                "options": {
                    "beats_fields": {
                        "description": "Old description",
                        "type": "list",
                        "no_log": True,
                    }
                }
            },
            generated,
            entries,
        )

        self.assertEqual(merged["options"]["beats_fields"]["default"], [])
        self.assertEqual(
            merged["options"]["beats_fields"]["description"], "New description"
        )
        self.assertTrue(merged["options"]["beats_fields"]["no_log"])

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
            "molecule>=26.8.0,<27",
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
            document = yaml.safe_load(path.read_text()) or {}
            actual = {
                collection["name"]: collection.get("version")
                for collection in document.get("collections", [])
            }
            self.assertEqual(
                actual,
                COLLECTION_CONSTRAINTS,
                f"{path} must declare every collection dependency with its constraint",
            )

    def test_incus_molecule_scenarios_have_lifecycle_playbooks(self):
        excluded = {"default", "shared", "cert_info_module"}
        scenarios = sorted(
            path.parent
            for path in (ROOT / "molecule").glob("*/molecule.yml")
            if path.parent.name not in excluded
        )

        self.assertTrue(scenarios)
        for scenario in scenarios:
            for playbook in ("create.yml", "destroy.yml"):
                path = scenario / playbook
                self.assertTrue(
                    path.is_file(),
                    f"{scenario.name} must provide an executable {playbook}",
                )
            molecule = yaml.safe_load((scenario / "molecule.yml").read_text()) or {}
            if len(molecule.get("platforms", [])) > 1:
                self.assertTrue(
                    (scenario / "prepare.yml").is_file(),
                    f"{scenario.name} must prepare name resolution for multiple hosts",
                )

    def test_ci_uses_python_312_for_ansible_220_dependencies(self):
        workflows = (
            ROOT / ".github" / "workflows" / "test_linting.yml",
            ROOT / ".github" / "workflows" / "molecule.yml",
            ROOT / ".github" / "workflows" / "test_full_stack.yml",
            ROOT / ".github" / "workflows" / "test_elasticsearch_upgrade.yml",
            ROOT / ".github" / "workflows" / "test_plugins.yml",
        )
        for path in workflows:
            source = path.read_text()
            self.assertIn(
                "command -v python3.12",
                source,
                f"{path} must select Python 3.12 for Ansible 2.20",
            )
            self.assertIn(
                'uv venv "$RUNNER_TEMP/venv"',
                source,
                f"{path} must install into an isolated Python 3.12 environment",
            )
            self.assertIn(
                'echo "$RUNNER_TEMP/venv/bin" >> "$GITHUB_PATH"',
                source,
                f"{path} must put the Python 3.12 executables first on PATH",
            )

    def test_molecule_prepare_files_use_shared_name_resolution(self):
        common = (ROOT / "molecule" / "shared" / "prepare_common.yml").read_text()
        self.assertIn("Populate /etc/hosts with molecule instances", common)
        self.assertIn("hostvars[item]['ansible_host']", common)

        prepare_files = sorted((ROOT / "molecule").glob("*/prepare.yml"))
        self.assertTrue(prepare_files)
        for path in prepare_files:
            source = path.read_text()
            self.assertIn(
                "include_tasks: ../shared/prepare_common.yml",
                source,
                f"{path} must include the shared prepare tasks",
            )
            self.assertNotIn(
                "Populate /etc/hosts with molecule instances",
                source,
                f"{path} must use shared name resolution",
            )

        for path in (
            ROOT / ".github" / "workflows" / "test_full_stack.yml",
            ROOT / ".github" / "workflows" / "test_elasticsearch_upgrade.yml",
        ):
            self.assertIn(
                "ansible-playbook --version",
                path.read_text(),
                f"{path} must verify the Ansible executable used by rollout jobs",
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

    def test_service_roles_share_elastic_package_installation(self):
        shared = (
            ROOT
            / "roles"
            / "elasticstack"
            / "tasks"
            / "install_elastic_package.yml"
        ).read_text()
        self.assertEqual(shared.count("ansible.builtin.package:"), 3)
        self.assertIn("state: \"{{ 'latest' if", shared)
        self.assertIn('enablerepo:', shared)
        self.assertEqual(shared.count('notify: "{{ _package_notify | default([]) }}"'), 3)

        for role, package_var, package_base, package_notify in (
            ("elasticsearch", "elasticsearch_package", "elasticsearch", "[]"),
            ("kibana", "kibana_package", "kibana", "- Restart Kibana"),
            ("logstash", "logstash_package", "logstash", "- Restart Logstash"),
        ):
            source = (ROOT / "roles" / role / "tasks" / "main.yml").read_text()
            include_block = re.search(
                rf"(?ms)^- name: Install {package_base.capitalize()} package\n.*?(?=^- name:|\Z)",
                source,
            )
            self.assertIsNotNone(include_block, f"{role} does not include the shared installer")
            include_source = include_block.group(0)
            self.assertIn(
                'ansible.builtin.include_tasks: "{{ role_path }}/../elasticstack/tasks/install_elastic_package.yml"',
                include_source,
            )
            self.assertIn(f'_package_name: "{{{{ {package_var} }}}}"', include_source)
            self.assertIn(f"_package_base_name: {package_base}", include_source)
            self.assertIn(package_notify, include_source)

        elasticsearch = (ROOT / "roles" / "elasticsearch" / "tasks" / "main.yml").read_text()
        self.assertIn("_elasticstack_package_changed", elasticsearch)
        self.assertNotIn("_elasticsearch_install_rpm_full", elasticsearch)

    def test_debian_package_bootstrap_retries_apt_lock_contention(self):
        tasks = yaml.safe_load(
            (ROOT / "roles" / "elasticstack" / "tasks" / "packages.yml").read_text()
        )
        bootstrap = next(
            task
            for task in tasks
            if task.get("name") == "packages | Bootstrap python3-apt for Ansible apt module"
        )
        self.assertEqual(
            bootstrap["ansible.builtin.raw"],
            "apt-get -o DPkg::Lock::Timeout=120 install -y python3-apt",
        )
        self.assertEqual(bootstrap["register"], "_elasticstack_python3_apt_install")
        self.assertEqual(
            bootstrap["until"], "_elasticstack_python3_apt_install is success"
        )
        self.assertEqual(bootstrap["retries"], 3)
        self.assertEqual(bootstrap["delay"], 10)

        apt_update = next(
            task for task in tasks if task.get("name") == "packages | Update apt cache."
        )
        self.assertEqual(apt_update["register"], "_elasticstack_apt_cache_update")
        self.assertEqual(
            apt_update["until"], "_elasticstack_apt_cache_update is success"
        )
        self.assertEqual(apt_update["retries"], 3)
        self.assertEqual(apt_update["delay"], 10)

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

    def test_elasticsearch_security_bootstrap_uses_a_certificate_validated_endpoint(self):
        source = (
            ROOT
            / "roles"
            / "elasticsearch"
            / "tasks"
            / "elasticsearch-security.yml"
        ).read_text()

        # The local password utilities perform their own TLS hostname
        # verification, so they must use the same endpoint that the role
        # configures and the generated node certificate identifies.
        self.assertGreaterEqual(source.count("--url"), 3)
        self.assertIn(
            "hostvars[item].elasticsearch_api_host | default('localhost', true)",
            source,
        )
        self.assertIn("'127.0.0.1'", source)
        self.assertIn(
            "ansible.builtin.copy:\n        dest: \"{{ elasticstack_initial_passwords }}\"",
            source,
        )
        self.assertNotIn(
            "elasticsearch-setup-passwords auto -b >",
            source,
        )

    def test_es8_initial_passwords_are_persisted_only_after_setup_runs(self):
        source = (
            ROOT
            / "roles"
            / "elasticsearch"
            / "tasks"
            / "elasticsearch-security.yml"
        ).read_text()
        persist_block = source[
            source.index("elasticsearch-security | Persist initial passwords (ES 8.x)") :
            source.index("elasticsearch-security | Create initial passwords (ES 9.x)")
        ]

        self.assertIn(
            "_elasticsearch_setup_passwords_result.changed | default(false) | bool",
            persist_block,
        )
        self.assertNotIn(
            "_elasticsearch_setup_passwords_result is not skipped",
            persist_block,
        )

    def test_elasticsearch_container_cache_cleanup_avoids_shell_globs(self):
        source = (
            ROOT
            / "roles"
            / "elasticsearch"
            / "tasks"
            / "elasticsearch-security.yml"
        ).read_text()

        self.assertIn("ansible.builtin.find:\n            paths: /var/cache", source)
        self.assertIn("file_type: any", source)
        self.assertIn("recurse: false", source)
        self.assertIn(
            'ansible.builtin.file:\n            path: "{{ item.path }}"\n            state: absent',
            source,
        )
        self.assertNotIn("rm -rf /var/cache/*", source)

    def test_security_documentation_covers_known_credential_defaults(self):
        source = (ROOT / "docs" / "guide" / "security.md").read_text()
        documented = {
            "elasticstack_ca_pass": "PleaseChangeMe",
            "elasticsearch_bootstrap_pw": "PleaseChangeMe",
            "elasticsearch_tls_key_passphrase": "PleaseChangeMeIndividually",
            "kibana_tls_key_passphrase": "PleaseChangeMe",
            "logstash_tls_key_passphrase": "LogstashChangeMe",
            "beats_tls_key_passphrase": "BeatsChangeMe",
        }
        for variable, value in documented.items():
            self.assertIn(
                f"| `{variable}` | `{value}` |",
                source,
                f"security guide is missing the known default for {variable}",
            )
        for marker in (
            "known strings, not secrets",
            "Ansible Vault",
            "elasticstack_initial_passwords",
            "logstash_writer",
        ):
            self.assertIn(marker, source)

    def test_external_certificate_only_modes_do_not_require_elasticsearch_passwords(self):
        beats = (ROOT / "roles" / "beats" / "tasks" / "beats-security.yml").read_text()
        kibana = (ROOT / "roles" / "kibana" / "tasks" / "kibana-security.yml").read_text()

        beats_block = beats[
            beats.index("- name: beats-security | Fetch Beats password") :
            beats.index("# -- Certificate expiry warning --")
        ]
        kibana_block = kibana[
            kibana.index("- name: kibana-security | Fetch Kibana password") :
            kibana.index("# -- Change kibana_system password if user defined one --")
        ]
        key_block = kibana[
            kibana.index("- name: kibana-security | Block for key generation") :
            kibana.index("- name: kibana-security | Handle auto-generated Kibana certificate distribution")
        ]

        self.assertIn("when: beats_security | bool", beats_block)
        self.assertIn("when: kibana_security | bool", kibana_block)
        self.assertIn("when: kibana_security | bool", key_block)

    def test_kibana_certificate_content_scenario_disables_backend_tls(self):
        source = (ROOT / "molecule" / "kibana_cert_content" / "converge.yml").read_text()
        self.assertIn("elasticsearch_security: false", source)
        self.assertIn("elasticsearch_http_security: false", source)
        self.assertNotIn(
            "set_ci_watermarks.yml",
            source,
            "the unsecured backend cannot use the HTTPS/password-only watermark helper",
        )

    def test_kibana_generated_encryption_keys_use_argv_and_secure_files(self):
        source = (ROOT / "roles" / "kibana" / "tasks" / "kibana-security.yml").read_text()
        self.assertEqual(source.count("- openssl\n          - rand\n"), 2)
        self.assertEqual(source.count("Persist generated"), 2)
        self.assertGreaterEqual(
            source.count('group: elasticsearch\n        mode: "0600"'),
            4,
        )
        self.assertIn("_kibana_generated_encryption_key.stdout", source)
        self.assertIn("_kibana_generated_savedobjects_encryption_key.stdout", source)
        self.assertNotIn("openssl rand -base64 36 >", source)

    def test_kibana_provided_encryption_keys_are_not_overwritten(self):
        source = (ROOT / "roles" / "kibana" / "tasks" / "kibana-security.yml").read_text()
        for marker in (
            "_kibana_generated_encryption_key.changed | default(false) | bool",
            "_kibana_generated_savedobjects_encryption_key.changed | default(false) | bool",
        ):
            self.assertIn(marker, source)
        self.assertNotIn("_kibana_generated_encryption_key.skipped", source)
        self.assertNotIn("_kibana_generated_savedobjects_encryption_key.skipped", source)
        for task_name, next_task_name in (
            ("kibana-security | Generate encryption key", "kibana-security | Persist generated encryption key"),
            (
                "kibana-security | Generate saved objects encryption key",
                "kibana-security | Persist generated saved objects encryption key",
            ),
        ):
            generation_block = source[
                source.index(task_name) : source.index(next_task_name)
            ]
            self.assertNotIn("changed_when: false", generation_block)

    def test_kibana_single_node_discovery_uses_local_api_endpoint(self):
        source = (ROOT / "roles" / "kibana" / "tasks" / "main.yml").read_text()

        # Incus gives a single container hostname a 127.0.1.1 entry, while
        # Elasticsearch's default [_local_, _site_] binding listens on
        # 127.0.0.1 and the container's site address. Use the configured API
        # endpoint when Kibana and Elasticsearch share that one host.
        self.assertIn(
            "hostvars[groups[elasticstack_elasticsearch_group_name][0]].elasticsearch_api_host",
            source,
        )
        self.assertIn(
            "groups[elasticstack_elasticsearch_group_name] | length == 1",
            source,
        )
        self.assertIn(
            "groups[elasticstack_elasticsearch_group_name][0] == inventory_hostname",
            source,
        )
        self.assertIn(
            "else groups[elasticstack_elasticsearch_group_name]",
            source,
        )

    def test_plugin_workflow_discovers_the_complete_unit_test_suite(self):
        source = (ROOT / ".github" / "workflows" / "test_plugins.yml").read_text()
        self.assertIn("pytest>=8.3,<9", source)
        self.assertIn("python -m pytest -q tests/unit", source)
        self.assertNotIn("python tests/unit/plugins/modules/test_cert_info.py", source)
        self.assertNotIn("python tests/unit/plugins/module_utils/test_certs.py", source)
        self.assertNotIn("python tests/unit/test_repository_contracts.py", source)

    def test_public_variables_have_argument_specs_and_executable_coverage(self):
        coverage = yaml.safe_load((ROOT / "tests" / "variable_coverage.yml").read_text())
        baselines = coverage["baselines"]
        explicit = coverage["explicit"]
        rollouts = coverage["rollouts"]
        behaviors = coverage["behaviors"]
        workflow_sources = "\n".join(
            path.read_text() for path in (ROOT / ".github" / "workflows").glob("*.yml")
        )

        for role in sorted(baselines):
            defaults_path = ROOT / "roles" / role / "defaults" / "main.yml"
            specs_path = ROOT / "roles" / role / "meta" / "argument_specs.yml"
            entries = parse_defaults(defaults_path)
            public = {entry["name"] for entry in entries}
            optional = {
                entry["name"] for entry in entries if not entry.get("has_default", False)
            }
            options = yaml.safe_load(specs_path.read_text())["argument_specs"]["main"]["options"]

            self.assertEqual(public, set(options), f"{role} public variable catalog drifted")
            explicit_variables = set(explicit.get(role, {}))
            rollout_variables = set(rollouts.get(role, {}))
            self.assertTrue(
                optional <= explicit_variables,
                f"{role} optional variables must have explicit executable coverage",
            )
            self.assertTrue(
                optional <= rollout_variables,
                f"{role} optional variables must have Molecule rollout coverage",
            )
            self.assertTrue(
                explicit_variables <= public,
                f"{role} explicit coverage references an unknown public variable",
            )
            self.assertTrue(
                rollout_variables <= public,
                f"{role} rollout coverage references an unknown public variable",
            )

            for variable, paths in explicit.get(role, {}).items():
                assignment = re.compile(
                    rf"(?m)^(?!\s*#)\s*{re.escape(variable)}\s*:"
                )
                self.assertTrue(paths, f"{role}.{variable} has no coverage path")
                for relative_path in paths:
                    path = ROOT / relative_path
                    self.assertTrue(path.exists(), f"Missing coverage file: {relative_path}")
                    self.assertRegex(
                        path.read_text(),
                        assignment,
                        f"{relative_path} does not assign {variable}",
                    )

            for relative_path in baselines[role]:
                path = ROOT / relative_path
                self.assertTrue(path.exists(), f"Missing baseline scenario: {relative_path}")
                source = path.read_text()
                scenario = path.parent.name
                self.assertTrue(
                    (path.parent / "verify.yml").exists(),
                    f"{scenario} baseline has no rollout verification",
                )
                self.assertIn(
                    scenario,
                    workflow_sources,
                    f"{scenario} baseline is not referenced by a CI workflow",
                )
                if role != "elasticstack":
                    self.assertIn(
                        f"oddly.elasticstack.{role}",
                        source,
                        f"{relative_path} does not execute the {role} role",
                    )

            for variable, rollout in rollouts.get(role, {}).items():
                scenario = rollout["scenario"]
                converge = ROOT / "molecule" / scenario / "converge.yml"
                verify = ROOT / "molecule" / scenario / "verify.yml"
                self.assertTrue(converge.exists(), f"Missing rollout converge: {converge}")
                self.assertTrue(verify.exists(), f"Missing rollout verify: {verify}")
                self.assertIn(
                    scenario,
                    workflow_sources,
                    f"{scenario} rollout is not referenced by a CI workflow",
                )
                if role != "elasticstack":
                    self.assertIn(
                        f"oddly.elasticstack.{role}",
                        converge.read_text(),
                        f"{scenario} rollout does not execute the {role} role",
                    )
                assignment = re.compile(
                    rf"(?m)^(?!\s*#)\s*{re.escape(variable)}\s*:"
                )
                self.assertRegex(
                    converge.read_text(),
                    assignment,
                    f"{scenario} does not assign rollout variable {variable}",
                )
                assertions_path = ROOT / rollout.get(
                    "assertions_file", f"molecule/{scenario}/verify.yml"
                )
                self.assertTrue(
                    assertions_path.exists(),
                    f"Missing rollout assertions file: {assertions_path}",
                )
                verify_source = _assertion_text(assertions_path)
                self.assertTrue(
                    rollout.get("expected"),
                    f"{scenario} has no assertion markers for {variable}",
                )
                for expected in rollout.get("expected", []):
                    self.assertIn(
                        expected,
                        verify_source,
                        f"{scenario} verify.yml does not assert {variable}: {expected}",
                    )

        for behavior in behaviors:
            role = behavior["role"]
            defaults_path = ROOT / "roles" / role / "defaults" / "main.yml"
            public = {entry["name"] for entry in parse_defaults(defaults_path)}
            scenario = behavior.get("scenario")
            contract = behavior.get("contract")
            self.assertEqual(
                bool(scenario) ^ bool(contract),
                True,
                f"{behavior['name']} must name exactly one scenario or contract",
            )

            if scenario:
                converge = ROOT / "molecule" / scenario / "converge.yml"
                verify = ROOT / "molecule" / scenario / "verify.yml"
                coverage_source = converge.read_text()
                self.assertTrue(converge.exists(), f"Missing behavior converge: {converge}")
                self.assertTrue(verify.exists(), f"Missing behavior verify: {verify}")
                self.assertIn(
                    scenario,
                    workflow_sources,
                    f"{scenario} behavior is not referenced by a CI workflow",
                )
                assertions_path = ROOT / behavior.get(
                    "assertions_file", f"molecule/{scenario}/verify.yml"
                )
                self.assertTrue(
                    assertions_path.exists(),
                    f"Missing behavior assertions file: {assertions_path}",
                )
                assertion_source = _assertion_text(assertions_path)
            else:
                contract_path = ROOT / contract
                coverage_source = contract_path.read_text()
                assertion_source = _assertion_text(contract_path)
                self.assertTrue(
                    contract_path.exists(),
                    f"Missing behavior contract: {contract_path}",
                )
                self.assertIn(
                    "for pb in *_contract.yml",
                    workflow_sources,
                    "integration behavior contracts must run in Test Contracts",
                )

            self.assertTrue(
                set(behavior["variables"]).issubset(public),
                f"{behavior['name']} references a variable outside {role}'s public catalog",
            )

            for variable in behavior["variables"]:
                assignment = re.compile(
                    rf"(?m)^(?!\s*#)\s*{re.escape(variable)}\s*:"
                )
                self.assertRegex(
                    coverage_source,
                    assignment,
                    f"{behavior['name']} does not assign behavior variable {variable}",
                )
            for role_reference in behavior["roles"]:
                self.assertIn(
                    role_reference,
                    coverage_source,
                    f"{scenario} does not execute {role_reference}",
                )

            for expected in behavior["expected"]:
                self.assertIn(
                    expected,
                    assertion_source,
                    f"{behavior['name']} does not assert behavior: {expected}",
                )

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
            (workflows / "test_unit.yml").write_text(
                "jobs:\n"
                "  molecule:\n"
                "    strategy:\n"
                "      matrix:\n"
                "        scenario:\n"
                "          - \"scenario with spaces\"\n"
            )
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
            (workflows / "test_unit.yml").write_text(
                "# orphan is mentioned in a comment only\n"
                "with:\n"
                "  scenarios: '[\"missing-verify\"]'\n"
            )

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
