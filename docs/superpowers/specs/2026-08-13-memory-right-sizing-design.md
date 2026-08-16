# Right-sizing the molecule container memory limits

Date: 2026-08-13
Status: instrumentation + proposal (no limit changes yet)

## Context

The memory gate (`Oddly/incus-memory-gate`, wired in by the gate PR)
admits jobs against the sum of committed `limits.memory` on the shared
incus-ci host. An oversized `memory_mb` in a scenario's `molecule.yml`
therefore costs concurrency: it reserves ledger capacity the container
never uses, so fewer jobs run at once than the host could safely
carry. This spec is about reclaiming that lost concurrency without
reintroducing the OOM kills the gate work just fixed.

The measurement principle and the sampler that implements it are
described in `ci/README.md`: right-size against **anon** (irreducible
RSS), captured as a per-container high-water by sampling, never
against total usage or `memory.peak`, which fill with reclaimable page
cache and read near the limit regardless of real need.

## Measured baseline (full-matrix max-load storm, 2026-08-13)

Cross-distro peak anon over a six-distro, max-parallel-6 run of the
full-stack matrix. Limits shown as the effective MiB the kernel
enforces (`memory_mb` in MB is ~4.7% higher). Zero OOM kills across
the whole run.

| node (scenario)                     | peak anon | limit  | anon% | reading                         |
|-------------------------------------|-----------|--------|-------|---------------------------------|
| logstash node (logstash_elasticsearch) | 939 MiB   | 2929   | 32%   | clear headroom                  |
| ES node (logstash_elasticsearch)    | 1690 MiB  | 3906   | 43%   | headroom                        |
| ES cluster node (elasticstack_default) | 5099 MiB  | 9765   | 52%   | moderate; cache-productive      |
| ES node (es_kibana)                 | 2110 MiB  | 4394   | 48%   | moderate                        |
| ES node (cert_renewal)              | 3865 MiB  | 5859   | 65%   | correctly sized                 |
| Kibana node (es_kibana)             | 1761 MiB  | 1953   | 90%   | tight — do not touch            |

The peak climbs through converge: the cluster node read 38% early and
52% at its peak, which is why a single snapshot is not enough and the
sampler exists.

## Proposal

Land the instrumentation now; defer every limit change until we have
two or three instrumented runs, then trim in a data-backed follow-up.
Trimming off a single storm, without PSI to confirm the container is
not thrashing cache at the smaller size, is exactly the mistake this
work exists to avoid.

When we do trim, the rules are: cut toward the cross-distro peak plus
a margin (the heaviest distro sets the floor, not the average); leave
IO/JVM working-set headroom on top of anon, more of it for
Elasticsearch nodes because the page cache backs Lucene; and watch
`oom_kill` and memory PSI on the run after each cut.

First candidates, by current signal:

- The logstash node in `logstash_elasticsearch` (939 MiB peak against a
  ~3072 MB limit) is the clearest cut — it is a Logstash JVM, not
  Lucene-backed, so it needs little cache headroom.
- The ES node in `logstash_elasticsearch` (1690 MiB) has room, but as
  an ES node it keeps a larger cache margin.

Explicitly leave alone: the Kibana node in `es_kibana` (90% of its 2 GB
limit — arguably already tight), `cert_renewal` (64-65%), and the
`elasticstack_default` cluster nodes (52% peak but heavily
cache-active during converge).

## Second dataset: full role matrix (2026-08-14), and why it is not
## yet a safe trim basis

A labelled run of the whole PR matrix, with the sampler and the
teardown hook both in place, captured 48 node-classes including the
config-only ES scenarios the storm missed (`elasticsearch_default`,
`_custom`, `_cert_content`, `_custom_certs`, `_no-security`,
`roles_calculation`, etc.). Zero OOM across all 115 teardown records.
Measured anon peaks against the current limits showed dramatic
apparent headroom: `roles_calculation` nodes at 4-5%, beats agents at
6-8%, `repos_default` at 9%, `kibana_default` at 22%, the config-only
ES nodes at 45-49%.

Those numbers are a **lower bound, not a safe trim basis**, because a
`ci:run` label triggers the `pull_request` path and therefore the
reduced PR matrix. Distro coverage in the data was debian13 and
rockylinux10 almost exclusively (rockylinux9 only 3 records, none for
repos), and releases skewed to 9. The memory high-water for these
scenarios is the package-install phase, and EL9's dnf is the hog —
`repos_default` was OOM-killed ~960 MiB on rockylinux9 (the reason the
gate PR raised it to 2048), while rockylinux10's dnf peaked under
96 MiB. rockylinux9 is exactly the distro this run did not measure, so
the low anon peaks are steady-state on the lean distros, not the
install spike on the distro that actually OOMs. Trimming any
package-installing scenario toward these numbers would walk straight
back into that OOM class.

## Third dataset: forced full distro run (2026-08-15), and the result

Rather than wait for the nightlies, we dispatched the role and
config-ES workflows on the gate branch, which fall through to the full
seven-distro, both-release matrix on `workflow_dispatch`. The sampler
captured every distro (rockylinux9 165 rows, all others 165-236) and
both releases, with zero OOM across the run.

The full data inverts the reduced-matrix picture. The memory
high-water is the package-install phase, and EL9's dnf plus the
Elasticsearch/beats install pushes almost every scenario far above the
lean-distro steady state:

- `roles_calculation`: ~85 MiB on the lean distros, 946 MiB peak on
  rockylinux9/r8.
- beats agents: ~130 MiB lean, 1073 MiB peak — trimming to 1024 would
  have OOM'd.
- `repos_default`: 961 MiB peak on rockylinux9/r8, which is why the
  gate PR raised it to 2048 and why it stays there.

Against the current limits, the cross-distro peaks land at 40-98% for
all but one scenario. The reduced-matrix "headroom" was an artifact of
the missing distros, and acting on it would have walked straight back
into the OOM class the gate work removed.

## The one change

`kibana_default` is the only genuinely over-provisioned scenario: its
single ES+Kibana node peaked at 923 MiB anon across all seven distros
and both releases, against the 4096 MB default it inherited. It is cut
to 3072 MB. The cut is conservative on purpose — that node also holds
a 2.3-2.5 GB page-cache working set, so 3072 reclaims a gigabyte of
gate ledger while keeping the cache room that ES wants; 2048 would
squeeze it and risk cache thrash. Watch memory PSI on the first run at
3072 before considering anything tighter. Every other limit is left as
measured — the current sizing, including the gate PR's bumps, is
correct once rockylinux9 and release 8 are in the data.

## Teardown telemetry (implemented)

The sampler is host-side and only records while it happens to be
running. To get a guaranteed per-container record on every CI run,
`molecule/shared/destroy.yml` now runs a best-effort task before each
`incus delete` that reads the container's top-level payload cgroup:
`memory.peak` (cache-inclusive high-water, an upper bound), final
`anon`/`file` from `memory.stat`, the limit from `memory.max`, and
`oom_kill` from `memory.events`. It writes one NDJSON line per
container to an accumulating ledger on the host
(`/root/mem-peaks/teardown.ndjson`) and a copy under
`MOLECULE_EPHEMERAL_DIRECTORY`, and is guarded with
`failed_when: false` so telemetry can never fail a teardown. It
complements the sampler: the sampler gives the true anon peak, the
teardown record guarantees coverage and the definitive `oom_kill`
count for every scenario, including the config-only ones this storm
missed.

This lands unvalidated against a live container (none were running
when it was written; the read logic was tested against a substitute
cgroup). The first labelled CI run on this branch is what confirms it
end to end; because it is `failed_when: false` it cannot break that
run even if a field reads wrong.

## Out of scope

No change to `Oddly/incus-memory-gate` and no change to the gate
ledger's reservation-before-committed read order.
