# Elasticstack Ansible Collection

Repo-specific guidance for Claude Code, organised by topic.

## Development commands

All commands run from the repo root.

```bash
# Argument-spec drift + is-defined-gate scanner. Cheap; worth running any
# time you touch defaults/main.yml, meta/argument_specs.yml, or a `when:` gate.
uv run --with pyyaml python3 scripts/check_argspecs.py

# Regenerate a role's argument_specs.yml from its defaults + @var docblocks.
# Destructive — overwrites roles/<role>/meta/argument_specs.yml in place.
uv run --with pyyaml python3 scripts/gen_argspecs.py roles/<role_name>

# Lint. CI runs yamllint + ansible-lint under the `lint_full` job; both are
# expected to be clean before push.
yamllint .
ansible-lint

# Molecule scenario end-to-end (local equivalent of what CI does across
# `converge` + `verify` — see .github/workflows/molecule.yml for the CI split).
# Set MOLECULE_DISTRO + ELASTIC_RELEASE to whatever combo you want to reproduce;
# the PR-time matrix uses rockylinux10/debian13 with ES 8/9.
MOLECULE_DISTRO=debian13 ELASTIC_RELEASE=9 molecule test -s <scenario>

# Orphan-scenario guard — fails when a molecule scenario is not referenced by
# any workflow, or is missing verify.yml assertions. Runs on PRs that touch
# molecule/ or .github/workflows/.
bash scripts/check-ci-coverage.sh
```

## Repository conventions

- **Task naming**: two-tier — the file the task lives in decides the
  form.
  - Any task file other than `main.yml`: `<file-basename> | Verb …`
    (lowercase prefix, uppercase verb). E.g. `elasticsearch-keystore |
    Set bootstrap password` in `elasticsearch-keystore.yml`.
  - `main.yml`: plain task names without a pipe prefix — orchestration
    tasks read more clearly as prose. E.g. `Include OS specific vars`,
    `Set node name if not overriden by user`.
  `name[casing]` is intentionally in ansible-lint's skip_list so the
  lowercase pipe prefix doesn't trip CI.
- **Commit messages**: Conventional Commits — `type(scope): imperative
  subject` (lowercase after the colon, no trailing period). Examples
  from `main`: `fix(elasticsearch): wait for green before taking the
  next node down during a rolling upgrade`, `chore(ci): give the
  incus-ci memory gate 45 min of patience instead of 15`,
  `refactor(elasticsearch): replace no-op loop-over-group in upgrade
  includes with a membership guard`. Bodies read as plain prose
  paragraphs (first person, no bullet lists or markdown headers),
  no LLM co-author trailers.
- **FQCN**: always. `ansible.builtin.uri`, not `uri`.

## Role default gating

When a role default is commented out (`# foo:`) or has an empty value
(`foo:`, `foo: ""`, `foo: []`, `foo: {}`), the downstream gate must be
an explicit non-empty check, not a bare `is defined`:

```yaml
# Wrong — silently changes behaviour when someone uncomments foo:
when: foo is defined

# Right — the empty sentinel behaves the same whether the default is
# commented, missing, or explicitly ""
when: foo | default('') | length > 0
```

The `elasticstack_cert_pass: ""` regression that took several rounds
to diagnose (empty string propagated into `elasticsearch-keystore add`
stdin and `elasticsearch-certutil --pass`) is the concrete example
this rule exists to prevent.

`scripts/check_argspecs.py` scans role tasks for this pattern and
fails CI when a bare `is defined` gate references a default var whose
declared value is empty or null.

## Fix workflow

When fixing a bug:

1. Before implementing, identify which molecule scenario covers this code path.
2. If no existing scenario catches the bug, add a verify assertion to the
   closest existing scenario — or extend its converge — rather than creating a
   new scenario. A new scenario is a last resort (each one adds ~10 min to CI).
3. Prefer the lightest test that proves the fix: a config assertion in
   verify.yml beats a full multi-node deployment. Only add nodes/complexity
   when the bug genuinely requires it (e.g. inter-node communication).
4. The test should fail without the fix and pass with it. Confirm this
   mentally or by describing the failure mode before implementing.

## Architecture

Six roles — one meta-role plus five siblings that import it:

```
roles/
  elasticstack/   Meta-role. Runs once per host (idempotency fact
                  _elasticstack_role_imported). Owns cert generation via
                  elasticsearch-certutil, CA lifecycle, initial password
                  handling (elasticstack-passwords.yml), and the shared
                  variables service roles read (elasticstack_release,
                  elasticstack_security, elasticstack_cert_pass,
                  elasticstack_ca_host).
  repos/          Elastic APT/YUM repo setup. Version-aware. Included
                  directly from playbooks and molecule converge.yml
                  before the service role runs — service roles never
                  pull it in themselves.
  elasticsearch/  Installs + configures Elasticsearch. Owns cluster
                  bootstrap, TLS keystore population, rolling upgrades, node
                  maintenance entry points (node_maintenance_start/_end).
  kibana/         Installs + configures Kibana. Owns Kibana keystore, Fleet
                  server config, service-account tokens.
  logstash/       Installs + configures Logstash. Owns pipelines, user/role
                  management against ES.
  beats/          Installs + configures Metricbeat/Filebeat/etc. Owns
                  module enablement, output config.
```

Each service role's `tasks/main.yml` pulls in the meta-role with
`ansible.builtin.import_role: name: oddly.elasticstack.elasticstack`;
the `_elasticstack_role_imported` fact makes subsequent imports on the
same host a no-op. Certificate generation delegates to
`elasticstack_ca_host` (defaults to the first host in the elasticsearch
group, or the current inventory host when that group is empty).

Elasticsearch has two extension points worth calling out separately:

- External `tasks_from:` entry points — invoked by callers with
  `include_role: name: … tasks_from: <name>`. Only two exist:
  `node_maintenance_start` and `node_maintenance_end` (external
  orchestrators for cluster health gating, voting exclusions, and ML
  upgrade mode). Documented in `docs/reference/elasticsearch.md`.
- Internal `include_tasks` from `main.yml` — `elasticsearch-rolling-upgrade.yml`
  fires when `elasticsearch-upgrade-detection.yml` sets
  `_elasticsearch_needs_rolling_upgrade`. Not an external entry point.

## Multi-OS

PR-time matrix: `rockylinux10`, `debian13`. Scheduled matrix expands to
`rockylinux9`, `ubuntu2204`, `ubuntu2404`, `ubuntu2604`, `debian12`,
`debian13`. Both RHEL-family and Debian-family paths need coverage —
per-OS variable files live at
`{{ ansible_facts.os_family }}_{{ ansible_facts.distribution_major_version }}.yml`
with a fallback to `{{ ansible_facts.os_family }}.yml`, loaded via
`include_vars` with `with_first_found` (see `roles/elasticsearch/tasks/main.yml`).

The heaviest scenarios by declared per-scenario memory in
`scripts/wait-for-memory.sh`: `elasticstack_default` (20 GB),
`elasticsearch_roles_calculation` (16 GB), `es_kibana` (13.8 GB),
`cert_renewal` (10.5 GB). `test_full_stack.yml` uses `max-parallel: 3`
because 6-way concurrency across the top four starved the biggest
scenarios on the shared incus-ci host — the reasoning and memory
arithmetic are in the concurrency-drop commit message (`git log
.github/workflows/test_full_stack.yml`).

## Reviewing PRs

**Diff-aware.** Don't apply the full checklist to every change:

- `scripts/`, `.github/workflows/`, `docs/`, `CLAUDE.md` — no molecule
  needed; lint + the drift/scanner check cover it. The full molecule
  matrix still fires because workflows trigger on `types: [labeled]`
  without a paths filter, so a docs-only diff will still burn the
  matrix if `ci:run` is applied.
- `roles/<name>/defaults/main.yml` or `roles/<name>/meta/argument_specs.yml`
  — always re-run `scripts/check_argspecs.py`. Both files must move
  together, and the entry-point-vs-`main` distinction matters (see the
  script docstring).
- `roles/<name>/tasks/**` — scope molecule reruns to scenarios that
  actually deploy that role. `test_full_stack.yml` runs a `changes`
  job with `dorny/paths-filter` to skip the matrix when nothing
  relevant changed; other workflows have no equivalent guard, so a
  touch on any tasks file drags the entire role matrix along.
- Bare `X is defined` gates in `when:` — the bug class this collection
  has hit repeatedly and now catches automatically via
  `scripts/check_argspecs.py`. If a variant slips past the scanner,
  fix every site in one PR — the `elasticstack_cert_pass` cascade
  needed parallel fixes in both `elasticsearch/tasks/main.yml` and
  `kibana/tasks/main.yml` before the deploy went green.

Cross-check against upstream conventions when in doubt:

- [Red Hat CoP automation good practices](https://github.com/redhat-cop/automation-good-practices)
- Official Ansible docs (`docs.ansible.com`) — prefer them over
  third-party tutorials when a directive's semantics are unclear.
