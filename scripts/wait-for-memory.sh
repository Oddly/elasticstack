#!/usr/bin/env bash
# Coordinated memory admission gate for the molecule runner pool.
#
# Each scenario reserves its memory_mb on the runner host before converge,
# and releases the reservation in a post-step. A flock-serialised reader
# sums in-flight reservations and only admits a new job when:
#
#   MemAvailable - sum(reservations) >= scenario_mb + buffer
#
# Reservations are files under $GATE_DIR keyed by RUNNER_NAME (so each runner
# instance can hold at most one). Stale files older than $TTL_SEC are
# garbage-collected during the lock window — covers crashed jobs that
# never reach the release step.
#
# Usage:
#   wait-for-memory.sh acquire <scenario> [timeout_s]
#   wait-for-memory.sh release
#
# Env:
#   RUNNER_NAME             (auto-set by GitHub Actions; required)
#   MOLECULE_GATE_DIR       (default /var/lib/molecule-gate, falls back to /tmp/molecule-gate)
#   MOLECULE_GATE_TTL       (default 3600 — drop reservations older than this)
#   WAIT_FOR_MEMORY_BUFFER_MB (default 2048 — extra headroom over scenario_mb)

set -euo pipefail

action="${1:?usage: $0 <acquire|release> [args...]}"

GATE_DIR="${MOLECULE_GATE_DIR:-/var/lib/molecule-gate}"
mkdir -p "$GATE_DIR" 2>/dev/null || {
  GATE_DIR=/tmp/molecule-gate
  mkdir -p "$GATE_DIR"
}
chmod 0777 "$GATE_DIR" 2>/dev/null || true

LOCK="$GATE_DIR/.lock"
TTL_SEC="${MOLECULE_GATE_TTL:-3600}"
buffer_mb="${WAIT_FOR_MEMORY_BUFFER_MB:-2048}"

runner="${RUNNER_NAME:-runner-$$}"
my_resv="$GATE_DIR/r.${runner}"

# --- Required MB per scenario (sum of memory_mb across all platforms) ---
# Update this table when a scenario's memory_mb changes.
declare -A REQ=(
  [beats_advanced]=2048
  [beats_default]=4096
  [beats_peculiar]=2048
  [beats_security]=8192
  [cert_renewal]=10752
  [elasticsearch_cert_content]=4096
  [elasticsearch_custom]=4096
  [elasticsearch_custom_certs]=4096
  [elasticsearch_custom_certs_minimal]=4096
  [elasticsearch_default]=8192
  [elasticsearch_diagnostics]=4096
  [elasticsearch_no-security]=8192
  [elasticsearch_roles_calculation]=16384
  [elasticsearch_security_api]=4096
  [elasticsearch_upgrade_8to9]=8192
  [elasticsearch_upgrade_8to9_single]=4096
  [elasticstack_default]=20480
  [es_kibana]=13824
  [kibana_custom]=8192
  [kibana_custom_certs]=8192
  [kibana_default]=4096
  [logstash_advanced]=2048
  [logstash_centralized_pipelines]=2048
  [logstash_custom_pipeline]=2048
  [logstash_default]=2048
  [logstash_elasticsearch]=8192
  [logstash_external_certs]=2048
  [logstash_standalone_certs]=2048
  [logstash_ssl]=2048
  [repos_default]=1024
)

# --- Helpers ---

# Sum reservations under exclusive lock; garbage-collect stale entries.
# Echoes "<reserved_mb>" to stdout. Caller must hold the lock or call this
# inside the locked section.
sum_reservations() {
  local now total=0 mtime mb
  now=$(date +%s)
  shopt -s nullglob
  for f in "$GATE_DIR"/r.*; do
    mtime=$(stat -c %Y "$f" 2>/dev/null || echo 0)
    if [ $(( now - mtime )) -gt "$TTL_SEC" ]; then
      rm -f "$f"
      continue
    fi
    mb=$(awk '{print $1+0; exit}' "$f" 2>/dev/null || echo 0)
    total=$(( total + mb ))
  done
  shopt -u nullglob
  echo "$total"
}

case "$action" in
  acquire)
    scenario="${2:?usage: $0 acquire <scenario> [timeout_s]}"
    timeout_s="${3:-1800}"
    required="${REQ[$scenario]:-4096}"
    threshold=$(( required + buffer_mb ))

    printf 'molecule-gate[%s]: acquire scenario=%s required=%dMB buffer=%dMB threshold=%dMB timeout=%ds\n' \
      "$runner" "$scenario" "$required" "$buffer_mb" "$threshold" "$timeout_s"

    deadline=$(( $(date +%s) + timeout_s ))
    attempt=0
    while :; do
      attempt=$(( attempt + 1 ))
      # Critical section: read MemAvailable, sum reservations, optionally claim.
      exec 9>"$LOCK"
      flock 9
      reserved=$(sum_reservations)
      available=$(awk '/^MemAvailable:/{print int($2/1024)}' /proc/meminfo)
      effective=$(( available - reserved ))
      if [ "$effective" -ge "$threshold" ]; then
        printf '%d %s\n' "$required" "$scenario" > "$my_resv"
        flock -u 9
        printf 'molecule-gate[%s]: ADMITTED MemAvailable=%dMB reserved=%dMB effective=%dMB required=%dMB (attempt %d)\n' \
          "$runner" "$available" "$reserved" "$effective" "$threshold" "$attempt"
        exit 0
      fi
      flock -u 9

      now=$(date +%s)
      if [ "$now" -ge "$deadline" ]; then
        # Take the slot anyway under the same lock — better one OOM than a stuck queue.
        exec 9>"$LOCK"
        flock 9
        printf '%d %s\n' "$required" "$scenario" > "$my_resv"
        flock -u 9
        printf 'molecule-gate[%s]: TIMEOUT after %ds (effective=%dMB needed=%dMB) — proceeding without headroom\n' \
          "$runner" "$timeout_s" "$effective" "$threshold" >&2
        exit 0
      fi
      printf 'molecule-gate[%s]: waiting (available=%dMB reserved=%dMB effective=%dMB needed=%dMB, attempt %d)\n' \
        "$runner" "$available" "$reserved" "$effective" "$threshold" "$attempt"
      sleep 30
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
    flock -u 9
    ;;

  *)
    echo "usage: $0 <acquire|release> [args...]" >&2
    exit 2
    ;;
esac
