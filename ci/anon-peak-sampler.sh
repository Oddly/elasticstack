#!/usr/bin/env bash
# anon-peak-sampler.sh — per-container peak anonymous RSS (real memory, excl. page cache).
#
# Runs on the incus host (LXC 305 / incus-ci). Every $INTERVAL seconds it reads,
# for each running incus container, the *anon* line from the container's top-level
# cgroup memory.stat (hierarchical → whole-container total, excludes reclaimable
# page cache) and keeps the high-water mark per container across its whole life.
# Survives container churn: a container's peak is retained after it is destroyed.
#
# Why sample instead of reading a counter: cgroup v2 exposes memory.peak, but that
# is usage INCLUDING page cache, which fills toward the limit without reflecting
# real need. There is no kernel high-water for anon alone, so we poll.
#
# Env:
#   INTERVAL   seconds between samples          (default 1)
#   OUT        output dir                        (default /root/mem-peaks)
#   NDJSON     if set to a path, append one JSON line per container per tick
#              (time-series; off by default to keep it light)
#
# Live view:   cat $OUT/peaks.txt          (rewritten every tick)
# Final view:  send SIGTERM/SIGINT (pkill -f anon-peak-sampler) → prints summary
set -uo pipefail
INTERVAL="${INTERVAL:-1}"
OUT="${OUT:-/root/mem-peaks}"
NDJSON="${NDJSON:-}"
mkdir -p "$OUT"
STATE="$OUT/peaks.tsv"
TABLE="$OUT/peaks.txt"
touch "$STATE"

declare -A PA PC LIM OOM SC   # peakAnon, peakCache, limit, oom_kills, scenarioClass (MiB)

# Resume prior peaks if the sampler is restarted.
while IFS=$'\t' read -r n pa lim pc oom sc; do
  [ -n "${n:-}" ] && { PA[$n]=$pa; LIM[$n]=$lim; PC[$n]=$pc; OOM[$n]=$oom; SC[$n]=$sc; }
done < "$STATE"

scenario_of(){ echo "$1" | sed -E 's/-(debian|rocky|rockylinux|ubuntu)[0-9]*.*$//'; }

render(){
  : > "$STATE.tmp"
  for n in "${!PA[@]}"; do
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$n" "${PA[$n]}" "${LIM[$n]:-0}" "${PC[$n]:-0}" "${OOM[$n]:-0}" "${SC[$n]:-}"
  done > "$STATE.tmp"
  mv "$STATE.tmp" "$STATE"
  {
    echo "# updated $(date -u +%FT%TZ)  interval=${INTERVAL}s  metric=peak anon RSS (real, excl. cache)"
    echo
    echo "== per scenario-class (max anon over all distro/release instances) =="
    printf '%-26s %10s %8s %6s %4s\n' scenario peakAnonMiB limitMiB anon% oom
    awk -F'\t' '{c=$1; sub(/-(debian|rocky|rockylinux|ubuntu)[0-9]*.*$/,"",c);
      a[c]=($2>a[c]?$2:a[c]); l[c]=($3>l[c]?$3:l[c]); o[c]+=$5}
      END{for(s in a){p=(l[s]>0?int(a[s]*100/l[s]):0); printf "%-26s %10s %8s %5s%% %4s\n",s,a[s],l[s],p,o[s]}}' \
      "$STATE" | sort -k2 -rn
    echo
    echo "== per container instance =="
    printf '%-42s %10s %8s %6s %10s %4s\n' container peakAnonMiB limitMiB anon% peakCacheMiB oom
    sort -t$'\t' -k2 -rn "$STATE" | while IFS=$'\t' read -r n pa lim pc oom sc; do
      p=0; [ "${lim:-0}" -gt 0 ] && p=$(( pa*100/lim ))
      printf '%-42s %10s %8s %5s%% %10s %4s\n' "$n" "$pa" "$lim" "$p" "$pc" "$oom"
    done
  } > "$TABLE"
}

trap 'render; echo; echo "=== FINAL PEAK SUMMARY ==="; cat "$TABLE"; exit 0' INT TERM

while true; do
  ts=$(date -u +%FT%TZ)
  while IFS= read -r d; do
    [ -f "$d/memory.stat" ] || continue
    n=${d##*/lxc.payload.}
    anon=$(( $(awk '/^anon /{print $2; exit}' "$d/memory.stat" 2>/dev/null || echo 0) / 1048576 ))
    cache=$(( $(awk '/^file /{print $2; exit}' "$d/memory.stat" 2>/dev/null || echo 0) / 1048576 ))
    mx=$(cat "$d/memory.max" 2>/dev/null || echo max)
    if [ "$mx" = max ]; then lim=0; else lim=$(( mx / 1048576 )); fi
    oom=$(awk '/^oom_kill /{print $2; exit}' "$d/memory.events" 2>/dev/null || echo 0)
    (( anon  > ${PA[$n]:-0}  )) && PA[$n]=$anon
    (( cache > ${PC[$n]:-0}  )) && PC[$n]=$cache
    (( ${oom:-0} > ${OOM[$n]:-0} )) && OOM[$n]=$oom
    LIM[$n]=$lim
    SC[$n]=$(scenario_of "$n")
    [ -n "$NDJSON" ] && printf '{"t":"%s","c":"%s","anon_mb":%s,"cache_mb":%s,"lim_mb":%s,"oom":%s}\n' \
      "$ts" "$n" "$anon" "$cache" "$lim" "$oom" >> "$NDJSON"
  done < <(find /sys/fs/cgroup -type d -name 'lxc.payload.*' 2>/dev/null)
  render
  sleep "$INTERVAL"
done
