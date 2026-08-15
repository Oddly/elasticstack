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

## Revised plan

Do not trim off the reduced-matrix data. The instrumentation is now in
place, and the scheduled nightlies run the full distro set including
rockylinux9 and release 8. Let the sampler and teardown hook
accumulate two or three nightlies, then right-size against the
cross-distro peak — which is what those two mechanisms exist to
provide. `repos_default` in particular stays where the gate PR put it
until rockylinux9 data says otherwise. The 48-node reduced-matrix
table is kept only as a steady-state reference, not a target.

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
