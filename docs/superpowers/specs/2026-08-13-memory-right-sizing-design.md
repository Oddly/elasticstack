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

## Gap this run did not close

The scenarios the gate's own sizing notes flag as the real fat — the
config-only Elasticsearch scenarios still at 4096 with a 1 GB heap
(`elasticsearch_default`, `_custom`, `_custom_certs`,
`_custom_certs_minimal`, `_cert_content`, `_security_api`,
`_no-security`, and the ES node inside the `kibana_*` scenarios) — did
not land cleanly in this storm's sampler data. They run in the role
matrix, which executed on separate runs whose containers were torn
down before the host-side sampler stabilized. Their anon floor
(~1.9 GB for a 1 GB-heap ES node, from spot readings) suggests real
headroom against 4096, but we have no peak for them yet. Capturing
them reliably is the point of the teardown hook below.

## Next increment: teardown telemetry

The sampler is host-side and only records while it happens to be
running. To get a guaranteed per-container record on every CI run,
add a best-effort task to `molecule/shared/destroy.yml` that, before
each `incus delete`, reads from the container's top-level payload
cgroup: `memory.peak` (cache-inclusive high-water, an upper bound),
final `anon`/`file` from `memory.stat`, the limit from `memory.max`,
and `oom_kill` from `memory.events`. Append one NDJSON line per
container under `MOLECULE_EPHEMERAL_DIRECTORY` and upload it as a CI
artifact. Guard it with `failed_when: false` so telemetry can never
fail a teardown. It complements the sampler: the sampler gives the
true anon peak, the teardown record guarantees coverage and the
definitive `oom_kill` count for every scenario, including the
config-only ones this run missed.

## Out of scope

No change to `Oddly/incus-memory-gate` and no change to the gate
ledger's reservation-before-committed read order.
