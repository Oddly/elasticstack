# Performance Tuning

## JVM heap sizing

The Elasticsearch role auto-calculates heap based on available memory:

- **Default formula**: `min(RAM/2, 30GB)` with a 1GB minimum
- **Container-aware**: reads cgroup memory limits and uses those instead of physical RAM
- **Override**: set `elasticsearch_heap` (in GB) to a fixed value

```yaml
# Let the role auto-calculate (recommended)
# elasticsearch_heap: ""

# Or set explicitly
elasticsearch_heap: "16"
```

Logstash heap is set separately:

```yaml
logstash_heap: "1g"   # default: 1g
```

!!! tip
    Never set heap above 30GB — the JVM loses compressed OOPs beyond that threshold, which actually reduces performance.

## Memory locking

Prevent Elasticsearch from swapping to disk:

```yaml
elasticsearch_memory_lock: true
```

This sets `bootstrap.memory_lock: true` in `elasticsearch.yml` and configures systemd to allow unlimited memory locking. Essential for production — swapping causes GC pauses that look like node failures.

!!! note
    In containers with cgroup memory limits, memory locking is usually unnecessary since the kernel handles memory boundaries. But it doesn't hurt to enable it.

## JVM garbage collection tuning

The role manages the JVM options file. For custom GC parameters:

```yaml
elasticsearch_jvm_custom_parameters:
  - "-XX:+UseG1GC"
  - "-XX:MaxGCPauseMillis=200"
  - "-XX:InitiatingHeapOccupancyPercent=75"
```

Elasticsearch 8.x+ uses G1GC by default. Only add custom parameters if you've profiled your specific workload and have evidence that defaults aren't optimal.

## Thread pool sizing

For search-heavy workloads:

```yaml
elasticsearch_extra_config:
  thread_pool.search.size: 30          # default: cpu_count * 3/2 + 1
  thread_pool.search.queue_size: 1000  # default: 1000
  thread_pool.write.queue_size: 500    # default: 200
```

## Disk watermarks

Control when Elasticsearch stops allocating shards based on disk usage:

```yaml
elasticsearch_cluster_settings:
  cluster.routing.allocation.disk.watermark.low: "85%"     # stop allocating new shards
  cluster.routing.allocation.disk.watermark.high: "90%"    # start relocating shards away
  cluster.routing.allocation.disk.watermark.flood_stage: "95%"  # read-only indices
```

These are dynamic settings applied via the cluster settings API — no restart needed.

## Recovery throttling

Limit how much bandwidth shard recovery uses (prevents recovery from saturating the network):

```yaml
elasticsearch_cluster_settings:
  indices.recovery.max_bytes_per_sec: "100mb"   # default: 40mb
```

Increase this on fast networks to speed up recovery after a node restart.

## Logstash pipeline tuning

```yaml
logstash_pipeline_workers: 4        # default: cpu_count
logstash_pipeline_batch_size: 250   # default: 125
logstash_pipeline_batch_delay: 50   # default: 50 (ms)
```

Increase `pipeline_batch_size` for throughput-oriented workloads. Decrease it for latency-sensitive pipelines.

### Persistent queues

For at-least-once delivery (survives Logstash restarts):

```yaml
logstash_queue_type: persisted      # default: memory
logstash_queue_max_bytes: "4gb"
```

Persistent queues write to disk, so use fast storage (SSD/NVMe). Monitor queue depth via the Logstash monitoring API.
