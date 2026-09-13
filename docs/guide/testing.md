# Testing and coverage

The collection uses several test layers because a variable can be accepted by
Ansible, render valid configuration, and still fail when the service starts.
Coverage is organized around the behavior a variable controls rather than a
Cartesian product of every possible setting.

## Coverage contract

The public variable catalog comes from each role's `defaults/main.yml` and its
generated `meta/argument_specs.yml`. `tests/variable_coverage.yml` records the
executable evidence for that catalog, and the repository contract tests fail
when the catalog or its coverage entries drift.

Each useful variable belongs to one or more of these coverage levels:

1. **Baseline**: the role runs with its normal defaults and the verify play
   checks installation, service state, and the principal rendered files.
2. **Render contract**: a fast integration test assigns a value and asserts the
   exact rendered configuration. This is appropriate for scalar formatting,
   list handling, and optional template fragments.
3. **Service rollout**: a Molecule scenario installs the affected service,
   starts it, and verifies that the setting is accepted by the real service.
4. **Behavior contract**: a focused integration or Molecule test checks a
   lifecycle, security, certificate, upgrade, or multi-role interaction.
5. **Negative contract**: invalid combinations fail early with an actionable
   message and do not perform a partial deployment.

A variable is considered covered when the test assigns it, executes the role
or task that consumes it, and asserts an observable result. A converge-only
assignment does not count as coverage.

Defaulted feature controls that share a rollout are recorded as named behavior
groups in `tests/variable_coverage.yml`. The repository contract requires every
grouped variable to be assigned by the scenario and requires each listed
observable marker to appear in its `verify.yml` assertions.

## Collection-specific matrix

The matrix grows by risk and by branch, with pairwise combinations for settings
that interact. The scenarios below are the durable anchors for that work.

| Area | Required behavior paths | Existing or planned executable anchor |
| --- | --- | --- |
| Shared collection and repositories | CA creation and reuse, passphrase handling, certificate renewal, repository release and mirror settings | `elasticstack_default`, `elasticstack_common_passphrase`, `cert_renewal`, and repository contracts |
| Elasticsearch installation | package and service lifecycle, YAML and logging controls, JVM and OS tuning, data and log paths, and logrotate syntax | `elasticsearch_default`, `elasticsearch_no-security`, `elasticsearch_custom`, `elasticsearch_diagnostics`, and template contracts |
| Elasticsearch cluster operations | node role calculation, quorum validation, cluster settings, LogsDB data-stream behavior, maintenance, rolling restart, and upgrade sequencing | `elasticsearch_roles_calculation`, `elasticsearch_default`, node-maintenance and rolling-restart contracts, and the 8-to-9 upgrade scenarios |
| Elasticsearch security | generated and external TLS, PEM and PKCS12 files, inline content, bundled CA extraction, built-in and custom users, roles, mappings, idempotence, and password rotation | certificate Molecule scenarios, `security_and_certificate_contract.yml`, `elasticsearch_security_management_contract.yml`, and the real-ES `elasticsearch_security_api` scenario |
| Kibana | backend protocol and host discovery, generated and external TLS, PEM and PKCS12 handling, encryption keys, readiness, and extra configuration | `kibana_default`, `es_kibana`, `kibana_extras`, `kibana_custom_certs`, `cert_renewal`, and the Kibana rollout matrix |
| Logstash | pipeline lifecycle, beats and Elastic Agent inputs, TLS modes, Elasticsearch outputs, authentication and roles, queues, dead-letter queues, monitoring, and config syntax | `logstash_default`, `logstash_advanced`, `logstash_elasticsearch`, `logstash_external_certs`, `logstash_ssl`, and `logstash_standalone_certs` |
| Beats | Filebeat, Auditbeat, and Metricbeat lifecycle, inputs, queues, outputs, load balancing, TLS modes, and module setup | `beats_default`, `beats_advanced`, `beats_peculiar`, `beats_security`, plus render contracts |
| Elastic Agent | package installation on Elastic 8 and 9, standalone policy rendering and backups, opt-in management, Fleet enrollment, Fleet Server flags and package flavor, certificate content/file/collection-CA paths, enrollment idempotence, secret-free state, and Beats migration | `elastic_agent_default` and `elastic_agent_fleet` on Rocky Linux and Debian, plus repository and variable-coverage contracts |

The matrix deliberately gives certificate source, content, fallback, and
certificate-key mismatch paths
their own assertions. Those paths need both file or content equality checks and
service-level probes because a certificate can be copied successfully while
the daemon still rejects its format or trust chain.

The higher-risk checks are deliberately split between levels. The real-ES
security scenario reconciles a role, user, and role mapping through the
collection with a custom `elastic` password, then reads those objects back and
authenticates as the managed user. The Elasticsearch default scenario creates
a `logs-*` data stream and checks the backing index's `logsdb` mode. The custom
Elasticsearch scenario runs logrotate's parser against the rendered policy and
checks that a custom `elasticsearch_logpath` is used. Kibana's rollout probes
require `status.overall.level: available` where an Elasticsearch backend is
present, including the HTTPS certificate-renewal path; a repository contract
also protects both readiness commands from falling back to `/bin/sh`.

## CI responsibilities

Every committed Molecule scenario must have a `verify.yml` and be referenced by
an active workflow. Pull requests run the fast unit, contract, lint, and
role-specific paths. The `ci:run` label starts the Incus-backed rollout matrix,
including converge, verify, and idempotence checks. Scheduled runs widen the
operating-system and Elastic release matrix.

The EOL workflow is scheduled or manually dispatched because its data source is
external. Its classification and GitHub environment-file output are tested
deterministically in `tests/unit/test_check_eol.py`; the scheduled workflow
exercises the live API fetch and issue update path.

The full-stack gate is required before merge when shared roles, full-stack
scenarios, or their workflows change. A failed rollout is investigated at the
scenario level and fixed with a focused test before the broader matrix is
started again.

## Adding coverage for a new variable

When adding or changing a public variable:

1. Classify its default path, alternate branches, and interactions.
2. Add or extend the smallest contract that observes the rendered or runtime
   result.
3. Add the variable to `tests/variable_coverage.yml` with its scenario and
   assertion marker.
4. Run the focused unit or contract test immediately.
5. Run the affected Molecule scenario in CI and confirm verify and idempotence.
6. Add a negative case when invalid input could create an unsafe or partial
   deployment.

This process provides broad confidence without claiming that every theoretical
transmutation has been executed. The catalog and ledger make any remaining
untested branch visible for the next risk-based addition.
