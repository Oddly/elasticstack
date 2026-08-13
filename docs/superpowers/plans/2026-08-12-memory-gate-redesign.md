# Memory-Gate Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the memory gate as a reusable public repo (`Oddly/incus-memory-gate`: script + composite action + hermetic test suite + own CI), and convert oddly/elasticstack into its first consumer (create.yml reservation conversion, container limit fixes, thin `uses:` wiring, max-parallel back to 6).

**Architecture:** The gate is a single-authority admission decision — `MemTotal − reserve − Σ committed limits.memory − Σ pending reservations` — with FIFO queueing, bounded overtakes (K=10), and fail-fast at a deadline. Reservations convert into committed capacity when the consumer's launch step deletes the reservation file right after `incus launch` (contract: file `r.<runner>` in the gate dir, content `<need_mb> <label>`). The gate repo owns the logic and tests; consumers own launch-side conversion and their capacity budgets.

**Tech Stack:** bash (flock, GNU coreutils), python3 + PyYAML (parsing helpers), composite GitHub Action, Ansible/molecule (consumer side).

**Spec:** `docs/superpowers/specs/2026-08-12-memory-gate-redesign-design.md` (approved, incl. the 2026-08-13 Packaging section). Read it before starting.

## Global Constraints

- Two working directories: gate repo `~/git/incus-memory-gate` (branch `main`, new repo — direct commits are fine) and consumer `~/git/elasticstack` (branch `ci/memory-gate-redesign`). Every task names its repo.
- Commit style (both repos): Conventional Commits — `type(scope): imperative subject`, lowercase after colon, no trailing period; bodies are plain prose paragraphs, first person. NEVER mention any LLM/AI assistant in commits, code, or comments. No co-author trailers.
- elasticstack: `yamllint .` and `ansible-lint` must be clean before any push; Ansible FQCN always.
- The gate tests are Linux-only (`flock`, GNU `stat -c`, `touch -d`). On this macOS workstation run them via Docker (image `gate-test` = python:3.12-slim + pyyaml, already built):
  `tar c -C ~/git/incus-memory-gate . | docker run --rm -i gate-test bash -c 'mkdir /r && tar x -C /r && cd /r && bash tests/run-tests.sh'`
- Gate env contract: `RUNNER_NAME`, `INCUS_HOST`, `MOLECULE_SSH_KEY`, `MOLECULE_GATE_DIR` (default `/tmp/molecule-gate`), `INCUS_RESERVE_MB` (default `12288`), `INCUS_DEFAULT_MEMORY_MB` (default `4096`), `MOLECULE_GATE_TTL` (default `3600`), `GATE_TICKET_STALE_SECONDS` (default `120`), `GATE_MAX_OVERTAKES` (default `10`), `GATE_MEMINFO` (default `/proc/meminfo`), `GATE_INCUS_QUERY` (default: ssh incus list), `GATE_POLL_SECONDS` (default `30`). **Empty-string env values count as unset** (the action passes inputs through unconditionally) — every default goes through the `cfg` helper.
- Gate CLI: `wait-for-memory.sh acquire (--need-mb <MB> | --molecule-scenario <name>) [--label <name>] [--deadline <seconds>]` (deadline default 2700; label defaults to the scenario name, else `job`) and `wait-for-memory.sh release`.
- Gate file formats: reservation `r.<runner>` contains `<need_mb> <label>`; ticket `q.<epoch10>.<runner>` contains `<need_mb> <label> <overtakes>`. Ticket owners refresh with `touch` only (preserving the counter); only a bypasser rewrites a ticket.

---

### Task 1: Gate repo scaffold + test harness

**Repo:** `~/git/incus-memory-gate` (create it)

**Files:**
- Create: repo on GitHub (`Oddly/incus-memory-gate`, public) and locally
- Create: `LICENSE` (GPL-3.0, copied from elasticstack), `README.md` (skeleton), `.github/workflows/test.yml`
- Create: `tests/helpers.sh`, `tests/run-tests.sh`, `tests/test_harness.sh` (ported from the preserved elasticstack harness at `~/git/elasticstack/.superpowers/sdd/2026-08-12-memory-gate-redesign/ported-harness/`)

**Interfaces:**
- Produces: harness helper names every later test task uses verbatim — `setup`, `set_mem_total <mb>`, `set_incus_containers "<name>:<status>:<limit>" ...`, `make_scenario <name> <mb|none> ...`, `run_gate <runner> <action> [args...]`, `assert_eq`, `assert_file`, `assert_no_file` — and the env vars `setup` exports (see Global Constraints; `setup` sets the `GATE_*` test hooks, `INCUS_RESERVE_MB=0`, and a 10240 MB MemTotal).

- [ ] **Step 1: Create the repo**

```bash
gh repo create Oddly/incus-memory-gate --public \
  --description "Memory admission gate for CI jobs sharing one incus host: committed-limits ledger, FIFO queue with bounded overtakes, fail-fast" \
  --clone
mv incus-memory-gate ~/git/ 2>/dev/null || true
cd ~/git/incus-memory-gate
cp ~/git/elasticstack/LICENSE LICENSE
```

- [ ] **Step 2: Port the harness** — copy the three files from `~/git/elasticstack/.superpowers/sdd/2026-08-12-memory-gate-redesign/ported-harness/` into `tests/`, then apply exactly these adaptations:

In `tests/helpers.sh`:
- `GATE_SCRIPT` resolves to the repo root script:
  ```bash
  GATE_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/wait-for-memory.sh"
  ```
- `run_gate` stays exactly:
  ```bash
  run_gate() {
    local name="$1"
    shift
    (cd "$REPO_FAKE" && RUNNER_NAME="$name" bash "$GATE_SCRIPT" "$@")
  }
  ```
  (callers now pass CLI flags, e.g. `run_gate r1 acquire --molecule-scenario demo --deadline 1`).

`tests/run-tests.sh` and `tests/test_harness.sh` are unchanged apart from living in `tests/` instead of `tests/gate/`.

- [ ] **Step 3: Write `README.md` skeleton** (completed in Task 5):

```markdown
# incus-memory-gate

Memory admission gate for CI jobs that share one incus host:
a committed-limits ledger, a FIFO queue with bounded overtakes,
and fail-fast semantics. Ships as a composite GitHub Action and
as a plain script.

Documentation lands with the first release; see `action.yml` and
the header of `wait-for-memory.sh` for the contract.
```

- [ ] **Step 4: Write `.github/workflows/test.yml`**

```yaml
---
name: Test
on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  gate_tests:
    # The suite is hermetic (fake meminfo, fake incus query, tmpdir gate
    # state) — no incus and no self-hosted runner needed.
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Check out code
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1

      - name: Install PyYAML
        run: python3 -m pip install --user pyyaml

      - name: Run gate tests
        run: bash tests/run-tests.sh

  shellcheck:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - name: Check out code
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1

      - name: Shellcheck the gate and tests
        run: shellcheck wait-for-memory.sh tests/*.sh
```

- [ ] **Step 5: Run the suite in the Linux test env; expect the harness smoke test green**

Run: `tar c -C ~/git/incus-memory-gate . | docker run --rm -i gate-test bash -c 'mkdir /r && tar x -C /r && cd /r && bash tests/run-tests.sh'`
Expected: `gate tests: 1 passed, 0 failed` (only `test_harness.sh` exists; it does not invoke the gate script).

- [ ] **Step 6: Commit and push**

```bash
git add -A
git commit -m "chore: scaffold the gate repo with its hermetic test harness"
git push -u origin main
```
Then check `gh run watch` (or `gh run list --limit 1`) — the `gate_tests` job must pass on GitHub too; `shellcheck` must pass on the test files (the gate script doesn't exist yet, so keep `wait-for-memory.sh` out of the shellcheck args until Task 2 — use `shellcheck tests/*.sh` in this commit and extend it in Task 2).

---

### Task 2: Gate script — admission ledger, lifecycle, fail-fast (strict FIFO)

**Repo:** `~/git/incus-memory-gate`

**Files:**
- Create: `wait-for-memory.sh`
- Create: `tests/test_admission.sh`, `tests/test_lifecycle.sh`
- Modify: `.github/workflows/test.yml` (shellcheck args gain `wait-for-memory.sh`)

**Interfaces:**
- Consumes: harness helpers from Task 1.
- Produces: the gate CLI from Global Constraints (exit 0 admitted / exit 1 starved / exit 2 usage); log vocabulary `need=`, `committed=`, `reserved=`, `free=`, `ADMITTED`, `STARVED`, `released`, `nothing to release` (tests grep these); the `cfg` helper pattern; gate file formats. Task 3 adds the overtake branch at the `# BYPASS` marker; everything else is final here.

- [ ] **Step 1: Write `tests/test_admission.sh`**

```bash
#!/usr/bin/env bash
source "$(dirname "$0")/helpers.sh"
setup

# 1. need derivation sums platform memory_mb (molecule mode)
make_scenario demo 4096 2048
out=$(run_gate r1 acquire --molecule-scenario demo --deadline 1)
echo "$out" | grep -q 'need=6144MB' || { echo "derivation: $out"; exit 1; }
run_gate r1 release >/dev/null

# 2. platform without memory_mb falls back to 4096
make_scenario nodefault none
out=$(run_gate r2 acquire --molecule-scenario nodefault --deadline 1)
echo "$out" | grep -q 'need=4096MB' || { echo "default: $out"; exit 1; }
run_gate r2 release >/dev/null

# 3. ${VAR:-default} resolution in molecule.yml
mkdir -p "$REPO_FAKE/molecule/envsub"
cat > "$REPO_FAKE/molecule/envsub/molecule.yml" <<'EOF'
platforms:
  - name: "es-${MOLECULE_DISTRO:-debian12}"
    memory_mb: ${TEST_MEM_MB:-2048}
EOF
out=$(run_gate r3 acquire --molecule-scenario envsub --deadline 1)
echo "$out" | grep -q 'need=2048MB' || { echo "envsub default: $out"; exit 1; }
run_gate r3 release >/dev/null
out=$(TEST_MEM_MB=512 run_gate r4 acquire --molecule-scenario envsub --deadline 1)
echo "$out" | grep -q 'need=512MB' || { echo "envsub override: $out"; exit 1; }
run_gate r4 release >/dev/null

# 4. --need-mb mode with a label; reservation carries the label
out=$(run_gate r10 acquire --need-mb 1536 --label build-job --deadline 1)
echo "$out" | grep -q 'need=1536MB' || { echo "need-mb mode: $out"; exit 1; }
grep -q '^1536 build-job$' "$MOLECULE_GATE_DIR/r.r10" || { echo "label missing"; exit 1; }
run_gate r10 release >/dev/null

# 5. exactly one of --need-mb / --molecule-scenario is required
if run_gate r11 acquire --deadline 1 >/dev/null 2>&1; then
  echo "acquire without a need source must fail"; exit 1
fi
if run_gate r12 acquire --need-mb 512 --molecule-scenario demo --deadline 1 >/dev/null 2>&1; then
  echo "acquire with both need sources must fail"; exit 1
fi

# 6. limits.memory unit parsing; stopped containers ignored
set_incus_containers "a:Running:1GiB" "b:Running:1024MiB" "c:Running:1GB" "d:Stopped:512GB"
make_scenario small 1024
out=$(run_gate r5 acquire --molecule-scenario small --deadline 1)
echo "$out" | grep -q 'committed=3072MB' || { echo "units: $out"; exit 1; }
run_gate r5 release >/dev/null

# 7. blocked -> fail fast with verdict, ticket cleaned up
set_incus_containers "big:Running:8192MB"      # free = 10240 - 8192 = 2048
make_scenario heavy 4096
if out=$(run_gate r6 acquire --molecule-scenario heavy --deadline 1 2>&1); then
  echo "should have starved: $out"; exit 1
fi
echo "$out" | grep -q 'STARVED' || { echo "verdict: $out"; exit 1; }
assert_no_file "$MOLECULE_GATE_DIR/r.r6"
[ -z "$(ls "$MOLECULE_GATE_DIR" 2>/dev/null | grep '^q\.')" ] || { echo "ticket leaked"; exit 1; }

# 8. foreign reservations count against free
set_incus_containers
echo "8192 other" > "$MOLECULE_GATE_DIR/r.other"
make_scenario mid 4096                          # free = 10240 - 8192 = 2048
if run_gate r7 acquire --molecule-scenario mid --deadline 1 >/dev/null 2>&1; then
  echo "reservation not counted"; exit 1
fi
rm -f "$MOLECULE_GATE_DIR/r.other"

# 9. incus query failure -> refuse to admit, non-zero exit
make_scenario small2 1024
if GATE_INCUS_QUERY=false run_gate r8 acquire --molecule-scenario small2 --deadline 1 >/dev/null 2>&1; then
  echo "admitted blind on query failure"; exit 1
fi

# 10. no INCUS_HOST and no GATE_INCUS_QUERY -> clear failure
if (unset GATE_INCUS_QUERY INCUS_HOST; run_gate r9 acquire --molecule-scenario small2 --deadline 1 >/dev/null 2>&1); then
  echo "admitted blind without a query source"; exit 1
fi

# 11. empty-string env counts as unset (the action passes inputs through)
out=$(INCUS_RESERVE_MB= GATE_MAX_OVERTAKES= run_gate r13 acquire --need-mb 1024 --deadline 1)
echo "$out" | grep -q 'reserve=12288MB' || { echo "cfg empty-env: $out"; exit 1; }
run_gate r13 release >/dev/null

echo OK
```

Note on case 11: `setup` exports `INCUS_RESERVE_MB=0`, so this case overrides it to the empty string and expects the built-in 12288 default to kick in — with MemTotal 10240 that makes free negative, so… **it must starve, not admit.** Write case 11 as:

```bash
if out=$(INCUS_RESERVE_MB= run_gate r13 acquire --need-mb 1024 --deadline 1 2>&1); then
  echo "empty INCUS_RESERVE_MB must mean default 12288, which cannot fit: $out"; exit 1
fi
echo "$out" | grep -q 'reserve=12288MB' || { echo "cfg empty-env: $out"; exit 1; }
```

- [ ] **Step 2: Write `tests/test_lifecycle.sh`**

```bash
#!/usr/bin/env bash
source "$(dirname "$0")/helpers.sh"
setup

# 1. release removes reservation and any ticket for the runner
echo "1024 x" > "$MOLECULE_GATE_DIR/r.rel1"
echo "1024 x 0" > "$MOLECULE_GATE_DIR/q.0000000001.rel1"
out=$(run_gate rel1 release)
echo "$out" | grep -q 'released' || { echo "release: $out"; exit 1; }
assert_no_file "$MOLECULE_GATE_DIR/r.rel1"
assert_no_file "$MOLECULE_GATE_DIR/q.0000000001.rel1"

# 2. release after the launcher already converted the reservation is a no-op
out=$(run_gate rel2 release)
echo "$out" | grep -q 'nothing to release' || { echo "noop release: $out"; exit 1; }

# 3. reservations older than the TTL are garbage-collected by acquire
echo "4096 stale" > "$MOLECULE_GATE_DIR/r.dead"
touch -d '2 hours ago' "$MOLECULE_GATE_DIR/r.dead"
make_scenario mid2 8192                # if stale counted: 10240-4096=6144 < 8192
run_gate live acquire --molecule-scenario mid2 --deadline 1 >/dev/null \
  || { echo "stale reservation not GCd"; exit 1; }
assert_no_file "$MOLECULE_GATE_DIR/r.dead"
run_gate live release >/dev/null

echo OK
```

- [ ] **Step 3: Run the suite to verify the new tests fail** (no `wait-for-memory.sh` exists yet)

Run: `tar c -C ~/git/incus-memory-gate . | docker run --rm -i gate-test bash -c 'mkdir /r && tar x -C /r && cd /r && bash tests/run-tests.sh'`
Expected: `test_harness.sh` passes; `test_admission.sh` and `test_lifecycle.sh` FAIL (script missing).

- [ ] **Step 4: Write `wait-for-memory.sh`** (complete file; the `# BYPASS` marker line is where Task 3 inserts the overtake branch)

```bash
#!/usr/bin/env bash
# Memory admission gate for CI jobs sharing one incus host.
#
# Admission formula (all MB):
#
#   free = MemTotal - reserve - committed - reservations
#   admit when free >= my_need
#
#   committed    sum of limits.memory over *running* incus containers
#   reservations jobs admitted here whose containers are not launched yet;
#                the consumer's launch step deletes the reservation right
#                after `incus launch`, converting it into committed capacity
#   my_need      --need-mb, or --molecule-scenario <name>: the sum of
#                memory_mb (default 4096) over the platforms in
#                molecule/<name>/molecule.yml relative to the working
#                directory, after ${VAR:-default} resolution
#
# Queueing: FIFO tickets with bounded overtakes. A waiter that fits may
# bypass a blocked head until the head's ticket has been overtaken
# GATE_MAX_OVERTAKES times; then the queue is strict until the head is
# admitted. At the deadline the gate FAILS (exit 1) instead of barging in:
# a starved job is an explicit retryable failure, not an OOM risk.
#
# Usage:
#   wait-for-memory.sh acquire --need-mb <MB> [--label <name>] [--deadline <s>]
#   wait-for-memory.sh acquire --molecule-scenario <name> [--label <name>] [--deadline <s>]
#   wait-for-memory.sh release
#
# Env (an empty value counts as unset — a composite action passes its
# inputs through unconditionally):
#   RUNNER_NAME               one reservation/ticket per runner instance
#   INCUS_HOST                host queried for running containers
#   MOLECULE_SSH_KEY          key for that query (optional if agent/config)
#   MOLECULE_GATE_DIR         default /tmp/molecule-gate
#   INCUS_RESERVE_MB          host OS/runner/incusd reserve, default 12288
#   INCUS_DEFAULT_MEMORY_MB   per-platform default, 4096
#   MOLECULE_GATE_TTL         reservation GC age, default 3600
#   GATE_TICKET_STALE_SECONDS ticket GC age, default 120
#   GATE_MAX_OVERTAKES        bypasses a head tolerates, default 10
#   GATE_MEMINFO              test hook, default /proc/meminfo
#   GATE_INCUS_QUERY          test hook: command emitting `incus list -f json`
#   GATE_POLL_SECONDS         test hook, default 30

set -euo pipefail

cfg() {  # cfg VAR DEFAULT — empty env value counts as unset
  local v="${!1:-}"
  if [ -n "$v" ]; then echo "$v"; else echo "$2"; fi
}

action="${1:?usage: $0 <acquire|release> [args...]}"
shift

GATE_DIR=$(cfg MOLECULE_GATE_DIR /tmp/molecule-gate)
mkdir -p "$GATE_DIR"
chmod 0777 "$GATE_DIR" 2>/dev/null || true
LOCK="$GATE_DIR/.lock"

TTL_SEC=$(cfg MOLECULE_GATE_TTL 3600)
TICKET_STALE_SEC=$(cfg GATE_TICKET_STALE_SECONDS 120)
POLL_SEC=$(cfg GATE_POLL_SECONDS 30)
RESERVE_MB=$(cfg INCUS_RESERVE_MB 12288)
MEMINFO=$(cfg GATE_MEMINFO /proc/meminfo)
MAX_OVERTAKES=$(cfg GATE_MAX_OVERTAKES 10)

runner=$(cfg RUNNER_NAME "runner-$$")
my_resv="$GATE_DIR/r.${runner}"

mem_total_mb() { awk '/^MemTotal:/{print int($2/1024); exit}' "$MEMINFO"; }

incus_query() {
  local q
  q=$(cfg GATE_INCUS_QUERY "")
  if [ -n "$q" ]; then
    $q
  else
    local host key
    host=$(cfg INCUS_HOST "")
    key=$(cfg MOLECULE_SSH_KEY "")
    [ -n "$host" ] || {
      echo "INCUS_HOST or GATE_INCUS_QUERY must be set - refusing to admit blind" >&2
      return 1
    }
    # shellcheck disable=SC2086
    ssh -o StrictHostKeyChecking=no -o BatchMode=yes \
      ${key:+-i "$key"} \
      "root@${host}" -- incus list -f json --project default < /dev/null
  fi
}

committed_mb() {
  incus_query | python3 -c '
import json, re, sys
total = 0
for c in json.load(sys.stdin):
    if c.get("status") != "Running":
        continue
    mem = (c.get("config") or {}).get("limits.memory") or "0"
    m = re.match(r"(\d+)\s*(GB|GiB|MB|MiB)?", mem)
    if m:
        val = int(m.group(1))
        if (m.group(2) or "MB").upper() in ("GB", "GIB"):
            val *= 1024
        total += val
print(total)
'
}

derive_need_mb() {  # $1 = scenario name; resolves molecule/<name>/molecule.yml from CWD
  python3 -c '
import os, re, sys, yaml
raw = open(sys.argv[1]).read()
raw = re.sub(
    r"\$\{(\w+)(?::-([^}]*))?\}",
    lambda m: os.environ.get(m.group(1), m.group(2) or ""),
    raw,
)
default = int(os.environ.get("INCUS_DEFAULT_MEMORY_MB") or "4096")
platforms = (yaml.safe_load(raw) or {}).get("platforms", [])
print(sum(int(p.get("memory_mb", default)) for p in platforms))
' "molecule/$1/molecule.yml"
}

file_field() {  # $1 file, $2 field index, $3 default when missing/empty
  local v
  v=$(awk -v n="$2" 'NR==1{print $n}' "$1" 2>/dev/null || true)
  echo "${v:-$3}"
}

gc_and_sum_reservations() {  # call under the lock; echoes reserved_mb
  local now total=0 mtime f
  now=$(date +%s)
  shopt -s nullglob
  for f in "$GATE_DIR"/r.*; do
    mtime=$(stat -c %Y "$f" 2>/dev/null || echo 0)
    if [ $(( now - mtime )) -gt "$TTL_SEC" ]; then
      rm -f "$f"
      continue
    fi
    total=$(( total + $(file_field "$f" 1 0) ))
  done
  shopt -u nullglob
  echo "$total"
}

gc_tickets() {  # call under the lock
  local now mtime f
  now=$(date +%s)
  shopt -s nullglob
  for f in "$GATE_DIR"/q.*; do
    mtime=$(stat -c %Y "$f" 2>/dev/null || echo 0)
    if [ $(( now - mtime )) -gt "$TICKET_STALE_SEC" ]; then
      rm -f "$f"
    fi
  done
  shopt -u nullglob
}

case "$action" in
  acquire)
    need="" label="" scenario="" timeout_s=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --need-mb)           need="$2"; shift 2 ;;
        --molecule-scenario) scenario="$2"; shift 2 ;;
        --label)             label="$2"; shift 2 ;;
        --deadline)          timeout_s="$2"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
      esac
    done
    if { [ -n "$need" ] && [ -n "$scenario" ]; } || { [ -z "$need" ] && [ -z "$scenario" ]; }; then
      echo "acquire needs exactly one of --need-mb or --molecule-scenario" >&2
      exit 2
    fi
    if [ -n "$scenario" ]; then
      need=$(derive_need_mb "$scenario")
      label="${label:-$scenario}"
    fi
    label="${label:-job}"
    timeout_s="${timeout_s:-2700}"

    total=$(mem_total_mb)
    my_ticket="$GATE_DIR/q.$(printf '%010d' "$(date +%s)").${runner}"

    printf 'molecule-gate[%s]: acquire label=%s need=%dMB total=%dMB reserve=%dMB timeout=%ds\n' \
      "$runner" "$label" "$need" "$total" "$RESERVE_MB" "$timeout_s"

    deadline=$(( $(date +%s) + timeout_s ))
    attempt=0
    while :; do
      attempt=$(( attempt + 1 ))
      exec 9>"$LOCK"
      flock 9
      if [ -f "$my_ticket" ]; then
        touch "$my_ticket"   # refresh liveness; preserves the overtake counter
      else
        printf '%d %s 0\n' "$need" "$label" > "$my_ticket"
      fi
      gc_tickets
      reserved=$(gc_and_sum_reservations)
      committed=$(committed_mb)
      free=$(( total - RESERVE_MB - committed - reserved ))

      head=$(ls -1 "$GATE_DIR"/q.* 2>/dev/null | sort | head -n1 || true)
      head_need=$(file_field "$head" 1 0)
      head_overtakes=$(file_field "$head" 3 0)

      admit=no
      if [ "$free" -ge "$need" ]; then
        if [ "$head" = "$my_ticket" ]; then
          admit=yes
        fi
        # BYPASS: bounded-overtake branch added in a follow-up commit
      fi

      if [ "$admit" = yes ]; then
        printf '%d %s\n' "$need" "$label" > "$my_resv"
        rm -f "$my_ticket"
        flock -u 9
        printf 'molecule-gate[%s]: ADMITTED committed=%dMB reserved=%dMB free=%dMB need=%dMB (attempt %d)\n' \
          "$runner" "$committed" "$reserved" "$free" "$need" "$attempt"
        exit 0
      fi

      position=$(ls -1 "$GATE_DIR"/q.* 2>/dev/null | sort | grep -n -x -F "$my_ticket" | cut -d: -f1 || true)
      flock -u 9

      now=$(date +%s)
      if [ "$now" -ge "$deadline" ]; then
        exec 9>"$LOCK"
        flock 9
        rm -f "$my_ticket"
        flock -u 9
        printf 'molecule-gate[%s]: STARVED after %ds: position=%s head_need=%dMB head_overtakes=%s committed=%dMB reserved=%dMB free=%dMB need=%dMB\n' \
          "$runner" "$timeout_s" "${position:-?}" "$head_need" "$head_overtakes" "$committed" "$reserved" "$free" "$need" >&2
        exit 1
      fi
      printf 'molecule-gate[%s]: waiting position=%s head_need=%dMB head_overtakes=%s committed=%dMB reserved=%dMB free=%dMB need=%dMB (attempt %d)\n' \
        "$runner" "${position:-?}" "$head_need" "$head_overtakes" "$committed" "$reserved" "$free" "$need" "$attempt"
      sleep "$POLL_SEC"
    done
    ;;

  release)
    exec 9>"$LOCK"
    flock 9
    if [ -f "$my_resv" ]; then
      rm -f "$my_resv"
      printf 'molecule-gate[%s]: released\n' "$runner"
    else
      printf 'molecule-gate[%s]: nothing to release\n' "$runner"
    fi
    rm -f "$GATE_DIR"/q.*."$runner"
    flock -u 9
    ;;

  *)
    echo "usage: $0 <acquire|release> [args...]" >&2
    exit 2
    ;;
esac
```

Implementation notes, read before writing:
- `committed_mb` runs **inside** the lock. Reading it outside opens a race where a just-converted job is counted neither as reservation nor as committed, over-admitting a waiter.
- `set -e` + command substitution: helpers that can fail end in `|| true` / `|| echo 0` internally, so assignments don't kill the script; the deliberate exceptions are `committed_mb` and `derive_need_mb` — their failure MUST abort (never admit blind).
- Ticket filenames embed a zero-padded epoch so lexical `sort` is FIFO order; ties sort by runner name, which is stable and fair enough.
- `rm -f "$GATE_DIR"/q.*."$runner"` in release: an unmatched glob expands to itself and `rm -f` ignores it — no nullglob needed there.
- `chmod +x wait-for-memory.sh`.

- [ ] **Step 5: Extend shellcheck in `.github/workflows/test.yml`** — change the shellcheck step's run line to:

```yaml
        run: shellcheck wait-for-memory.sh tests/*.sh
```

- [ ] **Step 6: Run the suite; expect all three files green**

Run: `tar c -C ~/git/incus-memory-gate . | docker run --rm -i gate-test bash -c 'mkdir /r && tar x -C /r && cd /r && bash tests/run-tests.sh'`
Expected: `gate tests: 3 passed, 0 failed`
Also run shellcheck locally: `docker run --rm -v ~/git/incus-memory-gate:/mnt koalaman/shellcheck:stable wait-for-memory.sh tests/*.sh` (or `shellcheck` if installed) — clean or justified disables only.

- [ ] **Step 7: Commit and push; confirm the repo CI is green**

```bash
git add wait-for-memory.sh tests/test_admission.sh tests/test_lifecycle.sh .github/workflows/test.yml
git commit -m "feat: admission gate on a committed-limits ledger with fail-fast"
git push && gh run watch --exit-status
```

---

### Task 3: Bounded-overtake queue policy

**Repo:** `~/git/incus-memory-gate`

**Files:**
- Modify: `wait-for-memory.sh` (the `# BYPASS` marker inside the admission decision)
- Create: `tests/test_queue.sh`

**Interfaces:**
- Consumes: the gate CLI and file formats from Task 2; harness helpers from Task 1.
- Produces: the final admission decision. `GATE_MAX_OVERTAKES` becomes honored.

- [ ] **Step 1: Write `tests/test_queue.sh`**

```bash
#!/usr/bin/env bash
source "$(dirname "$0")/helpers.sh"
setup

# 1. blocked head admits as soon as capacity frees (FIFO base case)
set_incus_containers "big:Running:9216MB"        # free = 1024
make_scenario twoG 2048
run_gate first acquire --molecule-scenario twoG --deadline 6 >/dev/null &
fpid=$!
sleep 1
set_incus_containers                              # capacity freed
wait "$fpid" || { echo "head should admit after capacity frees"; exit 1; }
run_gate first release >/dev/null

# 2. a smaller job bypasses a blocked head and increments its counter
set_incus_containers "big:Running:8192MB"        # free = 2048
make_scenario huge 4096
make_scenario tiny 1024
run_gate heavy acquire --molecule-scenario huge --deadline 8 >/dev/null 2>&1 &
hpid=$!
sleep 1                                           # heavy is now the head
GATE_MAX_OVERTAKES=10 run_gate quick acquire --molecule-scenario tiny --deadline 3 >/dev/null \
  || { echo "bypass should admit a fitting job"; exit 1; }
grep -q ' 1$' "$MOLECULE_GATE_DIR"/q.*.heavy \
  || { echo "head counter not incremented"; exit 1; }
run_gate quick release >/dev/null

# 3. owner refresh preserves the counter; at K the queue goes strict
head_ticket=$(ls "$MOLECULE_GATE_DIR"/q.*.heavy)
need=$(awk '{print $1}' "$head_ticket")
lbl=$(awk '{print $2}' "$head_ticket")
printf '%s %s 10\n' "$need" "$lbl" > "$head_ticket"
sleep 1   # heavy keeps polling; if it rewrote its ticket the counter resets
if GATE_MAX_OVERTAKES=10 run_gate quick2 acquire --molecule-scenario tiny --deadline 2 >/dev/null 2>&1; then
  echo "strict phase must refuse bypass at K overtakes"; exit 1
fi
grep -q ' 10$' "$head_ticket" || { echo "owner refresh clobbered the counter"; exit 1; }

# 4. the starved head cleans up its ticket on the way out
wait "$hpid" && { echo "heavy should have starved"; exit 1; }
[ -z "$(ls "$MOLECULE_GATE_DIR" 2>/dev/null | grep '^q\.')" ] \
  || { echo "starved head leaked its ticket"; exit 1; }

# 5. a stale ticket (dead job) stops blocking the queue
set_incus_containers "big:Running:8192MB"        # free = 2048
echo "9999 ghost 0" > "$MOLECULE_GATE_DIR/q.0000000001.ghost"
touch -d '1 minute ago' "$MOLECULE_GATE_DIR/q.0000000001.ghost"
GATE_MAX_OVERTAKES=0 run_gate solo acquire --molecule-scenario tiny --deadline 3 >/dev/null \
  || { echo "stale ticket should be GCd, not block"; exit 1; }
run_gate solo release >/dev/null

echo OK
```

- [ ] **Step 2: Run the suite to see the new tests fail**

Run: the Docker suite command from Global Constraints.
Expected: `test_queue.sh` FAILS at case 2 (no bypass branch yet); the other three files stay green.

- [ ] **Step 3: Add the bypass branch** — replace the `# BYPASS` marker inside the `if [ "$free" -ge "$need" ]` block with:

```bash
        elif [ "$head_overtakes" -lt "$MAX_OVERTAKES" ]; then
          # Bounded overtake: keep capacity utilized while the head cannot
          # fit, but count every bypass on the head ticket. At the cap the
          # queue goes strict until the head is admitted, so a heavy
          # job's extra wait is bounded by K admissions' releases.
          admit=yes
          head_label=$(file_field "$head" 2 unknown)
          printf '%s %s %d\n' "$head_need" "$head_label" \
            $(( head_overtakes + 1 )) > "$head"
```

- [ ] **Step 4: Run the suite; expect all green**

Run: the Docker suite command.
Expected: `gate tests: 4 passed, 0 failed`

- [ ] **Step 5: Commit and push; confirm repo CI green**

```bash
git add wait-for-memory.sh tests/test_queue.sh
git commit -m "feat: bound queue overtakes so heavy jobs cannot starve"
git push && gh run watch --exit-status
```

---

### Task 4: Concurrency stress test

**Repo:** `~/git/incus-memory-gate`

**Files:**
- Create: `tests/test_stress.sh`

**Interfaces:**
- Consumes: gate CLI (final), harness helpers.
- Produces: nothing new — a regression tripwire for lock races.

- [ ] **Step 1: Write `tests/test_stress.sh`**

```bash
#!/usr/bin/env bash
# Concurrency stress: 12 workers with deterministic mixed needs race for a
# 10 GB budget. After each admission the worker re-reads the ledger under
# the same lock and records a violation if the reserved sum exceeds the
# budget — any over-admission caused by a locking bug is caught by the
# admitting worker's own check before it releases. Ordering guarantees are
# unit-tested in test_queue.sh, not here.
source "$(dirname "$0")/helpers.sh"
setup

set_mem_total 10240
BUDGET=10240
RANDOM=42                       # fixed seed: needs are reproducible
needs=()
for i in $(seq 1 12); do
  needs+=( $(( 1024 + RANDOM % 3072 )) )
done

worker() {
  local i="$1" need="$2" total f
  if run_gate "w$i" acquire --need-mb "$need" --label "stress$i" --deadline 30 >/dev/null 2>&1; then
    (
      flock -s 9
      total=0
      for f in "$MOLECULE_GATE_DIR"/r.*; do
        [ -f "$f" ] || continue
        total=$(( total + $(awk '{print $1; exit}' "$f") ))
      done
      if [ "$total" -gt "$BUDGET" ]; then
        echo "VIOLATION: reserved=${total}MB > budget=${BUDGET}MB" >> "$T/violations"
      fi
    ) 9>"$MOLECULE_GATE_DIR/.lock"
    sleep "0.$(( 1 + i % 4 ))"
    run_gate "w$i" release >/dev/null
  else
    echo "w$i" >> "$T/starved"
  fi
}

for i in $(seq 1 12); do
  worker "$i" "${needs[$(( i - 1 ))]}" &
done
wait

assert_no_file "$T/violations"
leftovers=$(ls "$MOLECULE_GATE_DIR" 2>/dev/null | grep -c '^[qr]\.' || true)
assert_eq "$leftovers" "0" "no orphaned tickets or reservations"
if [ -f "$T/starved" ]; then
  echo "note: starved workers: $(tr '\n' ' ' < "$T/starved")"
fi
echo OK
```

- [ ] **Step 2: Run the suite (twice, to shake out flakiness)**

Run: the Docker suite command, twice.
Expected: `gate tests: 5 passed, 0 failed` both times. If a run hangs longer than ~60s, a worker is deadlocked — that is a real gate bug, not a test problem.

- [ ] **Step 3: Commit and push; confirm repo CI green**

```bash
git add tests/test_stress.sh
git commit -m "test: stress the ledger under concurrent acquires"
git push && gh run watch --exit-status
```

---

### Task 5: action.yml, README, release v1.0.0

**Repo:** `~/git/incus-memory-gate`

**Files:**
- Create: `action.yml`
- Modify: `README.md` (full documentation)

**Interfaces:**
- Consumes: gate CLI (final).
- Produces: the action interface consumers use — inputs `mode`, `need-mb`, `molecule-scenario`, `label`, `deadline-seconds`, `incus-host`, `ssh-key`, `reserve-mb`, `max-overtakes`, `gate-dir` — and the release tag `v1.0.0` whose commit SHA Task 8 pins.

- [ ] **Step 1: Write `action.yml`**

```yaml
---
name: 'Incus memory gate'
description: >-
  Memory admission gate for CI jobs sharing one incus host: a
  committed-limits ledger, a FIFO queue with bounded overtakes, and
  fail-fast semantics.
inputs:
  mode:
    description: 'acquire or release'
    required: true
  need-mb:
    description: 'memory to reserve in MB (exclusive with molecule-scenario)'
    default: ''
  molecule-scenario:
    description: >-
      derive the need by summing memory_mb over the platforms in
      molecule/<scenario>/molecule.yml in the workspace
    default: ''
  label:
    description: 'diagnostic label for the reservation (defaults to the scenario name)'
    default: ''
  deadline-seconds:
    description: 'acquire deadline in seconds (script default 2700)'
    default: ''
  incus-host:
    description: 'host queried for running containers (required for acquire)'
    default: ''
  ssh-key:
    description: 'path to the SSH key used for the incus query'
    default: ''
  reserve-mb:
    description: 'MB reserved for host OS/runners/incusd (script default 12288)'
    default: ''
  max-overtakes:
    description: 'bypasses a queue head tolerates before the queue goes strict (script default 10)'
    default: ''
  gate-dir:
    description: 'shared gate state directory (script default /tmp/molecule-gate)'
    default: ''
runs:
  using: composite
  steps:
    - shell: bash
      # Every input is routed through env — never interpolated as
      # ${{ }} text inside the script body — so no input value can
      # inject shell syntax (GitHub Actions hardening guidance).
      env:
        GATE_MODE: ${{ inputs.mode }}
        GATE_NEED_MB: ${{ inputs.need-mb }}
        GATE_MOLECULE_SCENARIO: ${{ inputs.molecule-scenario }}
        GATE_INPUT_LABEL: ${{ inputs.label }}
        GATE_DEADLINE_SECONDS: ${{ inputs.deadline-seconds }}
        INCUS_HOST: ${{ inputs.incus-host }}
        MOLECULE_SSH_KEY: ${{ inputs.ssh-key }}
        INCUS_RESERVE_MB: ${{ inputs.reserve-mb }}
        GATE_MAX_OVERTAKES: ${{ inputs.max-overtakes }}
        MOLECULE_GATE_DIR: ${{ inputs.gate-dir }}
      run: |
        set -euo pipefail
        case "$GATE_MODE" in
          acquire)
            args=()
            if [ -n "$GATE_NEED_MB" ]; then
              args+=(--need-mb "$GATE_NEED_MB")
            fi
            if [ -n "$GATE_MOLECULE_SCENARIO" ]; then
              args+=(--molecule-scenario "$GATE_MOLECULE_SCENARIO")
            fi
            if [ -n "$GATE_INPUT_LABEL" ]; then
              args+=(--label "$GATE_INPUT_LABEL")
            fi
            if [ -n "$GATE_DEADLINE_SECONDS" ]; then
              args+=(--deadline "$GATE_DEADLINE_SECONDS")
            fi
            bash "${{ github.action_path }}/wait-for-memory.sh" acquire "${args[@]}"
            ;;
          release)
            bash "${{ github.action_path }}/wait-for-memory.sh" release
            ;;
          *)
            echo "unknown mode: $GATE_MODE" >&2
            exit 2
            ;;
        esac
```

- [ ] **Step 2: Write the full `README.md`** — sections, in this order, in plain prose:
  1. What it is: one paragraph — the admission formula, why committed limits beat MemAvailable (hard cgroup caps make `Σ limits ≤ MemTotal − reserve` a real no-OOM guarantee), fail-fast philosophy.
  2. Queue policy: FIFO tickets, bounded overtakes with K default 10, deadline verdict line.
  3. Usage as an action: two YAML snippets — an acquire step (`mode: acquire`, `molecule-scenario`/`need-mb`, `incus-host`, `ssh-key`) and a paired release step (`if: always()`, `mode: release`). Note the SHA-pinning convention (`uses: Oddly/incus-memory-gate@<sha> # v1.0.0`).
  4. Usage as a plain script: the CLI synopsis from the script header.
  5. The conversion contract: reservation file `r.<runner>` (content `<need_mb> <label>`) in the gate dir; the launcher deletes it right after `incus launch` so the job is counted via committed `limits.memory` from then on. Include this exact shell fragment as the reference converter:
     ```bash
     # inside the flock'd launch section, after all `incus launch` calls:
     if [ -n "$RUNNER_NAME" ]; then
       rm -f "/tmp/molecule-gate/r.${RUNNER_NAME}"
     fi
     ```
  6. Env reference: the table from the script header (name, default, meaning), noting empty-string-is-unset.
  7. Requirements: Linux gate host, bash + flock + python3 + PyYAML on the runner, SSH root access to the incus host (or `GATE_INCUS_QUERY` override).
  8. Testing: `bash tests/run-tests.sh` on Linux; what the suite covers.

- [ ] **Step 3: Run the suite once more (nothing should change) and lint the action**

Run: the Docker suite command → `gate tests: 5 passed, 0 failed`.
Run: `docker run --rm -v ~/git/incus-memory-gate:/mnt koalaman/shellcheck:stable -s bash /dev/null` is not applicable to action.yml — instead validate YAML: `python3 -c "import yaml; yaml.safe_load(open('$HOME/git/incus-memory-gate/action.yml'))" && echo yaml-ok`.

- [ ] **Step 4: Commit, push, tag and release v1.0.0**

```bash
git add action.yml README.md
git commit -m "feat: composite action interface and documentation"
git push && gh run watch --exit-status
git tag -a v1.0.0 -m "First release: committed-limits ledger, bounded-overtake queue, fail-fast"
git push origin v1.0.0
git rev-parse v1.0.0^{commit}   # record this SHA — Task 8 pins it
```

---

### Task 6: elasticstack create.yml — convert reservations, keep a dev-path check

**Repo:** `~/git/elasticstack` (branch `ci/memory-gate-redesign`)

**Files:**
- Modify: `molecule/shared/create.yml` (header comment, vars, and the "Wait for capacity and launch containers (locked)" task)

**Interfaces:**
- Consumes: reservation file format `r.<runner>` = `<need_mb> <label>` in `/tmp/molecule-gate` (Task 2's contract).
- Produces: the conversion behavior the gate's ledger arithmetic assumes. No later task depends on names introduced here.

- [ ] **Step 1: Update the header comment block** — replace lines 8–14 (the "Memory-based capacity gate:" paragraph) with:

```yaml
# Memory admission:
#   In CI, admission happens in the workflow's "Acquire memory slot" step
#   (the Oddly/incus-memory-gate action), which leaves a reservation file
#   in /tmp/molecule-gate. When that file exists we launch unconditionally
#   and delete it right after `incus launch` — from then on the job is
#   counted via committed limits.memory, so nothing is double-counted.
#   Runs without a reservation (local development) get a capacity check
#   against the same ledger here, so a laptop run cannot stampede CI.
```

- [ ] **Step 2: Add two vars** after the `incus_reserve_mb` var (keep `incus_reserve_mb` itself — the dev path still uses it):

```yaml
    # Set by GitHub Actions; empty for local development runs.
    runner_name: "{{ lookup('env', 'RUNNER_NAME') | default('', true) }}"
    molecule_gate_dir: "{{ lookup('env', 'MOLECULE_GATE_DIR') | default('/tmp/molecule-gate', true) }}"
```

- [ ] **Step 3: Replace the "Wait for capacity and launch containers (locked)" task** (comment, shell block, and retry settings) with:

```yaml
    # Launch under the host-side lock. CI jobs arrive holding a gate
    # reservation and launch unconditionally; the reservation is deleted
    # right after the launches, converting it into committed limits.memory.
    # Dev runs (no reservation) check the shared ledger first.
    - name: Wait for capacity and launch containers (locked)  # noqa: risky-shell-pipe
      ansible.builtin.shell: |
        {{ _ssh_cmd }} bash -s << 'REMOTE_SCRIPT'
        set -o pipefail
        exec 9>/var/lock/molecule-create.lock
        flock -x -w 60 9 || exit 1

        gate_dir={{ molecule_gate_dir }}
        my_resv="$gate_dir/r.{{ runner_name }}"

        if [ -n "{{ runner_name }}" ] && [ -f "$my_resv" ]; then
          echo "Gate reservation present for {{ runner_name }} — admission already granted."
        else
          total_mb=$(free -m | awk '/Mem:/{print $2}')
          reserve_mb={{ incus_reserve_mb }}
          committed_mb=$(incus list -f json --project default < /dev/null | \
            python3 -c '
        import json, re, sys
        total = 0
        for c in json.load(sys.stdin):
            if c.get("status") != "Running":
                continue
            mem = (c.get("config") or {}).get("limits.memory") or "0"
            m = re.match(r"(\d+)\s*(GB|GiB|MB|MiB)?", mem)
            if m:
                val = int(m.group(1))
                if (m.group(2) or "MB").upper() in ("GB", "GIB"):
                    val *= 1024
                total += val
        print(total)
        ')
          reserved_mb=0
          for f in "$gate_dir"/r.*; do
            [ -f "$f" ] || continue
            mb=$(awk '{print $1+0; exit}' "$f")
            reserved_mb=$(( reserved_mb + mb ))
          done
          needed_mb={{ _needed_mb }}
          available_mb=$(( total_mb - reserve_mb - committed_mb - reserved_mb ))
          if [ "$available_mb" -lt "$needed_mb" ]; then
            echo "No capacity: ${committed_mb}MB committed + ${reserved_mb}MB reserved + ${needed_mb}MB needed > ${total_mb}MB total - ${reserve_mb}MB reserve"
            exit 1
          fi
          echo "Memory OK: ${committed_mb}MB committed, ${reserved_mb}MB reserved, ${needed_mb}MB needed, ${available_mb}MB available"
        fi

        {% for item in molecule_yml.platforms %}
        {% set mem_mb = item.memory_mb | default(incus_default_memory_mb) | int %}
        incus delete {{ item.name }} --force 2>/dev/null || true
        incus launch {{ incus_images[item.distro | default("debian12")] }} {{ item.name }} \
          --storage {{ incus_storage_pool | default("default") }} \
          -c limits.memory={{ mem_mb }}MB \
          -c security.nesting=true \
          -c security.privileged=true \
          -c user.managed-by=molecule \
          -c user.created-at={{ now(utc=true).strftime("%Y-%m-%dT%H:%M:%SZ") }} \
          {{ "-c user.ci-run-id=" ~ ci_run_id if ci_run_id else "" }} \
          {{ "-c user.ci-repository=" ~ ci_repository if ci_repository else "" }} < /dev/null || exit 1
        {% endfor %}

        # Conversion: the containers are Running and therefore counted as
        # committed limits.memory by every ledger reader, so the
        # reservation must go now.
        if [ -n "{{ runner_name }}" ]; then
          rm -f "$my_resv"
        fi
        REMOTE_SCRIPT
      changed_when: true
      register: _launch_result
      # Dev-path capacity retries: 10 × 30s keeps a laptop run patient for
      # five minutes. CI jobs (reservation present) only land here on
      # genuine incus launch errors, where a retry is also the right call.
      # CI queueing happens in the workflow's acquire step now, before any
      # converge work is done — not in this loop.
      retries: 10
      delay: 30
      until: _launch_result.rc == 0
```

Notes:
- The `incus launch` loop, jinja `{% for %}`, and all container flags are byte-identical to the current file — only the admission logic around the loop and the trailing conversion change.
- If a launch fails mid-loop, the script exits before the conversion `rm`, so the reservation survives into the retry — correct, the containers may be partially up but the ledger stays covered.

- [ ] **Step 4: Lint**

Run: `yamllint molecule/shared/create.yml && ansible-lint molecule/shared/create.yml`
Expected: clean (the `# noqa: risky-shell-pipe` carries over).

- [ ] **Step 5: Commit**

```bash
git add molecule/shared/create.yml
git commit -m "feat(ci): convert gate reservations into committed capacity at launch"
```

---

### Task 7: Container memory limits + CLAUDE.md reference

**Repo:** `~/git/elasticstack` (branch `ci/memory-gate-redesign`)

**Files:**
- Modify: `molecule/repos_default/molecule.yml:12-15`
- Modify: `molecule/kibana_custom/molecule.yml:19`
- Modify: `molecule/kibana_custom_certs/molecule.yml:19`
- Modify: `molecule/kibana_extras/molecule.yml:25`
- Modify: `CLAUDE.md` (Multi-OS section, the "heaviest scenarios" paragraph)

**Interfaces:**
- Consumes: nothing.
- Produces: the memory_mb values the gate derives need from. No sync step needed — the gate reads these files directly.

- [ ] **Step 1: repos_default** — replace the comment + value:

```yaml
    # 2048 MiB: dnf/python3 on rockylinux9 peaks near 1 GB during the
    # security-packages install (56 cgroup OOM kills at the old 1024 in
    # the 30 days to 2026-08-12, per the host kernel journal).
    memory_mb: 2048
```

- [ ] **Step 2: Kibana containers** — in each of `kibana_custom`, `kibana_custom_certs`, `kibana_extras`, change the `memory_mb: 2048` on the kibana-group platform (`kib-cust-kb1`, `kib-extcrt-kb1`, `kib-extra-kb1`) to:

```yaml
    # 3072 MiB: Kibana 9's node process was cgroup-OOM-killed at ~1.6 GB
    # anon RSS under the old 2048 limit (kernel journal, 2026-08); killed
    # Kibana loops under systemd restart and the converge hangs to the
    # job timeout.
    memory_mb: 3072
```

Do NOT touch the `memory_mb: 4096` elasticsearch platforms in those files.

- [ ] **Step 3: CLAUDE.md** — in the Multi-OS section, replace the sentence beginning "The heaviest scenarios by declared per-scenario memory in `scripts/wait-for-memory.sh`:" so the paragraph reads:

```markdown
The heaviest scenarios by summed platform `memory_mb` in
`molecule/<scenario>/molecule.yml` (which is exactly what the
Oddly/incus-memory-gate action admits on — there is no separate table
to keep in sync): `elasticstack_default` (20 GB),
`elasticsearch_roles_calculation` (16 GB), `es_kibana` (13.8 GB),
`cert_renewal` (10.5 GB).
```

Keep the rest of the paragraph (the `max-parallel` sentence) unchanged — Task 9 rewrites it.

- [ ] **Step 4: Lint + sanity-check derived needs**

Run: `yamllint molecule/` then, from the repo root:
```bash
python3 - <<'PY'
import yaml
for s in ['repos_default', 'kibana_custom', 'kibana_custom_certs', 'kibana_extras']:
    raw = open(f'molecule/{s}/molecule.yml').read()
    for tok, val in [('${MOLECULE_DISTRO:-debian12}', 'debian12'),
                     ('${ELASTIC_RELEASE:-9}', '9'),
                     ('${MOLECULE_RUN_SUFFIX}', '')]:
        raw = raw.replace(tok, val)
    d = yaml.safe_load(raw)
    print(s, sum(int(p.get('memory_mb', 4096)) for p in d['platforms']))
PY
```
Expected: `repos_default 2048`, `kibana_custom 7168`, `kibana_custom_certs 7168`, `kibana_extras 7168`.

- [ ] **Step 5: Commit**

```bash
git add molecule/repos_default/molecule.yml molecule/kibana_custom/molecule.yml \
        molecule/kibana_custom_certs/molecule.yml molecule/kibana_extras/molecule.yml CLAUDE.md
git commit -m "fix(ci): give repos and kibana containers the memory they actually use"
```

---

### Task 8: elasticstack workflow wiring — consume the action, drop the local script

**Repo:** `~/git/elasticstack` (branch `ci/memory-gate-redesign`)

**Files:**
- Modify: `.github/workflows/molecule.yml` (Acquire + Release memory slot steps)
- Modify: `.github/workflows/test_full_stack.yml` (Acquire + Release memory slot steps)
- Modify: `.github/workflows/test_elasticsearch_upgrade.yml` (both jobs' Acquire + Release steps)
- Delete: `scripts/wait-for-memory.sh`

**Interfaces:**
- Consumes: the action interface from Task 5 and the `v1.0.0` commit SHA recorded there (referred to below as `<GATE_SHA>` — substitute the real 40-char SHA everywhere).

- [ ] **Step 1: Replace the acquire step in `test_full_stack.yml` and in both jobs of `test_elasticsearch_upgrade.yml`** (fixed job budgets of 180 and 60 minutes — the 2700s default deadline leaves 135 and 15 minutes of runway respectively). Exact step, identical in all three:

```yaml
      - name: Acquire memory slot
        # Single-authority admission gate: MemTotal − reserve − committed
        # limits.memory − pending reservations, FIFO with bounded
        # overtakes. Fails after its 45-min deadline instead of barging
        # in — a starved job is an explicit retryable failure, not an
        # OOM risk. create.yml converts the reservation into committed
        # capacity right after the containers launch.
        uses: Oddly/incus-memory-gate@<GATE_SHA>  # v1.0.0
        with:
          mode: acquire
          molecule-scenario: ${{ matrix.scenario }}
          incus-host: ${{ secrets.INCUS_HOST }}
          ssh-key: ${{ runner.temp }}/molecule_id_ed25519
```

- [ ] **Step 2: Replace the acquire step in `molecule.yml`** — its `timeout-minutes` is the caller-supplied `inputs.timeout` (default 60, as low as 20 for `test_elasticsearch_modules`), and GitHub expressions cannot do arithmetic, so a tiny step computes the deadline first:

```yaml
      - name: Compute gate deadline
        # Keep the gate deadline 15 minutes under this job's
        # timeout-minutes so a starved job fails at the gate with a
        # queue/ledger verdict instead of at the workflow cancel with
        # nothing. Floor of 300s.
        id: gate
        run: |
          deadline=$(( (${{ inputs.timeout }} - 15) * 60 ))
          [ "$deadline" -ge 300 ] || deadline=300
          echo "deadline=$deadline" >> "$GITHUB_OUTPUT"

      - name: Acquire memory slot
        # Single-authority admission gate: MemTotal − reserve − committed
        # limits.memory − pending reservations, FIFO with bounded
        # overtakes. create.yml converts the reservation into committed
        # capacity right after the containers launch.
        uses: Oddly/incus-memory-gate@<GATE_SHA>  # v1.0.0
        with:
          mode: acquire
          molecule-scenario: ${{ matrix.scenario }}
          deadline-seconds: ${{ steps.gate.outputs.deadline }}
          incus-host: ${{ secrets.INCUS_HOST }}
          ssh-key: ${{ runner.temp }}/molecule_id_ed25519
```

- [ ] **Step 3: Replace every "Release memory slot" step in the same four places** (keep the existing comment and `if: always()`):

```yaml
      - name: Release memory slot
        # Runs whether converge/verify/idempotence passed or failed, so
        # the reservation is freed promptly. Normally a no-op: create.yml
        # already converted the reservation at container launch.
        if: always()
        uses: Oddly/incus-memory-gate@<GATE_SHA>  # v1.0.0
        with:
          mode: release
```

- [ ] **Step 4: Delete the local script**

```bash
git rm scripts/wait-for-memory.sh
```
Then `grep -rn "wait-for-memory" . --exclude-dir=.git --exclude-dir=.superpowers --exclude-dir=docs` — the only hits left must be the workflow comments referencing the gate concept (fine) and none referencing `scripts/wait-for-memory.sh`.

- [ ] **Step 5: Lint + step-order sanity check**

Run: `yamllint .github/workflows/` and confirm in all three files that the "Set up SSH key for molecule" step precedes the acquire step (the gate's incus query needs the key on disk).

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/molecule.yml .github/workflows/test_full_stack.yml \
        .github/workflows/test_elasticsearch_upgrade.yml
git commit -m "chore(ci): consume the incus-memory-gate action instead of the local script

The gate now lives in Oddly/incus-memory-gate with its own hermetic
test suite and CI, pinned here by SHA. The reusable molecule workflow
derives the gate deadline from its timeout input so a starved job
always fails at the gate step with a queue verdict rather than at the
workflow cancel."
```

---

### Task 9: Raise full-stack max-parallel (separate, revertable)

**Repo:** `~/git/elasticstack` (branch `ci/memory-gate-redesign`)

**Files:**
- Modify: `.github/workflows/test_full_stack.yml` (strategy block)
- Modify: `CLAUDE.md` (the max-parallel sentence in Multi-OS)

**Interfaces:** none.

- [ ] **Step 1: Replace the max-parallel comment + value** in `test_full_stack.yml`:

```yaml
      # Each scenario/distro/release combo needs 15-25 GB of container RAM
      # on the shared incus-ci host. The admission gate (FIFO with bounded
      # overtakes, fail-fast) now guarantees heavy scenarios can't be
      # starved by smaller jobs, so the cap is back to the throughput
      # target it was originally sized for. The 3-slot value was a
      # workaround for gate starvation that no longer exists; if the
      # nightly storm shows starved jobs or OOMs, revert this commit
      # first and investigate the gate second.
      max-parallel: 6
```

- [ ] **Step 2: Update the CLAUDE.md sentence** about `max-parallel: 3` to:

```markdown
`test_full_stack.yml` uses `max-parallel: 6`; the admission gate (the
Oddly/incus-memory-gate action: FIFO, bounded overtakes, fail-fast)
keeps the heaviest scenarios from being starved on the shared
incus-ci host — the history of the 6→3→6 moves is in `git log
.github/workflows/test_full_stack.yml`.
```

- [ ] **Step 3: Lint and commit**

```bash
yamllint .github/workflows/test_full_stack.yml
git add .github/workflows/test_full_stack.yml CLAUDE.md
git commit -m "chore(ci): raise full-stack concurrency back to six slots

The 3-slot cap was a workaround for heavy scenarios losing the memory
race under the old gate. With admission now FIFO with bounded
overtakes and fail-fast semantics, starvation is bounded by design,
so we return to the throughput target the pool was sized for. If the
nightly storm proves otherwise this commit is the first thing to
revert."
```

---

### Task 10: Staged validation, PR, acceptance

**Repo:** `~/git/elasticstack` (operational; gate repo already released)

- [ ] **Step 1: Push the branch and open the PR**

```bash
git push -u origin ci/memory-gate-redesign
gh pr create --title "ci: consume the extracted incus-memory-gate action, fix container limits" --body "$(cat <<'EOF'
We had two overlapping admission gates for the shared incus-ci host and
they disagreed with each other: the workflow-level gate reasoned about
MemAvailable minus reservations, create.yml reasoned about committed
limits.memory, and a job's reservation kept counting against capacity
for its whole run while its containers' real usage was already visible.
That double-count is what starved the heavy scenarios and forced the
full-stack matrix down to three slots.

The gate logic now lives in its own public repo,
Oddly/incus-memory-gate, as a composite action with a hermetic test
suite and its own CI, so other projects can reuse it. This PR makes the
collection its first consumer: the workflows acquire through the
action (SHA-pinned), create.yml deletes the reservation right after
incus launch so the job is counted through its containers' limits from
then on, and the old scripts/wait-for-memory.sh is gone along with its
hand-maintained scenario memory table — the gate sums memory_mb
straight from the scenario's molecule.yml.

Admission is FIFO with bounded overtakes: smaller jobs can pass a
blocked heavy job, but only ten times, then the queue goes strict until
the head is admitted. At the deadline the gate fails with a
queue/ledger verdict instead of proceeding without headroom. The repos
and kibana container limits also go up: the host kernel journal shows
dnf being OOM-killed inside the 1 GB repos container 56 times in the
last month, and Kibana 9 dying at ~1.6 GB inside the 2 GB kibana
containers, which is what was hanging those jobs to their timeout. The
last commit returns full-stack max-parallel to six; if the next nightly
storm shows starvation or OOMs, revert that commit first.
EOF
)"
```

- [ ] **Step 2: Staged validation of create.yml on incus-ci (quiet window — check `gh run list --limit 5` shows nothing molecule-heavy in progress)**

CI path (reservation present → unconditional launch + conversion):
```bash
ssh root@172.30.0.172 'mkdir -p /tmp/molecule-gate && echo "1024 repos_default" > /tmp/molecule-gate/r.staged-test && ls -la /tmp/molecule-gate/'
cd ~/git/elasticstack
RUNNER_NAME=staged-test MOLECULE_DISTRO=debian13 ELASTIC_RELEASE=9 INCUS_HOST=172.30.0.172 \
  molecule create -s repos_default
ssh root@172.30.0.172 'ls -la /tmp/molecule-gate/'   # r.staged-test must be GONE (converted)
```

Dev path (no reservation → ledger check; foreign reservations respected):
```bash
ssh root@172.30.0.172 'echo "120000 hog" > /tmp/molecule-gate/r.hog'   # reserve ~all capacity
MOLECULE_DISTRO=debian13 ELASTIC_RELEASE=9 INCUS_HOST=172.30.0.172 \
  molecule create -s repos_default   # expect "No capacity: ... reserved ..." retry messages — Ctrl-C after the first
ssh root@172.30.0.172 'rm /tmp/molecule-gate/r.hog'
MOLECULE_DISTRO=debian13 ELASTIC_RELEASE=9 INCUS_HOST=172.30.0.172 \
  molecule create -s repos_default   # expect "Memory OK: ..." and a launch
MOLECULE_DISTRO=debian13 ELASTIC_RELEASE=9 INCUS_HOST=172.30.0.172 \
  molecule destroy -s repos_default
```

- [ ] **Step 3: Label the PR and watch the full matrix**

```bash
gh pr edit <N> --add-label 'ci:run'
```
While it runs: `ssh root@172.30.0.172 'watch -n30 ls -la /tmp/molecule-gate/'` and spot-check "Acquire memory slot" logs for moving `waiting position=… free=…` lines. Pass = every molecule job admitted or explicitly starved (none hung), full-stack green. After any new push, re-trigger with the label toggle: `gh pr edit <N> --remove-label 'ci:run' && gh pr edit <N> --add-label 'ci:run'`.

- [ ] **Step 4: Acceptance — next Tue/Thu/Sat nightly storm after merge**

```bash
ssh root@lab "journalctl -k --since '1 day ago' | grep -c 'oom_memcg=/lxc/305/ns/lxc.payload'"   # expect 0
gh run list --created <nightly-date> --json name,conclusion   # expect no failure/cancelled from gate starvation or timeout
```
Compare full-stack wall clock against the 2026-08-12 baseline. If starvation or OOMs appear, revert the max-parallel commit first, investigate the gate second.

---

## Self-review notes

- Spec coverage: Packaging section → Tasks 1, 5, 8; §1 ledger → Task 2; §2 conversion + dev path → Task 6; §3 queue/fail-fast → Tasks 2–3; §4 limits/knobs → Tasks 7, 9; testing section → Tasks 1–4 (suite), Task 1/5 (gate repo CI replaces the planned elasticstack gate_tests job, per the Packaging section), Task 10 (staged + acceptance).
- The old script's `/var/lib/molecule-gate` first-choice dir is intentionally dropped (never writable in practice; `/tmp/molecule-gate` is the observed real path). `MOLECULE_GATE_DIR`/`gate-dir` still overrides.
- Type consistency: ticket = `<need> <label> <overtakes>`, reservation = `<need> <label>`, grep vocab (`need=`, `committed=`, `ADMITTED`, `STARVED`) is identical between the script in Task 2 and every test in Tasks 2–4; the action inputs in Task 5 match the CLI flags consumed in Task 8.
- elasticstack no longer gets `tests/gate/` or a `gate_tests` contracts job — the suite and CI live in the gate repo. The earlier elasticstack harness commit was dropped from the branch; the files were preserved and are ported by Task 1.
