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
STATIC_TASK_INCLUDE = re.compile(
    r"(?m)^\s*(?:ansible\.builtin\.)?include_tasks:\s*['\"]?([^'\"\s#]+)"
)
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


def _assertion_text(path, seen=None):
    """Return assert expressions from a playbook and its static task includes."""
    path = path.resolve()
    if seen is None:
        seen = set()
    if path in seen:
        return ""
    seen.add(path)

    document = yaml.safe_load(path.read_text()) or {}
    expressions = []

    def visit(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "that":
                    values = value if isinstance(value, list) else [value]
                    expressions.extend(str(item) for item in values)
                if key in {"include_tasks", "ansible.builtin.include_tasks"}:
                    if isinstance(value, str) and "{{" not in value:
                        included = (path.parent / value).resolve()
                        if included.is_file():
                            expressions.append(_assertion_text(included, seen))
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(document)
    return "\n".join(expressions)


def _source_with_static_includes(path, seen=None):
    """Return a playbook source plus the task files it statically includes."""
    path = path.resolve()
    if seen is None:
        seen = set()
    if path in seen or not path.is_file():
        return ""
    seen.add(path)

    source = path.read_text()
    for include in STATIC_TASK_INCLUDE.findall(source):
        if "{{" in include:
            continue
        included = (path.parent / include).resolve()
        source += _source_with_static_includes(included, seen)
    return source


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

    def test_kics_scan_is_independent_of_docker_and_checksum_pinned(self):
        source = (ROOT / ".github" / "workflows" / "kics.yml").read_text()
        self.assertNotIn("docker run", source)
        self.assertIn("kics_${KICS_VERSION}_linux_amd64.tar.gz", source)
        self.assertIn(
            "8a5aa375ccfdc0ddd1114eddf1f9638ad7f6122e98d12a592207509dbe6d81f8",
            source,
        )
        self.assertIn(
            "305fd652d9291fb5f0a3437a4f0a2c953fffa7d2827bb4fd4907c82c1a8cbad9",
            source,
        )
        self.assertIn("sha256sum --check --strict", source)
        self.assertIn("unzip -q -o", source)
        self.assertIn("cd \"$RUNNER_TEMP/kics\"", source)
        self.assertIn("./kics scan", source)
        self.assertIn("test -d \"$install_dir/assets/queries\"", source)
        self.assertIn("persist-credentials: false", source)

    def test_ci_run_label_consumer_uses_available_api_client(self):
        path = ROOT / ".github" / "workflows" / "consume_ci_run_label.yml"
        source = path.read_text()

        self.assertIn("set -euo pipefail", source)
        self.assertIn("curl", source)
        self.assertIn("--fail-with-body", source)
        self.assertIn("GITHUB_API_URL", source)
        self.assertIn("GITHUB_TOKEN", source)
        self.assertIn("labels/ci%3Arun", source)
        self.assertNotIn("gh pr edit", source)

    def test_eol_workflow_runs_monitor_and_consumes_issue_signal(self):
        source = (ROOT / ".github" / "workflows" / "check_eol.yml").read_text()
        self.assertIn("python3 scripts/check_eol.py", source)
        self.assertIn('--github-env "$GITHUB_ENV"', source)
        self.assertIn("if: env.HAS_ISSUES == 'true'", source)

    def test_container_images_are_digest_pinned_when_used(self):
        images = []
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
            for line in path.read_text().splitlines():
                if "docker run" in line or "checkmarx/kics:" in line:
                    images.extend(re.findall(r"([\w.-]+/[\w.-]+:[^\s\\]+)", line))

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
            "pytest>=9.1.1,<10",
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
            self.assertTrue(
                "command -v python3.12" in source
                or (
                    "actions/setup-python@" in source
                    and "python-version: '3.12'" in source
                ),
                f"{path} must select Python 3.12 for Ansible 2.20",
            )
            self.assertTrue(
                'uv venv "$RUNNER_TEMP/venv"' in source
                or 'python -m venv "$RUNNER_TEMP/venv"' in source,
                f"{path} must install into an isolated Python 3.12 environment",
            )
            self.assertIn(
                'echo "$RUNNER_TEMP/venv/bin" >> "$GITHUB_PATH"',
                source,
                f"{path} must put the Python 3.12 executables first on PATH",
            )

    def test_test_dependency_changes_trigger_dependency_sensitive_ci(self):
        contracts_path = ROOT / ".github" / "workflows" / "test_contracts.yml"
        contracts = yaml.safe_load(contracts_path.read_text()) or {}
        workflow_on = contracts.get("on", contracts.get(True, {}))
        contract_paths = workflow_on["pull_request"]["paths"]
        self.assertIn(
            "requirements-test.txt",
            contract_paths,
            f"{contracts_path} must test changes to test dependencies",
        )

        full_stack_path = ROOT / ".github" / "workflows" / "test_full_stack.yml"
        full_stack = yaml.safe_load(full_stack_path.read_text()) or {}
        filter_step = next(
            step
            for step in full_stack["jobs"]["changes"]["steps"]
            if step.get("id") == "filter"
        )
        path_filters = yaml.safe_load(filter_step["with"]["filters"]) or {}
        self.assertIn(
            "requirements-test.txt",
            path_filters["should_test"],
            f"{full_stack_path} must test changes to test dependencies",
        )
        for path in (
            "roles/elasticsearch/tasks/elasticsearch-cluster-settings.yml",
            "roles/elasticsearch/templates/elasticsearch.yml.j2",
        ):
            self.assertIn(
                path,
                path_filters["should_test"],
                f"{full_stack_path} must run full-stack idempotence for {path}",
            )

    def test_molecule_prepare_files_use_shared_name_resolution(self):
        common = (ROOT / "molecule" / "shared" / "prepare_common.yml").read_text()
        self.assertIn("Populate /etc/hosts with molecule instances", common)
        self.assertIn("hostvars[item]['ansible_host']", common)
        common_tasks = yaml.safe_load(common)
        hosts_task = next(
            task
            for task in common_tasks
            if task.get("name") == "Populate /etc/hosts with molecule instances"
        )
        self.assertEqual(
            hosts_task["ansible.builtin.lineinfile"]["regexp"],
            r"^.*\s{{ item | regex_escape }}$",
        )

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

        elasticsearch_template = (
            ROOT / "roles" / "elasticsearch" / "templates" / "elasticsearch.yml.j2"
        ).read_text()
        self.assertIn(
            "[elasticsearch_certs_dir ~ '/ca.crt'] | to_json",
            elasticsearch_template,
        )
        self.assertGreaterEqual(
            elasticsearch_template.count("elasticsearch_certs_dir ~"),
            14,
        )

        workflow = (ROOT / ".github" / "workflows" / "test_full_stack.yml").read_text()
        self.assertIn("roles/elasticsearch/tasks/main.yml", workflow)

        elasticsearch_docs = (ROOT / "docs" / "reference" / "elasticsearch.md").read_text()
        kibana_docs = (ROOT / "docs" / "reference" / "kibana.md").read_text()
        self.assertIn("generated or external TLS certificates", elasticsearch_docs)
        self.assertIn("generated or external TLS certificates", kibana_docs)
        self.assertIn("{{ kibana_certs_dir }}/", kibana_docs)

    def test_elasticsearch_and_kibana_certificate_directories_are_configurable(self):
        for role, variable, default, hardcoded, files in (
            (
                "elasticsearch",
                "elasticsearch_certs_dir",
                "/etc/elasticsearch/certs",
                "/etc/elasticsearch/certs",
                (
                    "tasks/main.yml",
                    "tasks/elasticsearch-security.yml",
                    "templates/elasticsearch.yml.j2",
                ),
            ),
            (
                "kibana",
                "kibana_certs_dir",
                "/etc/kibana/certs",
                "/etc/kibana/certs",
                ("tasks/kibana-security.yml", "templates/kibana.yml.j2"),
            ),
        ):
            defaults = (ROOT / "roles" / role / "defaults" / "main.yml").read_text()
            self.assertRegex(
                defaults,
                rf"(?m)^{re.escape(variable)}:\s+{re.escape(default)}$",
            )
            specs = yaml.safe_load(
                (ROOT / "roles" / role / "meta" / "argument_specs.yml").read_text()
            )
            option = specs["argument_specs"]["main"]["options"][variable]
            self.assertEqual(option["type"], "str")
            self.assertEqual(option["default"], default)
            for relative_path in files:
                source = (ROOT / "roles" / role / relative_path).read_text()
                self.assertNotIn(
                    hardcoded,
                    source,
                    f"{relative_path} still hardcodes the cert directory",
                )
                self.assertTrue(
                    f"{{{{ {variable} }}}}" in source or f"{variable} ~" in source,
                    f"{relative_path} does not use {variable}",
                )

    def test_certificate_renewal_exercises_custom_generated_certificate_directories(self):
        converge = (ROOT / "molecule" / "cert_renewal" / "converge.yml").read_text()
        verify = (ROOT / "molecule" / "cert_renewal" / "verify.yml").read_text()

        for variable, directory, filename in (
            (
                "elasticsearch_certs_dir",
                "/etc/elasticsearch/renewal-certs",
                "{{ elasticsearch_certs_dir }}/{{ ansible_facts.hostname }}.p12",
            ),
            (
                "kibana_certs_dir",
                "/etc/kibana/renewal-certs",
                "{{ kibana_certs_dir }}/{{ ansible_facts.hostname }}-kibana.p12",
            ),
        ):
            self.assertGreaterEqual(converge.count(f"{variable}: {directory}"), 4)
            self.assertIn(f"{variable}: {directory}", verify)
            self.assertIn(filename, converge)
            self.assertIn(filename, verify)

        workflow = (ROOT / ".github" / "workflows" / "test_full_stack.yml").read_text()
        for path in (
            "roles/elasticsearch/meta/argument_specs.yml",
            "roles/elasticsearch/tasks/elasticsearch-security.yml",
            "roles/kibana/meta/argument_specs.yml",
            "roles/kibana/tasks/kibana-security.yml",
        ):
            self.assertIn(path, workflow)

    def test_elasticsearch_certificate_content_verification_uses_configured_directory(self):
        converge = (ROOT / "molecule" / "elasticsearch_cert_content" / "converge.yml").read_text()
        verify = (ROOT / "molecule" / "elasticsearch_cert_content" / "verify.yml").read_text()

        self.assertIn("elasticsearch_certs_dir: /etc/elasticsearch/certs", verify)
        self.assertGreaterEqual(verify.count("{{ elasticsearch_certs_dir }}"), 4)
        self.assertNotIn("certificate: certs/", verify)
        self.assertNotIn("elasticsearch_certs_dir:", converge)

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

    def test_elasticsearch_logrotate_installs_runtime_package_when_enabled(self):
        tasks = yaml.safe_load(
            (ROOT / "roles" / "elasticsearch" / "tasks" / "main.yml").read_text()
        )
        install = next(
            task
            for task in tasks
            if task.get("name") == "Install logrotate package for Elasticsearch"
        )
        self.assertEqual(install["ansible.builtin.package"]["name"], "logrotate")
        self.assertEqual(install["ansible.builtin.package"]["state"], "present")
        self.assertEqual(install["when"], "elasticsearch_logrotate_enabled | bool")
        self.assertEqual(install["retries"], 3)
        self.assertEqual(install["delay"], 10)

    def test_elasticsearch_template_uses_precomputed_discovery_values(self):
        template = (
            ROOT / "roles" / "elasticsearch" / "templates" / "elasticsearch.yml.j2"
        ).read_text()
        values_task = (
            ROOT / "roles" / "elasticsearch" / "tasks" / "elasticsearch-template-values.yml"
        ).read_text()
        main = (ROOT / "roles" / "elasticsearch" / "tasks" / "main.yml").read_text()

        self.assertNotIn("{% for host in groups", template)
        self.assertIn("_elasticsearch_discovery_seed_hosts | to_json", template)
        self.assertIn("_elasticsearch_initial_master_nodes | to_json", template)
        self.assertIn(
            "not (elasticsearch_cluster_set_up | default(false) | bool)", template
        )
        self.assertIn("_elasticsearch_discovery_seed_hosts", values_task)
        self.assertIn("_elasticsearch_initial_master_nodes", values_task)
        self.assertIn(
            "ansible.builtin.import_tasks: elasticsearch-template-values.yml",
            main,
        )

    def test_cluster_settings_match_check_is_idempotent(self):
        tasks = yaml.safe_load(
            (
                ROOT
                / "roles"
                / "elasticsearch"
                / "tasks"
                / "elasticsearch-cluster-settings.yml"
            ).read_text()
        )
        check = next(
            task
            for task in tasks[1]["block"]
            if task.get("name")
            == "elasticsearch-cluster-settings | Check if settings already match"
        )
        self.assertFalse(check["changed_when"])

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

    def test_variable_defaults_are_explicit_and_internal_sentinels_are_private(self):
        shared_defaults = yaml.safe_load(
            (ROOT / "roles" / "elasticstack" / "defaults" / "main.yml").read_text()
        )
        self.assertEqual(shared_defaults["elasticstack_version"], "")
        self.assertEqual(shared_defaults["elasticstack_cert_pass"], "")

        for role, expected in {
            "elasticsearch": {
                "elasticsearch_extra_config": {},
                "elasticsearch_fs_repo": [],
            },
            "kibana": {"kibana_extra_config": {}},
            "beats": {"beats_fields": [], "beats_filebeat_modules": []},
            "logstash": {
                "logstash_pipeline_unsafe_shutdown": False,
                "logstash_skip_root_check": False,
            },
        }.items():
            defaults = yaml.safe_load(
                (ROOT / "roles" / role / "defaults" / "main.yml").read_text()
            )
            for variable, value in expected.items():
                self.assertEqual(defaults[variable], value)

        for path, dead_variable in (
            (ROOT / "roles" / "kibana" / "defaults" / "main.yml", "kibana_tls_cert"),
            (ROOT / "roles" / "kibana" / "defaults" / "main.yml", "kibana_tls_key"),
        ):
            self.assertNotRegex(
                path.read_text(),
                rf"(?m)^\s*{re.escape(dead_variable)}\s*:",
            )
        role_sources = "\n".join(
            path.read_text()
            for path in (ROOT / "roles").rglob("*.yml")
        )
        self.assertNotIn("elasticstack_globals_set", role_sources)

        logstash_defaults = yaml.safe_load(
            (ROOT / "roles" / "logstash" / "defaults" / "main.yml").read_text()
        )
        self.assertEqual(
            {
                name: logstash_defaults[name]
                for name in (
                    "logstash_config_autoreload_interval",
                    "logstash_http_host",
                    "logstash_http_port",
                    "logstash_input_beats_timeout",
                    "logstash_sniffing_delay",
                    "logstash_sniffing_path",
                    "logstash_dead_letter_queue_enable",
                    "logstash_dead_letter_queue_retain_age",
                    "logstash_log_format",
                )
            },
            {
                "logstash_config_autoreload_interval": "3s",
                "logstash_http_host": "127.0.0.1",
                "logstash_http_port": "9600-9700",
                "logstash_input_beats_timeout": "60s",
                "logstash_sniffing_delay": 5,
                "logstash_sniffing_path": "/_nodes/http",
                "logstash_dead_letter_queue_enable": False,
                "logstash_dead_letter_queue_retain_age": "7d",
                "logstash_log_format": "plain",
            },
        )

        for role, sentinels in {
            "elasticsearch": ("_elasticsearch_freshstart", "_elasticsearch_freshstart_security"),
            "kibana": ("_kibana_freshstart",),
            "logstash": ("_logstash_freshstart",),
        }.items():
            public = {entry["name"] for entry in parse_defaults(ROOT / "roles" / role / "defaults/main.yml")}
            private_vars = yaml.safe_load((ROOT / "roles" / role / "vars/main.yml").read_text()) or {}
            for sentinel in sentinels:
                self.assertNotIn(sentinel.lstrip("_"), public)
                self.assertEqual(private_vars[sentinel], {"changed": False})

        upgrade_detection = (
            ROOT / "roles" / "elasticsearch" / "tasks" / "elasticsearch-upgrade-detection.yml"
        ).read_text()
        self.assertIn(
            "elasticstack_version | default('') | string | length > 0",
            upgrade_detection,
        )
        upgrade_tasks = (ROOT / "roles" / "elasticsearch" / "tasks" / "main.yml").read_text()
        self.assertIn(
            "elasticstack_version | default('latest ' ~ elasticstack_release ~ '.x', true)",
            upgrade_tasks,
        )
        for variable in (
            "logstash_security",
            "logstash_input_beats",
            "logstash_input_beats_ssl",
            "logstash_output_elasticsearch",
            "logstash_elasticsearch_output",
            "logstash_monitoring_enabled",
            "logstash_global_ecs",
        ):
            entry = next(
                entry
                for entry in parse_defaults(ROOT / "roles" / "logstash" / "defaults/main.yml")
                if entry["name"] == variable
            )
            self.assertFalse(entry["has_default"], variable)

    def test_stack_security_scenarios_exercise_inherited_false(self):
        scenarios = {
            "molecule/elasticsearch_no-security/converge.yml": "elasticsearch_security",
            "molecule/kibana_cert_content/converge.yml": "kibana_security",
            "molecule/logstash_default/converge.yml": "logstash_security",
        }
        for relative_path, role_variable in scenarios.items():
            source = (ROOT / relative_path).read_text()
            self.assertIn("elasticstack_security: false", source)
            self.assertNotRegex(
                source,
                rf"(?m)^\s*{re.escape(role_variable)}\s*:\s*false\s*$",
            )

        for role in ("elasticsearch", "kibana"):
            source = (ROOT / "roles" / role / "tasks" / "main.yml").read_text()
            self.assertIn("elasticstack_security | bool", source)
        logstash = (ROOT / "roles" / "logstash" / "tasks" / "logstash-compatibility.yml").read_text()
        self.assertIn("elasticstack_security | default(false)", logstash)

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
        self.assertIn("elasticstack_security: false", source)
        self.assertNotIn("elasticsearch_security: false", source)
        self.assertNotIn("kibana_security: false", source)
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

    def test_kibana_readiness_commands_are_safe_on_dash(self):
        """The readiness probes must not silently fall back to /bin/sh."""
        for relative_path in (
            "roles/kibana/tasks/main.yml",
            "roles/kibana/tasks/restart_and_verify_kibana.yml",
        ):
            document = yaml.safe_load((ROOT / relative_path).read_text()) or []
            readiness_tasks = []

            def visit(node):
                if isinstance(node, dict):
                    shell = node.get("ansible.builtin.shell")
                    command = shell.get("cmd", "") if isinstance(shell, dict) else ""
                    if "HTTP_CODE" in command and "api/status" in command:
                        readiness_tasks.append(shell)
                    for value in node.values():
                        visit(value)
                elif isinstance(node, list):
                    for item in node:
                        visit(item)

            visit(document)
            self.assertEqual(len(readiness_tasks), 1, relative_path)
            shell = readiness_tasks[0]
            self.assertEqual(shell.get("executable"), "/bin/bash", relative_path)
            self.assertIn("set -o pipefail", shell["cmd"], relative_path)
            self.assertIn("systemctl is-active", shell["cmd"], relative_path)

    def test_service_restart_wrappers_use_shared_lifecycle_tasks(self):
        expected = {
            "roles/elasticsearch/tasks/restart_and_verify_elasticsearch.yml": "elasticsearch",
            "roles/kibana/tasks/restart_and_verify_kibana.yml": "kibana",
            "roles/logstash/tasks/restart_and_verify_logstash.yml": "logstash",
            "roles/beats/tasks/restart_and_verify_beat.yml": "{{ _beat_service_name }}",
        }

        for relative_path, service_name in expected.items():
            document = yaml.safe_load((ROOT / relative_path).read_text()) or []
            includes = [
                task
                for task in document
                if isinstance(task, dict) and "ansible.builtin.include_tasks" in task
            ]
            self.assertTrue(includes, relative_path)

            include = includes[0]["ansible.builtin.include_tasks"]
            include_file = include.get("file") if isinstance(include, dict) else include
            self.assertEqual(
                include_file,
                "{{ role_path }}/../elasticstack/tasks/restart_and_verify_service.yml",
                relative_path,
            )
            self.assertEqual(includes[0].get("vars", {}).get("_service_name"), service_name)

    def test_beats_templates_share_common_setup_fragment(self):
        template_paths = (
            "auditbeat.yml.j2",
            "filebeat.yml.j2",
            "metricbeat.yml.j2",
        )
        for filename in template_paths:
            source = (ROOT / "roles" / "beats" / "templates" / filename).read_text()
            self.assertEqual(
                source.count("{% include '_beats_setup.j2' %}"),
                1,
                filename,
            )
            self.assertNotIn("setup.template.settings:", source, filename)
            self.assertNotIn("setup.kibana:", source, filename)

        fragment = (
            ROOT / "roles" / "beats" / "templates" / "_beats_setup.j2"
        ).read_text()
        self.assertEqual(fragment.count("setup.template.settings:"), 1)
        self.assertEqual(fragment.count("setup.kibana:"), 1)
        self.assertIn("elasticstack_full_stack | bool", fragment)

    def test_logstash_templates_use_resolved_tls_option_names(self):
        options = yaml.safe_load(
            (ROOT / "roles" / "logstash" / "tasks" / "logstash-template-options.yml").read_text()
        )
        self.assertEqual(len(options), 2)
        self.assertIn("_logstash_input_ssl_options", options[0]["ansible.builtin.set_fact"])
        self.assertIn("_logstash_output_ssl_options", options[1]["ansible.builtin.set_fact"])

        input_template = (ROOT / "roles" / "logstash" / "templates" / "10-input.conf.j2").read_text()
        output_template = (ROOT / "roles" / "logstash" / "templates" / "90-output.conf.j2").read_text()
        for template in (input_template, output_template):
            self.assertNotIn("elasticstack_release | int >= 9", template)
        self.assertIn("_logstash_input_ssl_options.enabled", input_template)
        self.assertIn("_logstash_input_ssl_options.client_authentication", input_template)
        self.assertIn("_logstash_output_ssl_options.enabled", output_template)
        self.assertIn("_logstash_output_ssl_options.keystore_path", output_template)

    def test_auditbeat_modules_are_configurable(self):
        defaults = yaml.safe_load(
            (ROOT / "roles" / "beats" / "defaults" / "main.yml").read_text()
        )
        template = (
            ROOT / "roles" / "beats" / "templates" / "auditbeat.yml.j2"
        ).read_text()

        self.assertEqual(len(defaults["beats_auditbeat_modules"]), 4)
        self.assertEqual(defaults["beats_auditbeat_modules"][0]["module"], "auditd")
        self.assertEqual(
            defaults["beats_auditbeat_modules"][1]["module"], "file_integrity"
        )
        self.assertIn("beats_auditbeat_modules | to_nice_yaml", template)
        self.assertNotIn("/usr/bin", template)
        documentation = (ROOT / "docs" / "reference" / "beats.md").read_text()
        self.assertIn("audit_rule_files:", documentation)
        self.assertIn("state.period: 12h", documentation)
        verify = (ROOT / "molecule" / "beats_advanced" / "verify.yml").read_text()
        self.assertIn("auditbeat", verify)
        self.assertIn("- test", verify)
        self.assertIn("- config", verify)

    def test_molecule_reuses_shared_service_and_readiness_checks(self):
        kibana_shared = (
            ROOT / "molecule" / "shared" / "verify_kibana_available.yml"
        ).read_text()
        self.assertIn("ansible.builtin.uri:", kibana_shared)
        self.assertIn("register: kibana_status", kibana_shared)
        self.assertIn("overall.level", kibana_shared)
        self.assertIn("_kibana_is_https", kibana_shared)
        self.assertIn("_kibana_use_auth", kibana_shared)
        self.assertIn("_verify_kibana_auth_http", kibana_shared)
        self.assertIn("follow_redirects: none", kibana_shared)
        self.assertIn("else omit", kibana_shared)
        self.assertIn("_verify_kibana_validate_certs | default(true)", kibana_shared)

        for scenario in ("cert_renewal", "kibana_custom_certs"):
            source = (ROOT / "molecule" / scenario / "verify.yml").read_text()
            self.assertIn(
                "_verify_kibana_validate_certs: false",
                source,
                f"{scenario} uses a self-signed Kibana certificate",
            )

        for scenario in (
            "cert_renewal",
            "elasticstack_default",
            "es_kibana",
            "kibana_custom",
            "kibana_custom_certs",
        ):
            source = (ROOT / "molecule" / scenario / "verify.yml").read_text()
            self.assertIn(
                "include_tasks: ../shared/verify_kibana_available.yml",
                source,
                scenario,
            )

        custom_kibana_verify = (ROOT / "molecule" / "kibana_custom" / "verify.yml").read_text()
        self.assertIn("_verify_kibana_auth_http: true", custom_kibana_verify)

        logstash_service_shared = (
            ROOT / "molecule" / "shared" / "verify_logstash_service.yml"
        ).read_text()
        self.assertIn("register: logstash_service", logstash_service_shared)
        self.assertIn("logstash_service.failed", logstash_service_shared)
        self.assertIn("logstash_service.changed", logstash_service_shared)

        logstash_shared = (
            ROOT / "molecule" / "shared" / "verify_logstash_port.yml"
        ).read_text()
        self.assertIn("ansible.builtin.wait_for:", logstash_shared)
        self.assertIn("register: logstash_port_check", logstash_shared)
        self.assertIn("Get installed Logstash version", logstash_shared)
        self.assertIn("--config.test_and_exit", logstash_shared)

        for scenario in (
            "logstash_advanced",
            "logstash_external_certs",
            "logstash_ssl",
            "logstash_standalone_certs",
        ):
            source = (ROOT / "molecule" / scenario / "verify.yml").read_text()
            self.assertIn(
                "include_tasks: ../shared/verify_logstash_service.yml",
                source,
                scenario,
            )
            self.assertIn(
                "include_tasks: ../shared/verify_logstash_port.yml",
                source,
                scenario,
            )
            self.assertNotIn(
                "Get installed Logstash version",
                source,
                f"{scenario} must use the shared Logstash version check",
            )

        cert_shared = (
            ROOT / "molecule" / "shared" / "generate_test_certs_openssl.yml"
        ).read_text()
        for marker in (
            "transport.cnf",
            "transport.crt",
            "http.cnf",
            "http.crt",
            "-CAcreateserial",
        ):
            self.assertIn(marker, cert_shared)

        for scenario in (
            "elasticsearch_cert_content",
            "elasticsearch_custom_certs",
            "kibana_custom_certs",
        ):
            source = (ROOT / "molecule" / scenario / "converge.yml").read_text()
            self.assertIn(
                "include_tasks: ../shared/generate_test_certs_openssl.yml",
                source,
                scenario,
            )
            self.assertNotIn(
                "openssl genrsa",
                source,
                f"{scenario} must use the shared OpenSSL fixture",
            )

    def test_molecule_password_checks_use_shared_safe_fetch(self):
        shared = (ROOT / "molecule" / "shared" / "verify_fetch_password.yml").read_text()
        self.assertIn("ansible.builtin.command:", shared)
        self.assertIn("- awk", shared)
        self.assertIn("$1 == \"PASSWORD\" && $2 == user", shared)
        self.assertIn("_verify_initial_passwords_path", shared)
        self.assertIn("failed_when:", shared)
        self.assertIn("no_log:", shared)

        watermarks = (ROOT / "molecule" / "shared" / "set_ci_watermarks.yml").read_text()
        self.assertIn("ansible.builtin.command:", watermarks)
        self.assertIn("check_mode: false", watermarks)
        self.assertIn("$1 == \"PASSWORD\" && $2 == \"elastic\"", watermarks)
        self.assertIn("failed_when:", watermarks)

        for scenario in (
            "cert_renewal",
            "elasticsearch_cert_content",
            "elasticsearch_custom_certs",
            "elasticsearch_custom_certs_minimal",
            "elasticsearch_diagnostics",
            "elasticsearch_upgrade_8to9",
            "elasticsearch_upgrade_8to9_single",
            "beats_security",
            "elasticstack_default",
            "es_kibana",
            "kibana_custom",
            "kibana_custom_certs",
            "logstash_elasticsearch",
        ):
            source = (ROOT / "molecule" / scenario / "verify.yml").read_text()
            self.assertIn(
                "include_tasks: ../shared/verify_fetch_password.yml",
                source,
                scenario,
            )
            self.assertNotIn(
                'grep "PASSWORD elastic "',
                source,
                f"{scenario} must use the shared password reader",
            )

        for scenario in ("elasticsearch_upgrade_8to9", "elasticsearch_upgrade_8to9_single"):
            source = (ROOT / "molecule" / scenario / "verify.yml").read_text()
            self.assertIn("_verify_initial_passwords_path:", source, scenario)

            converge = (ROOT / "molecule" / scenario / "converge.yml").read_text()
            self.assertIn(
                "include_tasks: ../shared/verify_fetch_password.yml",
                converge,
                f"{scenario} converge",
            )
            self.assertIn("_verify_initial_passwords_path:", converge, scenario)

        old_password_guard = (ROOT / "molecule" / "elasticsearch_default" / "verify.yml").read_text()
        self.assertIn("ansible.builtin.command:", old_password_guard)
        self.assertIn("no_log: true", old_password_guard)
        self.assertNotIn('grep "PASSWORD elastic "', old_password_guard)

    def test_molecule_reuses_shared_elasticsearch_health_checks(self):
        shared = (ROOT / "molecule" / "shared" / "verify_es_health.yml").read_text()
        self.assertIn("_verify_es_statuses", shared)
        self.assertIn("_verify_es_health_query", shared)
        self.assertIn("_verify_es_retries", shared)
        self.assertIn("_verify_es_delay", shared)
        self.assertIn("in _health_statuses", shared)

        scenarios = (
            "cert_renewal",
            "elasticsearch_cert_content",
            "elasticsearch_custom_certs",
            "elasticsearch_custom_certs_minimal",
            "elasticsearch_diagnostics",
            "beats_security",
            "elasticstack_default",
            "es_kibana",
            "kibana_custom",
            "kibana_custom_certs",
            "logstash_elasticsearch",
        )
        for scenario in scenarios:
            source = (ROOT / "molecule" / scenario / "verify.yml").read_text()
            self.assertIn(
                "include_tasks: ../shared/verify_es_health.yml",
                source,
                scenario,
            )

        for scenario in scenarios:
            source = (ROOT / "molecule" / scenario / "verify.yml").read_text()
            self.assertNotIn(
                "_cluster/health",
                source,
                f"{scenario} must use the shared Elasticsearch health check",
            )

        beats_security = (ROOT / "molecule" / "beats_security" / "verify.yml").read_text()
        self.assertIn(
            "_verify_es_statuses: [green, yellow]",
            beats_security,
            "beats_security must allow yellow health for its single-node cluster",
        )

        for relative_path in (
            "molecule/elasticsearch_upgrade_8to9/converge.yml",
            "molecule/elasticsearch_upgrade_8to9/verify.yml",
            "molecule/elasticsearch_upgrade_8to9_single/converge.yml",
            "molecule/elasticsearch_upgrade_8to9_single/verify.yml",
        ):
            source = (ROOT / relative_path).read_text()
            self.assertIn(
                "include_tasks: ../shared/verify_es_health.yml",
                source,
                relative_path,
            )
            self.assertNotIn("_cluster/health", source, relative_path)

    def test_molecule_reuses_shared_elasticsearch_converge_sequence(self):
        shared = (ROOT / "molecule" / "shared" / "converge_elasticsearch.yml").read_text()
        self.assertIn("oddly.elasticstack.repos", shared)
        self.assertIn("oddly.elasticstack.elasticsearch", shared)
        self.assertIn("cleanup_cache.yml", shared)
        self.assertIn("set_ci_watermarks.yml", shared)
        self.assertIn("_converge_cleanup_cache", shared)
        self.assertIn("_converge_set_watermarks", shared)

        scenarios = (
            "elasticsearch_cert_content",
            "elasticsearch_custom",
            "elasticsearch_custom_certs",
            "elasticsearch_custom_certs_minimal",
            "elasticsearch_default",
            "elasticsearch_diagnostics",
            "elasticsearch_no-security",
            "elasticsearch_roles_calculation",
            "elasticsearch_upgrade_8to9",
            "elasticsearch_upgrade_8to9_single",
        )
        for scenario in scenarios:
            source = (ROOT / "molecule" / scenario / "converge.yml").read_text()
            self.assertIn(
                "include_tasks: ../shared/converge_elasticsearch.yml",
                source,
                scenario,
            )

    def test_logstash_role_permission_variables_use_corrected_spelling(self):
        defaults = (ROOT / "roles" / "logstash" / "defaults" / "main.yml").read_text()
        specs = yaml.safe_load(
            (ROOT / "roles" / "logstash" / "meta" / "argument_specs.yml").read_text()
        )["argument_specs"]["main"]["options"]
        security = (ROOT / "roles" / "logstash" / "tasks" / "logstash-security.yml").read_text()

        for variable in (
            "logstash_role_indices_names",
            "logstash_role_indices_privileges",
            "logstash_role_indicies_names",
            "logstash_role_indicies_privileges",
        ):
            self.assertIn(variable, defaults)
            self.assertIn(variable, specs)

        self.assertIn("logstash-role-permissions.yml", security)
        permissions = (
            ROOT / "roles" / "logstash" / "tasks" / "logstash-role-permissions.yml"
        ).read_text()
        self.assertIn("else logstash_role_indicies_names", permissions)
        self.assertIn("else logstash_role_indicies_privileges", permissions)
        contract = (ROOT / "tests" / "integration" / "collection_variable_contract.yml").read_text()
        self.assertIn("legacy-logs-*", contract)
        self.assertIn("preferred-logs-*", contract)

    def test_plugin_workflow_discovers_the_complete_unit_test_suite(self):
        source = (ROOT / ".github" / "workflows" / "test_plugins.yml").read_text()
        self.assertIn("pytest>=9.1.1,<10", source)
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
                execution_source = _source_with_static_includes(path)
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
                        execution_source,
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
                        _source_with_static_includes(converge),
                        f"{scenario} rollout does not execute the {role} role",
                    )
                assignment = re.compile(
                    rf"(?m)^(?!\s*#)\s*{re.escape(variable)}\s*:"
                )
                if rollout.get("uses_default", False):
                    self.assertNotRegex(
                        converge.read_text(),
                        assignment,
                        f"{scenario} overrides default rollout variable {variable}",
                    )
                else:
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

            recorded_variables = (
                set(explicit.get(role, {}))
                | set(rollouts.get(role, {}))
                | {
                    variable
                    for behavior in behaviors
                    if behavior["role"] == role
                    for variable in behavior["variables"]
                }
            )
            assigned_by_rollout = {
                variable
                for rollout_file in (
                    list((ROOT / "molecule").glob("*/converge.yml"))
                    + list((ROOT / "molecule").glob("*/molecule.yml"))
                )
                for variable in public
                if re.search(
                    rf"(?m)^(?!\s*#)\s*{re.escape(variable)}\s*:",
                    rollout_file.read_text(),
                )
            }
            self.assertTrue(
                assigned_by_rollout <= recorded_variables,
                f"{role} rollout assignments missing from variable coverage ledger: "
                f"{sorted(assigned_by_rollout - recorded_variables)}",
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
                self.assertTrue(converge.exists(), f"Missing behavior converge: {converge}")
                self.assertTrue(verify.exists(), f"Missing behavior verify: {verify}")
                execution_source = _source_with_static_includes(converge)
                self.assertIn(
                    scenario,
                    workflow_sources,
                    f"{scenario} behavior is not referenced by a CI workflow",
                )
                assignment_path = ROOT / behavior.get(
                    "assignment_file", f"molecule/{scenario}/converge.yml"
                )
                self.assertTrue(
                    assignment_path.exists(),
                    f"Missing behavior assignment file: {assignment_path}",
                )
                coverage_source = assignment_path.read_text()
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
                execution_source = coverage_source
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
                    execution_source,
                    f"{scenario} does not execute {role_reference}",
                )

            for expected in behavior["expected"]:
                self.assertIn(
                    expected,
                    assertion_source,
                    f"{behavior['name']} does not assert behavior: {expected}",
                )

    def test_public_variables_are_documented(self):
        documentation = "\n".join(
            path.read_text() for path in (ROOT / "docs").rglob("*.md")
        )
        for role in ("beats", "elasticsearch", "elasticstack", "kibana", "logstash"):
            readme = ROOT / "roles" / role / "README.md"
            if readme.exists():
                documentation += "\n" + readme.read_text()
            missing = [
                entry["name"]
                for entry in parse_defaults(ROOT / "roles" / role / "defaults/main.yml")
                if entry["name"] not in documentation
            ]
            self.assertEqual(
                missing,
                [],
                f"{role} public variables missing documentation: {missing}",
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

    def test_diagnostic_artifacts_are_isolated_per_workflow_attempt(self):
        action = (ROOT / ".github" / "actions" / "collect-diagnostics" / "action.yml").read_text()
        diagnostic_dir = (
            '"/tmp/molecule-diagnostics-${GITHUB_RUN_ID:-local}-'
            '${GITHUB_RUN_ATTEMPT:-1}-${DIAGNOSTIC_ARTIFACT_NAME:-unknown}"'
        )
        self.assertEqual(action.count(f"diag={diagnostic_dir}"), 2)
        self.assertEqual(action.count("DIAGNOSTIC_ARTIFACT_NAME: ${{ inputs.artifact-name }}"), 2)
        self.assertIn(
            "path: /tmp/molecule-diagnostics-${{ github.run_id }}-${{ github.run_attempt }}-${{ inputs.artifact-name }}/",
            action,
        )
        self.assertNotIn("path: /tmp/molecule-diagnostics/", action)

    def test_linting_does_not_consume_the_incus_runner_pool(self):
        workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "test_linting.yml").read_text())
        lint_job = workflow["jobs"]["lint"]
        self.assertEqual(lint_job["runs-on"], "ubuntu-latest")
        source = (ROOT / ".github" / "workflows" / "test_linting.yml").read_text()
        self.assertIn("actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97", source)
        self.assertIn('python -m venv "$RUNNER_TEMP/venv"', source)
        self.assertNotIn("secrets.INCUS_HOST", source)
        self.assertNotIn("CACHE_HOST", source)

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
