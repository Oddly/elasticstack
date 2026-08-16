# CI memory measurement

This directory holds the tooling we use to right-size the molecule
container memory limits (`memory_mb` in each `molecule/<scenario>/molecule.yml`)
against real measurements instead of guesswork.

## Why anon, not usage

The memory gate (`Oddly/incus-memory-gate`, wired into the workflows by
the gate PR) admits jobs against the sum of committed `limits.memory`,
so an oversized limit costs concurrency rather than safety. The
question "is this limit too high" therefore comes down to how much
memory a container genuinely needs.

The trap is that a container's total usage climbs toward its limit
because the kernel fills the spare room with reclaimable page cache.
Reading `memory.peak` (or incus `usage_peak`) shows peak ≈ limit even
when the working set is far smaller, so it is useless for
right-sizing. The number that matters is **anon** — anonymous RSS,
which cannot be reclaimed and is what the OOM killer acts on. There is
no kernel high-water counter for anon alone, so we sample it.

## anon-peak-sampler.sh

Runs on the incus host (the runner LXC, `incus-ci`). Every second it
reads, for each running container, the `anon` line from the
container's **top-level** `lxc.payload.<name>` cgroup `memory.stat`
(this is hierarchical, so it is the whole-container total), and keeps
the high-water mark per container across its whole life — a peak
survives the container being destroyed. It also records the limit,
peak cache alongside for context, and the cgroup `oom_kill` count.

Read the top-level payload cgroup, not the container init PID's
cgroup: the init process sits in an `init.scope` leaf that reports a
couple of MiB, so resolving via `/proc/<pid>/cgroup` badly under-reads.

Deploy it as a systemd unit on the host so it survives ssh and session
drops:

```ini
# /etc/systemd/system/anon-peak-sampler.service
[Unit]
Description=Per-container anon RSS peak sampler (incus-ci right-sizing)
[Service]
Environment=INTERVAL=1
Environment=OUT=/root/mem-peaks
Environment=NDJSON=/root/mem-peaks/ts.ndjson
ExecStart=/usr/bin/bash /root/anon-peak-sampler.sh
Restart=on-failure
RestartSec=2
[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now anon-peak-sampler
cat /root/mem-peaks/peaks.txt        # live table, rewritten every tick
```

Outputs in `$OUT`: `peaks.txt` (human table, per scenario-class and
per container), `peaks.tsv` (persistent state, resumed on restart),
and `ts.ndjson` (per-tick time-series when `NDJSON` is set).

## Interpreting the numbers

Rank by anon%. A container sitting well under its limit on anon is a
trim candidate; one near its limit is correctly sized or tight and
must be left alone. Trim toward the cross-distro peak plus a margin,
never the average — the heaviest distro sets the floor. Leave real
IO/JVM working-set headroom on top: for Elasticsearch especially, the
page cache backs Lucene, so cutting to the anon floor invites cache
thrash and flaky converges even when it never OOMs. After any trim,
watch `oom_kill` and memory PSI on the next run before trusting it.
