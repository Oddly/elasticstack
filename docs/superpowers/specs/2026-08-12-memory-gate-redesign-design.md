# CI memory-gate redesign for incus-ci

Date: 2026-08-12
Status: approved

## Problem

Molecule CI jobs for this collection run on a single shared machine
(`incus-ci`, LXC 305: 24 vCPU / 128 GB, holding both the 30 GitHub
runner instances and the nested incus containers at `172.30.0.172`).
Admission is currently spread over four stacked mechanisms: the runner
pool size, per-workflow `max-parallel` caps, the reservation gate in
`scripts/wait-for-memory.sh`, and a second committed-memory check with
a 90×30s retry loop inside `molecule/shared/create.yml`.

Observed failure modes (kernel journal on the Proxmox host, 30 days to
2026-08-12):

- **Per-container cgroup OOM kills, not host exhaustion.**
  `repos_default` gives its container 1024 MB and dnf/python3 peaks at
  ~960 MB (56 kills, all on rockylinux9). The dedicated Kibana
  containers in `kibana_custom` and `kibana_custom_certs` get 2048 MB
  and Kibana 9 is killed at ~1.6 GB anon RSS (25 kills). A killed
  Kibana loops under systemd restart and the converge hangs until the
  60-minute job timeout — the 2026-08-12 nightly cancelled 19 kibana
  jobs this way.
- **Systematic over-conservatism in the gate.** A job holds its full
  reservation for its entire run while its containers' real usage is
  already depressing `MemAvailable`, so capacity is double-counted and
  perceived headroom is far below real headroom. This starves the
  heavy scenarios (20 GB `elasticstack_default`, 13.8 GB `es_kibana`),
  which is why `test_full_stack.yml` carries a `max-parallel: 3`
  workaround that roughly doubled wall clock.
- **Two gates, two metrics.** `wait-for-memory.sh` reasons about
  `MemAvailable` minus reservations; `create.yml` reasons about
  committed `limits.memory`. They can disagree, and each has its own
  timeout behaviour.
- **Barge-in after timeout.** `wait-for-memory.sh` proceeds without
  headroom after its deadline, deliberately risking OOM to avoid a
  wedged queue.
- **Drift by design.** The scenario→MB table hardcoded in
  `wait-for-memory.sh` must be kept in sync with
  `molecule/<scenario>/molecule.yml` by hand.

## Decisions taken during brainstorming

- Fix both layers in one effort: per-container limits and the
  host-level gate.
- Everything stays repo-side (`scripts/`, `.github/workflows/`,
  `molecule/shared/`). No services or manual setup on incus-ci; the
  gate stays cooperative flock + files.
- Gate policy is fail-fast: a job that cannot get capacity by its
  deadline fails with a diagnostic message. No barge-in.

## Design

### 1. One ledger, one formula

`scripts/wait-for-memory.sh acquire` becomes the only admission
decision and stops reading `MemAvailable`:

```
free = MemTotal − reserve_mb − Σ committed − Σ reservations
admit when free ≥ my_need
```

- **committed** — sum of `limits.memory` over all *running* incus
  containers, read over the same `root@$INCUS_HOST` SSH path
  `create.yml` already uses. The gate has exactly three consumers —
  `molecule.yml`, `test_full_stack.yml`, and both jobs of
  `test_elasticsearch_upgrade.yml` — and in all of them the SSH-key
  setup step already precedes the acquire step, so the step gains
  `INCUS_HOST` / `MOLECULE_SSH_KEY` env and nothing else moves.
- **reservations** — files `r.<runner>` under `/tmp/molecule-gate/`
  for jobs admitted but not yet launched (see §2). One per runner
  instance, as today.
- **reserve_mb** — the 12288 MB host reserve moves from `create.yml`
  into the gate (`INCUS_RESERVE_MB`, same default). The separate
  2048 MB `WAIT_FOR_MEMORY_BUFFER_MB` is deleted: limits are hard
  cgroup caps, so `Σ limits ≤ MemTotal − reserve` is a real
  no-host-OOM guarantee rather than a heuristic needing padding.
- **my_need** — auto-derived at acquire time by summing `memory_mb`
  (default 4096) over `platforms` in
  `molecule/<scenario>/molecule.yml`, after the same
  `${VAR:-default}` envsubst resolution `create.yml` applies. The
  hardcoded `REQ` table, its 4096 fallback for unknown scenarios, and
  the update-both-places comment rule are deleted.

`MemTotal` is read from local `/proc/meminfo`; runner host and incus
host are the same machine (verified: LXC 305 owns 172.30.0.172), which
is also what makes `/tmp/molecule-gate/` a valid shared ledger between
all 30 runners and the create playbook.

### 2. Reservations convert at container launch

Lifecycle: acquire writes `r.<runner>` under the gate flock → job
proceeds to converge → **`create.yml` deletes `r.<runner>` immediately
after `incus launch` succeeds** (create runs on the runner itself,
`connection: local`; `RUNNER_NAME` is in the job env). From that
moment the job's footprint is visible to other waiters as committed
`limits.memory` instead. Every job is counted exactly once at all
times — briefly twice during the handover, which errs in the safe
direction.

`create.yml` changes:

- **CI path:** when `r.$RUNNER_NAME` exists, launch unconditionally —
  admission already happened against the same ledger. The 90×30s
  capacity-retry loop is removed. Check-and-launch stays inside the
  existing `/var/lock/molecule-create.lock` critical section.
- **Local-dev path:** when no reservation exists (developer running
  `molecule test` from a laptop; there is no acquire step), keep a
  capacity check against the same ledger — committed **plus
  reservation files** (readable over the same root SSH session) — with
  a short retry (10×30s). A laptop run can therefore not stampede CI,
  and CI reservations are respected by outsiders.
- The launch section always deletes the reservation on success,
  whether or not it used the CI path (deleting a nonexistent file is a
  no-op).

The workflow `release` step (`if: always()`) is kept: it now cleans up
the reservation only when the job died between acquire and launch, and
removes the job's queue ticket (§3). The "nothing to release" branch
covers the normal converted case. The stale-reservation TTL (3600s) GC
stays as last-resort cleanup.

Two locks coexist deliberately: admission uses the gate flock
(`/tmp/molecule-gate/.lock`), launch uses
`/var/lock/molecule-create.lock`. Consistency does not require a
common lock because every job is continuously covered by reservation
∪ committed, with only safe-direction overlap during conversion.

### 3. FIFO queue with a no-harm bypass, fail-fast

- On entry, acquire writes a ticket `q.<epoch>.<runner>` and refreshes
  its mtime on every 30s poll. Tickets not refreshed for >120s are
  GC'd under the lock (covers cancelled/killed jobs).
- Under the lock, a waiter may claim capacity only if **(a)** it holds
  the oldest live ticket, or **(b)** admitting it still leaves
  `free − my_need ≥ head_need` — small jobs keep flowing around a
  waiting heavy job but can never push it back. This is the
  starvation fix that makes §4's throughput knobs safe.
- On admission the waiter converts: writes `r.<runner>`, removes its
  ticket, releases the lock.
- At the deadline acquire exits 1 with a one-line verdict: queue
  position, head scenario and its need, committed, reservations, free.
  Gate-caused OOMs become structurally impossible; a starved job is an
  explicit retryable failure instead of a 60-minute hang.
- The deadline default becomes 2700s and the three call sites drop
  their explicit `1800` argument, relying on the default; the second
  positional argument remains supported for overrides.
- Every poll logs the same numbers so the Actions log shows the queue
  moving.

### 4. Container limits and throughput knobs

- `molecule/repos_default/molecule.yml`: container 1024 → 2048 MB.
- Kibana containers (the 2048 MB entries) in `kibana_custom`,
  `kibana_custom_certs`, and `kibana_extras`: 2048 → 3072 MB.
  `kibana_extras` has no recorded kills but is the same class.
- No scenario table to sync — the gate reads need from the same file
  being edited.
- `test_full_stack.yml` `max-parallel`: 3 → 6, reverting the
  starvation workaround this redesign obsoletes. Its 180-minute
  `timeout-minutes` stays; revisit after observation. `molecule.yml`
  keeps its default `max-parallel: 10`.

## Error handling summary

| Situation | Behaviour |
| --- | --- |
| No capacity by deadline | acquire exits 1 with queue/ledger verdict; job fails retryably at the named "Acquire memory slot" step |
| Job cancelled while queued | ticket ages out (>120s) and is GC'd by the next waiter |
| Job dies between acquire and launch | release step removes reservation; TTL GC as backstop |
| Job dies after launch | containers cleaned by `molecule destroy` / stale-container cleanup workflow; reservation already converted, so ledger self-corrects via `incus list` |
| Local dev run during CI storm | short-retry ledger check (10×30s), then fails with the capacity message |
| incus unreachable from gate | acquire fails immediately with the SSH error rather than admitting blind |

## Testing

Coordination logic gets adversarial synthetic tests first, and they
live in the repo and run on every PR — not as a one-off check before
landing.

**Testability hooks in the gate script.** The script gains three env
overrides so tests run hermetically with no incus, no SSH, and no
sleep-30 waits: `GATE_MEMINFO` (path to a fake meminfo),
`GATE_INCUS_QUERY` (command producing `incus list -f json` output —
production default is the SSH invocation), and `GATE_POLL_SECONDS`.
Production behaviour with the defaults is unchanged.

**Unit suite** at `tests/gate/` (bats-core, pinned via
`requirements-test`-style vendoring or a plain bash assert harness if
we'd rather avoid the dependency), covering:

- admission arithmetic, including `limits.memory` unit parsing
  (`MB`/`MiB`/`GB`/`GiB`, missing limit → 0) and stopped containers
  being ignored;
- need derivation from a scenario's `molecule.yml`, including the
  `${VAR:-default}` envsubst path and the 4096 MB per-platform
  default;
- reservation accounting, TTL GC, and the conversion no-op (release
  after create.yml already deleted the file);
- FIFO ordering: head admitted first; no-harm bypass admits a small
  job only when `free − need ≥ head_need`, and blocks it otherwise;
- ticket GC: a ticket not refreshed for >120s is removed and the
  queue re-heads;
- fail-fast: deadline exceeded → exit 1 and the verdict line carries
  queue position, head need, committed, reservations, free;
- **concurrency stress:** N parallel acquires (mixed needs, fake
  budget, `GATE_POLL_SECONDS=1`) with randomized start jitter; assert
  the sum of admitted needs never exceeds the budget at any point,
  no reservation file is orphaned, and admission order never violates
  the FIFO/no-harm rule. Run with a fixed seed so failures reproduce.

**CI wiring.** A `gate_tests` job on `ubuntu-latest` (everything is
mocked, no self-hosted runner needed) added to the contracts workflow,
so it runs on every PR without the `ci:run` label. `scripts/` is added
to the paths that make it mandatory.

**create.yml paths** (Ansible + flock + SSH, not unit-testable in
isolation) get a staged validation on incus-ci during a quiet window:
one manual `molecule converge` with a reservation file present (CI
path: launches unconditionally, deletes the reservation) and one
without (dev path: ledger check with short retry, respects a
planted foreign reservation). Both observed via
`/tmp/molecule-gate/` listings and `incus list`.

**Real-world acceptance**, in order:

1. One labeled `ci:run` PR exercising the standard matrix plus
   full-stack; watch gate log lines and `/tmp/molecule-gate/` while
   it runs. Pass = every job admitted or queued with moving verdict
   lines, no step relying on the deleted retry loop.
2. The next Tue/Thu/Sat nightly storm. Pass = zero cgroup OOM kills
   in the Proxmox kernel journal for `lxc.payload.*`, zero
   gate-starved failures, and full-stack wall clock measurably below
   the max-parallel:3 baseline (2026-08-12 nightly is the reference).
3. Only after (2) passes does the max-parallel 3 → 6 commit stay; if
   the storm shows starvation or OOMs, that commit is reverted first
   and the gate investigated second.

## Rollout

One PR, two commits: (1) gate rewrite + unit suite + `gate_tests` CI
job + create.yml surgery + container limit bumps (atomic — nothing
external needs to stay in sync); (2) `max-parallel` 3 → 6,
independently revertable. The staged create.yml validation happens on
the PR branch before the label goes on; the nightly-storm acceptance
run decides whether commit (2) stays.
