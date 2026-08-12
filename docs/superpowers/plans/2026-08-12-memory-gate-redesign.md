# Memory-Gate Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two overlapping CI memory gates with a single committed-limits admission gate (FIFO + bounded overtakes, fail-fast), tested hermetically in CI, and fix the container limits that caused the observed cgroup OOM kills.

**Architecture:** `scripts/wait-for-memory.sh` becomes the only admission decision, using `MemTotal − reserve − Σ committed limits.memory − Σ pending reservations`. Reservations convert into committed capacity when `molecule/shared/create.yml` deletes them right after `incus launch`. Queueing is FIFO tickets with a bounded-overtake bypass (default K=10). A plain-bash hermetic test suite in `tests/gate/` runs on ubuntu-latest via the contracts workflow.

**Tech Stack:** bash (flock, GNU coreutils), python3 + PyYAML (parsing helpers), Ansible/molecule, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-12-memory-gate-redesign-design.md` (approved). Read it before starting.

## Global Constraints

- Branch: `ci/memory-gate-redesign` (exists; spec commits already on it).
- Commit style: Conventional Commits — `type(scope): imperative subject`, lowercase after colon, no trailing period; bodies are plain prose paragraphs, first person. NEVER mention any LLM/AI assistant in commits, code, or comments. No co-author trailers.
- `yamllint .` and `ansible-lint` must be clean before any push.
- Ansible: FQCN always (`ansible.builtin.shell`, not `shell`).
- The gate tests are Linux-only (`flock`, GNU `stat -c`, `touch -d`). On this macOS workstation run them inside a Linux VM: `orb` (OrbStack) gives a shell where `bash tests/gate/run-tests.sh` works from the repo path. CI runs them on ubuntu-latest.
- Gate env contract (referenced by several tasks):
  `RUNNER_NAME`, `INCUS_HOST`, `MOLECULE_SSH_KEY`, `MOLECULE_GATE_DIR` (default `/tmp/molecule-gate`), `INCUS_RESERVE_MB` (default `12288`), `INCUS_DEFAULT_MEMORY_MB` (default `4096`), `MOLECULE_GATE_TTL` (default `3600`), `GATE_TICKET_STALE_SECONDS` (default `120`), `GATE_MAX_OVERTAKES` (default `10`), `GATE_MEMINFO` (default `/proc/meminfo`), `GATE_INCUS_QUERY` (default: ssh incus list), `GATE_POLL_SECONDS` (default `30`).
- Gate file formats: reservation `r.<runner>` contains `<need_mb> <scenario>`; ticket `q.<epoch10>.<runner>` contains `<need_mb> <scenario> <overtakes>`. Ticket owners refresh with `touch` only (preserving the counter); only a bypasser rewrites a ticket.

---

### Task 1: Hermetic test harness

**Files:**
- Create: `tests/gate/helpers.sh`
- Create: `tests/gate/run-tests.sh`
- Create: `tests/gate/test_harness.sh`

**Interfaces:**
- Produces: `setup`, `set_mem_total <mb>`, `set_incus_containers "<name>:<status>:<limit>" ...`, `make_scenario <name> <mb|none> ...`, `run_gate <runner> <action> [args]`, `assert_eq <got> <want> <msg>`, `assert_file <path>`, `assert_no_file <path>`, and the env vars exported by `setup`. Every later test task consumes these exact names.

- [ ] **Step 1: Write `tests/gate/helpers.sh`**

```bash
#!/usr/bin/env bash
# Shared helpers for the memory-gate test suite. Source from test_*.sh.
# Linux-only: needs flock, GNU stat, GNU touch.
set -uo pipefail

GATE_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/scripts/wait-for-memory.sh"

setup() {
  T="$(mktemp -d)"
  export MOLECULE_GATE_DIR="$T/gate"
  export GATE_MEMINFO="$T/meminfo"
  export GATE_INCUS_QUERY="cat $T/incus.json"
  export GATE_POLL_SECONDS=0.2
  export GATE_TICKET_STALE_SECONDS=2
  export INCUS_RESERVE_MB=0
  REPO_FAKE="$T/repo"
  mkdir -p "$REPO_FAKE/molecule"
  echo '[]' > "$T/incus.json"
  set_mem_total 10240
  trap 'rm -rf "$T"' EXIT
}

set_mem_total() {
  printf 'MemTotal:       %d kB\n' $(( $1 * 1024 )) > "$GATE_MEMINFO"
}

# Each argument: "<name>:<status>:<limits.memory>". No arguments = no containers.
set_incus_containers() {
  python3 - "$T/incus.json" "$@" <<'PY'
import json, sys
out = []
for spec in sys.argv[2:]:
    name, status, limit = spec.split(":")
    out.append({"name": name, "status": status,
                "config": {"limits.memory": limit}})
json.dump(out, open(sys.argv[1], "w"))
PY
}

# make_scenario <name> <memory_mb...>; pass the literal word "none" for a
# platform that omits memory_mb (exercises the 4096 default).
make_scenario() {
  local dir="$REPO_FAKE/molecule/$1" i=0 mb
  mkdir -p "$dir"
  {
    echo "platforms:"
    shift
    for mb in "$@"; do
      i=$(( i + 1 ))
      echo "  - name: p$i"
      if [ "$mb" != none ]; then
        echo "    memory_mb: $mb"
      fi
    done
  } > "$dir/molecule.yml"
}

# run_gate <runner-name> <acquire|release> [args...] — runs from the fake
# repo root so scenario paths resolve like they do in CI.
run_gate() {
  local name="$1"
  shift
  (cd "$REPO_FAKE" && RUNNER_NAME="$name" bash "$GATE_SCRIPT" "$@")
}

assert_eq() {
  [ "$1" = "$2" ] || { echo "assert_eq failed: got '$1' want '$2' ($3)"; exit 1; }
}
assert_file() { [ -f "$1" ] || { echo "missing file: $1"; exit 1; }; }
assert_no_file() { [ ! -f "$1" ] || { echo "unexpected file: $1"; exit 1; }; }
```

- [ ] **Step 2: Write `tests/gate/run-tests.sh`**

```bash
#!/usr/bin/env bash
# Runner for the hermetic memory-gate suite. Each test_*.sh runs in its own
# bash process with a throwaway gate dir; a non-zero exit fails the suite.
# Linux-only (flock, GNU stat); in CI this runs on ubuntu-latest.
set -uo pipefail
cd "$(dirname "$0")"
pass=0 fail=0
for t in test_*.sh; do
  echo "== $t"
  if bash "$t"; then
    pass=$(( pass + 1 ))
  else
    fail=$(( fail + 1 ))
    echo "FAILED: $t"
  fi
done
echo "gate tests: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
```

- [ ] **Step 3: Write `tests/gate/test_harness.sh`** (smoke-tests the fixtures themselves)

```bash
#!/usr/bin/env bash
source "$(dirname "$0")/helpers.sh"
setup

set_mem_total 4096
grep -q 'MemTotal:       4194304 kB' "$GATE_MEMINFO" || { echo "meminfo fixture broken"; exit 1; }

set_incus_containers "a:Running:2GiB" "b:Stopped:1GB"
python3 -c '
import json, sys
data = json.load(open(sys.argv[1]))
assert len(data) == 2, data
assert data[0]["config"]["limits.memory"] == "2GiB", data
' "$T/incus.json"

make_scenario demo 4096 none
grep -q 'memory_mb: 4096' "$REPO_FAKE/molecule/demo/molecule.yml" || exit 1
assert_eq "$(grep -c 'name: p' "$REPO_FAKE/molecule/demo/molecule.yml")" "2" "two platforms"

echo OK
```

- [ ] **Step 4: Run the suite; expect the harness smoke test to pass** (the gate rewrite doesn't exist yet, but this file doesn't invoke it)

Run (inside a Linux shell): `bash tests/gate/run-tests.sh`
Expected: `== test_harness.sh` … `OK` … `gate tests: 1 passed, 0 failed`

- [ ] **Step 5: Commit**

```bash
git add tests/gate/
git commit -m "chore(ci): add hermetic test harness for the memory gate"
```

---

### Task 2: Gate rewrite — admission ledger, lifecycle, fail-fast (strict FIFO)

**Files:**
- Modify: `scripts/wait-for-memory.sh` (full rewrite)
- Create: `tests/gate/test_admission.sh`
- Create: `tests/gate/test_lifecycle.sh`

**Interfaces:**
- Consumes: harness helpers from Task 1.
- Produces: the gate CLI `wait-for-memory.sh acquire <scenario> [timeout_s]` (deadline default 2700, exit 0 admitted / exit 1 starved) and `wait-for-memory.sh release`; log line vocabulary `need=`, `committed=`, `reserved=`, `free=`, `ADMITTED`, `STARVED`, `released`, `nothing to release` (tests grep these); the gate file formats from Global Constraints. Task 3 adds the overtake branch inside the admission decision; everything else is final here.

- [ ] **Step 1: Write `tests/gate/test_admission.sh`**

```bash
#!/usr/bin/env bash
source "$(dirname "$0")/helpers.sh"
setup

# 1. need derivation sums platform memory_mb
make_scenario demo 4096 2048
out=$(run_gate r1 acquire demo 1)
echo "$out" | grep -q 'need=6144MB' || { echo "derivation: $out"; exit 1; }
run_gate r1 release >/dev/null

# 2. platform without memory_mb falls back to 4096
make_scenario nodefault none
out=$(run_gate r2 acquire nodefault 1)
echo "$out" | grep -q 'need=4096MB' || { echo "default: $out"; exit 1; }
run_gate r2 release >/dev/null

# 3. ${VAR:-default} resolution in molecule.yml
mkdir -p "$REPO_FAKE/molecule/envsub"
cat > "$REPO_FAKE/molecule/envsub/molecule.yml" <<'EOF'
platforms:
  - name: "es-${MOLECULE_DISTRO:-debian12}"
    memory_mb: ${TEST_MEM_MB:-2048}
EOF
out=$(run_gate r3 acquire envsub 1)
echo "$out" | grep -q 'need=2048MB' || { echo "envsub default: $out"; exit 1; }
run_gate r3 release >/dev/null
out=$(TEST_MEM_MB=512 run_gate r4 acquire envsub 1)
echo "$out" | grep -q 'need=512MB' || { echo "envsub override: $out"; exit 1; }
run_gate r4 release >/dev/null

# 4. limits.memory unit parsing; stopped containers ignored
set_incus_containers "a:Running:1GiB" "b:Running:1024MiB" "c:Running:1GB" "d:Stopped:512GB"
make_scenario small 1024
out=$(run_gate r5 acquire small 1)
echo "$out" | grep -q 'committed=3072MB' || { echo "units: $out"; exit 1; }
run_gate r5 release >/dev/null

# 5. blocked -> fail fast with verdict, ticket cleaned up
set_incus_containers "big:Running:8192MB"      # free = 10240 - 8192 = 2048
make_scenario heavy 4096
if out=$(run_gate r6 acquire heavy 1 2>&1); then
  echo "should have starved: $out"; exit 1
fi
echo "$out" | grep -q 'STARVED' || { echo "verdict: $out"; exit 1; }
assert_no_file "$MOLECULE_GATE_DIR/r.r6"
[ -z "$(ls "$MOLECULE_GATE_DIR" 2>/dev/null | grep '^q\.')" ] || { echo "ticket leaked"; exit 1; }

# 6. foreign reservations count against free
set_incus_containers
echo "8192 other" > "$MOLECULE_GATE_DIR/r.other"
make_scenario mid 4096                          # free = 10240 - 8192 = 2048
if run_gate r7 acquire mid 1 >/dev/null 2>&1; then
  echo "reservation not counted"; exit 1
fi
rm -f "$MOLECULE_GATE_DIR/r.other"

# 7. incus query failure -> refuse to admit, non-zero exit
make_scenario small2 1024
if GATE_INCUS_QUERY=false run_gate r8 acquire small2 1 >/dev/null 2>&1; then
  echo "admitted blind on query failure"; exit 1
fi

# 8. no INCUS_HOST and no GATE_INCUS_QUERY -> clear failure
if (unset GATE_INCUS_QUERY INCUS_HOST; run_gate r9 acquire small2 1 >/dev/null 2>&1); then
  echo "admitted blind without a query source"; exit 1
fi

echo OK
```

- [ ] **Step 2: Write `tests/gate/test_lifecycle.sh`**

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

# 2. release after create.yml already converted the reservation is a no-op
out=$(run_gate rel2 release)
echo "$out" | grep -q 'nothing to release' || { echo "noop release: $out"; exit 1; }

# 3. reservations older than the TTL are garbage-collected by acquire
echo "4096 stale" > "$MOLECULE_GATE_DIR/r.dead"
touch -d '2 hours ago' "$MOLECULE_GATE_DIR/r.dead"
make_scenario mid2 8192                # counts stale? 10240-4096=6144 < 8192
run_gate live acquire mid2 1 >/dev/null || { echo "stale reservation not GCd"; exit 1; }
assert_no_file "$MOLECULE_GATE_DIR/r.dead"
run_gate live release >/dev/null

echo OK
```

- [ ] **Step 3: Run the suite to verify the new tests fail against the old script**

Run: `bash tests/gate/run-tests.sh`
Expected: `test_harness.sh` passes; `test_admission.sh` and `test_lifecycle.sh` FAIL (the old script has no `need=`/`committed=` vocabulary, reads `/proc/meminfo` directly, and ignores `GATE_*` env).

- [ ] **Step 4: Rewrite `scripts/wait-for-memory.sh`** (complete file; the `# BYPASS` marker line is where Task 3 inserts the overtake branch)

```bash
#!/usr/bin/env bash
# Single-authority memory admission gate for the molecule runner pool.
#
# Admission formula (all MB):
#
#   free = MemTotal - reserve - committed - reservations
#   admit when free >= my_need
#
#   committed    sum of limits.memory over *running* incus containers
#   reservations jobs admitted here whose containers are not launched yet;
#                molecule/shared/create.yml deletes the reservation right
#                after `incus launch`, converting it into committed capacity
#   my_need      sum of memory_mb (default 4096) over the platforms in
#                molecule/<scenario>/molecule.yml, after ${VAR:-default}
#                resolution — no hardcoded scenario table to keep in sync
#
# Queueing: FIFO tickets with bounded overtakes. A waiter that fits may
# bypass a blocked head until the head's ticket has been overtaken
# GATE_MAX_OVERTAKES times; then the queue is strict until the head is
# admitted. At the deadline the gate FAILS (exit 1) instead of barging in:
# a starved job is an explicit retryable failure, not an OOM risk.
#
# Usage (run from the repo root, so molecule/<scenario>/ resolves):
#   wait-for-memory.sh acquire <scenario> [timeout_s]   # default 2700
#   wait-for-memory.sh release
#
# Env:
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

action="${1:?usage: $0 <acquire|release> [args...]}"

GATE_DIR="${MOLECULE_GATE_DIR:-/tmp/molecule-gate}"
mkdir -p "$GATE_DIR"
chmod 0777 "$GATE_DIR" 2>/dev/null || true
LOCK="$GATE_DIR/.lock"

TTL_SEC="${MOLECULE_GATE_TTL:-3600}"
TICKET_STALE_SEC="${GATE_TICKET_STALE_SECONDS:-120}"
POLL_SEC="${GATE_POLL_SECONDS:-30}"
RESERVE_MB="${INCUS_RESERVE_MB:-12288}"
MEMINFO="${GATE_MEMINFO:-/proc/meminfo}"
MAX_OVERTAKES="${GATE_MAX_OVERTAKES:-10}"

runner="${RUNNER_NAME:-runner-$$}"
my_resv="$GATE_DIR/r.${runner}"

mem_total_mb() { awk '/^MemTotal:/{print int($2/1024); exit}' "$MEMINFO"; }

incus_query() {
  if [ -n "${GATE_INCUS_QUERY:-}" ]; then
    $GATE_INCUS_QUERY
  else
    : "${INCUS_HOST:?INCUS_HOST or GATE_INCUS_QUERY must be set - refusing to admit blind}"
    # shellcheck disable=SC2086
    ssh -o StrictHostKeyChecking=no -o BatchMode=yes \
      ${MOLECULE_SSH_KEY:+-i "$MOLECULE_SSH_KEY"} \
      "root@${INCUS_HOST}" -- incus list -f json --project default < /dev/null
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

derive_need_mb() {  # $1 = scenario name; resolves molecule/<scenario>/molecule.yml
  python3 -c '
import os, re, sys, yaml
raw = open(sys.argv[1]).read()
raw = re.sub(
    r"\$\{(\w+)(?::-([^}]*))?\}",
    lambda m: os.environ.get(m.group(1), m.group(2) or ""),
    raw,
)
default = int(os.environ.get("INCUS_DEFAULT_MEMORY_MB", "4096"))
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
    scenario="${2:?usage: $0 acquire <scenario> [timeout_s]}"
    timeout_s="${3:-2700}"
    need=$(derive_need_mb "$scenario")
    total=$(mem_total_mb)
    my_ticket="$GATE_DIR/q.$(printf '%010d' "$(date +%s)").${runner}"

    printf 'molecule-gate[%s]: acquire scenario=%s need=%dMB total=%dMB reserve=%dMB timeout=%ds\n' \
      "$runner" "$scenario" "$need" "$total" "$RESERVE_MB" "$timeout_s"

    deadline=$(( $(date +%s) + timeout_s ))
    attempt=0
    while :; do
      attempt=$(( attempt + 1 ))
      exec 9>"$LOCK"
      flock 9
      if [ -f "$my_ticket" ]; then
        touch "$my_ticket"   # refresh liveness; preserves the overtake counter
      else
        printf '%d %s 0\n' "$need" "$scenario" > "$my_ticket"
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
        printf '%d %s\n' "$need" "$scenario" > "$my_resv"
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
- `rm -f "$GATE_DIR"/q.*."$runner"` in release: unmatched glob expands to itself and `rm -f` ignores it — no nullglob needed there.

- [ ] **Step 5: Run the suite; expect all three files green**

Run: `bash tests/gate/run-tests.sh`
Expected: `gate tests: 3 passed, 0 failed`

- [ ] **Step 6: Check nothing else references the deleted REQ table**

Run: `grep -rn "REQ\[" scripts/ .github/ molecule/ docs/ CLAUDE.md || echo clean`
Expected: `clean` (CLAUDE.md's prose reference to per-scenario memory is rewritten in Task 6).

- [ ] **Step 7: Commit**

```bash
git add scripts/wait-for-memory.sh tests/gate/test_admission.sh tests/gate/test_lifecycle.sh
git commit -m "feat(ci): rewrite the memory gate around a committed-limits ledger"
```

---

### Task 3: Bounded-overtake queue policy

**Files:**
- Modify: `scripts/wait-for-memory.sh` (the `# BYPASS` marker inside the admission decision)
- Create: `tests/gate/test_queue.sh`

**Interfaces:**
- Consumes: the gate CLI and file formats from Task 2; harness helpers from Task 1.
- Produces: the final admission decision consumed by CI. `GATE_MAX_OVERTAKES` becomes honored.

- [ ] **Step 1: Write `tests/gate/test_queue.sh`**

```bash
#!/usr/bin/env bash
source "$(dirname "$0")/helpers.sh"
setup

# 1. blocked head admits as soon as capacity frees (FIFO base case)
set_incus_containers "big:Running:9216MB"        # free = 1024
make_scenario twoG 2048
run_gate first acquire twoG 6 >/dev/null &
fpid=$!
sleep 1
set_incus_containers                              # capacity freed
wait "$fpid" || { echo "head should admit after capacity frees"; exit 1; }
run_gate first release >/dev/null

# 2. a smaller job bypasses a blocked head and increments its counter
set_incus_containers "big:Running:8192MB"        # free = 2048
make_scenario huge 4096
make_scenario tiny 1024
run_gate heavy acquire huge 8 >/dev/null 2>&1 &
hpid=$!
sleep 1                                           # heavy is now the head
GATE_MAX_OVERTAKES=10 run_gate quick acquire tiny 3 >/dev/null \
  || { echo "bypass should admit a fitting job"; exit 1; }
grep -q ' 1$' "$MOLECULE_GATE_DIR"/q.*.heavy \
  || { echo "head counter not incremented"; exit 1; }
run_gate quick release >/dev/null

# 3. owner refresh preserves the counter; at K the queue goes strict
head_ticket=$(ls "$MOLECULE_GATE_DIR"/q.*.heavy)
need=$(awk '{print $1}' "$head_ticket")
scen=$(awk '{print $2}' "$head_ticket")
printf '%s %s 10\n' "$need" "$scen" > "$head_ticket"
sleep 1   # heavy keeps polling; if it rewrote its ticket the counter resets
if GATE_MAX_OVERTAKES=10 run_gate quick2 acquire tiny 2 >/dev/null 2>&1; then
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
GATE_MAX_OVERTAKES=0 run_gate solo acquire tiny 3 >/dev/null \
  || { echo "stale ticket should be GCd, not block"; exit 1; }
run_gate solo release >/dev/null

echo OK
```

- [ ] **Step 2: Run the suite to see the new tests fail**

Run: `bash tests/gate/run-tests.sh`
Expected: `test_queue.sh` FAILS at case 2 (no bypass branch yet); the other three files stay green.

- [ ] **Step 3: Add the bypass branch** — replace the `# BYPASS` marker inside the `if [ "$free" -ge "$need" ]` block with:

```bash
        elif [ "$head_overtakes" -lt "$MAX_OVERTAKES" ]; then
          # Bounded overtake: keep capacity utilized while the head cannot
          # fit, but count every bypass on the head ticket. At the cap the
          # queue goes strict until the head is admitted, so a heavy
          # scenario's extra wait is bounded by K admissions' releases.
          admit=yes
          head_scenario=$(file_field "$head" 2 unknown)
          printf '%s %s %d\n' "$head_need" "$head_scenario" \
            $(( head_overtakes + 1 )) > "$head"
```

- [ ] **Step 4: Run the suite; expect all green**

Run: `bash tests/gate/run-tests.sh`
Expected: `gate tests: 4 passed, 0 failed`

- [ ] **Step 5: Commit**

```bash
git add scripts/wait-for-memory.sh tests/gate/test_queue.sh
git commit -m "feat(ci): bound queue overtakes so heavy scenarios cannot starve"
```

---

### Task 4: Concurrency stress test

**Files:**
- Create: `tests/gate/test_stress.sh`

**Interfaces:**
- Consumes: gate CLI (final), harness helpers.
- Produces: nothing new — a regression tripwire for lock races.

- [ ] **Step 1: Write `tests/gate/test_stress.sh`**

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
  make_scenario "stress$i" "$need"
  if run_gate "w$i" acquire "stress$i" 30 >/dev/null 2>&1; then
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

Run: `bash tests/gate/run-tests.sh && bash tests/gate/run-tests.sh`
Expected: `gate tests: 5 passed, 0 failed` both times. If a run hangs longer than ~60s, a worker is deadlocked — that is a real gate bug, not a test problem.

- [ ] **Step 3: Commit**

```bash
git add tests/gate/test_stress.sh
git commit -m "test(ci): stress the memory gate ledger under concurrent acquires"
```

---

### Task 5: create.yml — convert reservations, keep a dev-path check

**Files:**
- Modify: `molecule/shared/create.yml` (header comment, vars, and the "Wait for capacity and launch containers (locked)" task)

**Interfaces:**
- Consumes: reservation file format `r.<runner>` = `<need_mb> <scenario>` in `/tmp/molecule-gate` (Task 2).
- Produces: the conversion behavior the gate's ledger arithmetic assumes. No later task depends on names introduced here.

- [ ] **Step 1: Update the header comment block** — replace lines 8–14 (the "Memory-based capacity gate:" paragraph) with:

```yaml
# Memory admission:
#   In CI, admission happens in the workflow's "Acquire memory slot" step
#   (scripts/wait-for-memory.sh), which leaves a reservation file in
#   /tmp/molecule-gate. When that file exists we launch unconditionally
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

### Task 6: Container memory limits + CLAUDE.md reference

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
`molecule/<scenario>/molecule.yml` (which is exactly what
`scripts/wait-for-memory.sh` admits on — there is no separate table to
keep in sync): `elasticstack_default` (20 GB),
`elasticsearch_roles_calculation` (16 GB), `es_kibana` (13.8 GB),
`cert_renewal` (10.5 GB).
```

Keep the rest of the paragraph (the `max-parallel` sentence) unchanged — Task 8 rewrites it.

- [ ] **Step 4: Lint + sanity-check derived needs**

Run: `yamllint molecule/ && python3 -c "
import yaml
for s in ['repos_default','kibana_custom','kibana_custom_certs','kibana_extras']:
    d = yaml.safe_load(open(f'molecule/{s}/molecule.yml').read().replace('\${MOLECULE_DISTRO:-debian12}','debian12').replace('\${ELASTIC_RELEASE:-9}','9').replace('\${MOLECULE_RUN_SUFFIX}',''))
    print(s, sum(int(p.get('memory_mb', 4096)) for p in d['platforms']))
"`
Expected: `repos_default 2048`, `kibana_custom 7168`, `kibana_custom_certs 7168`, `kibana_extras 7168`.

- [ ] **Step 5: Commit**

```bash
git add molecule/repos_default/molecule.yml molecule/kibana_custom/molecule.yml \
        molecule/kibana_custom_certs/molecule.yml molecule/kibana_extras/molecule.yml CLAUDE.md
git commit -m "fix(ci): give repos and kibana containers the memory they actually use"
```

---

### Task 7: Workflow wiring — acquire env, gate_tests job

**Files:**
- Modify: `.github/workflows/molecule.yml` (Acquire memory slot step, ~line 114)
- Modify: `.github/workflows/test_full_stack.yml` (Acquire memory slot step)
- Modify: `.github/workflows/test_elasticsearch_upgrade.yml` (both Acquire memory slot steps)
- Modify: `.github/workflows/test_contracts.yml` (paths + new job)

**Interfaces:**
- Consumes: gate CLI (`acquire <scenario>` — no timeout arg, default 2700) and its env contract; `tests/gate/run-tests.sh` from Task 1.
- Produces: nothing later tasks use.

- [ ] **Step 1a: Replace the acquire step in `test_full_stack.yml` and in both jobs of `test_elasticsearch_upgrade.yml`** (fixed job budgets of 180 and 60 minutes — the 2700s default deadline leaves 135 and 15 minutes of runway respectively). Exact step, identical in all three:

```yaml
      - name: Acquire memory slot
        # Single-authority admission gate: MemTotal − reserve − committed
        # limits.memory − pending reservations, FIFO with bounded
        # overtakes. Fails after its 45-min deadline instead of barging
        # in — a starved job is an explicit retryable failure, not an
        # OOM risk. create.yml converts the reservation into committed
        # capacity right after the containers launch.
        run: bash scripts/wait-for-memory.sh acquire "${{ matrix.scenario }}"
        env:
          INCUS_HOST: ${{ secrets.INCUS_HOST }}
          MOLECULE_SSH_KEY: ${{ runner.temp }}/molecule_id_ed25519
```

- [ ] **Step 1b: Replace the acquire step in `molecule.yml`** — its `timeout-minutes` is the caller-supplied `inputs.timeout` (default 60, as low as 20 for `test_elasticsearch_modules`), so the deadline is derived to always leave 15 minutes for converge+verify, floored at 300s:

```yaml
      - name: Acquire memory slot
        # Single-authority admission gate: MemTotal − reserve − committed
        # limits.memory − pending reservations, FIFO with bounded
        # overtakes. The deadline stays 15 minutes under this job's
        # timeout-minutes so a starved job fails HERE with a queue/ledger
        # verdict instead of at the workflow cancel with nothing.
        # create.yml converts the reservation into committed capacity
        # right after the containers launch.
        run: |
          deadline=$(( (${{ inputs.timeout }} - 15) * 60 ))
          [ "$deadline" -ge 300 ] || deadline=300
          bash scripts/wait-for-memory.sh acquire "${{ matrix.scenario }}" "$deadline"
        env:
          INCUS_HOST: ${{ secrets.INCUS_HOST }}
          MOLECULE_SSH_KEY: ${{ runner.temp }}/molecule_id_ed25519
```

Leave every "Release memory slot" step exactly as it is (`if: always()`, `bash scripts/wait-for-memory.sh release`) — release needs no env.

- [ ] **Step 2: test_contracts.yml — extend the pull_request paths filter**

```yaml
    paths:
      - 'roles/**'
      - 'tests/integration/**'
      - 'tests/fakes/**'
      - 'tests/gate/**'
      - 'scripts/wait-for-memory.sh'
      - '.github/workflows/test_contracts.yml'
```

- [ ] **Step 3: test_contracts.yml — add the gate_tests job** after the `contracts` job:

```yaml
  gate_tests:
    # The memory gate is pure coordination logic; its suite is hermetic
    # (fake meminfo, fake incus query, tmpdir gate state) and needs no
    # Incus and no self-hosted runner.
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Check out code
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1

      - name: Install PyYAML
        run: python3 -m pip install --user pyyaml

      - name: Run gate tests
        run: bash tests/gate/run-tests.sh
```

- [ ] **Step 4: Lint + step-order sanity check**

Run: `yamllint .github/workflows/ && for f in molecule.yml test_full_stack.yml test_elasticsearch_upgrade.yml; do awk '/Set up SSH key/{k=NR} /Acquire memory slot/{if(!k||NR<k){print FILENAME": acquire before ssh key"; exit 1}}' ".github/workflows/$f"; done && echo order-ok`
Expected: clean, `order-ok` (the gate's SSH query needs the key material already on disk).

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/molecule.yml .github/workflows/test_full_stack.yml \
        .github/workflows/test_elasticsearch_upgrade.yml .github/workflows/test_contracts.yml
git commit -m "chore(ci): wire the rewritten gate into the workflows and test it on every PR"
```

---

### Task 8: Raise full-stack max-parallel (separate, revertable)

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
`test_full_stack.yml` uses `max-parallel: 6`; the admission gate in
`scripts/wait-for-memory.sh` (FIFO, bounded overtakes, fail-fast)
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

### Task 9: Staged validation, PR, acceptance

**Files:** none (operational).

- [ ] **Step 1: Push the branch and open the PR**

```bash
git push -u origin ci/memory-gate-redesign
gh pr create --title "ci: single-authority memory gate with bounded-overtake queueing" --body "$(cat <<'EOF'
We had two overlapping admission gates for the shared incus-ci host and
they disagreed with each other: the workflow-level gate reasoned about
MemAvailable minus reservations, create.yml reasoned about committed
limits.memory, and a job's reservation kept counting against capacity
for its whole run while its containers' real usage was already visible.
That double-count is what starved the heavy scenarios and forced the
full-stack matrix down to three slots.

This makes scripts/wait-for-memory.sh the only admission decision,
based on MemTotal minus reserve minus committed limits minus pending
reservations. create.yml deletes the reservation right after incus
launch, so from that moment the job is counted through its containers'
limits and nothing is counted twice. Queueing is FIFO with bounded
overtakes: smaller jobs can pass a blocked heavy job, but only ten
times, then the queue goes strict until the head is admitted. At the
45-minute deadline the gate now fails with a queue/ledger verdict
instead of proceeding without headroom. The scenario memory table is
gone too — the gate sums memory_mb straight from the scenario's
molecule.yml, so there is nothing left to drift.

The gate logic has a hermetic test suite under tests/gate/ (fake
meminfo, fake incus query, real flock) including a seeded concurrency
stress case; it runs on ubuntu-latest via the contracts workflow on
every PR. The repos and kibana container limits also go up: the host
kernel journal shows dnf being OOM-killed inside the 1 GB repos
container 56 times in the last month, and Kibana 9 dying at ~1.6 GB
inside the 2 GB kibana containers, which is what was hanging those
jobs to their timeout. The last commit returns full-stack max-parallel
to six; if the next nightly storm shows starvation or OOMs, revert
that commit first.
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

- Spec coverage: §1 ledger → Task 2; §2 conversion + dev path → Task 5; §3 queue/fail-fast → Tasks 2–3; §4 limits/knobs → Tasks 6, 8; testing section → Tasks 1–4, 7 (gate_tests job), 9 (staged + acceptance); error-handling table rows are each covered by a named test case or Task 9 step.
- The old script's `/var/lib/molecule-gate` first-choice dir is intentionally dropped (never writable in practice; `/tmp/molecule-gate` is the observed real path). `MOLECULE_GATE_DIR` still overrides.
- Type consistency: ticket = `<need> <scenario> <overtakes>`, reservation = `<need> <scenario>`, grep vocab (`need=`, `committed=`, `ADMITTED`, `STARVED`) is identical between the script in Task 2 and every test in Tasks 2–4.
